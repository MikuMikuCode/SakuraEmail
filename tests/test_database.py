from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot.db import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
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

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self._temporary_directory.cleanup()

    async def test_thanks_are_limited_and_counted(self) -> None:
        gratitude_id = await self.database.record_thanks(101, "SakuraUser")
        self.assertIsNotNone(gratitude_id)
        assert gratitude_id is not None
        self.assertIsNone(await self.database.record_thanks(101, "SakuraUser"))

        self.assertTrue(await self.database.can_comment_on_thanks(gratitude_id, 101))
        self.assertFalse(await self.database.can_comment_on_thanks(gratitude_id, 999))
        self.assertFalse(
            await self.database.add_thanks_comment(gratitude_id, 999, "Чужой комментарий")
        )
        self.assertTrue(
            await self.database.add_thanks_comment(
                gratitude_id,
                101,
                "Спасибо за макрос!",
            )
        )
        self.assertFalse(await self.database.can_comment_on_thanks(gratitude_id, 101))
        self.assertFalse(
            await self.database.add_thanks_comment(gratitude_id, 101, "Второй комментарий")
        )

        stats = await self.database.get_thanks_stats()
        self.assertEqual(stats.today, 1)
        self.assertEqual(stats.total, 1)
        self.assertTrue(stats.notifications_enabled)

        await self.database.set_thanks_notifications_enabled(False)
        stats = await self.database.get_thanks_stats()
        self.assertFalse(stats.notifications_enabled)

        await self.database.delete_thanks_comment(gratitude_id, 101)
        self.assertTrue(await self.database.can_comment_on_thanks(gratitude_id, 101))

    async def test_user_lookup_and_request_completion(self) -> None:
        user = await self.database.find_user_by_username("sAKURAuSER")
        self.assertIsNotNone(user)
        self.assertEqual(user.telegram_id, 101)

        request_id = await self.database.create_support_request(
            101,
            "SakuraUser",
            "Нужна помощь",
        )
        self.assertEqual(await self.database.close_support_request(request_id), 101)
        self.assertIsNone(await self.database.close_support_request(request_id))

    async def test_work_settings_use_defaults_and_persist_changes(self) -> None:
        settings = await self.database.get_work_settings(101)
        self.assertEqual(settings.start_minutes, 9 * 60)
        self.assertEqual(settings.end_minutes, 18 * 60)
        self.assertTrue(settings.notifications_enabled)

        await self.database.set_work_notifications_enabled(101, False)
        await self.database.set_work_schedule(101, 10 * 60 + 15, 19 * 60 + 30)

        settings = await self.database.get_work_settings(101)
        self.assertEqual(settings.start_minutes, 10 * 60 + 15)
        self.assertEqual(settings.end_minutes, 19 * 60 + 30)
        self.assertFalse(settings.notifications_enabled)

        await self.database.set_work_notifications_enabled(101, True)
        settings = await self.database.get_work_settings(101)
        self.assertTrue(settings.notifications_enabled)
        self.assertEqual(settings.start_minutes, 10 * 60 + 15)
        self.assertEqual(settings.end_minutes, 19 * 60 + 30)

    async def test_work_reminder_due_window_and_deduplication(self) -> None:
        work_date = "2026-10-14"

        self.assertEqual(
            await self.database.list_due_work_reminders(work_date, 17 * 60 + 29),
            [],
        )

        at_half_past_five = await self.database.list_due_work_reminders(
            work_date,
            17 * 60 + 30,
        )
        self.assertEqual([candidate.telegram_id for candidate in at_half_past_five], [101])

        before_end = await self.database.list_due_work_reminders(work_date, 17 * 60 + 59)
        self.assertEqual([candidate.telegram_id for candidate in before_end], [101])
        self.assertEqual(await self.database.list_due_work_reminders(work_date, 18 * 60), [])

        await self.database.mark_work_reminder_handled(101, work_date, "sent")
        self.assertEqual(
            await self.database.list_due_work_reminders(work_date, 17 * 60 + 30),
            [],
        )

        next_day = await self.database.list_due_work_reminders(
            "2026-10-15",
            17 * 60 + 30,
        )
        self.assertEqual([candidate.telegram_id for candidate in next_day], [101])

        # INSERT OR IGNORE keeps the first result and, importantly, never
        # creates a second reminder candidate for the same employee and day.
        await self.database.mark_work_reminder_handled(101, work_date, "report_exists")
        self.assertEqual(
            await self.database.list_due_work_reminders(work_date, 17 * 60 + 30),
            [],
        )

    async def test_disabled_work_notifications_are_not_due(self) -> None:
        await self.database.set_work_notifications_enabled(101, False)
        self.assertEqual(
            await self.database.list_due_work_reminders("2026-10-14", 17 * 60 + 30),
            [],
        )

    async def test_access_snapshot_replaces_old_values_and_filters_registered_users(self) -> None:
        await self.database.upsert_user(
            telegram_id=202,
            username="BlockedUser",
            first_name="Blocked",
            last_name="",
            role="user",
        )
        await self.database.upsert_user(
            telegram_id=303,
            username="MissingUser",
            first_name="Missing",
            last_name="",
            role="user",
        )

        await self.database.replace_access_snapshot({101, 999}, {202})

        self.assertEqual(await self.database.get_access_status(101), "allowed")
        self.assertEqual(await self.database.get_access_status(202), "blocked")
        self.assertIsNone(await self.database.get_access_status(303))
        self.assertEqual(await self.database.list_allowed_user_ids(), {101})
        self.assertIsNotNone(await self.database.get_access_snapshot_synced_at())

        await self.database.replace_access_snapshot({202}, set())
        self.assertIsNone(await self.database.get_access_status(101))
        self.assertEqual(await self.database.get_access_status(202), "allowed")
        self.assertEqual(await self.database.list_allowed_user_ids(), {202})


if __name__ == "__main__":
    unittest.main()
