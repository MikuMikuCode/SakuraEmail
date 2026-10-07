from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from bot.api import SakuraAppsScriptApi


class ApiParsingTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
