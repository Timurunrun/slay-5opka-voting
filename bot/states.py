from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SubmissionStates(StatesGroup):
    choosing_source = State()
    waiting_video = State()


class NicknameStates(StatesGroup):
    waiting_value = State()


class ManualCreditStates(StatesGroup):
    waiting_user_id = State()
    waiting_amounts = State()
    waiting_reason = State()
