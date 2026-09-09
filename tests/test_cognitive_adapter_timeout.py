from pathlib import Path
import sys

import pytest

from mnemosyne.agent_memory import CognitiveAgentMemory, EventsAgentMemory, InMemoryBroker
from mnemosyne.cognitive_adapter import CognitiveWorkerAdapter, FAILED_EVENT


def test_hung_worker_times_out_restarts_once_and_emits_failed(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("hung-agent", broker)
    events = EventsAgentMemory("hung-agent", broker)
    failed = []
    events.listen(FAILED_EVENT, failed.append)

    command = [
        sys.executable,
        "-u",
        "-c",
        "import sys,time; sys.stdin.readline(); time.sleep(60)",
    ]
    adapter = CognitiveWorkerAdapter(
        "hung-agent",
        broker,
        tmp_path,
        command=command,
        request_timeout=0.1,
    ).start()
    try:
        first_process = adapter._process
        assert first_process is not None

        with pytest.raises(TimeoutError, match="timed out"):
            cognitive.emit({"operation": "ping"}, correlation_id="hung-ping")

        assert len(failed) == 1
        assert failed[0].correlation_id == "hung-ping"
        assert failed[0].payload["error"]["type"] == "TimeoutError"
        assert "timed out" in failed[0].payload["error"]["message"]
        assert first_process.poll() is not None
    finally:
        adapter.close()


def test_request_timeout_must_be_positive(tmp_path: Path) -> None:
    broker = InMemoryBroker()
    with pytest.raises(ValueError, match="greater than zero"):
        CognitiveWorkerAdapter("bad-timeout", broker, tmp_path, request_timeout=0)
