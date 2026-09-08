## Agent memory interface

The Agent-facing contract uses only two operations:

- emit: sends a memory request or event through the in-memory broker.
- listen: registers a handler for events belonging to the same Agent.

The Python Mnemosyne worker remains behind this boundary. A runtime adapter listens to
AgentMemory.Cognitive.Requested, calls the worker through NDJSON, and emits the
result back as an event such as AgentMemory.Cognitive.Stored. The Agent therefore
does not access SQLite or import Python.

Every Agent receives its own CognitiveAgentMemory, EventsAgentMemory, broker
namespace, and Mnemosyne database. The broker filters by agent_id, so an event
from one Agent cannot reach another Agent's listener.

Example:

    from mnemosyne.agent_memory import (
        CognitiveAgentMemory,
        EventsAgentMemory,
        InMemoryBroker,
    )

    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("sales-agent", broker)
    events = EventsAgentMemory("sales-agent", broker)

    events.listen("AgentMemory.Cognitive.Stored", handle_memory_stored)
    cognitive.emit({
        "operation": "remember",
        "content": "O cliente prefere Pix",
        "importance": 0.9,
    })

The current broker is synchronous and in-process. Its handler failure is propagated
to the Agent so the runtime can apply its self-healing policy. The same emit/listen
contract can later be implemented by a UbiQ transport.
