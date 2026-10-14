from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import aiohttp


class SakuraApiError(RuntimeError):
    """Base error returned by the Sakura Apps Script API."""


class SakuraApiUnavailable(SakuraApiError):
    """The remote API could not be reached or returned an invalid response."""


class SakuraApiRejected(SakuraApiError):
    """The remote API explicitly rejected the request."""


@dataclass(frozen=True, slots=True)
class LicenseKey:
    key: str
    license_type: str
    status: str
    status_code: str
    expires_at: str
    row_number: int


@dataclass(frozen=True, slots=True)
class RenewalNotification:
    telegram_id: int
    license_type: str
    expiring_key: str
    expiring_at: str
    new_key: str
    new_expires_at: str


@dataclass(frozen=True, slots=True)
class AccessSnapshot:
    allowed_ids: frozenset[int]
    blocked_ids: frozenset[int]


@dataclass(frozen=True, slots=True)
class WorkProfile:
    display_name: str
    full_name: str
    today_points: float
    week_points: float
    month_points: float


@dataclass(frozen=True, slots=True)
class WorkType:
    article: str
    coefficient: float


@dataclass(frozen=True, slots=True)
class WorkCatalog:
    employee_found: bool
    items: tuple[WorkType, ...]


@dataclass(frozen=True, slots=True)
class WorkReportItem:
    article: str
    quantity: int


@dataclass(frozen=True, slots=True)
class WorkReport:
    employee_found: bool
    found: bool
    editable: bool
    report_date: str
    items: tuple[WorkReportItem, ...]


@dataclass(frozen=True, slots=True)
class WorkReportSaveResult:
    saved: bool
    message: str
    unknown_articles: tuple[str, ...]


class SakuraAppsScriptApi:
    def __init__(self, url: str, secret: str) -> None:
        self._url = url
        self._secret = secret
        self._session: aiohttp.ClientSession | None = None

    async def connect(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def get_active_keys(self, telegram_id: int) -> list[LicenseKey]:
        payload = await self._post(
            "bot_get_keys",
            telegram_id=str(telegram_id),
        )
        raw_keys = payload.get("keys", [])
        if not isinstance(raw_keys, list):
            raise SakuraApiUnavailable("Apps Script returned an invalid keys collection")

        keys: list[LicenseKey] = []
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict):
                continue
            key = str(raw_key.get("key", "")).strip()
            if not key:
                continue
            keys.append(
                LicenseKey(
                    key=key,
                    license_type=str(raw_key.get("license_type", "")).strip(),
                    status=str(raw_key.get("status", "")).strip(),
                    status_code=str(raw_key.get("status_code", "")).strip(),
                    expires_at=str(raw_key.get("expires_at", "")).strip(),
                    row_number=_safe_int(raw_key.get("row_number")),
                )
            )
        return keys

    async def get_expiring_renewals(self) -> list[RenewalNotification]:
        payload = await self._post("bot_expiring_renewals")
        raw_items = payload.get("notifications", [])
        if not isinstance(raw_items, list):
            raise SakuraApiUnavailable("Apps Script returned an invalid notifications collection")

        notifications: list[RenewalNotification] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            try:
                telegram_id = int(str(raw_item.get("telegram_id", "")).strip())
            except ValueError:
                continue

            new_key = str(raw_item.get("new_key", "")).strip()
            expiring_key = str(raw_item.get("expiring_key", "")).strip()
            if not new_key or not expiring_key:
                continue

            notifications.append(
                RenewalNotification(
                    telegram_id=telegram_id,
                    license_type=str(raw_item.get("license_type", "")).strip(),
                    expiring_key=expiring_key,
                    expiring_at=str(raw_item.get("expiring_at", "")).strip(),
                    new_key=new_key,
                    new_expires_at=str(raw_item.get("new_expires_at", "")).strip(),
                )
            )
        return notifications

    async def get_access_snapshot(self) -> AccessSnapshot:
        payload = await self._post("bot_access_snapshot")
        raw_users = payload.get("users", [])
        if not isinstance(raw_users, list):
            raise SakuraApiUnavailable("Apps Script returned an invalid access snapshot")

        allowed_ids: set[int] = set()
        blocked_ids: set[int] = set()
        for raw_user in raw_users:
            if not isinstance(raw_user, dict):
                continue
            telegram_id = _safe_int(raw_user.get("telegram_id"))
            if telegram_id <= 0:
                continue
            if raw_user.get("blocked") is True:
                blocked_ids.add(telegram_id)
                allowed_ids.discard(telegram_id)
            elif telegram_id not in blocked_ids:
                allowed_ids.add(telegram_id)

        return AccessSnapshot(
            allowed_ids=frozenset(allowed_ids),
            blocked_ids=frozenset(blocked_ids),
        )

    async def get_work_profile(self, telegram_id: int) -> WorkProfile | None:
        payload = await self._post(
            "bot_work_profile",
            telegram_id=str(telegram_id),
        )
        if payload.get("found") is not True:
            return None

        stats = payload.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        return WorkProfile(
            display_name=str(payload.get("display_name", "")).strip(),
            full_name=str(payload.get("full_name", "")).strip(),
            today_points=_safe_float(stats.get("today")),
            week_points=_safe_float(stats.get("week")),
            month_points=_safe_float(stats.get("month")),
        )

    async def get_work_catalog(self, telegram_id: int) -> WorkCatalog:
        payload = await self._post(
            "bot_report_catalog",
            telegram_id=str(telegram_id),
        )
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise SakuraApiUnavailable("Apps Script returned an invalid work catalog")

        items: list[WorkType] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            article = str(raw_item.get("article", "")).strip().upper()
            coefficient = _safe_float(raw_item.get("coefficient"))
            if article and coefficient > 0:
                items.append(WorkType(article=article, coefficient=coefficient))
        return WorkCatalog(
            employee_found=payload.get("found") is True,
            items=tuple(items),
        )

    async def get_work_report(self, telegram_id: int, report_date: str) -> WorkReport:
        payload = await self._post(
            "bot_get_report",
            telegram_id=str(telegram_id),
            report_date=report_date,
        )
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise SakuraApiUnavailable("Apps Script returned invalid report items")

        items: list[WorkReportItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            article = str(raw_item.get("article", "")).strip().upper()
            quantity = _safe_int(raw_item.get("quantity"))
            if article and quantity > 0:
                items.append(WorkReportItem(article=article, quantity=quantity))
        return WorkReport(
            employee_found=payload.get("employee_found") is True,
            found=payload.get("found") is True,
            editable=payload.get("editable") is True,
            report_date=str(payload.get("report_date", report_date)).strip(),
            items=tuple(items),
        )

    async def save_work_report(
        self,
        telegram_id: int,
        report_date: str,
        items: list[WorkReportItem],
    ) -> WorkReportSaveResult:
        payload = await self._post(
            "bot_save_report",
            telegram_id=str(telegram_id),
            report_date=report_date,
            items=[
                {
                    "article": item.article,
                    "quantity": item.quantity,
                }
                for item in items
            ],
        )
        raw_unknown_articles = payload.get("unknown_articles", [])
        unknown_articles = (
            tuple(str(value).strip().upper() for value in raw_unknown_articles if str(value).strip())
            if isinstance(raw_unknown_articles, list)
            else ()
        )
        return WorkReportSaveResult(
            saved=payload.get("saved") is True,
            message=str(payload.get("message", "")).strip(),
            unknown_articles=unknown_articles,
        )

    async def _post(self, action: str, **values: Any) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Apps Script API is not connected")

        request_payload: dict[str, Any] = {
            "action": action,
            "secret": self._secret,
            **values,
        }

        try:
            async with self._session.post(
                self._url,
                json=request_payload,
                allow_redirects=True,
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise SakuraApiUnavailable(f"Apps Script returned HTTP {response.status}")
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise SakuraApiUnavailable("Apps Script returned non-JSON data") from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise SakuraApiUnavailable("Apps Script request failed") from exc

        if not isinstance(payload, dict):
            raise SakuraApiUnavailable("Apps Script returned an invalid response")
        if payload.get("ok") is not True:
            message = str(payload.get("message", "api_error"))
            if message == "unauthorized":
                raise SakuraApiRejected("Apps Script rejected BOT_API_SECRET")
            raise SakuraApiUnavailable(f"Apps Script error: {message}")
        return payload


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else 0
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        return 0
    return int(text)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
