from __future__ import annotations

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
    status: str
    status_code: str
    expires_at: str
    row_number: int


@dataclass(frozen=True, slots=True)
class RenewalNotification:
    telegram_id: int
    expiring_key: str
    expiring_at: str
    new_key: str
    new_expires_at: str


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
                    expiring_key=expiring_key,
                    expiring_at=str(raw_item.get("expiring_at", "")).strip(),
                    new_key=new_key,
                    new_expires_at=str(raw_item.get("new_expires_at", "")).strip(),
                )
            )
        return notifications

    async def _post(self, action: str, **values: str) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Apps Script API is not connected")

        request_payload: dict[str, str] = {
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
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

