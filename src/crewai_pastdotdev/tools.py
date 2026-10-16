"""past dev Recall and Ingest as CrewAI tools.

The model gives only the query or the content. The identity, the key and
every other setting are fixed when you build the tool, so an agent can never
read or write the memory of another person.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from crewai.tools import BaseTool, EnvVar
from pydantic import BaseModel, Field, PlainValidator, PrivateAttr, SecretStr, field_validator

from crewai_pastdotdev._common import (
    check_identity,
    clamp_limit,
    format_recall,
    make_client,
    source_id_for,
)
from crewai_pastdotdev.client import PastDevClient, PastDevError, RecallLevel


def _passthrough(value: Any) -> Any:
    return value


def _describe(error: PastDevError, operation: str) -> str:
    text = f"past dev {operation} failed: {error}."
    if error.status in (400, 401, 402, 403, 404, 409, 413) or error.code.endswith("-cap-reached"):
        text += " Do not retry this call."
    return text


class PastDevRecallInput(BaseModel):
    query: str = Field(
        ...,
        description="What to look for in memory, as a natural-language question or topic.",
    )


class PastDevIngestInput(BaseModel):
    content: str = Field(
        ...,
        description=(
            "The facts, decisions or observations to keep, written as complete, "
            "self-contained text."
        ),
    )


def _env_vars() -> list[EnvVar]:
    return [
        EnvVar(name="PAST_API_KEY", description="A past dev project API key (past_sk_...)."),
        EnvVar(
            name="PAST_API_HOST",
            description="The past dev API host, for a deployment in your own cloud.",
            required=False,
            default="https://api.past.dev",
        ),
    ]


class _PastDevTool(BaseTool):
    identity: str = Field(description="The past dev identity, fixed by the builder.")
    env_vars: list[EnvVar] = Field(default_factory=_env_vars)
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    api_host: str | None = Field(default=None)
    client: Annotated[PastDevClient | None, PlainValidator(_passthrough)] = Field(
        default=None, exclude=True, repr=False
    )

    _client: PastDevClient = PrivateAttr()

    @field_validator("identity")
    @classmethod
    def _valid_identity(cls, value: str) -> str:
        return check_identity(value)

    def model_post_init(self, context: Any, /) -> None:
        super().model_post_init(context)
        self._client = make_client(self.client, self.api_key, self.api_host)


class PastDevRecallTool(_PastDevTool):
    """Recall what past dev remembers about the fixed identity.

    Args:
        identity: The past dev identity to recall for. Set by your code.
        api_key: A project API key; defaults to ``PAST_API_KEY``.
        api_host: Defaults to ``PAST_API_HOST``, else ``https://api.past.dev``.
        limit: The maximum number of memories returned (1 to 200).
        level: The evidence budget: ``low``, ``medium``, ``high`` or ``extra-high``.
    """

    name: str = "past dev Recall"
    description: str = (
        "Recall memories from past dev: earlier facts, decisions, preferences and "
        "events about the current user. Returns the most relevant memories with "
        "their dates and quotations from their sources."
    )
    args_schema: type[BaseModel] = PastDevRecallInput
    limit: int = Field(default=10, ge=1, le=200)
    level: RecallLevel | None = Field(default=None)

    def _run(self, query: str, **kwargs: Any) -> str:
        if not query or not query.strip():
            return "past dev Recall needs a query."
        try:
            response = self._client.recall(
                query, identity=self.identity, limit=clamp_limit(self.limit), level=self.level
            )
        except PastDevError as error:
            return _describe(error, "Recall")
        return format_recall(response)

    async def _arun(self, query: str, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, query)


class PastDevIngestTool(_PastDevTool):
    """Ingest new information into past dev for the fixed identity.

    Args:
        identity: The past dev identity the content belongs to. Set by your code.
        api_key: A project API key; defaults to ``PAST_API_KEY``.
        api_host: Defaults to ``PAST_API_HOST``, else ``https://api.past.dev``.
        audience: An audience slug; omit it for project-visible memory.
        label: An optional short title stored with each data point.
        metadata: Optional JSON stored with each data point.
    """

    name: str = "past dev Ingest"
    description: str = (
        "Ingest information into past dev so it can be recalled later: facts, "
        "decisions, preferences or outcomes worth keeping about the current user. "
        "Send complete, self-contained text."
    )
    args_schema: type[BaseModel] = PastDevIngestInput
    audience: str | None = Field(default=None)
    label: str | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)

    def _run(self, content: str, **kwargs: Any) -> str:
        if not content or not content.strip():
            return "past dev Ingest needs content."
        try:
            receipt = self._client.ingest(
                content,
                identity=self.identity,
                id=source_id_for(self.identity, content),
                audience=self.audience,
                label=self.label,
                metadata=self.metadata,
            )
        except PastDevError as error:
            return _describe(error, "Ingest")
        if receipt.get("unchanged"):
            return f"past dev already has this content (source id {receipt.get('sourceId')})."
        return (
            f"Ingested into past dev (source id {receipt.get('sourceId')}, "
            f"status {receipt.get('status')}). It can be recalled once processing completes."
        )

    async def _arun(self, content: str, **kwargs: Any) -> str:
        return await asyncio.to_thread(self._run, content)
