"""Bridge between the Agent emit/listen contract and Mnemosyne.

This is the executable reference adapter for runtimes that keep the broker and
Mnemosyne in one process. A Zig runtime can preserve the same event contract
while replacing the direct worker call with its NDJSON child-process client.
"""

from __future__ import annotations

from typing import Callable

from mnemosyne.agent_memory import (
    AgentMemoryEvent,
    CognitiveAgentMemory,
    EventsAgentMemory,
)
from mnemosyne.cognitive_protocol import PROTOCOL_VERSION, parse_request
from mnemosyne.cognitive_worker import CognitiveMemoryWorker


class CognitiveMemoryAdapter:
    """Consume cognitive requests and emit correlated Ok/Error events."""

    OPERATIONS = frozenset({"remember", "recall", "correct", "stats", "ping"})

    def __init__(
        self,
        worker: CognitiveMemoryWorker,
        cognitive: CognitiveAgentMemory,
        events: EventsAgentMemory,
    ) -> None:
        if not (worker.agent_id == cognitive.agent_id == events.agent_id):
            raise ValueError("worker, cognitive memory, and events memory must share agent_id")
        self.worker = worker
        self.cognitive = cognitive
        self.events = events
        self._unsubscribe: Callable[[], None] | None = cognitive.listen(
            CognitiveAgentMemory.REQUESTED,
            self._handle,
        )

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _handle(self, event: AgentMemoryEvent) -> None:
        payload = dict(event.payload)
        operation = payload.pop("operation", None)

        try:
            if operation not in self.OPERATIONS:
                raise ValueError(f"unsupported cognitive operation: {operation}")
            method, params = parse_request(
                {
                    "protocol": PROTOCOL_VERSION,
                    "method": operation,
                    "params": payload,
                }
            )
            result = self.worker.dispatch(method, params)
        except Exception as error:
            self.events.emit(
                CognitiveAgentMemory.ERROR,
                {
                    "operation": operation,
                    "error": {
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                },
                correlation_id=event.correlation_id,
            )
            return

        self.events.emit(
            CognitiveAgentMemory.OK,
            {
                "operation": operation,
                "result": result,
            },
            correlation_id=event.correlation_id,
        )


__all__ = ["CognitiveMemoryAdapter"]
