from __future__ import annotations

import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from .api import SakuraApiError, SakuraAppsScriptApi
from .config import Settings
from .db import Database, SupportRequest, ThanksStats
from .formatting import display_license_type, format_datetime
from .keyboards import (
    LEGACY_REQUEST_KEY_TEXT,
    MANAGEMENT_TEXT,
    MY_KEYS_TEXT,
    THANKS_TEXT,
    application_keyboard,
    cancel_action_keyboard,
    close_request_keyboard,
    main_keyboard,
    management_keyboard,
    thanks_settings_keyboard,
)
from .states import ApplicationStates, CreatorMessageStates


APPLICATION_PROMPT = (
    "• Опишите в одном предложении ваш запрос. Вы можете запросить дополнительный "
    "ключ, получить техническую поддержку или просто поблагодарить :3\n\n"
    "При запросе дополнительного ключа сообщите, зачем вам нужен новый ключ."
)


def build_router(
    settings: Settings,
    database: Database,
    api: SakuraAppsScriptApi,
) -> Router:
    router = Router(name="sakuraemail")

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext, bot: Bot) -> None:
        await _remove_action_prompt(bot, state)
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
    async def cancel(message: Message, state: FSMContext, bot: Bot) -> None:
        await _remove_action_prompt(bot, state)
        await state.clear()
        user = _require_user(message.from_user)
        await message.answer(
            "Действие отменено.",
            reply_markup=main_keyboard(user.id == settings.owner_id),
        )

    @router.callback_query(F.data == "cancel_action")
    async def cancel_action(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        tracked_chat_id = data.get("action_prompt_chat_id")
        tracked_message_id = data.get("action_prompt_message_id")
        if (
            callback.message is not None
            and tracked_chat_id is not None
            and tracked_message_id is not None
            and (
                callback.message.chat.id != int(tracked_chat_id)
                or callback.message.message_id != int(tracked_message_id)
            )
        ):
            await callback.answer("Это действие уже завершено")
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            return

        current_state = await state.get_state()
        await state.clear()
        await callback.answer("Действие отменено" if current_state else "Действие уже завершено")
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass

    @router.callback_query(F.data == "new_key_request")
    async def begin_application(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await state.clear()
        await state.set_state(ApplicationStates.waiting_for_reason)
        if callback.message is not None:
            prompt = await callback.message.answer(
                APPLICATION_PROMPT,
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.message(ApplicationStates.waiting_for_reason)
    async def receive_application(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        reason = (message.text or "").strip()
        if not reason:
            await message.answer("Пожалуйста, отправьте запрос одним текстовым сообщением.")
            return
        if len(reason) > 2000:
            await message.answer("Сообщение слишком длинное. Сократите его до 2000 символов.")
            return

        is_creator = user.id == settings.owner_id
        await _save_user(database, user, is_creator)
        request_id = await database.create_support_request(user.id, user.username, reason)
        await _remove_action_prompt(bot, state)
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
            f"Запрос:\n{escape(reason)}"
        )
        try:
            await bot.send_message(
                settings.owner_id,
                owner_text,
                reply_markup=close_request_keyboard(request_id),
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            # The request remains available in the creator panel.
            pass

    @router.message(StateFilter(None), F.text.in_({MY_KEYS_TEXT, LEGACY_REQUEST_KEY_TEXT}))
    async def request_key(message: Message) -> None:
        user = _require_user(message.from_user)
        is_creator = user.id == settings.owner_id
        await _save_user(database, user, is_creator)

        await message.answer(
            "🌸 Ищу ваши актуальные ключи…",
            reply_markup=main_keyboard(is_creator),
        )
        try:
            keys = await api.get_active_keys(user.id)
        except SakuraApiError:
            await message.answer(
                "Не удалось получить данные о ключах. Попробуйте немного позже.",
                reply_markup=application_keyboard(),
            )
            return

        if not keys:
            await message.answer(
                "Активных ключей нет",
                reply_markup=application_keyboard(),
            )
            return

        lines = ["🌸 <b>Ваши активные ключи</b>"]
        has_used_key = False
        for index, license_key in enumerate(keys, start=1):
            lines.append("")
            if len(keys) > 1:
                lines.append(f"<b>Ключ {index}</b>")
            lines.append(f"<blockquote><code>{escape(license_key.key)}</code></blockquote>")
            lines.append(
                f"Вид подписки: {escape(display_license_type(license_key.license_type))}"
            )
            lines.append(f"Статус: {escape(license_key.status)}")
            if license_key.expires_at:
                lines.append(f"Действует до: {escape(format_datetime(license_key.expires_at))}")
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
            reply_markup=application_keyboard(),
        )

    @router.message(StateFilter(None), F.text == THANKS_TEXT)
    async def thanks(message: Message, bot: Bot) -> None:
        user = _require_user(message.from_user)
        is_creator = user.id == settings.owner_id
        await _save_user(database, user, is_creator)

        if is_creator:
            stats = await database.get_thanks_stats()
            await message.answer(
                _format_thanks_stats(stats),
                reply_markup=thanks_settings_keyboard(stats.notifications_enabled),
            )
            return

        accepted = await database.record_thanks(user.id, user.username)
        if not accepted:
            await message.answer(
                "Спасибо уже отправлено 💗 Повторить можно один раз через сутки."
            )
            return

        await message.answer("Спасибо! Передала создателю (˶ᵔ ᵕ ᵔ˶)♡")
        if not await database.thanks_notifications_enabled():
            return

        username = f"@{escape(user.username)}" if user.username else escape(user.full_name)
        try:
            await bot.send_message(
                settings.owner_id,
                f"{username} сказал(а) спасибо! (づ｡◕‿‿◕｡)づ ♡",
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            pass

    @router.message(StateFilter(None), F.text == MANAGEMENT_TEXT)
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

    @router.callback_query(F.data == "admin_message_user")
    async def begin_creator_message(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await state.clear()
        await state.set_state(CreatorMessageStates.waiting_for_username)
        if callback.message is not None:
            prompt = await callback.message.answer(
                "Отправьте тег пользователя, которому хотите написать. Например: @username\n\n"
                "Пользователь должен хотя бы один раз запустить бота через /start.",
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.message(CreatorMessageStates.waiting_for_username)
    async def receive_creator_message_username(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        user = _require_user(message.from_user)
        if user.id != settings.owner_id:
            return

        raw_username = (message.text or "").strip()
        username = raw_username[1:] if raw_username.startswith("@") else raw_username
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
            await message.answer("Отправьте корректный Telegram-тег в формате @username.")
            return

        recipient = await database.find_user_by_username(username)
        if recipient is None:
            await message.answer(
                "Не нашла этого пользователя в базе. Он должен сначала отправить боту /start."
            )
            return

        await _remove_action_prompt(bot, state)
        await state.set_state(CreatorMessageStates.waiting_for_message)
        await state.update_data(
            recipient_id=recipient.telegram_id,
            recipient_username=recipient.username or username,
        )
        prompt = await message.answer(
            f"Теперь отправьте сообщение для @{escape(recipient.username or username)}.",
            reply_markup=cancel_action_keyboard(),
        )
        await _remember_action_prompt(state, prompt)

    @router.message(CreatorMessageStates.waiting_for_message)
    async def send_creator_message(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        if user.id != settings.owner_id:
            return

        text = (message.text or "").strip()
        if not text:
            await message.answer("Отправьте сообщение текстом.")
            return
        if len(text) > 3500:
            await message.answer("Сообщение слишком длинное. Сократите его до 3500 символов.")
            return

        data = await state.get_data()
        recipient_id = int(data.get("recipient_id", 0))
        recipient_username = str(data.get("recipient_username", "пользователь"))
        if not recipient_id:
            await state.clear()
            await message.answer("Получатель потерян. Начните отправку сообщения заново.")
            return

        try:
            await bot.send_message(
                recipient_id,
                "💌 <b>Сообщение от создателя</b>\n\n" + escape(text),
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            await message.answer(
                "Не удалось отправить сообщение. Возможно, пользователь заблокировал бота."
            )
            return

        await _remove_action_prompt(bot, state)
        await state.clear()
        await message.answer(
            f"Сообщение для @{escape(recipient_username)} отправлено.",
            reply_markup=main_keyboard(True),
        )

    @router.callback_query(F.data.startswith("close_request:"))
    async def close_request(callback: CallbackQuery, bot: Bot) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        try:
            request_id = int((callback.data or "").split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer("Некорректная заявка", show_alert=True)
            return

        telegram_id = await database.close_support_request(request_id)
        if telegram_id is None:
            await callback.answer("Заявка уже выполнена")
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

        user_notified = True
        try:
            await bot.send_message(
                telegram_id,
                f"🌸 Ваша заявка №{request_id} закрыта. Если понадобится помощь, "
                "вы всегда можете оставить новую.",
            )
        except (TelegramForbiddenError, TelegramBadRequest):
            user_notified = False

        await callback.answer(
            "Заявка выполнена"
            if user_notified
            else "Заявка выполнена, но пользователь недоступен",
            show_alert=not user_notified,
        )
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data == "toggle_thanks_notifications")
    async def toggle_thanks_notifications(callback: CallbackQuery) -> None:
        if not _is_owner(callback.from_user, settings):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        currently_enabled = await database.thanks_notifications_enabled()
        await database.set_thanks_notifications_enabled(not currently_enabled)
        stats = await database.get_thanks_stats()
        await callback.answer(
            "Уведомления включены" if stats.notifications_enabled else "Уведомления отключены"
        )
        if callback.message is not None:
            await callback.message.edit_text(
                _format_thanks_stats(stats),
                reply_markup=thanks_settings_keyboard(stats.notifications_enabled),
            )

    return router


async def _save_user(database: Database, user: User, is_creator: bool) -> None:
    await database.upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        role="creator" if is_creator else "user",
    )


async def _remember_action_prompt(state: FSMContext, message: Message) -> None:
    await state.update_data(
        action_prompt_chat_id=message.chat.id,
        action_prompt_message_id=message.message_id,
    )


async def _remove_action_prompt(bot: Bot, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = data.get("action_prompt_chat_id")
    message_id = data.get("action_prompt_message_id")
    if chat_id is None or message_id is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass


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
        f"Создана: {escape(format_datetime(request.created_at))}\n\n"
        f"{escape(request.reason)}"
    )


def _format_thanks_stats(stats: ThanksStats) -> str:
    notifications = "включены" if stats.notifications_enabled else "отключены"
    return (
        "💗 <b>Спасибо</b>\n"
        f"За сегодня: {stats.today}\n"
        f"За всё время: {stats.total}\n"
        f"Уведомления: {notifications}"
    )
