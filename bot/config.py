from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator


BASE_DIR = Path(__file__).resolve().parent.parent


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings(BaseModel):
    """Runtime configuration sourced from environment variables."""

    bot_token: str = Field(..., alias="BOT_TOKEN")
    admin_ids: List[int] = Field(..., alias="ADMIN_IDS")
    database_url: str = Field("sqlite+aiosqlite:///./data/voting.db", alias="DATABASE_URL")
    submissions_open_default: bool = Field(True, alias="SUBMISSIONS_OPEN_DEFAULT")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value: object) -> List[int]:
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, str):
            chunks = re.split(r"[\s,]+", value.strip())
            return [int(chunk) for chunk in chunks if chunk]
        raise TypeError("ADMIN_IDS must be a comma-separated string or list of integers")

    @field_validator("submissions_open_default", mode="before")
    @classmethod
    def _boolify(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    """Load settings from environment (.env is supported)."""

    load_dotenv(BASE_DIR / ".env")
    try:
        return Settings.model_validate(dict(os.environ))
    except ValidationError as exc:  # pragma: no cover - configuration errors happen at runtime
        missing = ", ".join(err["loc"][0] for err in exc.errors())
        raise RuntimeError(f"Configuration error, missing or invalid values for: {missing}") from exc


settings = load_settings()


def ensure_sqlite_path_exists(database_url: str) -> None:
    """Create parent directories for SQLite database files when needed."""

    if not database_url.startswith("sqlite"):
        return
    _, _, raw_path = database_url.partition("///")
    if not raw_path:
        return
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / raw_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
