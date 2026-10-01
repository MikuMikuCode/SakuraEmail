from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    owner_id: int
    apps_script_url: str
    bot_api_secret: str
    database_path: Path
    notification_poll_seconds: int

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()

        bot_token = _required("BOT_TOKEN")
        owner_id_text = _required("BOT_OWNER_ID")
        apps_script_url = _required("APPS_SCRIPT_URL")
        bot_api_secret = _required("BOT_API_SECRET")

        try:
            owner_id = int(owner_id_text)
        except ValueError as exc:
            raise ConfigurationError("BOT_OWNER_ID must be an integer") from exc

        if not apps_script_url.startswith("https://") or not apps_script_url.endswith("/exec"):
            raise ConfigurationError("APPS_SCRIPT_URL must be the HTTPS Web App URL ending in /exec")

        if len(bot_api_secret) < 32:
            raise ConfigurationError("BOT_API_SECRET must contain at least 32 characters")

        database_path = Path(os.getenv("DATABASE_PATH", "data/sakuraemail.sqlite3")).expanduser()

        try:
            notification_poll_seconds = int(os.getenv("NOTIFICATION_POLL_SECONDS", "3600"))
        except ValueError as exc:
            raise ConfigurationError("NOTIFICATION_POLL_SECONDS must be an integer") from exc

        notification_poll_seconds = max(notification_poll_seconds, 300)

        return cls(
            bot_token=bot_token,
            owner_id=owner_id,
            apps_script_url=apps_script_url,
            bot_api_secret=bot_api_secret,
            database_path=database_path,
            notification_poll_seconds=notification_poll_seconds,
        )


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Environment variable {name} is required")
    return value

