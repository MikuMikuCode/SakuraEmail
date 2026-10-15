from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from bot.api import (
    AccessDirectoryEntry,
    AccessSnapshot,
    SakuraApiUnavailable,
    SakuraAppsScriptApi,
    WorkCatalog,
    WorkProfile,
    WorkReport,
    WorkReportItem,
    WorkReportSaveResult,
    WorkType,
)


class ApiParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_access_snapshot_prefers_blocked_duplicate_and_skips_bad_ids(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "users": [
                    {"telegram_id": "101", "blocked": False},
                    {"telegram_id": 202, "blocked": False},
                    {"telegram_id": "101", "blocked": True},
                    {"telegram_id": "bad", "blocked": True},
                    "bad row",
                ],
                "employees": [
                    {
                        "telegram_id": "",
                        "telegram_username": " @MissingUser ",
                        "full_name": " Иванова Анна Сергеевна ",
                        "blocked": False,
                    },
                    {
                        "telegram_id": "101",
                        "telegram_username": "BlockedUser",
                        "full_name": "Петров Иван",
                        "blocked": True,
                    },
                    {"telegram_id": "bad", "telegram_username": "", "full_name": ""},
                ],
            }
        )

        self.assertEqual(
            await api.get_access_snapshot(),
            AccessSnapshot(
                allowed_ids=frozenset({202}),
                blocked_ids=frozenset({101}),
                employees=(
                    AccessDirectoryEntry(
                        telegram_id=None,
                        username="MissingUser",
                        full_name="Иванова Анна Сергеевна",
                        blocked=False,
                    ),
                    AccessDirectoryEntry(
                        telegram_id=101,
                        username="BlockedUser",
                        full_name="Петров Иван",
                        blocked=True,
                    ),
                ),
            ),
        )
        api._post.assert_awaited_once_with("bot_access_snapshot")

    async def test_license_type_is_read_for_keys_and_renewals(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            side_effect=[
                {
                    "keys": [
                        {
                            "key": "AAAA-BBBB",
                            "license_type": "MaketPro",
                            "status": "Свободен",
                            "status_code": "free",
                            "expires_at": "2027-10-01 21:15:30",
                            "row_number": 10,
                        }
                    ]
                },
                {
                    "notifications": [
                        {
                            "telegram_id": "101",
                            "license_type": "Maket",
                            "expiring_key": "OLD-KEY",
                            "expiring_at": "2027-09-28 21:15:30",
                            "new_key": "NEW-KEY",
                            "new_expires_at": "2027-10-28 21:15:30",
                        }
                    ]
                },
            ]
        )

        keys = await api.get_active_keys(101)
        renewals = await api.get_expiring_renewals()

        self.assertEqual(keys[0].license_type, "MaketPro")
        self.assertEqual(renewals[0].license_type, "Maket")

    async def test_work_profile_is_parsed_and_request_uses_string_telegram_id(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "found": True,
                "display_name": "  Иван Иванов  ",
                "full_name": "  Иванов Иван Иванович  ",
                "stats": {
                    "today": "12.5",
                    "week": 48,
                    "month": "not-a-number",
                },
            }
        )

        profile = await api.get_work_profile(123456789)

        self.assertEqual(
            profile,
            WorkProfile(
                display_name="Иван Иванов",
                full_name="Иванов Иван Иванович",
                today_points=12.5,
                week_points=48.0,
                month_points=0.0,
            ),
        )
        api._post.assert_awaited_once_with(
            "bot_work_profile",
            telegram_id="123456789",
        )

    async def test_work_profile_returns_none_when_employee_is_not_found(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(return_value={"found": False})

        self.assertIsNone(await api.get_work_profile(101))

    async def test_work_profile_treats_invalid_stats_collection_as_empty(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "found": True,
                "display_name": "Иван Иванов",
                "full_name": "Иванов Иван Иванович",
                "stats": [1, 2, 3],
            }
        )

        profile = await api.get_work_profile(101)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.today_points, 0.0)
        self.assertEqual(profile.week_points, 0.0)
        self.assertEqual(profile.month_points, 0.0)

    async def test_work_catalog_is_normalized_and_invalid_entries_are_skipped(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "found": True,
                "items": [
                    {"article": " fgr ", "coefficient": "1"},
                    {"article": "SnB", "coefficient": 3.5},
                    {"article": "", "coefficient": 2},
                    {"article": "ZERO", "coefficient": 0},
                    {"article": "NEG", "coefficient": -1},
                    {"article": "BAD", "coefficient": "invalid"},
                    "not-a-dict",
                ],
            }
        )

        catalog = await api.get_work_catalog(777)

        self.assertEqual(
            catalog,
            WorkCatalog(
                employee_found=True,
                items=(
                    WorkType(article="FGR", coefficient=1.0),
                    WorkType(article="SNB", coefficient=3.5),
                ),
            ),
        )
        api._post.assert_awaited_once_with(
            "bot_report_catalog",
            telegram_id="777",
        )

    async def test_work_catalog_rejects_invalid_items_collection(self) -> None:
        for raw_items in (None, {}, "FGR"):
            with self.subTest(raw_items=raw_items):
                api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
                api._post = AsyncMock(return_value={"found": True, "items": raw_items})

                with self.assertRaisesRegex(
                    SakuraApiUnavailable,
                    "invalid work catalog",
                ):
                    await api.get_work_catalog(101)

    async def test_work_report_is_parsed_and_request_contains_report_date(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "employee_found": True,
                "found": True,
                "editable": True,
                "report_date": " 2026-10-12 ",
                "items": [
                    {"article": " fgr ", "quantity": "12"},
                    {"article": "SnB", "quantity": 6},
                    {"article": "", "quantity": 4},
                    {"article": "ZERO", "quantity": 0},
                    {"article": "NEG", "quantity": -2},
                    {"article": "BAD", "quantity": "1.5"},
                    {"article": "FLOAT", "quantity": 1.5},
                    {"article": "BOOL", "quantity": True},
                    None,
                ],
            }
        )

        report = await api.get_work_report(555, "2026-10-12")

        self.assertEqual(
            report,
            WorkReport(
                employee_found=True,
                found=True,
                editable=True,
                report_date="2026-10-12",
                items=(
                    WorkReportItem(article="FGR", quantity=12),
                    WorkReportItem(article="SNB", quantity=6),
                ),
            ),
        )
        api._post.assert_awaited_once_with(
            "bot_get_report",
            telegram_id="555",
            report_date="2026-10-12",
        )

    async def test_work_report_uses_requested_date_when_response_omits_it(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "employee_found": True,
                "found": False,
                "editable": False,
                "items": [],
            }
        )

        report = await api.get_work_report(101, "2026-10-11")

        self.assertEqual(report.report_date, "2026-10-11")
        self.assertFalse(report.found)
        self.assertEqual(report.items, ())

    async def test_work_report_rejects_invalid_items_collection(self) -> None:
        for raw_items in (None, {}, "FGR 12"):
            with self.subTest(raw_items=raw_items):
                api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
                api._post = AsyncMock(return_value={"items": raw_items})

                with self.assertRaisesRegex(
                    SakuraApiUnavailable,
                    "invalid report items",
                ):
                    await api.get_work_report(101, "2026-10-12")

    async def test_save_work_report_sends_items_and_parses_result(self) -> None:
        api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
        api._post = AsyncMock(
            return_value={
                "saved": True,
                "message": "  report_saved  ",
                "unknown_articles": [" dfg ", "", "  ", 123],
            }
        )
        items = [
            WorkReportItem(article="FGR", quantity=12),
            WorkReportItem(article="SNB", quantity=6),
        ]

        result = await api.save_work_report(999, "2026-10-12", items)

        self.assertEqual(
            result,
            WorkReportSaveResult(
                saved=True,
                message="report_saved",
                unknown_articles=("DFG", "123"),
            ),
        )
        api._post.assert_awaited_once_with(
            "bot_save_report",
            telegram_id="999",
            report_date="2026-10-12",
            items=[
                {"article": "FGR", "quantity": 12},
                {"article": "SNB", "quantity": 6},
            ],
        )

    async def test_save_work_report_treats_invalid_unknown_articles_as_empty(self) -> None:
        for raw_unknown_articles in (None, {}, "DFG"):
            with self.subTest(raw_unknown_articles=raw_unknown_articles):
                api = SakuraAppsScriptApi("https://example.com/exec", "x" * 32)
                api._post = AsyncMock(
                    return_value={
                        "saved": False,
                        "message": "unknown_articles",
                        "unknown_articles": raw_unknown_articles,
                    }
                )

                result = await api.save_work_report(101, "2026-10-12", [])

                self.assertEqual(
                    result,
                    WorkReportSaveResult(
                        saved=False,
                        message="unknown_articles",
                        unknown_articles=(),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
