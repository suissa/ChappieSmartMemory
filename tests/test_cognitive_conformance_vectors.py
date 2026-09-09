from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


VECTORS = Path(__file__).parents[1] / "docs" / "protocol" / "cognitive-memory-v1.conformance.json"


def command(data_dir: Path, agent_id: str) -> list[str]:
    return [sys.executable, "-m", "mnemosyne.cognitive_worker", "--agent-id", agent_id, "--data-dir", str(data_dir)]


@contextmanager
def worker(data_dir: Path, agent_id: str):
    process = subprocess.Popen(command(data_dir, agent_id), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        yield process
    finally:
        if process.poll() is None:
            send(process, {"id": "close", "method": "close"})
            process.wait(timeout=10)


def send(process, payload: dict) -> dict:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, "worker terminated without a response"
    return json.loads(line)


def load_vectors() -> dict:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def assert_expectation(request: dict, response: dict, expect: dict) -> None:
    assert response["ok"] is expect["ok"], response
    if expect.get("same_id"):
        assert response.get("id") == request.get("id")
    if "error_type" in expect:
        assert response["error"]["type"] == expect["error_type"]


def contents(response: dict) -> list[str]:
    assert response["ok"], response
    return [str(item.get("content", "")) for item in response["result"]["items"]]


def test_request_vectors_are_transport_neutral_and_executable(tmp_path: Path) -> None:
    vectors = load_vectors()
    assert vectors["protocol"] == "1.0"
    with worker(tmp_path, "vector-agent") as process:
        for vector in vectors["request_vectors"]:
            response = send(process, vector["request"])
            assert_expectation(vector["request"], response, vector["expect"])


def test_stateful_remember_recall_correct_vector(tmp_path: Path) -> None:
    scenario = load_vectors()["stateful_scenarios"][0]
    with worker(tmp_path, scenario["agent_id"]) as process:
        stored = send(process, {"protocol": "1.0", "id": "remember", "method": "remember", "params": {"content": scenario["original"], "importance": 0.7}})
        assert stored["ok"], stored
        original_id = stored["result"]["memory_id"]

        before = contents(send(process, {"protocol": "1.0", "id": "recall-old", "method": "recall", "params": {"query": "conformanceoldbelief"}}))
        assert scenario["original"] in before

        corrected = send(process, {"protocol": "1.0", "id": "correct", "method": "correct", "params": {"content": scenario["corrected"], "correction_of": original_id, "importance": 1.0}})
        assert corrected["ok"], corrected
        assert corrected["result"]["correction_of"] == original_id

        old_after = contents(send(process, {"protocol": "1.0", "id": "recall-old-after", "method": "recall", "params": {"query": "conformanceoldbelief"}}))
        new_after = contents(send(process, {"protocol": "1.0", "id": "recall-new", "method": "recall", "params": {"query": "conformancenewbelief"}}))
        assert scenario["original"] not in old_after
        assert scenario["corrected"] in new_after


def test_stateful_agent_isolation_vector(tmp_path: Path) -> None:
    scenario = load_vectors()["stateful_scenarios"][1]
    with worker(tmp_path, scenario["agent_a"]) as first:
        stored = send(first, {"protocol": "1.0", "id": "private-write", "method": "remember", "params": {"content": scenario["content"], "importance": 1.0}})
        assert stored["ok"], stored

    with worker(tmp_path, scenario["agent_b"]) as second:
        foreign = contents(send(second, {"protocol": "1.0", "id": "private-read", "method": "recall", "params": {"query": "conformanceprivateknowledge"}}))
        assert scenario["content"] not in foreign
