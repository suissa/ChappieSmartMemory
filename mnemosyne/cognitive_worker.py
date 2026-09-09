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
    CorrectRequest,
    PROTOCOL_VERSION,
    RecallRequest,
    RememberRequest,
    parse_request,
)


class CognitiveMemoryWorker:
    def __init__(self, agent_id: str, data_dir: Path):
        self.agent_id = agent_id
        self.data_dir = data_dir.resolve()
        self.banks = BankManager(self.data_dir)
        if not self.banks.bank_exists(agent_id):
            self.banks.create_bank(agent_id)
        self.memory = Mnemosyne(bank=agent_id, db_path=self.banks.get_bank_db_path(agent_id))
        self._init_idempotency_ledger()

    @property
    def db_path(self) -> Path:
        return self.banks.get_bank_db_path(self.agent_id)

    def _init_idempotency_ledger(self) -> None:
        self.memory.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cognitive_effects (
                action_id TEXT NOT NULL,
                memory_operation_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY (action_id, memory_operation_id, operation)
            )
            """
        )
        self.memory.conn.commit()

    def _effect_key(self, params: RememberRequest | CorrectRequest) -> tuple[str, str] | None:
        if params.action_id is None and params.memory_operation_id is None:
            return None
        if params.action_id is None or params.memory_operation_id is None:
            raise ValueError("action_id and memory_operation_id must be provided together")
        return params.action_id, params.memory_operation_id

    def _lookup_effect(
        self,
        operation: str,
        params: RememberRequest | CorrectRequest,
    ) -> dict[str, Any] | None:
        key = self._effect_key(params)
        if key is None:
            return None
        row = self.memory.conn.execute(
            """
            SELECT result_json
            FROM cognitive_effects
            WHERE action_id = ? AND memory_operation_id = ? AND operation = ?
            """,
            (key[0], key[1], operation),
        ).fetchone()
        if row is not None:
            result = json.loads(row[0])
            result["deduplicated"] = True
            return result

        # Crash-window recovery: the memory write may have committed immediately
        # before the worker died and before the ledger row was recorded. Recover
        # from metadata persisted in the same Agent bank instead of writing again.
        rows = self.memory.conn.execute(
            "SELECT id, metadata_json FROM memories ORDER BY timestamp DESC"
        ).fetchall()
        for memory_id, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if (
                metadata.get("action_id") == key[0]
                and metadata.get("memory_operation_id") == key[1]
                and metadata.get("cognitive_operation") == operation
            ):
                result: dict[str, Any] = {
                    "memory_id": memory_id,
                    "agent_id": self.agent_id,
                }
                if operation == "correct":
                    correction_of = metadata.get("correction_of")
                    if correction_of:
                        self.memory.invalidate(correction_of, replacement_id=memory_id)
                        result["correction_of"] = correction_of
                self._record_effect(operation, params, result)
                result["deduplicated"] = True
                return result
        return None

    def _record_effect(
        self,
        operation: str,
        params: RememberRequest | CorrectRequest,
        result: dict[str, Any],
    ) -> None:
        key = self._effect_key(params)
        if key is None:
            return
        self.memory.conn.execute(
            """
            INSERT OR IGNORE INTO cognitive_effects (
                action_id, memory_operation_id, operation, result_json
            ) VALUES (?, ?, ?, ?)
            """,
            (key[0], key[1], operation, json.dumps(result, ensure_ascii=False, default=str)),
        )
        self.memory.conn.commit()

    def dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "ping":
            return {"agent_id": self.agent_id, "db_path": str(self.db_path)}
        if method == "stats":
            return self.banks.get_bank_stats(self.agent_id)
        if method == "remember":
            assert isinstance(params, RememberRequest)
            duplicate = self._lookup_effect(method, params)
            if duplicate is not None:
                return duplicate
            metadata = dict(params.metadata or {})
            metadata.setdefault("agent_session_id", params.session_id)
            if params.action_id is not None:
                metadata.update(
                    {
                        "action_id": params.action_id,
                        "memory_operation_id": params.memory_operation_id,
                        "cognitive_operation": method,
                    }
                )
            memory_id = self.memory.remember(
                params.content,
                source=params.source,
                importance=params.importance,
                scope="global",
                metadata=metadata,
            )
            if memory_id is None:
                raise ValueError("memory was rejected by the Mnemosyne write filter")
            result = {"memory_id": memory_id, "agent_id": self.agent_id, "deduplicated": False}
            self._record_effect(method, params, result)
            return result
        if method == "recall":
            assert isinstance(params, RecallRequest)
            results = self.memory.recall(params.query, top_k=params.top_k)
            return {"items": results, "agent_id": self.agent_id}
        if method == "correct":
            assert isinstance(params, CorrectRequest)
            duplicate = self._lookup_effect(method, params)
            if duplicate is not None:
                return duplicate
            if self.memory.get(params.correction_of) is None:
                raise ValueError(f"correction target does not exist: {params.correction_of}")
            metadata = dict(params.metadata or {})
            metadata.update(
                {
                    "agent_session_id": params.session_id,
                    "correction_of": params.correction_of,
                    "correction_protocol": PROTOCOL_VERSION,
                }
            )
            if params.action_id is not None:
                metadata.update(
                    {
                        "action_id": params.action_id,
                        "memory_operation_id": params.memory_operation_id,
                        "cognitive_operation": method,
                    }
                )
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
            result = {
                "memory_id": memory_id,
                "correction_of": params.correction_of,
                "agent_id": self.agent_id,
                "deduplicated": False,
            }
            self._record_effect(method, params, result)
            return result
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
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": {"type": type(error).__name__, "message": str(error)},
                }
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
