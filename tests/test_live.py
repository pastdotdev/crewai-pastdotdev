"""One round trip against the real past dev API.

Skipped unless PAST_API_KEY is set (PAST_API_HOST is optional). It spends a
few credits: one small Ingest and one Recall. The connection check and the
deletion are free.
"""

from __future__ import annotations

import os
import uuid

import pytest

from crewai_pastdotdev import PastDevClient, PastDevMemory

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("PAST_API_KEY"), reason="PAST_API_KEY is not set"),
]

SMOKE_IDENTITY = "crewai-pastdotdev-smoke"


def test_ingest_recall_and_delete_against_the_real_api() -> None:
    with PastDevClient() as client:
        client.check_connection()
        memory = PastDevMemory(identity=SMOKE_IDENTITY, client=client)

        marker = uuid.uuid4().hex[:8]
        record = memory.remember(f"Smoke test {marker}: the test color is teal.")
        assert record is not None and record.id.startswith("crewai-")

        # Processing is asynchronous, so the new data point may not be readable
        # yet; the call itself must succeed and return matches in CrewAI's shape.
        matches = memory.recall("What is the test color?", limit=3)
        assert all(m.record.content for m in matches)

        assert memory.forget(record_ids=[record.id]) == 1
