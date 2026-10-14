from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from .api import SakuraApiError, SakuraAppsScriptApi
from .db import BotUser, Database


logger = logging.getLogger(__name__)

ACCESS_CACHE_TTL = timedelta(days=3)
FAILED_REFRESH_RETRY = timedelta(minutes=5)
CASTLE_MESSAGE = "🍄 Прости, твоя принцесса в другом замке (｡•́︿•̀｡)"
ACCESS_UNAVAILABLE_MESSAGE = (
    "🌸 Сейчас я не могу проверить доступ. Попробуйте немного позже."
)


class AccessDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class AccessController:
    def __init__(
        self,
        database: Database,
        api: SakuraAppsScriptApi,
        cache_ttl: timedelta = ACCESS_CACHE_TTL,
    ) -> None:
        self._database = database
        self._api = api
        self._cache_ttl = cache_ttl
        self._refresh_lock = asyncio.Lock()
        self._next_refresh_attempt: datetime | None = None

    async def check(self, telegram_id: int) -> AccessDecision:
        if not await self.ensure_fresh():
            return AccessDecision.UNAVAILABLE
        status = await self._database.get_access_status(telegram_id)
        return (
            AccessDecision.ALLOWED
            if status == "allowed"
            else AccessDecision.DENIED
        )

    async def allowed_registered_users(self) -> list[BotUser] | None:
        if not await self.ensure_fresh():
            return None
        allowed_ids = await self._database.list_allowed_user_ids()
        return [
            user
            for user in await self._database.list_users()
            if user.telegram_id in allowed_ids
        ]

    async def allowed_ids(self) -> set[int] | None:
        if not await self.ensure_fresh():
            return None
        return await self._database.list_allowed_user_ids()

    async def ensure_fresh(self) -> bool:
        synced_at = await self._database.get_access_snapshot_synced_at()
        now = datetime.now(timezone.utc)
        if synced_at is not None and now - synced_at < self._cache_ttl:
            return True
        if self._next_refresh_attempt is not None and now < self._next_refresh_attempt:
            return False

        async with self._refresh_lock:
            synced_at = await self._database.get_access_snapshot_synced_at()
            now = datetime.now(timezone.utc)
            if synced_at is not None and now - synced_at < self._cache_ttl:
                return True
            if self._next_refresh_attempt is not None and now < self._next_refresh_attempt:
                return False
            try:
                snapshot = await self._api.get_access_snapshot()
            except SakuraApiError:
                logger.warning("Access snapshot is temporarily unavailable")
                self._next_refresh_attempt = now + FAILED_REFRESH_RETRY
                return False
            await self._database.replace_access_snapshot(
                snapshot.allowed_ids,
                snapshot.blocked_ids,
            )
            self._next_refresh_attempt = None
            return True


class AccessMiddleware(BaseMiddleware):
    def __init__(self, access: AccessController) -> None:
        self._access = access

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, (Message, CallbackQuery)) or event.from_user is None:
            return await handler(event, data)

        decision = await self._access.check(event.from_user.id)
        if decision == AccessDecision.ALLOWED:
            return await handler(event, data)

        state = data.get("state")
        if isinstance(state, FSMContext):
            await state.clear()

        text = CASTLE_MESSAGE if decision == AccessDecision.DENIED else ACCESS_UNAVAILABLE_MESSAGE
        if isinstance(event, CallbackQuery):
            await event.answer()
            if event.message is not None:
                await event.message.answer(text, reply_markup=ReplyKeyboardRemove())
        else:
            await event.answer(text, reply_markup=ReplyKeyboardRemove())
        return None
