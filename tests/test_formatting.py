from __future__ import annotations

import unittest

from bot.formatting import display_license_type, format_datetime


class FormattingTests(unittest.TestCase):
    def test_apps_script_datetime_is_reformatted_without_time_shift(self) -> None:
        self.assertEqual(
            format_datetime("2027-10-01 21:15:30"),
            "01.10.2027 21:15:30",
        )

    def test_utc_database_datetime_is_shown_in_moscow_time(self) -> None:
        self.assertEqual(
            format_datetime("2027-10-01T18:15:30+00:00"),
            "01.10.2027 21:15:30",
        )

    def test_license_types_are_canonicalized(self) -> None:
        self.assertEqual(display_license_type("maket-pro"), "MaketPro")
        self.assertEqual(display_license_type("Maket"), "Maket")


if __name__ == "__main__":
    unittest.main()
