import unittest

from bot.decor import (
    DECORATION_DOT,
    MINIMAL_FLOWER,
    PINK_STARS,
    SAKURA_1,
    SAKURA_2,
    SAKURA_3,
    SAKURA_4,
    SAKURA_ANIMATED,
)


class CustomEmojiDecorTests(unittest.TestCase):
    def test_all_supplied_custom_emoji_ids_are_present(self) -> None:
        expected = {
            SAKURA_1: "5321445337074780874",
            SAKURA_2: "5341648665666689667",
            SAKURA_3: "5343770933561692873",
            SAKURA_4: "5303076693957682292",
            SAKURA_ANIMATED: "5399982606538280504",
            DECORATION_DOT: "5363997884473696887",
            PINK_STARS: "5456184310895748720",
            MINIMAL_FLOWER: "5352799848171062377",
        }

        for markup, emoji_id in expected.items():
            with self.subTest(emoji_id=emoji_id):
                self.assertIn(f'emoji-id="{emoji_id}"', markup)
                self.assertTrue(markup.startswith("<tg-emoji "))
                self.assertTrue(markup.endswith("</tg-emoji>"))


if __name__ == "__main__":
    unittest.main()
