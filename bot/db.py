from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from .formatting import MOSCOW_TIMEZONE


@dataclass(frozen=True, slots=True)
class SupportRequest:
    request_id: int
    telegram_id: int
    username: str | None
    reason: str
    created_at: str


@dataclass(frozen=True, slots=True)
class BotUser:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str


@dataclass(frozen=True, slots=True)
class ThanksStats:
    today: int
    total: int
    notifications_enabled: bool


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        await self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL CHECK (role IN ('creator', 'user')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username_snapshot TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'closed')),
                created_at TEXT NOT NULL,
                closed_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS sent_notifications (
                notification_hash TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS gratitudes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username_snapshot TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_support_requests_status
                ON support_requests(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_gratitudes_user_created
                ON gratitudes(telegram_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_gratitudes_created
                ON gratitudes(created_at);
            """
        )
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str,
        last_name: str,
        role: str,
    ) -> None:
        connection = self._require_connection()
        now = _utc_now()
        async with self._lock:
            await connection.execute(
                """
                INSERT INTO users (
                    telegram_id, username, first_name, last_name, role,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    role = excluded.role,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, username, first_name, last_name, role, now, now),
            )
            await connection.commit()

    async def user_exists(self, telegram_id: int) -> bool:
        connection = self._require_connection()
        cursor = await connection.execute(
            "SELECT 1 FROM users WHERE telegram_id = ?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def find_user_by_username(self, username: str) -> BotUser | None:
        connection = self._require_connection()
        cursor = await connection.execute(
            """
            SELECT telegram_id, username, first_name, last_name
            FROM users
            WHERE username IS NOT NULL AND LOWER(username) = LOWER(?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (username,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return BotUser(
            telegram_id=int(row["telegram_id"]),
            username=str(row["username"]) if row["username"] else None,
            first_name=str(row["first_name"]),
            last_name=str(row["last_name"]),
        )

    async def create_support_request(
        self,
        telegram_id: int,
        username: str | None,
        reason: str,
    ) -> int:
        connection = self._require_connection()
        async with self._lock:
            cursor = await connection.execute(
                """
                INSERT INTO support_requests (
                    telegram_id, username_snapshot, reason, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (telegram_id, username, reason, _utc_now()),
            )
            await connection.commit()
            request_id = int(cursor.lastrowid)
            await cursor.close()
            return request_id

    async def list_pending_requests(self, limit: int = 20) -> list[SupportRequest]:
        connection = self._require_connection()
        cursor = await connection.execute(
            """
            SELECT id, telegram_id, username_snapshot, reason, created_at
            FROM support_requests
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            SupportRequest(
                request_id=int(row["id"]),
                telegram_id=int(row["telegram_id"]),
                username=row["username_snapshot"],
                reason=str(row["reason"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    async def close_support_request(self, request_id: int) -> int | None:
        connection = self._require_connection()
        async with self._lock:
            request_cursor = await connection.execute(
                """
                SELECT telegram_id
                FROM support_requests
                WHERE id = ? AND status = 'pending'
                """,
                (request_id,),
            )
            request_row = await request_cursor.fetchone()
            await request_cursor.close()
            if request_row is None:
                return None

            cursor = await connection.execute(
                """
                UPDATE support_requests
                SET status = 'closed', closed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_utc_now(), request_id),
            )
            await connection.commit()
            await cursor.close()
            return int(request_row["telegram_id"])

    async def get_stats(self) -> tuple[int, int]:
        connection = self._require_connection()
        users_cursor = await connection.execute("SELECT COUNT(*) AS count FROM users")
        users_row = await users_cursor.fetchone()
        await users_cursor.close()

        requests_cursor = await connection.execute(
            "SELECT COUNT(*) AS count FROM support_requests WHERE status = 'pending'"
        )
        requests_row = await requests_cursor.fetchone()
        await requests_cursor.close()

        return int(users_row["count"]), int(requests_row["count"])

    async def record_thanks(self, telegram_id: int, username: str | None) -> bool:
        connection = self._require_connection()
        now = datetime.now(timezone.utc)
        async with self._lock:
            cursor = await connection.execute(
                """
                SELECT created_at
                FROM gratitudes
                WHERE telegram_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (telegram_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                last_sent = _parse_utc(str(row["created_at"]))
                if now - last_sent < timedelta(days=1):
                    return False

            await connection.execute(
                """
                INSERT INTO gratitudes (telegram_id, username_snapshot, created_at)
                VALUES (?, ?, ?)
                """,
                (telegram_id, username, now.isoformat(timespec="seconds")),
            )
            await connection.commit()
            return True

    async def get_thanks_stats(self) -> ThanksStats:
        connection = self._require_connection()
        moscow_now = datetime.now(MOSCOW_TIMEZONE)
        moscow_day_start = moscow_now.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_day_start = moscow_day_start.astimezone(timezone.utc).isoformat(timespec="seconds")

        today_cursor = await connection.execute(
            "SELECT COUNT(*) AS count FROM gratitudes WHERE created_at >= ?",
            (utc_day_start,),
        )
        today_row = await today_cursor.fetchone()
        await today_cursor.close()

        total_cursor = await connection.execute("SELECT COUNT(*) AS count FROM gratitudes")
        total_row = await total_cursor.fetchone()
        await total_cursor.close()

        return ThanksStats(
            today=int(today_row["count"]),
            total=int(total_row["count"]),
            notifications_enabled=await self.thanks_notifications_enabled(),
        )

    async def thanks_notifications_enabled(self) -> bool:
        connection = self._require_connection()
        cursor = await connection.execute(
            "SELECT setting_value FROM bot_settings WHERE setting_key = 'thanks_notifications'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is None or str(row["setting_value"]) != "off"

    async def set_thanks_notifications_enabled(self, enabled: bool) -> None:
        connection = self._require_connection()
        async with self._lock:
            await connection.execute(
                """
                INSERT INTO bot_settings (setting_key, setting_value)
                VALUES ('thanks_notifications', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value
                """,
                ("on" if enabled else "off",),
            )
            await connection.commit()

    async def notification_was_sent(self, notification_hash: str) -> bool:
        connection = self._require_connection()
        cursor = await connection.execute(
            "SELECT 1 FROM sent_notifications WHERE notification_hash = ?",
            (notification_hash,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def mark_notification_sent(self, notification_hash: str, telegram_id: int) -> None:
        connection = self._require_connection()
        async with self._lock:
            await connection.execute(
                """
                INSERT OR IGNORE INTO sent_notifications (
                    notification_hash, telegram_id, sent_at
                ) VALUES (?, ?, ?)
                """,
                (notification_hash, telegram_id, _utc_now()),
            )
            await connection.commit()

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected")
        return self._connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
