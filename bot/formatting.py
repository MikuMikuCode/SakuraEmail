from __future__ import annotations

from datetime import datetime, timedelta, timezone


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


def format_datetime(value: str) -> str:
    """Format API and database timestamps for Russian-speaking users."""
    raw_value = value.strip()
    if not raw_value:
        return ""

    normalized = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw_value

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(MOSCOW_TIMEZONE)
    return parsed.strftime("%d.%m.%Y %H:%M:%S")


def display_license_type(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if normalized == "maketpro":
        return "MaketPro"
    if normalized == "maket":
        return "Maket"
    return "Не указан"
