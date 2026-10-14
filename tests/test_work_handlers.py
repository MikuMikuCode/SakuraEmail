from __future__ import annotations

import unittest
from datetime import date

from bot.api import WorkReportItem
from bot.work_handlers import (
    format_date_button,
    format_report_confirmation,
    format_existing_today_report,
    parse_report_text,
    parse_schedule,
    recent_report_dates,
)


class WorkReportParsingTests(unittest.TestCase):
    def test_single_report_item_is_normalized(self) -> None:
        self.assertEqual(
            parse_report_text("  fgr 12  "),
            (WorkReportItem(article="FGR", quantity=12),),
        )

    def test_multiple_separators_and_duplicate_articles_are_supported(self) -> None:
        self.assertEqual(
            parse_report_text("fgr 12, SNB 6; fgr 3\nabc-1 2"),
            (
                WorkReportItem(article="FGR", quantity=15),
                WorkReportItem(article="SNB", quantity=6),
                WorkReportItem(article="ABC-1", quantity=2),
            ),
        )

    def test_invalid_report_values_are_rejected(self) -> None:
        invalid_values = (
            "",
            "FGR",
            "FGR zero",
            "FGR 0",
            "FGR -1",
            "FGR 1.5",
            "FGR 1,",
            "FGR 1,, SNB 2",
            "FGR 1000001",
            "FGR 999999, FGR 2",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_report_text(value)


class WorkScheduleParsingTests(unittest.TestCase):
    def test_schedule_accepts_supported_dashes_and_moscow_suffix(self) -> None:
        self.assertEqual(parse_schedule("09:00-18:00"), (540, 1080))
        self.assertEqual(parse_schedule("9:15–17:45 мск"), (555, 1065))
        self.assertEqual(parse_schedule("10:00—19:00 МСК"), (600, 1140))

    def test_invalid_and_too_short_schedules_are_rejected(self) -> None:
        invalid_values = (
            "",
            "09.00-18.00",
            "24:00-18:00",
            "09:60-18:00",
            "18:00-09:00",
            "09:00-09:00",
            "09:00-09:29",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_schedule(value)


class WorkReportFormattingTests(unittest.TestCase):
    def test_existing_today_report_is_shown_before_replacement(self) -> None:
        self.assertEqual(
            format_existing_today_report(
                [
                    WorkReportItem(article="FGR", quantity=10),
                    WorkReportItem(article="SNB", quantity=9),
                ]
            ),
            "🌸 Вы сегодня его уже отправляли:\n\n"
            "FGR · 10\n"
            "SNB · 9\n\n"
            "Изменить?",
        )

    def test_recent_dates_are_three_calendar_days_in_chronological_order(self) -> None:
        self.assertEqual(
            recent_report_dates(date(2026, 10, 14)),
            (
                date(2026, 10, 12),
                date(2026, 10, 13),
                date(2026, 10, 14),
            ),
        )

    def test_date_button_uses_fixed_russian_weekday(self) -> None:
        self.assertEqual(format_date_button(date(2026, 10, 12)), "Пн • 12.10")
        self.assertEqual(format_date_button(date(2026, 10, 18)), "Вс • 18.10")

    def test_confirmation_matches_required_format_and_escapes_article(self) -> None:
        self.assertEqual(
            format_report_confirmation(
                date(2026, 10, 12),
                [
                    WorkReportItem(article="FGR", quantity=1),
                    WorkReportItem(article="<SNB>", quantity=3),
                ],
            ),
            "🌸 <b>Отчёт за 12.10.2026</b>\n\n"
            "FGR · 1\n"
            "&lt;SNB&gt; · 3\n\n"
            "Всё верно? Отправить отчёт?",
        )


if __name__ == "__main__":
    unittest.main()
