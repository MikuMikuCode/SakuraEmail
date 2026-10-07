from __future__ import annotations

import asyncio
import hashlib
import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from .api import RenewalNotification, SakuraApiError, SakuraAppsScriptApi
from .db import Database
from .formatting import display_license_type, format_datetime


logger = logging.getLogger(__name__)


async def notification_worker(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
    poll_seconds: int,
) -> None:
    while True:
        try:
            await deliver_renewal_notifications(bot, api, database)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected renewal notification worker error")
        await asyncio.sleep(poll_seconds)


async def deliver_renewal_notifications(
    bot: Bot,
    api: SakuraAppsScriptApi,
    database: Database,
) -> None:
    try:
        notifications = await api.get_expiring_renewals()
    except SakuraApiError:
        logger.warning("Renewal notification API is temporarily unavailable")
        return

    delivered = 0
    for notification in notifications:
        if not await database.user_exists(notification.telegram_id):
            continue

        notification_hash = _notification_hash(notification)
        if await database.notification_was_sent(notification_hash):
            continue

        text = (
            "🌸 <b>Ваша лицензия скоро закончится</b>\n\n"
            f"Новый ключ:\n<blockquote><code>{escape(notification.new_key)}</code></blockquote>\n"
            f"Вид подписки: {escape(display_license_type(notification.license_type))}"
        )
        if notification.new_expires_at:
            text += f"\nДействует до: {escape(format_datetime(notification.new_expires_at))}"

        try:
            await bot.send_message(notification.telegram_id, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            # Telegram bots cannot initiate a dialog and cannot write to a
            # user who blocked the bot. Do not mark the message as delivered.
            continue

        await database.mark_notification_sent(notification_hash, notification.telegram_id)
        delivered += 1

    if delivered:
        logger.info("Delivered %s renewal notification(s)", delivered)


def _notification_hash(notification: RenewalNotification) -> str:
    value = (
        f"{notification.telegram_id}|"
        f"{notification.expiring_key.upper()}|"
        f"{notification.new_key.upper()}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
