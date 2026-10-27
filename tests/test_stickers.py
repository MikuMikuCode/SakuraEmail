from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.enums import MessageEntityType

from bot.handlers import StickerPackResponder, _custom_emoji_ids


class StickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sticker_pack_is_loaded_once_and_cached(self) -> None:
        bot = AsyncMock(spec=Bot)
        bot.get_sticker_set.return_value = SimpleNamespace(
            stickers=[
                SimpleNamespace(file_id="sticker-1"),
                SimpleNamespace(file_id="sticker-2"),
            ]
        )
        responder = StickerPackResponder("AinoStick")

        first = await responder.choose(bot)
        second = await responder.choose(bot)

        self.assertIn(first, {"sticker-1", "sticker-2"})
        self.assertIn(second, {"sticker-1", "sticker-2"})
        bot.get_sticker_set.assert_awaited_once_with(name="AinoStick")

    async def test_custom_emoji_ids_are_deduplicated(self) -> None:
        custom = SimpleNamespace(
            type=MessageEntityType.CUSTOM_EMOJI,
            custom_emoji_id="emoji-123",
        )
        regular = SimpleNamespace(
            type=MessageEntityType.BOLD,
            custom_emoji_id=None,
        )
        message = SimpleNamespace(
            entities=[custom, regular, custom],
            caption_entities=None,
        )

        self.assertEqual(_custom_emoji_ids(message), ("emoji-123",))


if __name__ == "__main__":
    unittest.main()
