## Agent memory interface

The Agent-facing contract uses only two operations:

- emit: sends a memory request or event through the in-memory broker.
- listen: registers a handler for events belonging to the same Agent.

The Python Mnemosyne worker remains behind this boundary. `CognitiveWorkerAdapter`
listens to `AgentMemory.Cognitive.Requested`, calls the Agent-scoped worker through
NDJSON, and emits the result back through the same broker. The Agent therefore does
not access SQLite or import the cognitive worker implementation.

Every Agent receives its own `CognitiveAgentMemory`, `EventsAgentMemory`, broker
namespace, worker adapter, and Mnemosyne database. The broker filters by `agent_id`,
so an event from one Agent cannot reach another Agent's listener.

Example:

    from pathlib import Path

    from mnemosyne.agent_memory import (
        CognitiveAgentMemory,
        EventsAgentMemory,
        InMemoryBroker,
    )
    from mnemosyne.cognitive_adapter import CognitiveWorkerAdapter

    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("sales-agent", broker)
    events = EventsAgentMemory("sales-agent", broker)

    events.listen("AgentMemory.Cognitive.Stored", handle_memory_stored)
    events.listen("AgentMemory.Cognitive.Recalled", handle_memory_recalled)
    events.listen("AgentMemory.Cognitive.Failed", handle_memory_failure)

    with CognitiveWorkerAdapter(
        "sales-agent",
        broker,
        Path("agents/sales-agent/cognitive"),
    ):
        cognitive.emit({
            "operation": "remember",
            "content": "O cliente prefere Pix",
            "importance": 0.9,
        })

Supported request operations and result events are:

- `remember` -> `AgentMemory.Cognitive.Stored`
- `recall` -> `AgentMemory.Cognitive.Recalled`
- `correct` -> `AgentMemory.Cognitive.Corrected`
- `stats` -> `AgentMemory.Cognitive.Stats`
- `ping` -> `AgentMemory.Cognitive.Pong`
- any adapter or worker failure -> `AgentMemory.Cognitive.Failed`

The request correlation id is preserved on the emitted result event. Worker failures
emit `Failed` and are also propagated through the synchronous broker so the runtime
can apply its self-healing policy.

The current broker is synchronous and in-process. The same `emit`/`listen` contract
can later be implemented by UbiQ without changing the Agent-facing API or the NDJSON
worker protocol.
