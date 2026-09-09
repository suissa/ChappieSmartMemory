"""Agent-facing emit/listen interfaces backed by an in-memory broker.

The public vocabulary is deliberately limited to emit and listen.
The broker is transport-agnostic and can later be replaced by UbiQ or another
adapter without changing the Agent-facing contract.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class AgentMemoryEvent:
    type: str
    agent_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid4()))


Listener = Callable[[AgentMemoryEvent], None]


class InMemoryBroker:
    """Synchronous, in-process event broker."""

    def __init__(self) -> None:
        self._listeners: dict[tuple[str, str], list[Listener]] = defaultdict(list)
        self._lock = RLock()

    def emit(self, event: AgentMemoryEvent) -> None:
        with self._lock:
            listeners = tuple(self._listeners.get((event.agent_id, event.type), ()))
            listeners += tuple(self._listeners.get((event.agent_id, "*"), ()))
        for listener in listeners:
            listener(event)

    def listen(self, agent_id: str, event_type: str, handler: Listener) -> Callable[[], None]:
        key = (agent_id, event_type)
        with self._lock:
            self._listeners[key].append(handler)
        removed = False

        def unsubscribe() -> None:
            nonlocal removed
            if removed:
                return
            with self._lock:
                listeners = self._listeners.get(key)
                if listeners and handler in listeners:
                    listeners.remove(handler)
                    if not listeners:
                        self._listeners.pop(key, None)
            removed = True

        return unsubscribe


class CognitiveAgentMemory:
    """Agent-facing cognitive memory boundary."""

    REQUESTED = "AgentMemory.Cognitive.Requested"
    OK = "AgentMemory.Cognitive.Ok"
    ERROR = "AgentMemory.Cognitive.Error"

    def __init__(self, agent_id: str, broker: InMemoryBroker) -> None:
        self.agent_id = agent_id
        self.broker = broker

    def emit(self, payload: dict[str, Any], *, correlation_id: str | None = None) -> str:
        event = AgentMemoryEvent(
            type=self.REQUESTED,
            agent_id=self.agent_id,
            payload=dict(payload),
            correlation_id=correlation_id or str(uuid4()),
        )
        self.broker.emit(event)
        return event.correlation_id

    def listen(self, event_type: str, handler: Listener) -> Callable[[], None]:
        return self.broker.listen(self.agent_id, event_type, handler)


class EventsAgentMemory:
    """Event-facing boundary for the Agent's in-memory memory events."""

    def __init__(self, agent_id: str, broker: InMemoryBroker) -> None:
        self.agent_id = agent_id
        self.broker = broker

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> str:
        event = AgentMemoryEvent(
            type=event_type,
            agent_id=self.agent_id,
            payload=dict(payload or {}),
            correlation_id=correlation_id or str(uuid4()),
        )
        self.broker.emit(event)
        return event.correlation_id

    def listen(self, event_type: str, handler: Listener) -> Callable[[], None]:
        return self.broker.listen(self.agent_id, event_type, handler)


__all__ = [
    "AgentMemoryEvent",
    "CognitiveAgentMemory",
    "EventsAgentMemory",
    "InMemoryBroker",
    "Listener",
]
