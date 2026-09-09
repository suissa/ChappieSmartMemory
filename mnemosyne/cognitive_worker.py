"""Agent-scoped NDJSON worker for the language-neutral cognitive interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mnemosyne import Mnemosyne
from mnemosyne.core.banks import BankManager
from mnemosyne.cognitive_protocol import (
    CorrectRequest, PROTOCOL_VERSION, RecallRequest, RememberRequest, parse_request,
)


class CognitiveMemoryWorker:
    def __init__(self, agent_id: str, data_dir: Path):
        self.agent_id = agent_id
        self.data_dir = data_dir.resolve()
        self.banks = BankManager(self.data_dir)
        if not self.banks.bank_exists(agent_id):
            self.banks.create_bank(agent_id)
        self.memory = Mnemosyne(bank=agent_id, db_path=self.banks.get_bank_db_path(agent_id))

    @property
    def db_path(self) -> Path:
        return self.banks.get_bank_db_path(self.agent_id)

    def dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "ping":
            return {"agent_id": self.agent_id, "db_path": str(self.db_path)}
        if method == "stats":
            return self.banks.get_bank_stats(self.agent_id)
        if method == "remember":
            assert isinstance(params, RememberRequest)
            metadata = dict(params.metadata or {})
            metadata.setdefault("agent_session_id", params.session_id)
            # One bank belongs to one Agent. Map the public Agent scope to
            # Mnemosyne's bank-local global scope so it remains visible across
            # any future internal sessions without crossing Agent boundaries.
            memory_id = self.memory.remember(
                params.content,
                source=params.source,
                importance=params.importance,
                scope="global",
                metadata=metadata,
            )
            if memory_id is None:
                raise ValueError("memory was rejected by the Mnemosyne write filter")
            return {"memory_id": memory_id, "agent_id": self.agent_id}
        if method == "recall":
            assert isinstance(params, RecallRequest)
            results = self.memory.recall(params.query, top_k=params.top_k)
            return {"items": results, "agent_id": self.agent_id}
        if method == "correct":
            assert isinstance(params, CorrectRequest)
            if self.memory.get(params.correction_of) is None:
                raise ValueError(f"correction target does not exist: {params.correction_of}")
            metadata = dict(params.metadata or {})
            metadata.update({
                "agent_session_id": params.session_id,
                "correction_of": params.correction_of,
                "correction_protocol": PROTOCOL_VERSION,
            })
            memory_id = self.memory.remember(
                params.content,
                source=params.source,
                importance=params.importance,
                scope="global",
                metadata=metadata,
            )
            if memory_id is None:
                raise ValueError("corrected memory was rejected by the Mnemosyne write filter")
            if not self.memory.invalidate(params.correction_of, replacement_id=memory_id):
                raise RuntimeError(f"failed to supersede correction target: {params.correction_of}")
            return {"memory_id": memory_id, "correction_of": params.correction_of,
                    "agent_id": self.agent_id}
        if method == "close":
            return {"closed": True}
        raise ValueError(f"unsupported method: {method}")

    def serve(self, input_stream, output_stream) -> int:
        for line in input_stream:
            if not line.strip():
                continue
            request_id = None
            try:
                payload = json.loads(line)
                request_id = payload.get("id")
                method, params = parse_request(payload)
                response = {"id": request_id, "ok": True, "result": self.dispatch(method, params)}
                output_stream.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
                output_stream.flush()
                if method == "close":
                    return 0
            except Exception as error:
                response = {"id": request_id, "ok": False,
                            "error": {"type": type(error).__name__, "message": str(error)}}
                output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
                output_stream.flush()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    return CognitiveMemoryWorker(args.agent_id, args.data_dir).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
