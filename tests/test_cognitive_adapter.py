"""End-to-end tests for emit -> broker -> Mnemosyne -> result event."""

from pathlib import Path

import pytest

from mnemosyne.agent_memory import (
    CognitiveAgentMemory,
    EventsAgentMemory,
    InMemoryBroker,
)
from mnemosyne.cognitive_adapter import CognitiveMemoryAdapter
from mnemosyne.cognitive_worker import CognitiveMemoryWorker


def memory_stack(tmp_path: Path, agent_id: str = "agent-a"):
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory(agent_id, broker)
    events = EventsAgentMemory(agent_id, broker)
    worker = CognitiveMemoryWorker(agent_id, tmp_path)
    adapter = CognitiveMemoryAdapter(worker, cognitive, events)
    return cognitive, events, adapter


def test_emit_remember_then_emit_recall_returns_learned_memory(tmp_path: Path) -> None:
    cognitive, events, adapter = memory_stack(tmp_path)
    completed = []
    events.listen(CognitiveAgentMemory.OK, completed.append)

    remember_id = cognitive.emit(
        {
            "operation": "remember",
            "content": "A janela de manutenção é domingo; marcador emitlistenprobe.",
            "source": "emit-listen-e2e",
            "importance": 0.95,
        }
    )
    recall_id = cognitive.emit(
        {
            "operation": "recall",
            "query": "emitlistenprobe",
            "top_k": 5,
        }
    )

    try:
        assert [event.correlation_id for event in completed] == [remember_id, recall_id]
        assert completed[0].payload["operation"] == "remember"
        assert completed[0].payload["result"]["memory_id"]

        recalled = completed[1].payload["result"]["items"]
        assert any("emitlistenprobe" in item["content"] for item in recalled)
    finally:
        adapter.close()


def test_emit_preserves_correlation_id_on_error(tmp_path: Path) -> None:
    cognitive, events, adapter = memory_stack(tmp_path)
    failed = []
    events.listen(CognitiveAgentMemory.ERROR, failed.append)

    correlation_id = cognitive.emit(
        {"operation": "recall", "query": "", "top_k": 5},
        correlation_id="request-from-zig-42",
    )

    try:
        assert correlation_id == "request-from-zig-42"
        assert len(failed) == 1
        assert failed[0].correlation_id == correlation_id
        assert failed[0].payload["operation"] == "recall"
        assert failed[0].payload["error"]["type"] == "ValueError"
    finally:
        adapter.close()


def test_closed_adapter_stops_consuming_requests(tmp_path: Path) -> None:
    cognitive, events, adapter = memory_stack(tmp_path)
    completed = []
    events.listen(CognitiveAgentMemory.OK, completed.append)

    adapter.close()
    cognitive.emit({"operation": "ping"})

    assert completed == []


def test_adapter_rejects_cross_agent_wiring(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("agent-a", broker)
    events = EventsAgentMemory("agent-b", broker)
    worker = CognitiveMemoryWorker("agent-a", tmp_path)

    with pytest.raises(ValueError, match="share agent_id"):
        CognitiveMemoryAdapter(worker, cognitive, events)
