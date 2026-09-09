## Agent memory interface

The Agent-facing contract uses only two operations:

- `emit`: sends a cognitive request or an Agent memory event.
- `listen`: registers a handler for events belonging to the same Agent.

`CognitiveAgentMemory` and `EventsAgentMemory` share an `InMemoryBroker`.
The broker keys listeners by `agent_id` and event type, so one Agent cannot
observe another Agent's memory events.

## Executable Python adapter

`CognitiveMemoryAdapter` is the reference implementation of the complete flow:

```text
CognitiveAgentMemory.emit
    -> InMemoryBroker
    -> CognitiveMemoryAdapter
    -> Mnemosyne
    -> EventsAgentMemory.emit
    -> Agent listener
```

The adapter listens to `AgentMemory.Cognitive.Requested`. Successful operations
emit `AgentMemory.Cognitive.Ok`; rejected operations emit
`AgentMemory.Cognitive.Error`. Both preserve the original `correlation_id`.

```python
from pathlib import Path

from mnemosyne.agent_memory import (
    CognitiveAgentMemory,
    EventsAgentMemory,
    InMemoryBroker,
)
from mnemosyne.cognitive_adapter import CognitiveMemoryAdapter
from mnemosyne.cognitive_worker import CognitiveMemoryWorker

agent_id = "sales-agent"
broker = InMemoryBroker()
cognitive = CognitiveAgentMemory(agent_id, broker)
events = EventsAgentMemory(agent_id, broker)
worker = CognitiveMemoryWorker(agent_id, Path("agents/sales-agent/cognitive"))
adapter = CognitiveMemoryAdapter(worker, cognitive, events)

events.listen(CognitiveAgentMemory.OK, handle_memory_result)
events.listen(CognitiveAgentMemory.ERROR, handle_memory_error)

cognitive.emit({
    "operation": "remember",
    "content": "O cliente prefere Pix",
    "importance": 0.9,
})
```

Supported operations are `remember`, `recall`, `correct`, `stats`, and
`ping`. Calling `adapter.close()` removes its listener.

## Zig runtime

The Zig runtime keeps this same event contract. Its adapter replaces the direct
Python call with the existing NDJSON child-process client:

```text
CognitiveAgentMemory.emit
    -> Zig in-memory broker
    -> Zig Mnemosyne adapter
    -> NDJSON worker process
    -> EventsAgentMemory.emit
```

The Agent never imports Python and never reads the Mnemosyne SQLite schema.
It only emits requests and listens for correlated Ok/Error events. The same
contract can later be transported by UbiQ without changing Agent behavior.

Every Agent owns its own memory namespace, worker, and SQLite bank.
