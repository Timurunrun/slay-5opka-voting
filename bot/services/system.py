from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models import SystemState


async def get_system_state(session: AsyncSession) -> SystemState:
    state = await session.get(SystemState, 1)
    if state:
        return state
    state = SystemState(id=1, submissions_open=settings.submissions_open_default)
    session.add(state)
    await session.commit()
    return state


async def set_submissions_open(session: AsyncSession, open_for_submissions: bool) -> SystemState:
    state = await get_system_state(session)
    state.submissions_open = open_for_submissions
    await session.commit()
    return state
