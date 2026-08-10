from __future__ import annotations

import asyncio
import json

import httpx

from symbios_gateway.context import SymbiosContextClient


def test_context_client_uses_bearer_auth_and_canonical_read_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/brief":
            return httpx.Response(200, json={"text": "Priority: Symbios Terminal"})
        return httpx.Response(
            200,
            json={
                "query": "terminal",
                "total_results": 1,
                "raw_results": [{"text": "Voice gateway work"}],
            },
        )

    client = SymbiosContextClient(
        base_url="https://context.test",
        token="server-only-token",
        transport=httpx.MockTransport(handler),
    )

    brief = asyncio.run(client.execute("get_operational_brief", {}))
    search = asyncio.run(
        client.execute("search_symbios_context", {"query": "terminal"})
    )

    assert brief["output"] == "Priority: Symbios Terminal"
    assert json.loads(search["output"])["total_results"] == 1
    assert [request.url.path for request in requests] == ["/brief", "/query"]
    assert all(
        request.headers["authorization"] == "Bearer server-only-token"
        for request in requests
    )


def test_context_client_exposes_no_write_or_session_close_tool() -> None:
    client = SymbiosContextClient(
        base_url="https://context.test",
        token="server-only-token",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(500, json={"detail": "must not be called"})
        ),
    )

    result = asyncio.run(client.execute("close_and_ingest_session", {}))

    assert result == {"error": "unknown read-only Symbios context tool"}
