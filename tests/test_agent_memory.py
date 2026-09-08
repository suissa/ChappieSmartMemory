from mnemosyne.agent_memory import (
    CognitiveAgentMemory,
    EventsAgentMemory,
    InMemoryBroker,
)


def test_cognitive_emit_reaches_listener_for_same_agent():
    broker = InMemoryBroker()
    cognitive = CognitiveAgentMemory("agent-a", broker)
    received = []

    cognitive.listen(CognitiveAgentMemory.REQUESTED, received.append)
    correlation_id = cognitive.emit({"content": "prefere Pix"})

    assert len(received) == 1
    assert received[0].agent_id == "agent-a"
    assert received[0].payload["content"] == "prefere Pix"
    assert received[0].correlation_id == correlation_id


def test_agents_are_isolated():
    broker = InMemoryBroker()
    first = EventsAgentMemory("agent-a", broker)
    second = EventsAgentMemory("agent-b", broker)
    received = []

    first.listen("Memory.Stored", received.append)
    second.emit("Memory.Stored", {"memory_id": "b-1"})

    assert received == []


def test_listen_returns_unsubscribe():
    broker = InMemoryBroker()
    events = EventsAgentMemory("agent-a", broker)
    received = []
    unsubscribe = events.listen("Memory.Stored", received.append)

    events.emit("Memory.Stored", {"memory_id": "one"})
    unsubscribe()
    events.emit("Memory.Stored", {"memory_id": "two"})

    assert [event.payload["memory_id"] for event in received] == ["one"]


def test_wildcard_listener_receives_agent_events():
    broker = InMemoryBroker()
    events = EventsAgentMemory("agent-a", broker)
    received = []

    events.listen("*", received.append)
    events.emit("Memory.Stored", {"memory_id": "one"})

    assert len(received) == 1
