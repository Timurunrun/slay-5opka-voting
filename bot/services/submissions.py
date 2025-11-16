from __future__ import annotations

from datetime import datetime

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Submission, SubmissionStatus, User, VoteSource


async def create_submission(
    session: AsyncSession,
    *,
    user_id: int,
    vote_source: VoteSource,
    file_id: str,
) -> Submission:
    submission = Submission(user_id=user_id, vote_source=vote_source, file_id=file_id)
    session.add(submission)
    await session.commit()
    await session.refresh(submission)
    return submission


async def get_next_pending_submission(session: AsyncSession) -> Submission | None:
    stmt = select(Submission).where(Submission.status == SubmissionStatus.PENDING).order_by(asc(Submission.created_at)).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def process_submission(
    session: AsyncSession,
    *,
    submission_id: int,
    moderator_id: int,
    status: SubmissionStatus,
    reason: str | None = None,
    block_user: bool = False,
) -> Submission | None:
    submission = await session.get(Submission, submission_id)
    if not submission or submission.status != SubmissionStatus.PENDING:
        return None
    submission.status = status
    submission.reason = reason
    submission.moderator_id = moderator_id
    submission.processed_at = datetime.utcnow()

    user = await session.get(User, submission.user_id)
    if not user:
        await session.commit()
        return submission

    if status == SubmissionStatus.APPROVED:
        if submission.vote_source == VoteSource.SELF:
            user.self_votes += 1
        else:
            user.referral_votes += 1
    if block_user:
        user.is_blocked = True

    await session.commit()
    await session.refresh(submission)
    return submission


async def apply_manual_credit(
    session: AsyncSession,
    *,
    telegram_id: int,
    self_votes: int,
    referral_votes: int,
) -> User | None:
    user = await session.get(User, telegram_id)
    if not user:
        user = User(telegram_id=telegram_id, display_name=f"ID {telegram_id}")
        session.add(user)
    user.self_votes += max(0, self_votes)
    user.referral_votes += max(0, referral_votes)
    await session.commit()
    return user
