from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .api import SakuraAppsScriptApi
from .config import ConfigurationError, Settings
from .db import Database
from .handlers import build_router
from .notifications import notification_worker


async def main() -> None:
    settings = Settings.from_environment()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    database = Database(settings.database_path)
    api = SakuraAppsScriptApi(settings.apps_script_url, settings.bot_api_secret)
    await database.connect()
    await api.connect()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_router(settings, database, api))

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть SakuraEmail"),
            BotCommand(command="cancel", description="Отменить текущее действие"),
        ]
    )

    worker = asyncio.create_task(
        notification_worker(
            bot,
            api,
            database,
            settings.notification_poll_seconds,
        )
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await bot.session.close()
        await api.close()
        await database.close()


def run() -> None:
    try:
        asyncio.run(main())
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

