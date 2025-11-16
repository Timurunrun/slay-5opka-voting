from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import User


@dataclass(slots=True)
class LeaderboardEntry:
    position: int
    display_name: str
    self_votes: int
    referral_votes: int

    @property
    def total(self) -> int:
        return self.self_votes + self.referral_votes


async def fetch_top_users(session: AsyncSession, limit: int = 10) -> list[LeaderboardEntry]:
    total_expr = User.self_votes + User.referral_votes
    stmt = (
        select(User, total_expr.label("total"))
        .where(total_expr > 0)
        .order_by(desc(total_expr), desc(User.referral_votes), User.display_name)
        .limit(limit)
    )
    result = await session.execute(stmt)
    entries: list[LeaderboardEntry] = []
    for idx, row in enumerate(result.all(), start=1):
        user: User = row.User
        entries.append(
            LeaderboardEntry(
                position=idx,
                display_name=user.display_name or user.username or f"ID {user.telegram_id}",
                self_votes=user.self_votes,
                referral_votes=user.referral_votes,
            )
        )
    return entries
