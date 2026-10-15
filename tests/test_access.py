from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from bot.access import AccessController, AccessDecision
from bot.api import AccessSnapshot, SakuraApiUnavailable, SakuraAppsScriptApi
from bot.db import Database


class AccessControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self._temporary_directory.name) / "test.sqlite3")
        await self.database.connect()
        for telegram_id in (101, 202, 303):
            await self.database.upsert_user(
                telegram_id=telegram_id,
                username=f"user{telegram_id}",
                first_name="User",
                last_name="",
                role="user",
            )
        self.api = AsyncMock(spec=SakuraAppsScriptApi)

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self._temporary_directory.cleanup()

    async def test_snapshot_is_reused_for_three_day_cache(self) -> None:
        self.api.get_access_snapshot.return_value = AccessSnapshot(
            allowed_ids=frozenset({101}),
            blocked_ids=frozenset({202}),
        )
        access = AccessController(self.database, self.api)

        self.assertEqual(await access.check(101), AccessDecision.ALLOWED)
        self.assertEqual(await access.check(202), AccessDecision.DENIED)
        self.assertEqual(await access.check(303), AccessDecision.DENIED)
        self.api.get_access_snapshot.assert_awaited_once_with()

        recipients = await access.allowed_registered_users()
        self.assertIsNotNone(recipients)
        assert recipients is not None
        self.assertEqual([user.telegram_id for user in recipients], [101])

    async def test_unavailable_initial_snapshot_fails_closed(self) -> None:
        self.api.get_access_snapshot.side_effect = SakuraApiUnavailable("offline")
        access = AccessController(self.database, self.api)

        self.assertEqual(await access.check(101), AccessDecision.UNAVAILABLE)

    async def test_manual_refresh_ignores_cache_and_returns_registered_counts(self) -> None:
        self.api.get_access_snapshot.side_effect = [
            AccessSnapshot(
                allowed_ids=frozenset({101}),
                blocked_ids=frozenset({202}),
            ),
            AccessSnapshot(
                allowed_ids=frozenset({101, 202}),
                blocked_ids=frozenset(),
            ),
        ]
        access = AccessController(self.database, self.api)

        self.assertEqual(await access.check(101), AccessDecision.ALLOWED)
        summary = await access.refresh_now()

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.allowed, 2)
        self.assertEqual(summary.blocked, 0)
        self.assertEqual(summary.missing, 1)
        self.assertEqual(summary.total, 3)
        self.assertEqual(self.api.get_access_snapshot.await_count, 2)


if __name__ == "__main__":
    unittest.main()
