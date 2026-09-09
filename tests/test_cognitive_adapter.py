from pathlib import Path

import pytest

from mnemosyne.agent_memory import CognitiveAgentMemory, EventsAgentMemory, InMemoryBroker
from mnemosyne.cognitive_adapter import CognitiveWorkerAdapter, FAILED_EVENT


def test_emit_listen_round_trip_uses_real_ndjson_worker(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("sales-agent", broker)
    events = EventsAgentMemory("sales-agent", broker)
    stored = []
    recalled = []

    events.listen("AgentMemory.Cognitive.Stored", stored.append)
    events.listen("AgentMemory.Cognitive.Recalled", recalled.append)

    with CognitiveWorkerAdapter("sales-agent", broker, tmp_path):
        remember_id = cognitive.emit(
            {
                "operation": "remember",
                "content": "Cliente prefere Pix; marcador adapterpixpreference.",
                "importance": 1.0,
            },
            correlation_id="remember-1",
        )
        recall_id = cognitive.emit(
            {"operation": "recall", "query": "adapterpixpreference", "top_k": 5},
            correlation_id="recall-1",
        )

    assert remember_id == "remember-1"
    assert recall_id == "recall-1"
    assert len(stored) == 1
    assert stored[0].correlation_id == "remember-1"
    assert stored[0].payload["operation"] == "remember"
    assert stored[0].payload["result"]["agent_id"] == "sales-agent"
    assert len(recalled) == 1
    assert recalled[0].correlation_id == "recall-1"
    contents = [item["content"] for item in recalled[0].payload["result"]["items"]]
    assert "Cliente prefere Pix; marcador adapterpixpreference." in contents


def test_adapter_preserves_agent_isolation(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive_a = CognitiveAgentMemory("agent-a", broker)
    cognitive_b = CognitiveAgentMemory("agent-b", broker)
    events_b = EventsAgentMemory("agent-b", broker)
    recalled_b = []
    events_b.listen("AgentMemory.Cognitive.Recalled", recalled_b.append)

    with CognitiveWorkerAdapter("agent-a", broker, tmp_path), CognitiveWorkerAdapter("agent-b", broker, tmp_path):
        cognitive_a.emit(
            {"operation": "remember", "content": "Segredo A; marcador adapterprivateknowledge."},
            correlation_id="private-write",
        )
        cognitive_b.emit(
            {"operation": "recall", "query": "adapterprivateknowledge"},
            correlation_id="foreign-read",
        )

    assert len(recalled_b) == 1
    assert recalled_b[0].payload["result"]["items"] == []


def test_adapter_emits_failed_and_propagates_handler_error(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("agent-a", broker)
    events = EventsAgentMemory("agent-a", broker)
    failed = []
    events.listen(FAILED_EVENT, failed.append)

    with CognitiveWorkerAdapter("agent-a", broker, tmp_path):
        with pytest.raises(ValueError, match="unsupported cognitive operation"):
            cognitive.emit({"operation": "erase-everything"}, correlation_id="bad-op")

    assert len(failed) == 1
    assert failed[0].correlation_id == "bad-op"
    assert failed[0].payload["operation"] == "erase-everything"
    assert failed[0].payload["error"]["type"] == "ValueError"
