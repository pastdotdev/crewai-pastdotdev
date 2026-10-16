from __future__ import annotations

import json

import httpx
import pytest
from conftest import FAKE_KEY, FakePast, error

from crewai_pastdotdev import DEFAULT_API_HOST, PastDevClient, PastDevError


def test_ingest_sends_the_api_field_keys(client: PastDevClient, fake_past: FakePast) -> None:
    receipt = client.ingest(
        "Ada joined the beta.",
        identity="ada",
        id="note-1",
        timestamp="2026-10-01T09:00:00Z",
        audience="team",
        label="Onboarding",
        metadata={"origin": "test"},
        idempotency_key="k-1",
    )
    request = fake_past.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{DEFAULT_API_HOST}/api/v1/ingest"
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert request.headers["User-Agent"].startswith("crewai-pastdotdev/")
    assert json.loads(request.content) == {
        "content": "Ada joined the beta.",
        "identity": "ada",
        "id": "note-1",
        "timestamp": "2026-10-01T09:00:00Z",
        "audience": "team",
        "label": "Onboarding",
        "metadata": {"origin": "test"},
        "idempotencyKey": "k-1",
    }
    assert receipt["sourceId"] == "note-1"


def test_ingest_leaves_out_unset_fields(client: PastDevClient, fake_past: FakePast) -> None:
    client.ingest("Only content.")
    assert fake_past.bodies("/api/v1/ingest") == [{"content": "Only content."}]


def test_recall_sends_the_api_field_keys(client: PastDevClient, fake_past: FakePast) -> None:
    response = client.recall(
        "report format",
        identity="ada",
        limit=5,
        level="medium",
        occurred_from="2026-01-01T00:00:00Z",
        occurred_to="2026-12-31T00:00:00Z",
        query_timestamp="2026-10-16T00:00:00Z",
        sort="chronological",
    )
    assert fake_past.bodies("/api/v1/recall") == [
        {
            "query": "report format",
            "identity": "ada",
            "limit": 5,
            "level": "medium",
            "queryTimestamp": "2026-10-16T00:00:00Z",
            "occurredFrom": "2026-01-01T00:00:00Z",
            "occurredTo": "2026-12-31T00:00:00Z",
            "sort": "chronological",
        }
    ]
    assert response["results"][0]["rank"] == 1


def test_recall_refuses_level_and_max_tokens_together(client: PastDevClient) -> None:
    with pytest.raises(ValueError):
        client.recall("q", identity="ada", level="low", max_tokens=100)


def test_delete_data_point_escapes_the_source_id(client: PastDevClient, fake_past: FakePast) -> None:
    receipt = client.delete_data_point("notes/17 a")
    assert fake_past.requests[0].method == "DELETE"
    assert fake_past.requests[0].url.raw_path == b"/api/v1/data-points/notes%2F17%20a"
    assert receipt["operationId"]


def test_check_connection_uses_audiences(client: PastDevClient, fake_past: FakePast) -> None:
    client.check_connection()
    assert fake_past.paths() == ["GET /api/v1/audiences"]


def test_list_identities_follows_the_cursor(client: PastDevClient, fake_past: FakePast) -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("after") == "c1":
            return httpx.Response(
                200, json={"identities": [{"identity": "b"}], "hasMore": False, "endCursor": None}
            )
        return httpx.Response(
            200, json={"identities": [{"identity": "a"}], "hasMore": True, "endCursor": "c1"}
        )

    fake_past.on("GET", "/api/v1/identities", pages)
    assert [i["identity"] for i in client.list_identities(page_size=1)] == ["a", "b"]
    assert len(fake_past.requests) == 2


def test_an_error_carries_code_message_and_request_id(
    client: PastDevClient, fake_past: FakePast
) -> None:
    fake_past.on(
        "POST",
        "/api/v1/ingest",
        lambda r: error(402, "out-of-credits", debugMessage="No credits left.", data={"creditsLeft": 0}),
    )
    with pytest.raises(PastDevError) as caught:
        client.ingest("x", identity="ada")
    assert caught.value.code == "out-of-credits"
    assert caught.value.status == 402
    assert caught.value.request_id == "req-402"
    assert caught.value.data == {"creditsLeft": 0}
    assert "out-of-credits" in str(caught.value) and "No credits left." in str(caught.value)
    assert len(fake_past.requests) == 1  # a 402 is never retried


def test_a_400_is_not_retried(client: PastDevClient, fake_past: FakePast) -> None:
    fake_past.on("POST", "/api/v1/recall", lambda r: error(400, "recall-range-invalid"))
    with pytest.raises(PastDevError):
        client.recall("q", identity="ada")
    assert len(fake_past.requests) == 1


def test_a_rate_limit_waits_and_retries(
    client: PastDevClient, fake_past: FakePast, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr("crewai_pastdotdev.client.time.sleep", waits.append)
    replies = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"audiences": []}),
    ]
    fake_past.on("GET", "/api/v1/audiences", lambda r: replies.pop(0))
    assert client.list_audiences() == []
    assert waits == [3.0]
    assert len(fake_past.requests) == 2


def test_a_rate_limit_gives_up_after_max_retries(
    client: PastDevClient, fake_past: FakePast, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("crewai_pastdotdev.client.time.sleep", lambda s: None)
    fake_past.on("GET", "/api/v1/audiences", lambda r: error(429))
    with pytest.raises(PastDevError) as caught:
        client.list_audiences()
    assert caught.value.code == "rate-limited"
    assert len(fake_past.requests) == 3


def test_a_spend_cap_is_not_retried(client: PastDevClient, fake_past: FakePast) -> None:
    fake_past.on("POST", "/api/v1/ingest", lambda r: error(429, "spend-cap-reached"))
    with pytest.raises(PastDevError) as caught:
        client.ingest("x", identity="ada")
    assert caught.value.code == "spend-cap-reached"
    assert len(fake_past.requests) == 1


def test_a_network_failure_is_a_past_dev_error() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = PastDevClient(api_key=FAKE_KEY, transport=httpx.MockTransport(fail))
    with pytest.raises(PastDevError) as caught:
        client.list_audiences()
    assert caught.value.code == "network-error"
    assert caught.value.status == 0


def test_key_and_host_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"audiences": []})

    monkeypatch.setenv("PAST_API_KEY", FAKE_KEY)
    monkeypatch.setenv("PAST_API_HOST", "https://memory.example.com/")
    client = PastDevClient(transport=httpx.MockTransport(handler))
    client.list_audiences()
    assert str(seen[0].url) == "https://memory.example.com/api/v1/audiences"
    assert seen[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in repr(client)


def test_a_missing_key_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAST_API_KEY", raising=False)
    with pytest.raises(ValueError, match="PAST_API_KEY"):
        PastDevClient()
