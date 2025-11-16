from __future__ import annotations

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from bot.config import settings


logger = logging.getLogger(__name__)


class AdminFilter(BaseFilter):
    """Allow handlers only for preconfigured Telegram IDs."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        user_id = getattr(user, "id", None)
        is_admin = bool(user and user_id in settings.admin_ids)
        logger.debug(
            "AdminFilter check: user_id=%s username=%s allowed=%s configured=%s",
            user_id,
            getattr(user, "username", None),
            is_admin,
            settings.admin_ids,
        )
        if not is_admin:
            logger.info(
                "Admin access denied for user_id=%s username=%s", user_id, getattr(user, "username", None)
            )
        return is_admin
