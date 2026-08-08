from __future__ import annotations

import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .security import hash_device_token


@dataclass(frozen=True)
class Enrollment:
    device_id: str
    client_id: str
    code: str
    challenge: str
    expires_at: int
    approved: bool


class GatewayStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS pending_enrollments (
                    device_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    code TEXT NOT NULL UNIQUE,
                    challenge TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (device_id, client_id)
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (device_id, client_id)
                );
                """
            )

    def close(self) -> None:
        self._connection.close()

    def authenticate(self, device_id: str, client_id: str, token: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT token_hash FROM devices WHERE device_id = ? AND client_id = ?",
                (device_id, client_id),
            ).fetchone()
        return row is not None and hmac.compare_digest(row["token_hash"], hash_device_token(token))

    def get_or_create_enrollment(
        self,
        device_id: str,
        client_id: str,
        *,
        ttl_seconds: int,
        now: int | None = None,
    ) -> Enrollment:
        current_time = int(time.time()) if now is None else now
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM pending_enrollments WHERE expires_at <= ?",
                (current_time,),
            )
            row = self._connection.execute(
                "SELECT * FROM pending_enrollments WHERE device_id = ? AND client_id = ?",
                (device_id, client_id),
            ).fetchone()
            if row is None:
                for _ in range(20):
                    code = f"{secrets.randbelow(1_000_000):06d}"
                    try:
                        self._connection.execute(
                            """
                            INSERT INTO pending_enrollments
                                (device_id, client_id, code, challenge, expires_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                device_id,
                                client_id,
                                code,
                                secrets.token_urlsafe(24),
                                current_time + ttl_seconds,
                            ),
                        )
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    raise RuntimeError("could not allocate a unique enrollment code")
                row = self._connection.execute(
                    "SELECT * FROM pending_enrollments WHERE device_id = ? AND client_id = ?",
                    (device_id, client_id),
                ).fetchone()
        return self._to_enrollment(row)

    def approve(self, code: str, *, now: int | None = None) -> Enrollment | None:
        current_time = int(time.time()) if now is None else now
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM pending_enrollments WHERE code = ? AND expires_at > ?",
                (code, current_time),
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                "UPDATE pending_enrollments SET approved = 1 WHERE code = ?",
                (code,),
            )
            row = dict(row)
            row["approved"] = 1
        return self._to_enrollment(row)

    def activate(self, device_id: str, client_id: str, *, now: int | None = None) -> str | None:
        current_time = int(time.time()) if now is None else now
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT approved FROM pending_enrollments
                WHERE device_id = ? AND client_id = ? AND expires_at > ?
                """,
                (device_id, client_id, current_time),
            ).fetchone()
            if row is None or not row["approved"]:
                return None
            token = secrets.token_urlsafe(32)
            token_hash = hash_device_token(token)
            self._connection.execute(
                """
                INSERT INTO devices (device_id, client_id, token_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id, client_id) DO UPDATE SET
                    token_hash = excluded.token_hash,
                    updated_at = excluded.updated_at
                """,
                (device_id, client_id, token_hash, current_time, current_time),
            )
            self._connection.execute(
                "DELETE FROM pending_enrollments WHERE device_id = ? AND client_id = ?",
                (device_id, client_id),
            )
        return token

    @staticmethod
    def _to_enrollment(row: sqlite3.Row | dict[str, object]) -> Enrollment:
        return Enrollment(
            device_id=str(row["device_id"]),
            client_id=str(row["client_id"]),
            code=str(row["code"]),
            challenge=str(row["challenge"]),
            expires_at=int(row["expires_at"]),
            approved=bool(row["approved"]),
        )
