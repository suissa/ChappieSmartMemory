"""Executable evidence that an Agent learned and retained cognitive facts.

These tests intentionally use lexical probes so CI remains deterministic when
MNEMOSYNE_NO_EMBEDDINGS=1. Each test prints a compact evidence record that is
embedded in the generated HTML report.
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def command(data_dir: Path, agent_id: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "mnemosyne.cognitive_worker",
        "--agent-id",
        agent_id,
        "--data-dir",
        str(data_dir),
    ]


@contextmanager
def worker(data_dir: Path, agent_id: str) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        command(data_dir, agent_id),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            send(process, {"id": "close", "method": "close"})
            process.wait(timeout=10)


def send(process: subprocess.Popen[str], payload: dict) -> dict:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, "Mnemosyne worker terminated without a response"
    response = json.loads(line)
    assert response.get("id") == payload.get("id")
    return response


def contents(response: dict) -> list[str]:
    assert response["ok"], response
    return [str(item.get("content", "")) for item in response["result"]["items"]]


def evidence(capability: str, *, learned: str, recalled: list[str]) -> None:
    print(
        "LEARNING_EVIDENCE "
        + json.dumps(
            {
                "capability": capability,
                "learned": learned,
                "recalled": recalled,
                "verified": learned in recalled,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def test_agent_learns_and_recalls_a_fact(tmp_path: Path) -> None:
    learned = "O cliente prefere Pix; marcador orionpixpreference."
    with worker(tmp_path, "sales-agent") as process:
        stored = send(
            process,
            {
                "protocol": "1.0",
                "id": "remember-1",
                "method": "remember",
                "params": {
                    "content": learned,
                    "source": "ci-learning-evidence",
                    "importance": 0.9,
                },
            },
        )
        assert stored["ok"], stored

        recalled = contents(
            send(
                process,
                {
                    "protocol": "1.0",
                    "id": "recall-1",
                    "method": "recall",
                    "params": {"query": "orionpixpreference", "top_k": 5},
                },
            )
        )

    evidence("remember-and-recall", learned=learned, recalled=recalled)
    assert learned in recalled


def test_learning_survives_worker_restart(tmp_path: Path) -> None:
    learned = "O fornecedor prioritário é Aurora; marcador auroraretentionprobe."
    with worker(tmp_path, "procurement-agent") as process:
        stored = send(
            process,
            {
                "id": "remember-before-restart",
                "method": "remember",
                "params": {
                    "content": learned,
                    "source": "ci-restart-evidence",
                    "importance": 1.0,
                },
            },
        )
        assert stored["ok"], stored

    with worker(tmp_path, "procurement-agent") as restarted:
        recalled = contents(
            send(
                restarted,
                {
                    "id": "recall-after-restart",
                    "method": "recall",
                    "params": {"query": "auroraretentionprobe", "top_k": 5},
                },
            )
        )

    evidence("restart-retention", learned=learned, recalled=recalled)
    assert learned in recalled


def test_agent_learns_an_explicit_correction(tmp_path: Path) -> None:
    previous = "O cliente prefere boleto; marcador oldpaymentbelief."
    corrected = "O cliente prefere cartão; marcador correctedpaymentbelief."

    with worker(tmp_path, "support-agent") as process:
        stored = send(
            process,
            {
                "id": "remember-original",
                "method": "remember",
                "params": {"content": previous, "importance": 0.6},
            },
        )
        assert stored["ok"], stored
        original_id = stored["result"]["memory_id"]

        correction = send(
            process,
            {
                "id": "correct-belief",
                "method": "correct",
                "params": {
                    "content": corrected,
                    "correction_of": original_id,
                    "importance": 1.0,
                },
            },
        )
        assert correction["ok"], correction
        assert correction["result"]["correction_of"] == original_id

        corrected_recall = contents(
            send(
                process,
                {
                    "id": "recall-correction",
                    "method": "recall",
                    "params": {"query": "correctedpaymentbelief", "top_k": 5},
                },
            )
        )
        old_recall = contents(
            send(
                process,
                {
                    "id": "recall-old-belief",
                    "method": "recall",
                    "params": {"query": "oldpaymentbelief", "top_k": 5},
                },
            )
        )

    evidence("explicit-correction", learned=corrected, recalled=corrected_recall)
    assert corrected in corrected_recall
    assert previous not in old_recall


def test_correction_requires_an_existing_target(tmp_path: Path) -> None:
    with worker(tmp_path, "support-agent") as process:
        response = send(
            process,
            {
                "id": "correct-missing",
                "method": "correct",
                "params": {
                    "content": "Nova verdade",
                    "correction_of": "missing-memory-id",
                },
            },
        )

    assert response["ok"] is False
    assert response["error"]["type"] == "ValueError"
    assert "does not exist" in response["error"]["message"]


def test_learning_is_private_to_its_agent(tmp_path: Path) -> None:
    learned = "Segredo cognitivo do Agent A; marcador privateagentknowledge."

    with worker(tmp_path, "agent-a") as first:
        stored = send(
            first,
            {
                "id": "remember-private",
                "method": "remember",
                "params": {"content": learned, "importance": 1.0},
            },
        )
        assert stored["ok"], stored

    with worker(tmp_path, "agent-b") as second:
        foreign_recall = contents(
            send(
                second,
                {
                    "id": "recall-foreign",
                    "method": "recall",
                    "params": {"query": "privateagentknowledge", "top_k": 5},
                },
            )
        )

    print(
        "LEARNING_EVIDENCE "
        + json.dumps(
            {
                "capability": "agent-isolation",
                "learned_by": "agent-a",
                "queried_by": "agent-b",
                "foreign_recall": foreign_recall,
                "verified": learned not in foreign_recall,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    assert learned not in foreign_recall
