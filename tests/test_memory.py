from __future__ import annotations

import copy

import pytest
from conftest import FAKE_KEY, FakePast, ScriptedLLM, error
from crewai import Agent, Crew, Task
from crewai.tools.memory_tools import create_memory_tools
from pydantic import SecretStr

from crewai_pastdotdev import PastDevClient, PastDevError, PastDevMemory
from crewai_pastdotdev._common import source_id_for


@pytest.fixture
def memory(client: PastDevClient) -> PastDevMemory:
    return PastDevMemory(identity="ada", client=client)


def test_remember_is_an_ingest_for_the_fixed_identity(
    memory: PastDevMemory, fake_past: FakePast
) -> None:
    record = memory.remember("Ada prefers short reports.", scope="/prefs", categories=["style"])
    assert record is not None
    body = fake_past.bodies("/api/v1/ingest")[0]
    assert body["content"] == "Ada prefers short reports."
    assert body["identity"] == "ada"
    assert body["id"] == source_id_for("ada", "Ada prefers short reports.")
    assert body["metadata"] == {"crewai_scope": "/prefs", "crewai_categories": ["style"]}
    assert record.id == body["id"]
    assert record.metadata["status"] == "queued"


def test_the_source_id_is_stable_per_identity_and_content() -> None:
    assert source_id_for("ada", "x") == source_id_for("ada", "x")
    assert source_id_for("ada", "x") != source_id_for("bob", "x")
    assert source_id_for("ada", "x").startswith("crewai-")


def test_audience_and_label_go_with_every_ingest(client: PastDevClient, fake_past: FakePast) -> None:
    memory = PastDevMemory(identity="ada", client=client, audience="support", label="Crew run")
    memory.remember("Ticket closed.")
    body = fake_past.bodies("/api/v1/ingest")[0]
    assert body["audience"] == "support"
    assert body["label"] == "Crew run"


def test_remember_many_ingests_in_the_background(memory: PastDevMemory, fake_past: FakePast) -> None:
    assert memory.remember_many(["one", "  ", "two"], root_scope="/crew/demo") == []
    memory.drain_writes()
    bodies = fake_past.bodies("/api/v1/ingest")
    assert [b["content"] for b in bodies] == ["one", "two"]
    assert all(b["metadata"] == {"crewai_scope": "/crew/demo"} for b in bodies)


def test_extract_memories_calls_no_llm(memory: PastDevMemory, fake_past: FakePast) -> None:
    assert memory.extract_memories("  Task: x\nResult: y  ") == ["Task: x\nResult: y"]
    assert memory.extract_memories("   ") == []
    assert fake_past.requests == []


def test_recall_maps_past_dev_results_to_memory_matches(
    memory: PastDevMemory, fake_past: FakePast
) -> None:
    matches = memory.recall("How does Ada like reports?", limit=500)
    body = fake_past.bodies("/api/v1/recall")[0]
    assert body == {"query": "How does Ada like reports?", "identity": "ada", "limit": 200}
    assert [m.record.content for m in matches] == [
        "Ada prefers short weekly reports.",
        "Ada wanted daily reports.",
    ]
    first, second = matches
    assert first.score == 1.0 and second.score == 0.5
    assert first.record.created_at.year == 2026 and first.record.created_at.tzinfo is not None
    assert first.record.metadata["excerpts"] == ["Please keep the weekly report short."]
    assert first.record.metadata["source_ids"] == ["crm-note-17"]
    assert second.record.metadata["superseded_at"] == "2026-10-01T09:30:00Z"
    assert "Ada prefers short weekly reports." in first.format()


def test_recall_sends_the_configured_budget(client: PastDevClient, fake_past: FakePast) -> None:
    PastDevMemory(identity="ada", client=client, recall_level="high").recall("q")
    PastDevMemory(identity="ada", client=client, recall_max_tokens=500).recall("q")
    bodies = fake_past.bodies("/api/v1/recall")
    assert bodies[0]["level"] == "high" and "maxTokens" not in bodies[0]
    assert bodies[1]["maxTokens"] == 500 and "level" not in bodies[1]


def test_level_and_max_tokens_cannot_both_be_set(client: PastDevClient) -> None:
    with pytest.raises(ValueError):
        PastDevMemory(identity="ada", client=client, recall_level="low", recall_max_tokens=10)


def test_an_empty_query_sends_nothing(memory: PastDevMemory, fake_past: FakePast) -> None:
    assert memory.recall("  ") == []
    assert fake_past.requests == []


def test_a_recall_error_is_raised(memory: PastDevMemory, fake_past: FakePast) -> None:
    fake_past.on("POST", "/api/v1/recall", lambda r: error(402, "out-of-credits"))
    with pytest.raises(PastDevError):
        memory.recall("q")


def test_forget_deletes_data_points_by_source_id(memory: PastDevMemory, fake_past: FakePast) -> None:
    fake_past.on("DELETE", "/api/v1/data-points/gone", lambda r: error(404, "not-found"))
    assert memory.forget(record_ids=["note-1", "gone"]) == 1
    assert fake_past.paths() == [
        "DELETE /api/v1/data-points/note-1",
        "DELETE /api/v1/data-points/gone",
    ]
    with pytest.raises(NotImplementedError):
        memory.forget(scope="/x")


def test_local_store_operations_say_what_to_use_instead(memory: PastDevMemory) -> None:
    for call in (memory.reset, memory.reset_all, memory.tree, memory.info, memory.list_scopes):
        with pytest.raises(NotImplementedError, match="past dev"):
            call()
    with pytest.raises(NotImplementedError):
        memory.update(None)


def test_read_only_memory_ingests_nothing(client: PastDevClient, fake_past: FakePast) -> None:
    memory = PastDevMemory(identity="ada", client=client, read_only=True)
    assert memory.remember("x") is None
    assert memory.remember_many(["x"]) == []
    assert fake_past.requests == []


def test_the_identity_is_required_and_checked(client: PastDevClient) -> None:
    with pytest.raises(ValueError):
        PastDevMemory(identity=" ", client=client)
    with pytest.raises(ValueError):
        PastDevMemory(identity="x" * 201, client=client)


def test_the_key_never_appears_in_dumps_or_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = PastDevMemory(identity="ada", api_key=SecretStr(FAKE_KEY))
    assert FAKE_KEY not in repr(memory)
    assert FAKE_KEY not in memory.model_dump_json()
    assert "api_key" not in memory.model_dump()


def test_the_key_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAST_API_KEY", FAKE_KEY)
    assert PastDevMemory(identity="ada")._client.api_host == "https://api.past.dev"


def test_a_deep_copy_shares_the_client(memory: PastDevMemory) -> None:
    clone = copy.deepcopy(memory)
    assert clone._client is memory._client
    assert clone.identity == "ada"


def test_a_crew_keeps_the_past_dev_memory(memory: PastDevMemory) -> None:
    agent = Agent(role="Writer", goal="Write", backstory="A writer.", llm=ScriptedLLM(model="fake", replies=["Final Answer: done"]))
    crew = Crew(agents=[agent], tasks=[Task(description="d", expected_output="e", agent=agent)],
                memory=memory)
    assert crew.memory is memory
    assert crew._memory is memory


def test_crewai_memory_tools_go_through_past_dev(memory: PastDevMemory, fake_past: FakePast) -> None:
    search, save = create_memory_tools(memory)
    assert "Ada prefers short weekly reports." in search.run(queries=["reports"])
    assert "Saved to memory" in save.run(contents=["Ada moved to Lyon."])
    assert [p.split(" ")[1] for p in fake_past.paths()] == ["/api/v1/recall", "/api/v1/ingest"]
