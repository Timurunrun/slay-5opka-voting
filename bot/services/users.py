from __future__ import annotations

from aiogram.types import User as TelegramUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import User


async def upsert_user(session: AsyncSession, tg_user: TelegramUser, is_admin: bool = False) -> User:
    user = await session.get(User, tg_user.id)
    if user:
        user.username = tg_user.username or user.username
        user.display_name = user.display_name or tg_user.full_name
        if is_admin and not user.is_admin:
            user.is_admin = True
    else:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            display_name=tg_user.full_name,
            is_admin=is_admin,
        )
        session.add(user)
    await session.commit()
    return user


async def update_display_name(session: AsyncSession, telegram_id: int, nickname: str) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return None
    user.display_name = nickname
    await session.commit()
    return user
