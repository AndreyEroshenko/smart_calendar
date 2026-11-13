"""Settings, read from environment variables (see .env.example)."""
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    allowed_user_ids: frozenset[int]
    calendar_id: str
    timezone: ZoneInfo
    claude_model: str
    claude_enabled: bool  # False until ANTHROPIC_API_KEY is set; the bot then only does /add and /list
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "smart_calendar.db"

    @property
    def google_token_path(self) -> Path:
        return self.data_dir / "google_token.json"


def load() -> Settings:
    ids = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "")
    return Settings(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        allowed_user_ids=frozenset(int(x) for x in ids.split(",") if x.strip()),
        calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        timezone=ZoneInfo(os.environ.get("TIMEZONE", "Australia/Melbourne")),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5"),
        claude_enabled=bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        data_dir=Path(os.environ.get("DATA_DIR", "data")),
    )
