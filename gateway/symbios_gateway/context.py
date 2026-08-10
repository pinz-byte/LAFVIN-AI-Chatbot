from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from .config import GatewaySettings


MAX_CONTEXT_RESPONSE_BYTES = 256 * 1024
MAX_TOOL_OUTPUT_CHARS = 12_000


class SymbiosContextError(RuntimeError):
    pass


def _bounded_text(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_TOOL_OUTPUT_CHARS:
        return value, False
    return value[:MAX_TOOL_OUTPUT_CHARS], True


@dataclass(frozen=True)
class SymbiosContextClient:
    base_url: str
    token: str = field(repr=False)
    timeout_seconds: float = 12.0
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)

    @classmethod
    def from_settings(cls, settings: GatewaySettings) -> "SymbiosContextClient":
        if not settings.context_enabled:
            raise SymbiosContextError("Symbios context is not configured")
        assert settings.context_base_url is not None
        assert settings.context_token is not None
        return cls(
            base_url=settings.context_base_url,
            token=settings.context_token,
            timeout_seconds=settings.context_timeout_seconds,
        )

    async def _post(self, route: str, payload: dict[str, object]) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self.token}"}
        timeout = httpx.Timeout(self.timeout_seconds)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                async with client.stream("POST", route, json=payload) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_CONTEXT_RESPONSE_BYTES:
                            raise SymbiosContextError("Symbios context response exceeded its limit")
        except SymbiosContextError:
            raise
        except httpx.TimeoutException as exc:
            raise SymbiosContextError("Symbios context timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise SymbiosContextError(
                f"Symbios context returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SymbiosContextError("Symbios context is unreachable") from exc

        try:
            decoded = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SymbiosContextError("Symbios context returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise SymbiosContextError("Symbios context returned an invalid object")
        return decoded

    async def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "get_operational_brief":
            result = await self._post("/brief", {"trigger": "voice_gateway"})
            brief = result.get("text", "")
            if not isinstance(brief, str):
                raise SymbiosContextError("Symbios brief did not contain text")
            output, truncated = _bounded_text(brief)
            return {
                "output": output,
                "truncated": truncated,
                "source": "symbios_memory_bridge",
            }

        if name == "search_symbios_context":
            query = arguments.get("query")
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
                return {"error": "query must contain between 1 and 500 characters"}
            result = await self._post(
                "/query",
                {
                    "query": query.strip(),
                    "limit": 6,
                    "score_threshold": 0.3,
                    "rerank": False,
                    "mode": "hybrid",
                    "depth": 2,
                    "min_salience": 0.0,
                },
            )
            degraded = result.get("degraded", {})
            safe_degraded = {
                "vector_unavailable": bool(
                    isinstance(degraded, dict) and degraded.get("vector_error")
                ),
                "graph_available": bool(
                    isinstance(degraded, dict) and degraded.get("graph_available")
                ),
            }
            safe_result = {
                "query": result.get("query", query.strip()),
                "total_results": result.get("total_results", 0),
                "results": result.get("results", {}),
                "raw_results": result.get("raw_results", [])[:6]
                if isinstance(result.get("raw_results"), list)
                else [],
                "graph_results": result.get("graph_results", [])[:6]
                if isinstance(result.get("graph_results"), list)
                else [],
                "namespaces_searched": result.get("namespaces_searched", []),
                "mode": result.get("mode", "hybrid"),
                "degraded": safe_degraded,
            }
            compact = json.dumps(safe_result, ensure_ascii=False, separators=(",", ":"))
            output, truncated = _bounded_text(compact)
            return {
                "output": output,
                "truncated": truncated,
                "source": "symbios_memory_bridge",
            }

        return {"error": "unknown read-only Symbios context tool"}
