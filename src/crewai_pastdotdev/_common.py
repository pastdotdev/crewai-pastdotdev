"""Helpers shared by the memory and the tools."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import SecretStr

from crewai_pastdotdev.client import PastDevClient

MAX_IDENTITY_LENGTH = 200
RECALL_LIMIT_MAX = 200

_FRACTION = re.compile(r"(\.\d{6})\d+")


def check_identity(identity: str) -> str:
    """Return the identity, or raise ``ValueError`` if past dev would refuse it."""
    if not identity or not identity.strip():
        raise ValueError("past dev needs an identity: the id of the person the memory is about.")
    if len(identity) > MAX_IDENTITY_LENGTH:
        raise ValueError(f"A past dev identity is at most {MAX_IDENTITY_LENGTH} characters.")
    return identity


def make_client(
    client: PastDevClient | None, api_key: SecretStr | None, api_host: str | None
) -> PastDevClient:
    if client is not None:
        return client
    return PastDevClient(
        api_key=api_key.get_secret_value() if api_key is not None else None,
        api_host=api_host,
    )


def source_id_for(identity: str, content: str) -> str:
    """A stable source id for one piece of content from one identity.

    The same content from the same identity gets the same id, so a repeated
    ingest is recognized as unchanged and costs nothing. Two identities that
    send the same words keep two separate data points.
    """
    digest = hashlib.sha256(f"{identity}\x00{content}".encode()).hexdigest()
    return f"crewai-{digest}"


def clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), RECALL_LIMIT_MAX))


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an API date-time (ISO 8601, ``Z`` suffix, up to 7 decimals)."""
    if not value:
        return None
    text = _FRACTION.sub(r"\1", value.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_recall(response: dict[str, Any]) -> str:
    """Render a recall response as text for an agent to read."""
    results = response.get("results") or []
    if not results:
        return "past dev found no relevant memories."
    lines = [f"past dev recalled {len(results)} memories, most relevant first:"]
    for result in results:
        date = (result.get("occurredAt") or "")[:10]
        artifact = result.get("artifact") or {}
        superseded = artifact.get("supersededAt")
        head = f"{result.get('rank', '?')}. [{date}] {result.get('content', '').strip()}"
        if superseded:
            head += f" (superseded on {superseded[:10]})"
        lines.append(head)
        for source in result.get("sources") or []:
            name = source.get("label") or source.get("sourceId")
            for excerpt in source.get("excerpts") or []:
                lines.append(f'   - "{excerpt}" ({name}, {(source.get("occurredAt") or "")[:10]})')
    return "\n".join(lines)
