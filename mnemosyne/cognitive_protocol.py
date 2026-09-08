"""Language-neutral cognitive memory protocol for Agent-scoped workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class RememberRequest:
    content: str
    source: str = "agent"
    importance: float = 0.5
    session_id: str = "default"
    scope: str = "agent"
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class RecallRequest:
    query: str
    top_k: int = 5
    session_id: str | None = None
    scope: str | None = None


@dataclass(frozen=True)
class CorrectRequest:
    content: str
    correction_of: str | None = None
    source: str = "agent_correction"
    importance: float = 0.8
    session_id: str = "default"
    scope: str = "agent"
    metadata: dict[str, Any] | None = None


def _string(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def _importance(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("importance must be numeric") from error
    if not 0.0 <= result <= 1.0:
        raise ValueError("importance must be between 0 and 1")
    return result


def parse_request(payload: dict[str, Any]) -> tuple[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    if payload.get("protocol") not in (None, PROTOCOL_VERSION):
        raise ValueError(f"unsupported protocol: {payload.get('protocol')}")
    method = _string(payload.get("method"), "method", 64)
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    if method == "remember":
        return method, RememberRequest(
            content=_string(params.get("content"), "content", 100_000),
            source=_string(params.get("source", "agent"), "source", 256),
            importance=_importance(params.get("importance", 0.5)),
            session_id=_string(params.get("session_id", "default"), "session_id", 256),
            scope=_string(params.get("scope", "agent"), "scope", 64),
            metadata=params.get("metadata"),
        )
    if method == "recall":
        top_k = int(params.get("top_k", 5))
        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        return method, RecallRequest(
            query=_string(params.get("query"), "query", 10_000),
            top_k=top_k, session_id=params.get("session_id"), scope=params.get("scope"),
        )
    if method == "correct":
        correction_of = params.get("correction_of")
        if correction_of is not None:
            correction_of = _string(correction_of, "correction_of", 256)
        return method, CorrectRequest(
            content=_string(params.get("content"), "content", 100_000),
            correction_of=correction_of,
            source=_string(params.get("source", "agent_correction"), "source", 256),
            importance=_importance(params.get("importance", 0.8)),
            session_id=_string(params.get("session_id", "default"), "session_id", 256),
            scope=_string(params.get("scope", "agent"), "scope", 64),
            metadata=params.get("metadata"),
        )
    if method in {"stats", "ping", "close"}:
        return method, params
    raise ValueError(f"unsupported method: {method}")


def request_to_dict(request: Any) -> dict[str, Any]:
    return asdict(request)

