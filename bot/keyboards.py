from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


MY_KEYS_TEXT = "Мои ключи"
LEGACY_REQUEST_KEY_TEXT = "🌸 Запросить ключ"
THANKS_TEXT = "Спасибо!"
MANAGEMENT_TEXT = "⚙️ Управление"


def main_keyboard(is_creator: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MY_KEYS_TEXT)],
        [KeyboardButton(text=THANKS_TEXT)],
    ]
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


def cancel_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить", callback_data="cancel_action")]
        ]
    )


def management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="💌 Заявки", callback_data="admin_requests")],
            [
                InlineKeyboardButton(
                    text="✉️ Написать пользователю",
                    callback_data="admin_message_user",
                )
            ],
        ]
    )


def close_request_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Выполнено",
                    callback_data=f"close_request:{request_id}",
                )
            ]
        ]
    )


def thanks_settings_keyboard(notifications_enabled: bool) -> InlineKeyboardMarkup:
    text = (
        "Отключить уведомления о спасибо"
        if notifications_enabled
        else "Включить уведомления о спасибо"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="toggle_thanks_notifications")]
        ]
    )
