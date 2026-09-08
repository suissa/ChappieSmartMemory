import json
import subprocess
import sys


def command(data_dir, agent_id):
    return [sys.executable, "-m", "mnemosyne.cognitive_worker", "--agent-id", agent_id,
            "--data-dir", str(data_dir)]


def send(process, payload):
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def test_agent_banks_are_isolated(tmp_path):
    first = subprocess.Popen(command(tmp_path, "agent-a"), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    second = subprocess.Popen(command(tmp_path, "agent-b"), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    try:
        assert send(first, {"id": 1, "method": "remember", "params":
                            {"content": "Agent A prefere Pix"}})["ok"]
        assert send(first, {"id": 2, "method": "recall", "params":
                            {"query": "qual pagamento"}})["ok"]
        result = send(second, {"id": 3, "method": "recall", "params":
                               {"query": "qual pagamento"}})
        assert result["ok"] and result["result"]["items"] == []
    finally:
        for process in (first, second):
            send(process, {"id": 9, "method": "close"})
            process.wait(timeout=10)
    assert (tmp_path / "banks" / "agent-a" / "mnemosyne.db").is_file()
    assert (tmp_path / "banks" / "agent-b" / "mnemosyne.db").is_file()


def test_worker_rejects_invalid_requests(tmp_path):
    process = subprocess.Popen(command(tmp_path, "agent-a"), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    try:
        response = send(process, {"id": 1, "method": "remember", "params": {"content": ""}})
        assert response["ok"] is False
        assert response["error"]["type"] == "ValueError"
        assert send(process, {"id": 2, "method": "ping"})["result"]["agent_id"] == "agent-a"
    finally:
        send(process, {"id": 3, "method": "close"})
        process.wait(timeout=10)

