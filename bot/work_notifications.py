from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from .access import AccessController
from .api import SakuraApiError, SakuraAppsScriptApi
from .db import Database
from .decor import SAKURA_ANIMATED
from .formatting import MOSCOW_TIMEZONE
from .keyboards import work_reminder_keyboard


logger = logging.getLogger(__name__)

REMINDER_TEXT = (
    f"{SAKURA_ANIMATED} До конца рабочего дня осталось полчаса!\n"
    "Не забудь заполнить баллы (｡•̀ᴗ-)✧"
)


async def work_report_notification_worker(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
    access: AccessController,
    poll_seconds: int = 60,
) -> None:
    while True:
        try:
            await deliver_work_report_notifications(bot, api, database, access)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected work report notification worker error")
        await asyncio.sleep(poll_seconds)


async def deliver_work_report_notifications(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
    access: AccessController,
    now: datetime | None = None,
) -> None:
    if now is None:
        moscow_now = datetime.now(MOSCOW_TIMEZONE)
    elif now.tzinfo is None:
        moscow_now = now.replace(tzinfo=MOSCOW_TIMEZONE)
    else:
        moscow_now = now.astimezone(MOSCOW_TIMEZONE)
    if moscow_now.weekday() >= 5:
        return

    report_date = moscow_now.date().isoformat()
    current_minutes = moscow_now.hour * 60 + moscow_now.minute
    candidates = await database.list_due_work_reminders(report_date, current_minutes)
    allowed_ids = await access.allowed_ids()
    if allowed_ids is None:
        logger.warning("Work reminder recipients could not be verified")
        return

    for candidate in candidates:
        if candidate.telegram_id not in allowed_ids:
            await database.mark_work_reminder_handled(
                candidate.telegram_id,
                report_date,
                "access_denied",
            )
            continue

        reminder_text = REMINDER_TEXT
        try:
            if moscow_now.weekday() == 4:
                current_week = current_week_work_dates(moscow_now.date())
                date_keys = [value.isoformat() for value in current_week]
                result = await api.get_missing_work_report_dates(
                    candidate.telegram_id,
                    date_keys,
                )
                if not result.employee_found:
                    await database.mark_work_reminder_handled(
                        candidate.telegram_id,
                        report_date,
                        "employee_not_found",
                    )
                    continue
                missing_keys = set(result.missing_dates)
                missing_dates = [
                    value for value in current_week if value.isoformat() in missing_keys
                ]
                reminder_text = format_friday_reminder(missing_dates)
            else:
                report = await api.get_work_report(candidate.telegram_id, report_date)
        except SakuraApiError:
            # Do not mark the attempt: retry while the employee is still inside
            # the 30-minute reminder window.
            logger.warning(
                "Work report API is unavailable for Telegram ID %s",
                candidate.telegram_id,
            )
            continue

        if moscow_now.weekday() != 4:
            if not report.employee_found:
                await database.mark_work_reminder_handled(
                    candidate.telegram_id,
                    report_date,
                    "employee_not_found",
                )
                continue
            if report.found:
                await database.mark_work_reminder_handled(
                    candidate.telegram_id,
                    report_date,
                    "report_exists",
                )
                continue

        try:
            await bot.send_message(
                candidate.telegram_id,
                reminder_text,
                reply_markup=work_reminder_keyboard(),
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            await database.mark_work_reminder_handled(
                candidate.telegram_id,
                report_date,
                "telegram_unavailable",
            )
            continue
        except TelegramAPIError:
            logger.warning(
                "Telegram is temporarily unavailable for work reminder to %s",
                candidate.telegram_id,
            )
            continue

        await database.mark_work_reminder_handled(
            candidate.telegram_id,
            report_date,
            "sent",
        )


def current_week_work_dates(today: date) -> tuple[date, date, date, date, date]:
    current_monday = today - timedelta(days=today.weekday())
    return tuple(current_monday + timedelta(days=offset) for offset in range(5))


def format_friday_reminder(missing_dates: list[date]) -> str:
    if not missing_dates:
        return REMINDER_TEXT

    weekdays = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
    lines = [REMINDER_TEXT, "", "За эту неделю не заполнен отчет:"]
    lines.extend(
        f"{weekdays[value.weekday()]} • <code>{value.strftime('%d.%m.%Y')}</code>"
        for value in missing_dates
    )
    return "\n".join(lines)
