from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


REQUEST_KEY_TEXT = "🌸 Запросить ключ"
MANAGEMENT_TEXT = "⚙️ Управление"


def main_keyboard(is_creator: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=REQUEST_KEY_TEXT)]]
    if is_creator:
        rows.append([KeyboardButton(text=MANAGEMENT_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def application_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оставить заявку", callback_data="new_key_request")]
        ]
    )


def management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💌 Заявки", callback_data="admin_requests")],
        ]
    )


def close_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Закрыть заявку",
                    callback_data=f"close_request:{request_id}",
                )
            ]
        ]
    )

