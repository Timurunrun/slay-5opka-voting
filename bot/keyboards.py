from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Засчитать голос")],
        [KeyboardButton(text="Доска почёта"), KeyboardButton(text="Изменить ник")],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="Мод-панель")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def submission_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Мой личный голос", callback_data="submission:self")],
            [InlineKeyboardButton(text="Знакомого по рекомендации", callback_data="submission:referral")],
        ]
    )


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Рассмотреть заявки")],
            [KeyboardButton(text="Лидерборд (мод)"), KeyboardButton(text="Управление")],
            [KeyboardButton(text="В главное меню")],
        ],
        resize_keyboard=True,
    )


def moderation_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"moderate:{submission_id}:approve"),
             InlineKeyboardButton(text="⛔️ Отклонить", callback_data=f"moderate:{submission_id}:reject")],
            [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"moderate:{submission_id}:block")],
        ]
    )


def management_keyboard(submissions_open: bool) -> InlineKeyboardMarkup:
    toggle_text = "Остановить приём заявок" if submissions_open else "Продолжить приём заявок"
    toggle_callback = "mgmt:toggle"
    manual_callback = "mgmt:manual"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=toggle_callback)],
            [InlineKeyboardButton(text="Засчитать голос вручную", callback_data=manual_callback)],
        ]
    )
