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
        self.assertTrue(await self.database.record_thanks(101, "SakuraUser"))
        self.assertFalse(await self.database.record_thanks(101, "SakuraUser"))

        stats = await self.database.get_thanks_stats()
        self.assertEqual(stats.today, 1)
        self.assertEqual(stats.total, 1)
        self.assertTrue(stats.notifications_enabled)

        await self.database.set_thanks_notifications_enabled(False)
        stats = await self.database.get_thanks_stats()
        self.assertFalse(stats.notifications_enabled)

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


if __name__ == "__main__":
    unittest.main()
