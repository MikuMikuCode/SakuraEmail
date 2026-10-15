from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


REPORT_TEXT = "Отчет"
LEGACY_REPORT_TEXT = "Отчёт"
KEYS_TEXT = "Ключи"
MY_KEYS_TEXT = "Мои ключи"
LEGACY_REQUEST_KEY_TEXT = "🌸 Запросить ключ"
SETTINGS_TEXT = "Настройки"
THANKS_TEXT = "Спасибо!"
MANAGEMENT_TEXT = "⚙️ Управление"


def main_keyboard(is_creator: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=REPORT_TEXT), KeyboardButton(text=KEYS_TEXT)],
        [KeyboardButton(text=SETTINGS_TEXT)],
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


def report_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Отменить", callback_data="work_report_cancel"),
                InlineKeyboardButton(text="Изменить", callback_data="work_report_change"),
            ],
            [InlineKeyboardButton(text="✅ Отправить", callback_data="work_report_submit")],
        ]
    )


def existing_report_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить",
                    callback_data="work_report_replace_today",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="work_report_keep_today",
                ),
            ]
        ]
    )


def work_settings_keyboard(notifications_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = (
        "Выключить уведомления"
        if notifications_enabled
        else "Включить уведомления"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить график работы",
                    callback_data="work_schedule_change",
                )
            ],
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data="work_notifications_toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить старый отчёт",
                    callback_data="work_old_reports",
                )
            ],
        ]
    )


def old_report_dates_keyboard(dates: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"work_report_view:{date_key}",
                )
                for date_key, label in dates
            ]
        ]
    )


def old_report_detail_keyboard(report_date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить",
                    callback_data=f"work_report_edit:{report_date}",
                )
            ]
        ]
    )


def work_reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Заполнить отчёт", callback_data="work_report_today")]
        ]
    )


def add_thanks_comment_keyboard(gratitude_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить",
                    callback_data=f"thanks_comment:{gratitude_id}",
                )
            ]
        ]
    )


def management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить доступ",
                    callback_data="admin_refresh_access",
                )
            ],
            [InlineKeyboardButton(text="💌 Заявки", callback_data="admin_requests")],
            [
                InlineKeyboardButton(
                    text="📣 Сообщение всем",
                    callback_data="admin_broadcast",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✉️ Написать пользователю",
                    callback_data="admin_message_user",
                )
            ],
        ]
    )


def broadcast_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data="admin_broadcast_cancel",
                ),
                InlineKeyboardButton(
                    text="✅ Отправить всем",
                    callback_data="admin_broadcast_send",
                ),
            ]
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
