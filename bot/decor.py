from __future__ import annotations


def custom_emoji(emoji_id: str, fallback: str) -> str:
    """Return Telegram HTML for a custom emoji with a readable fallback."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


SAKURA_1 = custom_emoji("5321445337074780874", "🌸")
SAKURA_2 = custom_emoji("5341648665666689667", "🌸")
SAKURA_3 = custom_emoji("5343770933561692873", "🌸")
SAKURA_4 = custom_emoji("5303076693957682292", "🌸")
SAKURA_ANIMATED = custom_emoji("5399982606538280504", "🌸")
DECORATION_DOT = custom_emoji("5363997884473696887", "▫️")
PINK_STARS = custom_emoji("5456184310895748720", "✨")
MINIMAL_FLOWER = custom_emoji("5352799848171062377", "🌸")
