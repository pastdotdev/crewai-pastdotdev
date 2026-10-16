from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import FakePast, error

from crewai_pastdotdev import PastDevClient, PastDevIngestTool, PastDevRecallTool
from crewai_pastdotdev._common import source_id_for


def test_the_model_sees_only_query_and_content(client: PastDevClient) -> None:
    recall = PastDevRecallTool(identity="ada", client=client)
    ingest = PastDevIngestTool(identity="ada", client=client)
    assert list(recall.args_schema.model_json_schema()["properties"]) == ["query"]
    assert list(ingest.args_schema.model_json_schema()["properties"]) == ["content"]
    assert recall.name == "past dev Recall"
    assert ingest.name == "past dev Ingest"


def test_recall_uses_the_fixed_identity(client: PastDevClient, fake_past: FakePast) -> None:
    tool = PastDevRecallTool(identity="ada", client=client, limit=3, level="medium")
    text = tool.run(query="reports", identity="mallory")
    assert fake_past.bodies("/api/v1/recall") == [
        {"query": "reports", "identity": "ada", "limit": 3, "level": "medium"}
    ]
    assert "1. [2026-10-01] Ada prefers short weekly reports." in text
    assert '"Please keep the weekly report short." (CRM note, 2026-10-01)' in text
    assert "(superseded on 2026-10-01)" in text


def test_recall_with_no_results(client: PastDevClient, fake_past: FakePast) -> None:
    fake_past.on(
        "POST",
        "/api/v1/recall",
        lambda r: httpx.Response(200, json={"asOf": "x", "usedEvidenceTokens": 0, "results": []}),
    )
    assert PastDevRecallTool(identity="ada", client=client).run(query="q") == (
        "past dev found no relevant memories."
    )


def test_ingest_uses_the_fixed_identity(client: PastDevClient, fake_past: FakePast) -> None:
    tool = PastDevIngestTool(identity="ada", client=client, audience="team", metadata={"via": "crew"})
    text = tool.run(content="Ada moved to Lyon.", identity="mallory")
    body = fake_past.bodies("/api/v1/ingest")[0]
    assert body == {
        "content": "Ada moved to Lyon.",
        "identity": "ada",
        "id": source_id_for("ada", "Ada moved to Lyon."),
        "audience": "team",
        "metadata": {"via": "crew"},
    }
    assert "Ingested into past dev" in text and body["id"] in text


def test_an_unchanged_ingest_says_so(client: PastDevClient, fake_past: FakePast) -> None:
    fake_past.on(
        "POST",
        "/api/v1/ingest",
        lambda r: httpx.Response(
            200,
            json={"projectId": 1, "ingestionId": "i", "sourceId": "s", "status": "completed",
                  "unchanged": True},
        ),
    )
    assert "already has" in PastDevIngestTool(identity="ada", client=client).run(content="x")


@pytest.mark.parametrize(
    ("status", "code", "final"),
    [(402, "out-of-credits", True), (400, "content-empty", True), (500, "internal", False)],
)
def test_errors_are_returned_to_the_agent(
    client: PastDevClient, fake_past: FakePast, status: int, code: str, final: bool
) -> None:
    fake_past.on("POST", "/api/v1/ingest", lambda r: error(status, code))
    text = PastDevIngestTool(identity="ada", client=client).run(content="x")
    assert code in text and f"req-{status}" in text
    assert ("Do not retry" in text) is final


def test_empty_input_sends_nothing(client: PastDevClient, fake_past: FakePast) -> None:
    assert "needs a query" in PastDevRecallTool(identity="ada", client=client).run(query=" ")
    assert "needs content" in PastDevIngestTool(identity="ada", client=client).run(content="")
    assert fake_past.requests == []


def test_a_tool_needs_an_identity(client: PastDevClient) -> None:
    with pytest.raises(ValueError):
        PastDevRecallTool(identity="", client=client)


def test_tools_declare_their_environment_variables(client: PastDevClient) -> None:
    names = [v.name for v in PastDevRecallTool(identity="ada", client=client).env_vars]
    assert names == ["PAST_API_KEY", "PAST_API_HOST"]


def test_tools_run_async(client: PastDevClient, fake_past: FakePast) -> None:
    recall = PastDevRecallTool(identity="ada", client=client)
    ingest = PastDevIngestTool(identity="ada", client=client)
    assert "past dev recalled" in asyncio.run(recall.arun(query="reports"))
    assert "Ingested" in asyncio.run(ingest.arun(content="Ada moved."))
