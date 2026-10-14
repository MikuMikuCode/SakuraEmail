from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from .api import SakuraApiError, SakuraAppsScriptApi
from .db import Database
from .formatting import MOSCOW_TIMEZONE
from .keyboards import work_reminder_keyboard


logger = logging.getLogger(__name__)

REMINDER_TEXT = (
    "🌸 До конца рабочего дня осталось полчаса!\n"
    "Не забудь заполнить баллы (｡•̀ᴗ-)✧"
)


async def work_report_notification_worker(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
    poll_seconds: int = 60,
) -> None:
    while True:
        try:
            await deliver_work_report_notifications(bot, api, database)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected work report notification worker error")
        await asyncio.sleep(poll_seconds)


async def deliver_work_report_notifications(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
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

    for candidate in candidates:
        try:
            report = await api.get_work_report(candidate.telegram_id, report_date)
        except SakuraApiError:
            # Do not mark the attempt: retry while the employee is still inside
            # the 30-minute reminder window.
            logger.warning(
                "Work report API is unavailable for Telegram ID %s",
                candidate.telegram_id,
            )
            continue

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
                REMINDER_TEXT,
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
