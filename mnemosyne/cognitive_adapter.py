"""Broker-to-NDJSON adapter for Agent-scoped cognitive memory."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from threading import RLock
from typing import Any

from mnemosyne.agent_memory import AgentMemoryEvent, CognitiveAgentMemory, InMemoryBroker
from mnemosyne.cognitive_protocol import PROTOCOL_VERSION


_RESULT_EVENTS = {
    "remember": "AgentMemory.Cognitive.Stored",
    "recall": "AgentMemory.Cognitive.Recalled",
    "correct": "AgentMemory.Cognitive.Corrected",
    "stats": "AgentMemory.Cognitive.Stats",
    "ping": "AgentMemory.Cognitive.Pong",
}
FAILED_EVENT = "AgentMemory.Cognitive.Failed"


class CognitiveWorkerAdapter:
    """Translate Agent memory broker events to the language-neutral NDJSON worker."""

    def __init__(
        self,
        agent_id: str,
        broker: InMemoryBroker,
        data_dir: Path,
        *,
        command: list[str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.broker = broker
        self.data_dir = Path(data_dir)
        self.command = command or [
            sys.executable,
            "-m",
            "mnemosyne.cognitive_worker",
            "--agent-id",
            agent_id,
            "--data-dir",
            str(self.data_dir),
        ]
        self._process: subprocess.Popen[str] | None = None
        self._unsubscribe = None
        self._lock = RLock()

    def start(self) -> "CognitiveWorkerAdapter":
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            if self._unsubscribe is None:
                self._unsubscribe = self.broker.listen(
                    self.agent_id,
                    CognitiveAgentMemory.REQUESTED,
                    self._handle,
                )
        return self

    def close(self) -> None:
        with self._lock:
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            try:
                self._request({"protocol": PROTOCOL_VERSION, "id": "adapter-close", "method": "close"}, process=process)
            finally:
                process.wait(timeout=10)

    def __enter__(self) -> "CognitiveWorkerAdapter":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _request(self, payload: dict[str, Any], *, process: subprocess.Popen[str] | None = None) -> dict[str, Any]:
        active = process or self._process
        if active is None or active.poll() is not None or active.stdin is None or active.stdout is None:
            raise RuntimeError("cognitive worker is not running")
        active.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        active.stdin.flush()
        line = active.stdout.readline()
        if not line:
            stderr = ""
            if active.stderr is not None:
                stderr = active.stderr.read().strip()
            raise RuntimeError(f"cognitive worker terminated without response: {stderr}")
        return json.loads(line)

    def _handle(self, event: AgentMemoryEvent) -> None:
        payload = dict(event.payload)
        operation = payload.pop("operation", None)
        if not isinstance(operation, str) or not operation:
            self._fail(event, operation, "operation must be a non-empty string")
            raise ValueError("operation must be a non-empty string")
        if operation not in _RESULT_EVENTS:
            self._fail(event, operation, f"unsupported cognitive operation: {operation}")
            raise ValueError(f"unsupported cognitive operation: {operation}")

        request = {
            "protocol": PROTOCOL_VERSION,
            "id": event.correlation_id,
            "method": operation,
            "params": payload,
        }
        with self._lock:
            try:
                response = self._request(request)
            except Exception as error:
                self._fail(event, operation, str(error), error_type=type(error).__name__)
                raise

        if response.get("id") != event.correlation_id:
            message = "cognitive worker response correlation id mismatch"
            self._fail(event, operation, message)
            raise RuntimeError(message)
        if not response.get("ok"):
            error = response.get("error") or {}
            message = str(error.get("message") or "cognitive worker request failed")
            self._fail(event, operation, message, error_type=str(error.get("type") or "WorkerError"))
            raise RuntimeError(message)

        self.broker.emit(
            AgentMemoryEvent(
                type=_RESULT_EVENTS[operation],
                agent_id=self.agent_id,
                payload={"operation": operation, "result": response.get("result")},
                correlation_id=event.correlation_id,
            )
        )

    def _fail(
        self,
        event: AgentMemoryEvent,
        operation: Any,
        message: str,
        *,
        error_type: str = "ValueError",
    ) -> None:
        self.broker.emit(
            AgentMemoryEvent(
                type=FAILED_EVENT,
                agent_id=self.agent_id,
                payload={
                    "operation": operation,
                    "error": {"type": error_type, "message": message},
                },
                correlation_id=event.correlation_id,
            )
        )


__all__ = ["CognitiveWorkerAdapter", "FAILED_EVENT"]
