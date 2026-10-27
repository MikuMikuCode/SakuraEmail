from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, call

from aiogram import Bot

from bot.access import AccessController
from bot.api import MissingReportsResult, SakuraApiError, SakuraAppsScriptApi, WorkReport
from bot.db import Database, WorkReminderCandidate
from bot.decor import SAKURA_ANIMATED
from bot.formatting import MOSCOW_TIMEZONE
from bot.work_notifications import (
    REMINDER_TEXT,
    deliver_weekly_missing_report_notifications,
    deliver_work_report_notifications,
    format_weekly_missing_reports,
    previous_week_work_dates,
)


MONDAY = datetime(2026, 10, 12, tzinfo=MOSCOW_TIMEZONE)
SATURDAY = datetime(2026, 10, 17, 17, 30, tzinfo=MOSCOW_TIMEZONE)


def _at(hour: int, minute: int) -> datetime:
    return MONDAY.replace(hour=hour, minute=minute)


def _report(*, found: bool) -> WorkReport:
    return WorkReport(
        employee_found=True,
        found=found,
        editable=True,
        report_date="2026-10-12",
        items=(),
    )


class WorkNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self._temporary_directory.name) / "test.sqlite3")
        await self.database.connect()
        await self.database.upsert_user(
            telegram_id=101,
            username="SakuraUser",
            first_name="Sakura",
            last_name="",
            role="user",
        )

        self.bot = AsyncMock(spec=Bot)
        self.api = AsyncMock(spec=SakuraAppsScriptApi)
        self.access = AsyncMock(spec=AccessController)
        self.access.allowed_ids.return_value = {101}

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self._temporary_directory.cleanup()

    async def test_default_schedule_starts_at_1730_and_success_is_deduplicated(self) -> None:
        self.api.get_work_report.return_value = _report(found=False)

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(17, 29),
        )

        self.api.get_work_report.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(17, 30),
        )
        await deliver_work_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(17, 31),
        )

        self.api.get_work_report.assert_awaited_once_with(101, "2026-10-12")
        self.bot.send_message.assert_awaited_once()
        send_args, send_kwargs = self.bot.send_message.await_args
        self.assertEqual(send_args, (101, REMINDER_TEXT))
        self.assertIn("reply_markup", send_kwargs)

        remaining = await self.database.list_due_work_reminders(
            "2026-10-12",
            17 * 60 + 31,
        )
        self.assertEqual(remaining, [])

    async def test_weekend_skips_database_api_and_telegram(self) -> None:
        database = AsyncMock(spec=Database)

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            database,
            self.access,
            now=SATURDAY,
        )

        database.list_due_work_reminders.assert_not_awaited()
        database.mark_work_reminder_handled.assert_not_awaited()
        self.api.get_work_report.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_existing_report_suppresses_message_and_marks_date_handled(self) -> None:
        database = AsyncMock(spec=Database)
        database.list_due_work_reminders.return_value = [
            WorkReminderCandidate(telegram_id=101, end_minutes=18 * 60)
        ]
        self.api.get_work_report.return_value = _report(found=True)

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            database,
            self.access,
            now=_at(17, 30),
        )

        self.bot.send_message.assert_not_awaited()
        database.mark_work_reminder_handled.assert_awaited_once_with(
            101,
            "2026-10-12",
            "report_exists",
        )

    async def test_denied_user_never_receives_work_reminder(self) -> None:
        database = AsyncMock(spec=Database)
        database.list_due_work_reminders.return_value = [
            WorkReminderCandidate(telegram_id=101, end_minutes=18 * 60)
        ]
        self.access.allowed_ids.return_value = set()

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            database,
            self.access,
            now=_at(17, 30),
        )

        self.api.get_work_report.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()
        database.mark_work_reminder_handled.assert_awaited_once_with(
            101,
            "2026-10-12",
            "access_denied",
        )

    async def test_api_error_leaves_reminder_unhandled_for_retry(self) -> None:
        database = AsyncMock(spec=Database)
        candidate = WorkReminderCandidate(telegram_id=101, end_minutes=18 * 60)
        database.list_due_work_reminders.return_value = [candidate]
        self.api.get_work_report.side_effect = SakuraApiError("temporary failure")

        await deliver_work_report_notifications(
            self.bot,
            self.api,
            database,
            self.access,
            now=_at(17, 30),
        )
        await deliver_work_report_notifications(
            self.bot,
            self.api,
            database,
            self.access,
            now=_at(17, 31),
        )

        self.assertEqual(
            self.api.get_work_report.await_args_list,
            [
                call(101, "2026-10-12"),
                call(101, "2026-10-12"),
            ],
        )
        database.mark_work_reminder_handled.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()

    async def test_monday_weekly_reminder_lists_missing_weekdays_and_is_deduplicated(self) -> None:
        self.api.get_missing_work_report_dates.return_value = MissingReportsResult(
            employee_found=True,
            missing_dates=("2026-10-05", "2026-10-09"),
        )

        await deliver_weekly_missing_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(18, 29),
        )
        self.bot.send_message.assert_not_awaited()

        await deliver_weekly_missing_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(18, 30),
        )
        await deliver_weekly_missing_report_notifications(
            self.bot,
            self.api,
            self.database,
            self.access,
            now=_at(18, 31),
        )

        self.api.get_missing_work_report_dates.assert_awaited_once_with(
            101,
            [
                "2026-10-05",
                "2026-10-06",
                "2026-10-07",
                "2026-10-08",
                "2026-10-09",
            ],
        )
        self.bot.send_message.assert_awaited_once()
        args, kwargs = self.bot.send_message.await_args
        self.assertEqual(args[0], 101)
        self.assertIn("ПН • <code>05.10.2026</code>", args[1])
        self.assertIn("ПТ • <code>09.10.2026</code>", args[1])
        self.assertIn("reply_markup", kwargs)

    def test_previous_week_and_message_format_are_fixed_to_monday_friday(self) -> None:
        self.assertEqual(
            previous_week_work_dates(date(2026, 10, 12)),
            (
                date(2026, 10, 5),
                date(2026, 10, 6),
                date(2026, 10, 7),
                date(2026, 10, 8),
                date(2026, 10, 9),
            ),
        )
        self.assertEqual(
            format_weekly_missing_reports(
                [date(2026, 10, 5), date(2026, 10, 9)]
            ),
            f"{SAKURA_ANIMATED} За прошлую неделю не заполнен отчёт:\n"
            "ПН • <code>05.10.2026</code>\n"
            "ПТ • <code>09.10.2026</code>",
        )


if __name__ == "__main__":
    unittest.main()
