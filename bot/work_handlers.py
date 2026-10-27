from __future__ import annotations

import re
from datetime import date, datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from .api import SakuraApiError, SakuraAppsScriptApi, WorkReportItem, WorkProfile, WorkType
from .config import Settings
from .db import Database, WorkSettings
from .formatting import MOSCOW_TIMEZONE
from .keyboards import (
    KEYS_TEXT,
    LEGACY_REPORT_TEXT,
    MANAGEMENT_TEXT,
    REPORT_TEXT,
    SETTINGS_TEXT,
    THANKS_TEXT,
    cancel_action_keyboard,
    existing_report_keyboard,
    main_keyboard,
    report_date_picker_keyboard,
    report_confirmation_keyboard,
    work_settings_keyboard,
)
from .states import WorkReportStates, WorkScheduleStates


_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_NAVIGATION_TEXTS = {
    REPORT_TEXT,
    LEGACY_REPORT_TEXT,
    KEYS_TEXT,
    SETTINGS_TEXT,
    THANKS_TEXT,
    MANAGEMENT_TEXT,
}


def build_work_router(
    settings: Settings,
    database: Database,
    api: SakuraAppsScriptApi,
) -> Router:
    router = Router(name="sakuraemail-work")

    @router.message(StateFilter(None), F.text.in_({REPORT_TEXT, LEGACY_REPORT_TEXT}))
    async def begin_report(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        await _save_user(database, user, user.id == settings.owner_id)
        await _show_report_date_picker(message, state, bot)

    @router.callback_query(F.data.in_({"work_report_today", "work_report_choose_date"}))
    async def begin_report_callback(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await callback.answer()
        if callback.message is None:
            return
        user = callback.from_user
        await _save_user(database, user, user.id == settings.owner_id)
        await _show_report_date_picker(callback.message, state, bot)

    @router.callback_query(F.data == "work_report_date_today")
    async def select_today_report_date(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        if not await _is_current_action_prompt(
            callback,
            state,
            WorkReportStates.choosing_date.state,
        ):
            return
        await callback.answer("Загружаю отчёт…")
        if callback.message is None:
            return
        await _begin_report(
            callback.message,
            state,
            bot,
            api,
            callback.from_user.id,
            _moscow_today(),
        )

    @router.callback_query(F.data == "work_report_date_custom")
    async def select_custom_report_date(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        if not await _is_current_action_prompt(
            callback,
            state,
            WorkReportStates.choosing_date.state,
        ):
            return
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await state.clear()
        await state.set_state(WorkReportStates.waiting_for_date)
        if callback.message is not None:
            prompt = await callback.message.answer(
                "🌸 Напишите дату отчёта в формате <code>ДД.ММ.ГГГГ</code>\n"
                "Например: <code>26.10.2026</code>",
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.message(WorkReportStates.waiting_for_date)
    async def receive_report_date(message: Message, state: FSMContext, bot: Bot) -> None:
        value = (message.text or "").strip()
        report_date = parse_report_date(value)
        if report_date is None:
            await _replace_input_prompt(
                message,
                state,
                bot,
                "Попробуйте снова. Напишите дату в формате "
                "<code>ДД.ММ.ГГГГ</code>, например <code>26.10.2026</code>.",
            )
            return
        if report_date > _moscow_today():
            await _replace_input_prompt(
                message,
                state,
                bot,
                "Отчёт за будущую дату заполнить нельзя. Укажите сегодняшний или прошедший день.",
            )
            return
        await _begin_report(
            message,
            state,
            bot,
            api,
            _require_user(message.from_user).id,
            report_date,
        )

    @router.callback_query(F.data == "work_report_replace_selected")
    async def replace_selected_report(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        if not await _is_current_action_prompt(
            callback,
            state,
            WorkReportStates.reviewing_existing.state,
        ):
            return
        data = await state.get_data()
        report_date = _parse_date_key(str(data.get("report_target_date", "")))
        report_prompt = str(data.get("report_prompt", ""))
        if report_date is None or report_date > _moscow_today() or not report_prompt:
            await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
            await _disable_callback_markup(callback)
            return
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await _disable_callback_markup(callback)
        await state.set_state(WorkReportStates.waiting_for_report)
        if callback.message is not None:
            prompt = await callback.message.answer(
                _report_input_text(report_date, report_prompt),
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.callback_query(F.data == "work_report_keep_selected")
    async def keep_selected_report(callback: CallbackQuery, state: FSMContext) -> None:
        if not await _is_current_action_prompt(
            callback,
            state,
            WorkReportStates.reviewing_existing.state,
        ):
            return
        await callback.answer("Отчёт оставлен без изменений")
        await state.clear()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await callback.message.answer(
                "Хорошо, оставляю отчёт без изменений 🌸",
                reply_markup=main_keyboard(callback.from_user.id == settings.owner_id),
            )

    @router.message(WorkReportStates.waiting_for_report)
    async def receive_report(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        text = (message.text or "").strip()
        if text in _NAVIGATION_TEXTS:
            await message.answer(
                "Сначала завершите ввод отчёта или нажмите «Отменить» под сообщением 🌸"
            )
            return

        try:
            items = parse_report_text(text)
        except ValueError:
            await _replace_input_prompt(
                message,
                state,
                bot,
                "Попробуйте снова. Используйте формат <code>FGR 12, SNB 6</code>.",
            )
            return

        data = await state.get_data()
        known_articles = {
            str(article).strip().upper()
            for article in data.get("work_catalog", [])
            if str(article).strip()
        }
        unknown_articles = [item.article for item in items if item.article not in known_articles]
        if unknown_articles:
            await _replace_input_prompt(
                message,
                state,
                bot,
                _unknown_articles_message(unknown_articles),
            )
            return

        report_date = _parse_date_key(str(data.get("report_target_date", "")))
        if report_date is None or report_date > _moscow_today():
            await _remove_action_prompt(bot, state)
            await state.clear()
            await message.answer(
                "Дата отчёта некорректна. Выберите сегодняшний или прошедший день.",
                reply_markup=main_keyboard(user.id == settings.owner_id),
            )
            return

        await _remove_action_prompt(bot, state)
        await state.set_state(WorkReportStates.confirming)
        await state.update_data(
            report_items=[
                {"article": item.article, "quantity": item.quantity}
                for item in items
            ]
        )
        confirmation = await message.answer(
            format_report_confirmation(report_date, items),
            reply_markup=report_confirmation_keyboard(),
        )
        await _remember_action_prompt(state, confirmation)
        await state.update_data(
            report_confirmation_chat_id=confirmation.chat.id,
            report_confirmation_message_id=confirmation.message_id,
        )

    @router.callback_query(F.data == "work_report_change")
    async def change_report(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if not await _is_current_confirmation(callback, state):
            return
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await state.set_state(WorkReportStates.waiting_for_report)
        if callback.message is not None:
            data = await state.get_data()
            report_date = _parse_date_key(str(data.get("report_target_date", "")))
            report_prompt = str(data.get("report_prompt", "")) or format_report_prompt(())
            prompt = await callback.message.answer(
                _report_input_text(report_date, report_prompt)
                if report_date is not None
                else report_prompt,
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.callback_query(F.data == "work_report_cancel")
    async def cancel_report(callback: CallbackQuery, state: FSMContext) -> None:
        if not await _is_current_confirmation(callback, state):
            return
        await callback.answer("Отчёт отменён")
        await state.clear()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await callback.message.answer(
                "Отчёт не был отправлен.",
                reply_markup=main_keyboard(callback.from_user.id == settings.owner_id),
            )

    @router.callback_query(F.data == "work_report_submit")
    async def submit_report(callback: CallbackQuery, state: FSMContext) -> None:
        if not await _is_current_confirmation(callback, state):
            return

        data = await state.get_data()
        report_date = str(data.get("report_target_date", ""))
        items = _items_from_state(data.get("report_items"))
        if not report_date or not items:
            await state.clear()
            await _disable_callback_markup(callback)
            await callback.answer("Данные отчёта потерялись. Заполните его ещё раз.", show_alert=True)
            return

        await callback.answer("Отправляю отчёт…")
        try:
            result = await api.save_work_report(callback.from_user.id, report_date, items)
        except SakuraApiError:
            if callback.message is not None:
                await callback.message.answer(
                    "Сейчас не удалось сохранить отчёт. Попробуйте нажать "
                    "«✅ Отправить» ещё раз чуть позже."
                )
            return

        if not result.saved:
            if result.message == "unknown_articles" and result.unknown_articles:
                await state.set_state(WorkReportStates.waiting_for_report)
                if callback.message is not None:
                    try:
                        await callback.message.edit_reply_markup(reply_markup=None)
                    except TelegramBadRequest:
                        pass
                    prompt = await callback.message.answer(
                        _unknown_articles_message(list(result.unknown_articles)),
                        reply_markup=cancel_action_keyboard(),
                    )
                    await _remember_action_prompt(state, prompt)
                return
            if result.message == "report_date_not_editable":
                await state.clear()
                await _disable_callback_markup(callback)
                text = "Отчёт за будущую дату сохранить нельзя. Выберите другую дату."
            elif result.message == "employee_not_found":
                await state.clear()
                await _disable_callback_markup(callback)
                text = "Не удалось подтвердить доступ. Обратитесь к создателю."
            else:
                text = "Не удалось сохранить отчёт. Проверьте данные и попробуйте ещё раз."
            if callback.message is not None:
                await callback.message.answer(text)
            return

        await state.clear()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
            await callback.message.answer(
                "🌸 <b>Отчёт сохранён!</b> Спасибо за работу (｡•̀ᴗ-)✧",
                reply_markup=main_keyboard(callback.from_user.id == settings.owner_id),
            )

    @router.message(StateFilter(None), F.text == SETTINGS_TEXT)
    async def open_settings(message: Message) -> None:
        user = _require_user(message.from_user)
        await _save_user(database, user, user.id == settings.owner_id)
        await _send_settings(message, user.id, database, api)

    @router.callback_query(F.data == "work_schedule_change")
    async def begin_schedule_change(
        callback: CallbackQuery,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await callback.answer()
        await _remove_action_prompt(bot, state)
        await state.clear()
        await state.set_state(WorkScheduleStates.waiting_for_schedule)
        if callback.message is not None:
            prompt = await callback.message.answer(
                "🌸 Напишите начало и конец рабочего дня по мск в формате:\n"
                "<code>09:00–18:00</code>",
                reply_markup=cancel_action_keyboard(),
            )
            await _remember_action_prompt(state, prompt)

    @router.message(WorkScheduleStates.waiting_for_schedule)
    async def receive_schedule(message: Message, state: FSMContext, bot: Bot) -> None:
        user = _require_user(message.from_user)
        text = (message.text or "").strip()
        if text in _NAVIGATION_TEXTS:
            await message.answer(
                "Сначала укажите график или нажмите «Отменить» под сообщением 🌸"
            )
            return
        try:
            start_minutes, end_minutes = parse_schedule(text)
        except ValueError:
            await _replace_input_prompt(
                message,
                state,
                bot,
                "Попробуйте снова. Напишите время в формате "
                "<code>09:00–18:00</code> мск.",
            )
            return

        await _save_user(database, user, user.id == settings.owner_id)
        await database.set_work_schedule(user.id, start_minutes, end_minutes)
        await _remove_action_prompt(bot, state)
        await state.clear()
        await message.answer("График сохранён 🌸")
        await _send_settings(message, user.id, database, api)

    @router.callback_query(F.data == "work_notifications_toggle")
    async def toggle_work_notifications(callback: CallbackQuery) -> None:
        await _save_user(
            database,
            callback.from_user,
            callback.from_user.id == settings.owner_id,
        )
        current = await database.get_work_settings(callback.from_user.id)
        await database.set_work_notifications_enabled(
            callback.from_user.id,
            not current.notifications_enabled,
        )
        updated = await database.get_work_settings(callback.from_user.id)
        await callback.answer(
            "Уведомления включены"
            if updated.notifications_enabled
            else "Уведомления выключены"
        )
        try:
            profile = await api.get_work_profile(callback.from_user.id)
        except SakuraApiError:
            profile = None
        if callback.message is not None and profile is not None:
            await callback.message.edit_text(
                _format_settings(profile, updated),
                reply_markup=work_settings_keyboard(updated.notifications_enabled),
            )
        elif callback.message is not None:
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=work_settings_keyboard(updated.notifications_enabled)
                )
            except TelegramBadRequest:
                pass

    return router


async def _show_report_date_picker(
    source_message: Message,
    state: FSMContext,
    bot: Bot,
) -> None:
    await _remove_action_prompt(bot, state)
    await state.clear()
    await state.set_state(WorkReportStates.choosing_date)
    today = _moscow_today()
    prompt = await source_message.answer(
        "🌸 <b>Выберите дату, за которую заполняете отчёт!</b>\n\n"
        f"Сегодня {format_report_date_label_html(today)}",
        reply_markup=report_date_picker_keyboard(),
    )
    await _remember_action_prompt(state, prompt)


async def _begin_report(
    source_message: Message,
    state: FSMContext,
    bot: Bot,
    api: SakuraAppsScriptApi,
    telegram_id: int,
    report_date: date,
) -> None:
    if report_date > _moscow_today():
        await source_message.answer(
            "Отчёт за будущую дату заполнить нельзя. Выберите другую дату."
        )
        return
    try:
        context = await api.get_work_report_context(
            telegram_id,
            report_date.isoformat(),
        )
    except SakuraApiError:
        await source_message.answer(
            "Не удалось загрузить данные отчёта. Попробуйте немного позже."
        )
        return
    if not context.employee_found:
        await source_message.answer("Не удалось подтвердить доступ. Обратитесь к создателю.")
        return
    if not context.catalog:
        await source_message.answer("Пока нет доступных видов макетов. Обратитесь к создателю.")
        return

    await _remove_action_prompt(bot, state)
    await state.clear()
    report_prompt = format_report_prompt(context.catalog)
    await state.update_data(
        report_target_date=report_date.isoformat(),
        work_catalog=[item.article for item in context.catalog],
        report_prompt=report_prompt,
    )

    if context.report.found:
        await state.set_state(WorkReportStates.reviewing_existing)
        existing = await source_message.answer(
            format_existing_report(report_date, context.report.items),
            reply_markup=existing_report_keyboard(),
        )
        await _remember_action_prompt(state, existing)
        return

    await state.set_state(WorkReportStates.waiting_for_report)
    prompt = await source_message.answer(
        _report_input_text(report_date, report_prompt),
        reply_markup=cancel_action_keyboard(),
    )
    await _remember_action_prompt(state, prompt)


async def _send_settings(
    message: Message,
    telegram_id: int,
    database: Database,
    api: SakuraAppsScriptApi,
) -> None:
    try:
        profile = await api.get_work_profile(telegram_id)
    except SakuraApiError:
        await message.answer("Не удалось загрузить личный кабинет. Попробуйте немного позже.")
        return
    if profile is None:
        await message.answer("Не удалось подтвердить доступ. Обратитесь к создателю.")
        return
    work_settings = await database.get_work_settings(telegram_id)
    await message.answer(
        _format_settings(profile, work_settings),
        reply_markup=work_settings_keyboard(work_settings.notifications_enabled),
    )


def parse_report_text(value: str) -> tuple[WorkReportItem, ...]:
    text = value.strip()
    if not text:
        raise ValueError("empty report")
    raw_parts = re.split(r"[,;\n]", text)
    if any(not part.strip() for part in raw_parts):
        raise ValueError("empty report item")

    quantities: dict[str, int] = {}
    order: list[str] = []
    for raw_part in raw_parts:
        match = re.fullmatch(r"([^\s,;]+)\s+(\d+)", raw_part.strip())
        if match is None:
            raise ValueError("invalid report item")
        article = re.sub(r"\s+", "", match.group(1)).upper()
        quantity = int(match.group(2))
        if not article or quantity <= 0:
            raise ValueError("invalid quantity")
        if article not in quantities:
            quantities[article] = 0
            order.append(article)
        quantities[article] += quantity
        if quantities[article] > 1_000_000:
            raise ValueError("quantity is too large")

    return tuple(
        WorkReportItem(article=article, quantity=quantities[article])
        for article in order
    )


def parse_schedule(value: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*(?:мск)?\s*",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError("invalid schedule")
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    if (
        start_hour > 23
        or end_hour > 23
        or start_minute > 59
        or end_minute > 59
    ):
        raise ValueError("invalid time")
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if end - start < 30:
        raise ValueError("work day is too short")
    return start, end


def parse_report_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def format_report_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def format_report_date_label(value: date) -> str:
    return f"{_WEEKDAYS[value.weekday()].upper()} • {format_report_date(value)}"


def format_report_date_label_html(value: date) -> str:
    return (
        f"{_WEEKDAYS[value.weekday()].upper()} • "
        f"<code>{format_report_date(value)}</code>"
    )


def format_report_prompt(items: tuple[WorkType, ...] | list[WorkType]) -> str:
    catalog_lines = []
    for item in items:
        article = escape(item.article)
        name = escape(item.name.strip())
        catalog_lines.append(f"{article} • {name}" if name else article)

    catalog = "\n".join(catalog_lines) or "Список пока пуст"
    return (
        "Считаем только <b>оригинальные макеты</b> 🌸\n"
        "Пишем артикул основной категории. Не BVKL, а VKL. Не ZTOP, а TOP.\n\n"
        "Все артикулы:\n"
        f"<blockquote expandable>{catalog}</blockquote>\n\n"
        "Напишите виды и количество одним сообщением. Например:\n"
        "<code>FGR 12</code> или <code>FGR 12, SNB 6</code>"
    )


def _report_input_text(report_date: date, report_prompt: str) -> str:
    return (
        f"🌸 <b>Отчёт за {format_report_date(report_date)}</b>\n\n"
        f"{report_prompt}"
    )


def format_report_confirmation(
    report_date: date,
    items: tuple[WorkReportItem, ...] | list[WorkReportItem],
) -> str:
    lines = [f"🌸 <b>Отчёт за {format_report_date(report_date)}</b>", ""]
    lines.extend(f"{escape(item.article)} · {item.quantity}" for item in items)
    lines.extend(["", "Всё верно? Отправить отчёт?"])
    return "\n".join(lines)


def format_saved_report(
    report_date: date,
    items: tuple[WorkReportItem, ...] | list[WorkReportItem],
) -> str:
    lines = [f"🌸 <b>Отчёт за {format_report_date(report_date)}</b>", ""]
    lines.extend(f"{escape(item.article)} · {item.quantity}" for item in items)
    return "\n".join(lines)


def format_existing_report(
    report_date: date,
    items: tuple[WorkReportItem, ...] | list[WorkReportItem],
) -> str:
    lines = [
        f"🌸 Вы уже отправляли отчёт за {format_report_date_label_html(report_date)}:",
        "",
    ]
    lines.extend(f"{escape(item.article)} · {item.quantity}" for item in items)
    lines.extend(["", "Изменить?"])
    return "\n".join(lines)


def _format_settings(profile: WorkProfile, work_settings: WorkSettings) -> str:
    notifications = "включены" if work_settings.notifications_enabled else "выключены"
    return (
        f"🌸 <b>{escape(profile.display_name or profile.full_name)}</b>\n\n"
        f"График: {_format_minutes(work_settings.start_minutes)}–"
        f"{_format_minutes(work_settings.end_minutes)} мск\n"
        f"Уведомления: {notifications}\n\n"
        "<b>Баллы</b>\n"
        f"Сегодня: {_format_points(profile.today_points)}\n"
        f"За неделю: {_format_points(profile.week_points)}\n"
        f"За месяц: {_format_points(profile.month_points)}"
    )


def _format_minutes(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _format_points(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _unknown_articles_message(articles: list[str]) -> str:
    unique = list(dict.fromkeys(article.upper() for article in articles))
    if len(unique) == 1:
        return f"Попробуйте снова. Макеты вида {escape(unique[0])} отсутствуют"
    return "Попробуйте снова. Макеты видов " + ", ".join(map(escape, unique)) + " отсутствуют"


def _items_from_state(raw_items: object) -> list[WorkReportItem]:
    if not isinstance(raw_items, list):
        return []
    items: list[WorkReportItem] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        article = str(raw_item.get("article", "")).strip().upper()
        try:
            quantity = int(raw_item.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        if article and quantity > 0:
            items.append(WorkReportItem(article=article, quantity=quantity))
    return items


def _parse_date_key(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _moscow_today() -> date:
    return datetime.now(MOSCOW_TIMEZONE).date()


async def _replace_input_prompt(
    message: Message,
    state: FSMContext,
    bot: Bot,
    text: str,
) -> None:
    await _remove_action_prompt(bot, state)
    prompt = await message.answer(text, reply_markup=cancel_action_keyboard())
    await _remember_action_prompt(state, prompt)


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


async def _is_current_confirmation(
    callback: CallbackQuery,
    state: FSMContext,
) -> bool:
    data = await state.get_data()
    current_state = await state.get_state()
    expected_chat_id = data.get("report_confirmation_chat_id")
    expected_message_id = data.get("report_confirmation_message_id")
    if (
        current_state != WorkReportStates.confirming.state
        or callback.message is None
        or expected_chat_id is None
        or expected_message_id is None
        or callback.message.chat.id != int(expected_chat_id)
        or callback.message.message_id != int(expected_message_id)
    ):
        await callback.answer("Это подтверждение уже неактуально")
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass
        return False
    return True


async def _is_current_action_prompt(
    callback: CallbackQuery,
    state: FSMContext,
    expected_state: str,
) -> bool:
    data = await state.get_data()
    current_state = await state.get_state()
    expected_chat_id = data.get("action_prompt_chat_id")
    expected_message_id = data.get("action_prompt_message_id")
    if (
        current_state != expected_state
        or callback.message is None
        or expected_chat_id is None
        or expected_message_id is None
        or callback.message.chat.id != int(expected_chat_id)
        or callback.message.message_id != int(expected_message_id)
    ):
        await callback.answer("Эта кнопка уже неактуальна")
        await _disable_callback_markup(callback)
        return False
    return True


async def _disable_callback_markup(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


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
