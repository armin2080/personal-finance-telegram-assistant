"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str | None
    telegram_allowed_user_ids: frozenset[int]
    database_path: Path
    user_timezone: str
    log_level: str
    minimum_free_bytes: int = 100 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(override=False)
        raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed_ids: set[int] = set()
        if raw_ids.strip():
            for item in raw_ids.split(","):
                item = item.strip()
                try:
                    numeric_id = int(item)
                    if numeric_id <= 0:
                        raise ValueError
                    allowed_ids.add(numeric_id)
                except ValueError as exc:
                    raise ValueError(
                        "TELEGRAM_ALLOWED_USER_IDS must contain comma-separated "
                        "positive numeric IDs."
                    ) from exc

        raw_path = os.getenv(
            "FPA_DATABASE_PATH",
            "~/.local/share/personal-finance-assistant/finance.sqlite3",
        )
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
        return cls(
            telegram_bot_token=token,
            telegram_allowed_user_ids=frozenset(allowed_ids),
            database_path=Path(raw_path).expanduser(),
            user_timezone=os.getenv("FPA_USER_TIMEZONE", "Europe/Berlin"),
            log_level=os.getenv("FPA_LOG_LEVEL", "INFO").upper(),
            minimum_free_bytes=int(os.getenv("FPA_MIN_FREE_BYTES", "104857600")),
            max_upload_bytes=int(os.getenv("FPA_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        )
