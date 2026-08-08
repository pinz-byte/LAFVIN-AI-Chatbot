from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class GatewaySettings:
    public_base_url: str
    jwt_secret: str
    admin_token: str
    upstream_ws_url: str
    database_path: Path
    upstream_authorization: str | None = None
    session_ttl_seconds: int = 300
    activation_ttl_seconds: int = 600
    allow_insecure_urls: bool = False

    def __post_init__(self) -> None:
        public = urlparse(self.public_base_url)
        upstream = urlparse(self.upstream_ws_url)
        expected_http = {"http", "https"} if self.allow_insecure_urls else {"https"}
        expected_ws = {"ws", "wss"} if self.allow_insecure_urls else {"wss"}
        if public.scheme not in expected_http or not public.netloc:
            raise ValueError("SYMBIOS_PUBLIC_BASE_URL must be a valid HTTPS URL")
        if upstream.scheme not in expected_ws or not upstream.netloc:
            raise ValueError("SYMBIOS_UPSTREAM_WS_URL must be a valid WSS URL")
        if len(self.jwt_secret) < 32:
            raise ValueError("SYMBIOS_JWT_SECRET must contain at least 32 characters")
        if len(self.admin_token) < 32:
            raise ValueError("SYMBIOS_ADMIN_TOKEN must contain at least 32 characters")
        if not 30 <= self.session_ttl_seconds <= 3600:
            raise ValueError("session TTL must be between 30 and 3600 seconds")
        if not 60 <= self.activation_ttl_seconds <= 3600:
            raise ValueError("activation TTL must be between 60 and 3600 seconds")

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise RuntimeError(f"missing required environment variable: {name}")
            return value

        return cls(
            public_base_url=required("SYMBIOS_PUBLIC_BASE_URL").rstrip("/"),
            jwt_secret=required("SYMBIOS_JWT_SECRET"),
            admin_token=required("SYMBIOS_ADMIN_TOKEN"),
            upstream_ws_url=required("SYMBIOS_UPSTREAM_WS_URL"),
            upstream_authorization=os.environ.get("SYMBIOS_UPSTREAM_AUTHORIZATION") or None,
            database_path=Path(os.environ.get("SYMBIOS_DB_PATH", "/data/symbios-gateway.sqlite3")),
            session_ttl_seconds=int(os.environ.get("SYMBIOS_SESSION_TTL_SECONDS", "300")),
            activation_ttl_seconds=int(os.environ.get("SYMBIOS_ACTIVATION_TTL_SECONDS", "600")),
        )

    @property
    def websocket_url(self) -> str:
        base = self.public_base_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base.removeprefix("https://")
        elif base.startswith("http://"):
            base = "ws://" + base.removeprefix("http://")
        return f"{base}/xiaozhi/v1/"
