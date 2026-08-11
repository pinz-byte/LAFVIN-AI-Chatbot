from __future__ import annotations

import hmac
import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .security import hash_device_token


@dataclass(frozen=True)
class Enrollment:
    device_id: str
    client_id: str
    code: str
    challenge: str
    expires_at: int
    approved: bool


class Store(Protocol):
    def close(self) -> None: ...

    def authenticate(self, device_id: str, client_id: str, token: str) -> bool: ...

    def get_or_create_enrollment(
        self,
        device_id: str,
        client_id: str,
        *,
        ttl_seconds: int,
        now: int | None = None,
    ) -> Enrollment: ...

    def approve(self, code: str, *, now: int | None = None) -> Enrollment | None: ...

    def activate(
        self,
        device_id: str,
        client_id: str,
        challenge: str,
        *,
        now: int | None = None,
    ) -> str | None: ...

    def save_terminal_snapshot(
        self, payload_json: str, *, source_at: int, received_at: int
    ) -> bool: ...

    def load_terminal_snapshot(self) -> str | None: ...


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
                CREATE TABLE IF NOT EXISTS terminal_snapshot (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload_json TEXT NOT NULL,
                    source_at INTEGER NOT NULL,
                    received_at INTEGER NOT NULL
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

    def activate(
        self,
        device_id: str,
        client_id: str,
        challenge: str,
        *,
        now: int | None = None,
    ) -> str | None:
        current_time = int(time.time()) if now is None else now
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT approved, challenge FROM pending_enrollments
                WHERE device_id = ? AND client_id = ? AND expires_at > ?
                """,
                (device_id, client_id, current_time),
            ).fetchone()
            if (
                row is None
                or not row["approved"]
                or not hmac.compare_digest(row["challenge"], challenge)
            ):
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

    def save_terminal_snapshot(
        self, payload_json: str, *, source_at: int, received_at: int
    ) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO terminal_snapshot
                    (singleton, payload_json, source_at, received_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    source_at = excluded.source_at,
                    received_at = excluded.received_at
                WHERE terminal_snapshot.source_at < excluded.source_at
                """,
                (payload_json, source_at, received_at),
            )
        return cursor.rowcount == 1

    def load_terminal_snapshot(self) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload_json FROM terminal_snapshot WHERE singleton = 1"
            ).fetchone()
        return None if row is None else str(row["payload_json"])

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


class FirestoreGatewayStore:
    """Persistent enrollment store for horizontally scaled Cloud Run instances."""

    def __init__(self, project: str) -> None:
        from google.cloud import firestore

        self._firestore = firestore
        self._client = firestore.Client(project=project)
        self._enrollments = self._client.collection("symbios_gateway_enrollments")
        self._codes = self._client.collection("symbios_gateway_activation_codes")
        self._devices = self._client.collection("symbios_gateway_devices")
        self._terminal = self._client.collection("symbios_gateway_terminal_feed")

    @staticmethod
    def _device_key(device_id: str, client_id: str) -> str:
        material = f"{device_id}\0{client_id}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def _to_enrollment(data: dict[str, object]) -> Enrollment:
        return Enrollment(
            device_id=str(data["device_id"]),
            client_id=str(data["client_id"]),
            code=str(data["code"]),
            challenge=str(data["challenge"]),
            expires_at=int(data["expires_at"]),
            approved=bool(data.get("approved", False)),
        )

    def close(self) -> None:
        self._client.close()

    def authenticate(self, device_id: str, client_id: str, token: str) -> bool:
        snapshot = self._devices.document(self._device_key(device_id, client_id)).get()
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        token_hash = data.get("token_hash")
        return isinstance(token_hash, str) and hmac.compare_digest(
            token_hash, hash_device_token(token)
        )

    def get_or_create_enrollment(
        self,
        device_id: str,
        client_id: str,
        *,
        ttl_seconds: int,
        now: int | None = None,
    ) -> Enrollment:
        current_time = int(time.time()) if now is None else now
        device_key = self._device_key(device_id, client_id)
        enrollment_ref = self._enrollments.document(device_key)

        for _ in range(20):
            code = f"{secrets.randbelow(1_000_000):06d}"
            code_ref = self._codes.document(code)
            transaction = self._client.transaction()

            @self._firestore.transactional
            def create(transaction):
                existing = enrollment_ref.get(transaction=transaction)
                old_code = None
                if existing.exists:
                    data = existing.to_dict() or {}
                    if int(data.get("expires_at", 0)) > current_time:
                        return data
                    old_code = data.get("code")

                existing_code = code_ref.get(transaction=transaction)
                if existing_code.exists:
                    return None
                if isinstance(old_code, str):
                    transaction.delete(self._codes.document(old_code))
                data = {
                    "device_id": device_id,
                    "client_id": client_id,
                    "code": code,
                    "challenge": secrets.token_urlsafe(24),
                    "expires_at": current_time + ttl_seconds,
                    "approved": False,
                }
                transaction.set(enrollment_ref, data)
                transaction.set(
                    code_ref,
                    {"device_key": device_key, "expires_at": current_time + ttl_seconds},
                )
                return data

            data = create(transaction)
            if data is not None:
                return self._to_enrollment(data)
        raise RuntimeError("could not allocate a unique enrollment code")

    def approve(self, code: str, *, now: int | None = None) -> Enrollment | None:
        current_time = int(time.time()) if now is None else now
        code_ref = self._codes.document(code)
        transaction = self._client.transaction()

        @self._firestore.transactional
        def approve(transaction):
            code_snapshot = code_ref.get(transaction=transaction)
            if not code_snapshot.exists:
                return None
            code_data = code_snapshot.to_dict() or {}
            if int(code_data.get("expires_at", 0)) <= current_time:
                transaction.delete(code_ref)
                return None
            device_key = code_data.get("device_key")
            if not isinstance(device_key, str):
                return None
            enrollment_ref = self._enrollments.document(device_key)
            snapshot = enrollment_ref.get(transaction=transaction)
            if not snapshot.exists:
                transaction.delete(code_ref)
                return None
            data = snapshot.to_dict() or {}
            if data.get("code") != code or int(data.get("expires_at", 0)) <= current_time:
                transaction.delete(code_ref)
                return None
            data["approved"] = True
            transaction.update(enrollment_ref, {"approved": True})
            return data

        data = approve(transaction)
        return None if data is None else self._to_enrollment(data)

    def activate(
        self,
        device_id: str,
        client_id: str,
        challenge: str,
        *,
        now: int | None = None,
    ) -> str | None:
        current_time = int(time.time()) if now is None else now
        device_key = self._device_key(device_id, client_id)
        enrollment_ref = self._enrollments.document(device_key)
        device_ref = self._devices.document(device_key)
        token = secrets.token_urlsafe(32)
        transaction = self._client.transaction()

        @self._firestore.transactional
        def activate(transaction):
            snapshot = enrollment_ref.get(transaction=transaction)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict() or {}
            stored_challenge = data.get("challenge")
            if (
                not data.get("approved")
                or int(data.get("expires_at", 0)) <= current_time
                or not isinstance(stored_challenge, str)
                or not hmac.compare_digest(stored_challenge, challenge)
            ):
                return False
            transaction.set(
                device_ref,
                {
                    "device_id": device_id,
                    "client_id": client_id,
                    "token_hash": hash_device_token(token),
                    "updated_at": current_time,
                },
            )
            code = data.get("code")
            if isinstance(code, str):
                transaction.delete(self._codes.document(code))
            transaction.delete(enrollment_ref)
            return True

        return token if activate(transaction) else None

    def save_terminal_snapshot(
        self, payload_json: str, *, source_at: int, received_at: int
    ) -> bool:
        snapshot_ref = self._terminal.document("latest")
        transaction = self._client.transaction()

        @self._firestore.transactional
        def save(transaction):
            existing = snapshot_ref.get(transaction=transaction)
            if existing.exists:
                data = existing.to_dict() or {}
                if int(data.get("source_at", 0)) >= source_at:
                    return False
            transaction.set(
                snapshot_ref,
                {
                    "payload_json": payload_json,
                    "source_at": source_at,
                    "received_at": received_at,
                },
            )
            return True

        return bool(save(transaction))

    def load_terminal_snapshot(self) -> str | None:
        snapshot = self._terminal.document("latest").get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        payload = data.get("payload_json")
        return payload if isinstance(payload, str) else None
