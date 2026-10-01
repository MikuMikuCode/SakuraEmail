from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from .api import SakuraApiError, SakuraAppsScriptApi
from .config import Settings
from .db import Database, SupportRequest
from .keyboards import (
    MANAGEMENT_TEXT,
    REQUEST_KEY_TEXT,
    application_keyboard,
    close_request_keyboard,
    main_keyboard,
    management_keyboard,
)
from .states import ApplicationStates


def build_router(
    settings: Settings,
    database: Database,
    api: SakuraAppsScriptApi,
) -> Router:
    router = Router(name="sakuraemail")

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        user = _require_user(message.from_user)
        is_creator = user.id == settings.owner_id
        await _save_user(database, user, is_creator)

        greeting = (
            f"🌸 <b>Добро пожаловать, {escape(user.first_name)}!</b>\n\n"
            "Я помогу получить лицензионный ключ для макроса и напомню о продлении."
        )
        if is_creator:
            greeting += "\n\nДля вас доступен раздел управления."

        await message.answer(
            greeting,
            reply_markup=main_keyboard(is_creator),
        )

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        user = _require_user(message.from_user)
        await message.answer(
            "Действие отменено.",
            reply_markup=main_keyboard(user.id == settings.owner_id),
        )

    @router.callback_query(F.data == "new_key_request")
    async def begin_application(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.set_state(ApplicationStates.waiting_for_reason)
        if callback.message is not None:
            await callback.message.answer("Напишите в одном сообщении зачем вам новый ключ")

    @router.message(ApplicationStates.waiting_for_reason)
    async def receive_application(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        reason = (message.text or "").strip()
        if not reason:
            await message.answer("Пожалуйста, отправьте причину одним текстовым сообщением.")
            return
        if len(reason) > 2000:
            await message.answer("Сообщение слишком длинное. Сократите его до 2000 символов.")
            return

        is_creator = user.id == settings.owner_id
        await _save_user(database, user, is_creator)
        request_id = await database.create_support_request(user.id, user.username, reason)
        await state.clear()

        await message.answer(
            "🌸 Заявка отправлена создателю.",
            reply_markup=main_keyboard(is_creator),
        )

        username = f"@{escape(user.username)}" if user.username else "тег отсутствует"
        owner_text = (
            f"💌 <b>Новая заявка №{request_id}</b>\n"
            f"Пользователь: {username}\n"
            f"Telegram ID: <code>{user.id}</code>\n\n"
            f"Причина:\n{escape(reason)}"
        )
        try:
            await bot.send_message(
                settings.owner_id,
                owner_text,
                reply_markup=close_request_keyboard(request_id),
            )
        except Exception:
            # The request remains in the creator panel even if the direct
            # notification could not be delivered.
            pass

    @router.message(F.text == REQUEST_KEY_TEXT)
    async def request_key(message: Message) -> None:
        user = _require_user(message.from_user)
        await _save_user(database, user, user.id == settings.owner_id)

        await message.answer("🌸 Ищу ваши актуальные ключи…")
        try:
            keys = await api.get_active_keys(user.id)
        except SakuraApiError:
            await message.answer(
                "Не удалось получить данные о ключах. Попробуйте немного позже."
            )
            return

        if not keys:
            await message.answer("Активных ключей нет")
            return

        lines = ["🌸 <b>Ваши активные ключи</b>"]
        has_used_key = False
        for index, license_key in enumerate(keys, start=1):
            lines.append("")
            if len(keys) > 1:
                lines.append(f"<b>Ключ {index}</b>")
            lines.append(f"<code>{escape(license_key.key)}</code>")
            lines.append(f"Статус: {escape(license_key.status)}")
            if license_key.expires_at:
                lines.append(f"Действует до: {escape(license_key.expires_at)}")
            if license_key.status_code == "used":
                has_used_key = True

        if has_used_key:
            lines.extend(
                [
                    "",
                    "Ключ уже был использован. Для запроса нового оставьте заявку",
                ]
            )

        await message.answer(
            "\n".join(lines),
            reply_markup=application_keyboard() if has_used_key else None,
        )

    @router.message(F.text == MANAGEMENT_TEXT)
    async def management(message: Message) -> None:
        user = _require_user(message.from_user)
        if user.id != settings.owner_id:
            return
        await message.answer(
            "🌸 <b>Управление SakuraEmail</b>",
            reply_markup=management_keyboard(),
        )

    @router.callback_query(F.data == "admin_stats")
    async def admin_stats(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return
        users_count, pending_count = await database.get_stats()
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                "📊 <b>Статистика</b>\n"
                f"Пользователей: {users_count}\n"
                f"Открытых заявок: {pending_count}"
            )

    @router.callback_query(F.data == "admin_requests")
    async def admin_requests(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return
        await callback.answer()
        if callback.message is None:
            return

        requests = await database.list_pending_requests()
        if not requests:
            await callback.message.answer("Открытых заявок нет.")
            return

        await callback.message.answer(f"💌 Открытых заявок: {len(requests)}")
        for request in requests:
            await callback.message.answer(
                _format_request(request),
                reply_markup=close_request_keyboard(request.request_id),
            )

    @router.callback_query(F.data.startswith("close_request:"))
    async def close_request(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        try:
            request_id = int((callback.data or "").split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer("Некорректная заявка", show_alert=True)
            return

        closed = await database.close_support_request(request_id)
        await callback.answer("Заявка закрыта" if closed else "Заявка уже закрыта")
        if closed and callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)

    return router


async def _save_user(database: Database, user: User, is_creator: bool) -> None:
    await database.upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        role="creator" if is_creator else "user",
    )


def _require_user(user: User | None) -> User:
    if user is None:
        raise RuntimeError("Telegram update does not contain a user")
    return user


def _is_owner(user: User, settings: Settings) -> bool:
    return user.id == settings.owner_id


def _format_request(request: SupportRequest) -> str:
    username = f"@{escape(request.username)}" if request.username else "тег отсутствует"
    return (
        f"💌 <b>Заявка №{request.request_id}</b>\n"
        f"Пользователь: {username}\n"
        f"Telegram ID: <code>{request.telegram_id}</code>\n"
        f"Создана: {escape(request.created_at)}\n\n"
        f"{escape(request.reason)}"
    )
