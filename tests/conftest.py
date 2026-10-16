"""A fake past dev API on httpx.MockTransport, and a scripted LLM."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import httpx
import pytest

# CrewAI sends anonymous telemetry by default; tests send nothing.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from crewai.llms.base_llm import BaseLLM

from crewai_pastdotdev import PastDevClient

FAKE_KEY = "past_sk_test_not_a_real_key"

RECALL_RESPONSE: dict[str, Any] = {
    "asOf": "2026-10-16T12:00:00Z",
    "usedEvidenceTokens": 42,
    "results": [
        {
            "id": "7d4c2f9e-1111-4c1a-9a55-000000000001",
            "rank": 1,
            "occurredAt": "2026-10-01T09:30:00.1234567Z",
            "content": "Ada prefers short weekly reports.",
            "artifact": {
                "id": "7d4c2f9e-1111-4c1a-9a55-000000000001",
                "kind": "observation",
                "occurredAt": "2026-10-01T09:30:00Z",
            },
            "sources": [
                {
                    "sourceId": "crm-note-17",
                    "occurredAt": "2026-10-01T09:30:00Z",
                    "label": "CRM note",
                    "excerpts": ["Please keep the weekly report short."],
                }
            ],
        },
        {
            "id": "7d4c2f9e-1111-4c1a-9a55-000000000002",
            "rank": 2,
            "occurredAt": "2026-09-12T08:00:00Z",
            "content": "Ada wanted daily reports.",
            "artifact": {
                "id": "7d4c2f9e-1111-4c1a-9a55-000000000002",
                "kind": "observation",
                "occurredAt": "2026-09-12T08:00:00Z",
                "supersededAt": "2026-10-01T09:30:00Z",
            },
            "sources": [],
        },
    ],
}


class FakePast:
    """Records every request and answers like the past dev API."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handlers: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

    def on(self, method: str, path: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handlers[(method, path)] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.handlers.get((request.method, request.url.path))
        if handler is not None:
            return handler(request)
        if request.method == "POST" and request.url.path == "/api/v1/ingest":
            body = json.loads(request.content)
            return httpx.Response(
                202,
                json={
                    "projectId": 1,
                    "ingestionId": "0f8e5f5a-0000-4000-8000-000000000001",
                    "sourceId": body.get("id", "sha"),
                    "status": "queued",
                    "unchanged": None,
                },
                headers={"X-Request-Id": "req-ingest"},
            )
        if request.method == "POST" and request.url.path == "/api/v1/recall":
            return httpx.Response(200, json=RECALL_RESPONSE)
        if request.method == "GET" and request.url.path == "/api/v1/audiences":
            return httpx.Response(200, json={"audiences": [{"slug": "project", "name": "Project"}]})
        if request.method == "DELETE" and request.url.path.startswith("/api/v1/data-points/"):
            source_id = request.url.path.rsplit("/", 1)[1]
            return httpx.Response(
                202, json={"operationId": "0f8e5f5a-0000-4000-8000-000000000009", "ids": [source_id]}
            )
        return httpx.Response(404, json={"code": "not-found", "status": 404})

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]


@pytest.fixture
def fake_past() -> FakePast:
    return FakePast()


@pytest.fixture
def client(fake_past: FakePast) -> PastDevClient:
    return PastDevClient(api_key=FAKE_KEY, transport=httpx.MockTransport(fake_past))


def error(status: int, code: str | None = None, **extra: Any) -> httpx.Response:
    headers = {"X-Request-Id": f"req-{status}"}
    if code is None:
        return httpx.Response(status, headers=headers)
    return httpx.Response(status, json={"code": code, "status": status, **extra}, headers=headers)


class ScriptedLLM(BaseLLM):
    """An LLM that answers with the next scripted reply and records prompts."""

    replies: list[str] = []
    prompts: list[str] = []

    def call(self, messages: Any, *args: Any, **kwargs: Any) -> str:
        if isinstance(messages, str):
            text = messages
        else:
            text = "\n".join(str(m.get("content", "")) for m in messages)
        self.prompts.append(text)
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 8192
