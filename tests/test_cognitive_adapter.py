from pathlib import Path

import pytest

from mnemosyne.agent_memory import CognitiveAgentMemory, EventsAgentMemory, InMemoryBroker
from mnemosyne.cognitive_adapter import CognitiveWorkerAdapter, FAILED_EVENT


def _effect(action_id: str, operation_id: str) -> dict[str, str]:
    return {"action_id": action_id, "memory_operation_id": operation_id}


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
                **_effect("action-sales-1", "remember-preference"),
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
    assert stored[0].payload["result"]["deduplicated"] is False
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
            {
                "operation": "remember",
                "content": "Segredo A; marcador adapterprivateknowledge.",
                **_effect("action-private-a", "remember-private"),
            },
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


def test_mutating_effect_requires_action_identity(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("identity-agent", broker)
    events = EventsAgentMemory("identity-agent", broker)
    failed = []
    events.listen(FAILED_EVENT, failed.append)

    with CognitiveWorkerAdapter("identity-agent", broker, tmp_path):
        with pytest.raises(ValueError, match="remember requires action_id"):
            cognitive.emit(
                {"operation": "remember", "content": "missing action identity"},
                correlation_id="missing-id",
            )

    assert failed[0].correlation_id == "missing-id"


def test_adapter_restarts_worker_that_died_before_next_request(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("restart-agent", broker)
    events = EventsAgentMemory("restart-agent", broker)
    pong = []
    events.listen("AgentMemory.Cognitive.Pong", pong.append)

    adapter = CognitiveWorkerAdapter("restart-agent", broker, tmp_path).start()
    try:
        first_process = adapter._process
        assert first_process is not None
        first_pid = first_process.pid

        first_process.terminate()
        first_process.wait(timeout=10)

        cognitive.emit({"operation": "ping"}, correlation_id="ping-after-death")

        assert adapter._process is not None
        assert adapter._process.poll() is None
        assert adapter._process.pid != first_pid
        assert len(pong) == 1
        assert pong[0].correlation_id == "ping-after-death"
        assert pong[0].payload["result"]["agent_id"] == "restart-agent"
    finally:
        adapter.close()


def test_same_action_effect_is_deduplicated_across_worker_restart(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("retry-agent", broker)
    events = EventsAgentMemory("retry-agent", broker)
    stored = []
    recalled = []
    events.listen("AgentMemory.Cognitive.Stored", stored.append)
    events.listen("AgentMemory.Cognitive.Recalled", recalled.append)

    adapter = CognitiveWorkerAdapter("retry-agent", broker, tmp_path).start()
    key = _effect("Action.PreferenceDetected:01JTEST", "preference-update")
    try:
        cognitive.emit(
            {
                "operation": "remember",
                "content": "Primeiro efeito; marcador originalactioneffect.",
                **key,
            },
            correlation_id="effect-first",
        )
        original_memory_id = stored[-1].payload["result"]["memory_id"]
        assert stored[-1].payload["result"]["deduplicated"] is False

        process = adapter._process
        assert process is not None
        process.terminate()
        process.wait(timeout=10)

        cognitive.emit(
            {
                "operation": "remember",
                "content": "Conteudo diferente que NAO pode ser aplicado; marcador duplicatedactioneffect.",
                **key,
            },
            correlation_id="effect-retry",
        )
        assert stored[-1].payload["result"]["memory_id"] == original_memory_id
        assert stored[-1].payload["result"]["deduplicated"] is True

        cognitive.emit(
            {"operation": "recall", "query": "duplicatedactioneffect", "top_k": 5},
            correlation_id="verify-no-duplicate",
        )
        duplicate_contents = [
            item["content"] for item in recalled[-1].payload["result"]["items"]
        ]
        assert all("duplicatedactioneffect" not in content for content in duplicate_contents)
    finally:
        adapter.close()


def test_adapter_start_and_close_are_idempotent(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    adapter = CognitiveWorkerAdapter("lifecycle-agent", broker, tmp_path)

    adapter.start()
    first_process = adapter._process
    first_unsubscribe = adapter._unsubscribe
    adapter.start()

    assert adapter._process is first_process
    assert adapter._unsubscribe is first_unsubscribe

    adapter.close()
    adapter.close()
    assert adapter._process is None
    assert adapter._unsubscribe is None
