from __future__ import annotations

import unittest
from datetime import date

from bot.api import WorkReportItem, WorkType
from bot.work_handlers import (
    format_existing_report,
    format_report_date_label,
    format_report_confirmation,
    format_report_prompt,
    parse_report_date,
    parse_report_text,
    parse_schedule,
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
    def test_report_prompt_contains_expandable_escaped_catalog_and_inline_example(self) -> None:
        prompt = format_report_prompt(
            [
                WorkType(article="FGR", coefficient=1, name="Фигурка 15см"),
                WorkType(article="FGR1", coefficient=1, name="Фигурка <15см>"),
            ]
        )

        self.assertIn("Считаем только <b>оригинальные макеты</b> 🌸", prompt)
        self.assertIn("Не BVKL, а VKL. Не ZTOP, а TOP.", prompt)
        self.assertIn(
            "<blockquote expandable>FGR • Фигурка 15см\n"
            "FGR1 • Фигурка &lt;15см&gt;</blockquote>",
            prompt,
        )
        self.assertIn(
            "<code>FGR 12</code> или <code>FGR 12, SNB 6</code>",
            prompt,
        )

    def test_existing_today_report_is_shown_before_replacement(self) -> None:
        self.assertEqual(
            format_existing_report(
                date(2026, 10, 12),
                [
                    WorkReportItem(article="FGR", quantity=10),
                    WorkReportItem(article="SNB", quantity=9),
                ]
            ),
            "🌸 Вы уже отправляли отчёт за <code>ПН • 12.10.2026</code>:\n\n"
            "FGR · 10\n"
            "SNB · 9\n\n"
            "Изменить?",
        )

    def test_arbitrary_report_date_and_label_are_supported(self) -> None:
        self.assertEqual(parse_report_date("12.10.2024"), date(2024, 10, 12))
        self.assertIsNone(parse_report_date("2024-10-12"))
        self.assertEqual(
            format_report_date_label(date(2026, 10, 12)),
            "ПН • 12.10.2026",
        )
        self.assertEqual(
            format_report_date_label(date(2026, 10, 18)),
            "ВС • 18.10.2026",
        )

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
