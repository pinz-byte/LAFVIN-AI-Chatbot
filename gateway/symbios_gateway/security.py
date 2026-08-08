from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class TokenError(ValueError):
    pass


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session_token(
    secret: str,
    *,
    device_id: str,
    client_id: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    issued_at = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "aud": "symbios-xiaozhi",
        "iss": "symbios-voice-gateway",
        "sub": device_id,
        "client_id": client_id,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    encoded_header = _encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    encoded_payload = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_encode(signature)}"


def verify_session_token(secret: str, token: str, *, now: int | None = None) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}"
        expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(encoded_signature)):
            raise TokenError("invalid signature")
        header = json.loads(_decode(encoded_header))
        payload = json.loads(_decode(encoded_payload))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenError("malformed token") from exc

    current_time = int(time.time()) if now is None else now
    if header != {"alg": "HS256", "typ": "JWT"}:
        raise TokenError("unsupported token header")
    if payload.get("aud") != "symbios-xiaozhi" or payload.get("iss") != "symbios-voice-gateway":
        raise TokenError("invalid token audience")
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
        raise TokenError("expired token")
    if not isinstance(payload.get("iat"), int) or payload["iat"] > current_time + 30:
        raise TokenError("invalid issue time")
    if not isinstance(payload.get("sub"), str) or not isinstance(payload.get("client_id"), str):
        raise TokenError("missing device claims")
    return payload


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
