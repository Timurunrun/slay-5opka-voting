from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.db import async_session, init_db
from bot.filters.admin import AdminFilter
from bot.keyboards import (
    admin_menu_keyboard,
    main_menu_keyboard,
    management_keyboard,
    moderation_keyboard,
    submission_source_keyboard,
)
from bot.models import SubmissionStatus, User, VoteSource
from bot.services.leaderboard import fetch_top_users
from bot.services.submissions import (
    apply_manual_credit,
    create_submission,
    get_next_pending_submission,
    process_submission,
)
from bot.services.system import get_system_state, set_submissions_open
from bot.services.users import update_display_name, upsert_user
from bot.states import ManualCreditStates, NicknameStates, SubmissionStates
from bot import texts


logger = logging.getLogger(__name__)
participant_router = Router(name="participants")
admin_router = Router(name="admins")
admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())


async def _ensure_user(message: Message) -> User | None:
    if not message.from_user:
        return None
    async with async_session() as session:
        return await upsert_user(session, message.from_user, message.from_user.id in settings.admin_ids)


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_ids)


def html_escape(value: object | None) -> str:
    if value is None:
        return ""
    return escape(str(value))


def _format_leaderboard(entries, extended: bool = False, limit: int | None = None) -> str:
    if limit is not None:
        entries = entries[:limit]
    if not entries:
        return (
            f"{texts.LEADERBOARD_HEADER}\n\n<i>Пока голоса на проверке у модераторов...</i>"
        )
    lines = [texts.LEADERBOARD_HEADER, ""]
    medal_map = {1: "💎", 2: "🟨", 3: "⬜"}
    for entry in entries:
        display_name = html_escape(entry.display_name)
        medal = medal_map.get(entry.position, "")
        base = f"{entry.position}. {display_name}: {entry.total} голос(ов)"
        if extended:
            base += f" — свои: {entry.self_votes}, рекомендации: {entry.referral_votes}"
        line = f"{medal + ' ' if medal else ''}{base}".strip()
        lines.append(f"<b>{line}</b>")
    return "\n".join(lines)


def _format_personal_stats(user: User | None) -> str:
    if not user:
        return "Ваши подтверждённые голоса: 0."
    total = user.self_votes + user.referral_votes
    return (
        f"<i>Ваши подтверждённые голоса: {total} "
        f", из них личных {user.self_votes}, а рекомендаций {user.referral_votes}).</i>"
    )


@participant_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _ensure_user(message)
    await message.answer(
        texts.START_MESSAGE,
        reply_markup=main_menu_keyboard(bool(user and user.is_admin)),
    )


@participant_router.message(Command("whoami"))
async def handle_whoami(message: Message) -> None:
    if not message.from_user:
        return
    is_admin = _is_admin(message)
    await message.answer(
        "Ваш Telegram ID: {id}\nСтатус: {status}\n<code>ADMIN_IDS</code>: {admins}".format(
            id=message.from_user.id,
            status="модератор" if is_admin else "участник",
            admins=", ".join(map(str, settings.admin_ids)) or "(пусто)",
        )
    )


@participant_router.message(StateFilter("*"), F.text.casefold() == "в главное меню")
async def back_to_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Главное меню", reply_markup=main_menu_keyboard(_is_admin(message)))


@participant_router.message(StateFilter("*"), F.text.casefold() == "доска почёта")
async def send_leaderboard(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with async_session() as session:
        entries = await fetch_top_users(session, limit=10)
        current_user = None
        if message.from_user:
            current_user = await session.get(User, message.from_user.id)
    await message.answer(
        f"{_format_personal_stats(current_user)}\n\n{_format_leaderboard(entries, limit=10)}",
        reply_markup=main_menu_keyboard(_is_admin(message)),
    )


@participant_router.message(StateFilter("*"), F.text.casefold() == "изменить ник")
async def prompt_nickname(message: Message, state: FSMContext) -> None:
    await state.set_state(NicknameStates.waiting_value)
    await message.answer(texts.NICKNAME_PROMPT)


@participant_router.message(NicknameStates.waiting_value)
async def set_nickname(message: Message, state: FSMContext) -> None:
    nickname = message.text.strip()
    if not (2 <= len(nickname) <= 32):
        await message.answer("Ник должен быть длиной от 2 до 32 символов.")
        return
    async with async_session() as session:
        updated = await update_display_name(session, message.from_user.id, nickname)
    if not updated:
        await message.answer("Сначала воспользуйтесь /start.")
    else:
        await message.answer(
            texts.NICKNAME_SAVED,
            reply_markup=main_menu_keyboard(_is_admin(message)),
        )
    await state.clear()


@participant_router.message(StateFilter("*"), F.text.casefold() == "засчитать голос")
async def start_submission_flow(message: Message, state: FSMContext) -> None:
    user = await _ensure_user(message)
    if not user:
        return
    await state.clear()
    async with async_session() as session:
        db_user = await session.get(User, user.telegram_id)
        if db_user and db_user.is_blocked:
            await message.answer("Вам ограничили отправку заявок. Свяжитесь с модератором, если это ошибка.")
            return
        system_state = await get_system_state(session)
        if not system_state.submissions_open:
            await message.answer(texts.NO_SUBMISSIONS_MESSAGE)
            return
    await state.set_state(SubmissionStates.choosing_source)
    await message.answer(
        "Чей голос оформляем?",
        reply_markup=submission_source_keyboard(),
    )


@participant_router.callback_query(F.data.startswith("submission:"))
async def choose_vote_source(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    parts = callback.data.split(":", maxsplit=1)
    if len(parts) != 2:
        await callback.answer()
        return
    source_raw = parts[1]
    vote_source = VoteSource.SELF if source_raw == "self" else VoteSource.REFERRAL
    await state.update_data(vote_source=vote_source.value)
    await state.set_state(SubmissionStates.waiting_video)
    instructions = texts.SUBMISSION_INSTRUCTIONS
    prompt = (
        texts.VIDEO_PROMPT_SELF if vote_source == VoteSource.SELF else texts.VIDEO_PROMPT_REFERRAL
    ).format(instructions=instructions)
    await callback.message.answer(prompt)
    await callback.answer("")


@participant_router.message(SubmissionStates.waiting_video, F.video)
async def handle_video_submission(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    vote_source_value = data.get("vote_source")
    if vote_source_value is None:
        await message.answer("Пожалуйста, выберите тип голоса кнопкой выше.")
        return
    vote_source = VoteSource(vote_source_value)
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = await upsert_user(session, message.from_user, message.from_user.id in settings.admin_ids)
        if user.is_blocked:
            await message.answer("Модераторы заблокировали ваши заявки. Если это ошибка — напишите им напрямую.")
            await state.clear()
            return
        state_row = await get_system_state(session)
        if not state_row.submissions_open:
            await message.answer(texts.NO_SUBMISSIONS_MESSAGE)
            await state.clear()
            return
        await create_submission(
            session,
            user_id=user.telegram_id,
            vote_source=vote_source,
            file_id=message.video.file_id,
        )
    await state.clear()
    await message.answer(
        "⌛ Голос отправлен на проверку модераторам. Мы проверим запись вручную и пришлём уведомление, как всё будет готово!",
        reply_markup=main_menu_keyboard(_is_admin(message)),
    )


@participant_router.message(AdminFilter(), Command("mod"))
async def show_admin_menu_via_command(message: Message) -> None:
    await message.answer(texts.ADMIN_MENU_INTRO, reply_markup=admin_menu_keyboard())


@participant_router.message(Command("mod"))
async def mod_not_allowed(message: Message) -> None:
    if not message.from_user:
        return
    await message.answer(
        "Команда доступна только модераторам. Ваш ID: {id}. Передайте его создателю бота для добавления в <code>ADMIN_IDS</code>.".format(
            id=message.from_user.id,
        )
    )


@participant_router.message(AdminFilter(), F.text.casefold() == "мод-панель")
async def show_admin_menu_button(message: Message) -> None:
    await message.answer(texts.ADMIN_MENU_INTRO, reply_markup=admin_menu_keyboard())


@participant_router.message(SubmissionStates.waiting_video)
async def remind_video_format(message: Message) -> None:
    await message.answer("Нужно прислать именно видео. Попробуй ещё раз и убедись, что оно прикреплено.")


# --- Admin handlers ---


@admin_router.message(F.text.casefold() == "лидерборд (мод)")
async def show_admin_leaderboard(message: Message) -> None:
    async with async_session() as session:
        entries = await fetch_top_users(session, limit=50)
    await message.answer(_format_leaderboard(entries, extended=True))


@admin_router.message(F.text.casefold() == "рассмотреть заявки")
async def review_queue(message: Message) -> None:
    await send_next_submission(message.bot, message.chat.id)


async def send_next_submission(bot: Bot, chat_id: int) -> None:
    async with async_session() as session:
        submission = await get_next_pending_submission(session)
        if not submission:
            await bot.send_message(chat_id, "Все заявки разобраны!")
            return
        user = await session.get(User, submission.user_id)
        if not user:
            await bot.send_message(chat_id, f"Не найден пользователь для заявки #{submission.id}.")
            return
    username_value = user.username or "—"
    username_html = html_escape(username_value)
    username_line = f"@{username_html}" if user.username else username_html
    display_name_html = html_escape(user.display_name or "—")
    caption = (
        f"Заявка #{submission.id}\n"
        f"Тип: {'личный голос' if submission.vote_source == VoteSource.SELF else 'рекомендация'}\n"
        f"TG: {username_line} (ID {user.telegram_id})\n"
        f"Ник в таблице: {display_name_html}\n"
        f"Статистика: свои {user.self_votes}, рекомендации {user.referral_votes}\n"
        f"Отправлено: {submission.created_at:%Y-%m-%d %H:%M UTC}"
    )
    try:
        await bot.send_video(chat_id, submission.file_id, caption=caption, reply_markup=moderation_keyboard(submission.id))
    except TelegramBadRequest as exc:  # pragma: no cover - depends on Telegram API
        logger.error("Failed to send video: %s", exc)
        await bot.send_message(chat_id, caption, reply_markup=moderation_keyboard(submission.id))


@admin_router.callback_query(F.data.startswith("moderate:"))
async def handle_moderation(callback: CallbackQuery) -> None:
    _, submission_id, action = callback.data.split(":")
    submission_id = int(submission_id)
    reason = "Отклонено модератором"
    status = SubmissionStatus.REJECTED
    block_user = False
    if action == "approve":
        status = SubmissionStatus.APPROVED
        reason = "Подтверждено"
    elif action == "reject":
        status = SubmissionStatus.REJECTED
    elif action == "block":
        status = SubmissionStatus.REJECTED
        block_user = True
        reason = "Пользователь заблокирован модератором"
    async with async_session() as session:
        submission = await process_submission(
            session,
            submission_id=submission_id,
            moderator_id=callback.from_user.id,
            status=status,
            reason=reason,
            block_user=block_user,
        )
        if not submission:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        user = await session.get(User, submission.user_id)
    await callback.answer("Решение сохранено")
    notify_text = ""
    if status == SubmissionStatus.APPROVED:
        notify_text = (
            "Заявка на добавление голоса подтверждена ✅"
            "\nСпасибо за честный голос! БОГЕМА БУДЕТ ПЛАКАТЬ!"
            "\n\n<b>КАК ДОБАВИТЬ СЧЁТЧИК ГОЛОСОВ В СТАТУС?</b>"
            "\n1. Зайдите в «Доску почёта» и посмотрите, сколько заявок вам одобрили."
            "\n2. Выберите из <a href=\"https://t.me/addemoji/SLAY5opka_by_TgEmodziBot\">пака</a> эмодзи с нужным количеством голосов."
            "\n\nБудьте честны с самими собой! Мы, как модеры, всё видим :)"
        )
    elif block_user:
        notify_text = (
            "Модераторы отклонили заявку на добавление голоса и временно заблокировали вам возможность отправки новых."
        )
    else:
        notify_text = (
            "Заявка на добавление голоса отклонена 😵"
            "\nПроверьте, что запись показывает процесс входа и сам факт голосования."
        )
    if notify_text:
        try:
            await callback.message.bot.send_message(submission.user_id, notify_text)
        except TelegramBadRequest:
            pass
    await send_next_submission(callback.message.bot, callback.message.chat.id)


@admin_router.message(F.text.casefold() == "управление")
async def show_management(message: Message) -> None:
    async with async_session() as session:
        state = await get_system_state(session)
    await message.answer(
        "Управление приёмом заявок и ручными начислениями:",
        reply_markup=management_keyboard(state.submissions_open),
    )


@admin_router.message(F.text.casefold() == "в главное меню")
async def admin_back_to_main(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Возвращаемся в режим участника.",
        reply_markup=main_menu_keyboard(_is_admin(message)),
    )


@admin_router.callback_query(F.data == "mgmt:toggle")
async def toggle_submissions(callback: CallbackQuery) -> None:
    async with async_session() as session:
        state = await get_system_state(session)
        new_state = await set_submissions_open(session, not state.submissions_open)
    status_text = "Подача заявок открыта" if new_state.submissions_open else "Подача заявок остановлена"
    await callback.answer(status_text)
    await callback.message.edit_reply_markup(reply_markup=management_keyboard(new_state.submissions_open))


@admin_router.callback_query(F.data == "mgmt:manual")
async def manual_credit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ManualCreditStates.waiting_user_id)
    await callback.message.answer(texts.MANUAL_CREDIT_PROMPT_ID)
    await callback.answer()


@admin_router.message(ManualCreditStates.waiting_user_id)
async def manual_credit_user(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Нужно отправить числовой Telegram ID.")
        return
    await state.update_data(target_id=int(message.text))
    await state.set_state(ManualCreditStates.waiting_amounts)
    await message.answer(texts.MANUAL_CREDIT_PROMPT_AMOUNTS)


@admin_router.message(ManualCreditStates.waiting_amounts)
async def manual_credit_amounts(message: Message, state: FSMContext) -> None:
    parts = message.text.replace(",", " ").split()
    if len(parts) != 2 or not all(part.lstrip("-+").isdigit() for part in parts):
        await message.answer("Укажите два числа через пробел, например <code>1 0</code>.")
        return
    self_votes, referral_votes = map(int, parts)
    if self_votes < 0 or referral_votes < 0:
        await message.answer("Числа не могут быть отрицательными.")
        return
    await state.update_data(self_votes=self_votes, referral_votes=referral_votes)
    await state.set_state(ManualCreditStates.waiting_reason)
    await message.answer(texts.MANUAL_CREDIT_PROMPT_REASON)


@admin_router.message(ManualCreditStates.waiting_reason)
async def manual_credit_reason(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target_id = data.get("target_id")
    self_votes = data.get("self_votes", 0)
    referral_votes = data.get("referral_votes", 0)
    reason = message.text.strip()
    if not target_id:
        await message.answer("ID не найден. Запустите процесс заново через панель управления.")
        await state.clear()
        return
    async with async_session() as session:
        user = await apply_manual_credit(
            session,
            telegram_id=target_id,
            self_votes=self_votes,
            referral_votes=referral_votes,
        )
    await state.clear()
    if not user:
        await message.answer("Не удалось найти пользователя даже после создания записи.")
        return
    safe_reason = html_escape(reason)
    await message.answer(
        f"Добавлено: свои {self_votes}, рекомендации {referral_votes}. Причина: {safe_reason}\n"
        "Лидерборд обновлён."
    )
    try:
        await message.bot.send_message(
            target_id,
            f"Модераторы обновили статистику: +{self_votes} своих голосов, +{referral_votes} рекомендаций."
            " Если есть вопросы — ответьте на это сообщение.",
        )
    except TelegramBadRequest:
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Configured admin IDs: %s", settings.admin_ids)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(participant_router)
    dp.include_router(admin_router)
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
