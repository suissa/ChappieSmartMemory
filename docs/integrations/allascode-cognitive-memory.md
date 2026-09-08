# AllasCode Cognitive Memory Interface

This integration gives the AllasCode runtime a language-neutral boundary around
Mnemosyne. The runtime may be implemented in Zig, Rust, Go or another language;
it does not import Python or access the SQLite file directly.

Each Agent owns one Mnemosyne bank:

```text
agents/{agent_id}/
├── cognitive/
│   └── banks/{agent_id}/mnemosyne.db
└── execution/
    └── eventstore.db
```

Start one worker for one Agent:

```bash
python -m mnemosyne.cognitive_worker \
  --agent-id sales-agent \
  --data-dir agents/sales-agent/cognitive
```

The parent runtime communicates through newline-delimited JSON (NDJSON). Every
request receives one response with the same `id`.

Supported methods are `ping`, `stats`, `remember`, `recall`, `correct` and
`close`. `correct` appends a new memory with `correction_of`; the original is
preserved as evidence and is never physically deleted by this protocol.

The worker must not open, query or correlate the Agent's EventStore. Mnemosyne
answers cognitive questions only. The EventStore remains responsible for the
current Intent, completed or failed Actions, consumed events and execution
restart. A worker failure becomes an input to the runtime's own self-healing
pipeline; it is not an AllasCode Action Error event by itself.

NDJSON keeps the boundary local, zero-cloud, streamable, easy to implement in
Zig, and replaceable later by a Unix socket without changing the methods. Only
one worker should own a bank connection; serialize requests per Agent.

Run the integration tests with:

```bash
pytest -q tests/test_cognitive_protocol.py
```

