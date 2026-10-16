"""past dev as CrewAI memory.

CrewAI 1.x has one ``Memory`` class. Its storage backends are vector stores
that receive embeddings, while past dev takes text and does its own
extraction, embedding and ranking. So this integration subclasses ``Memory``
and replaces the operations a crew calls: a save is a past dev Ingest and a
search is a past dev Recall. A crew accepts it wherever it accepts a
``Memory``::

    crew = Crew(agents=..., tasks=..., memory=PastDevMemory(identity="user-42"))
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated, Any, Literal

from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.memory_events import (
    MemoryQueryCompletedEvent,
    MemoryQueryFailedEvent,
    MemoryQueryStartedEvent,
)
from crewai.memory.types import MemoryMatch, MemoryRecord
from crewai.memory.unified_memory import Memory
from crewai.memory.utils import join_scope_paths
from pydantic import Field, PlainValidator, PrivateAttr, SecretStr, field_validator, model_validator

from crewai_pastdotdev._common import (
    check_identity,
    clamp_limit,
    make_client,
    parse_datetime,
    source_id_for,
)
from crewai_pastdotdev.client import PastDevClient, PastDevError, RecallLevel

_SOURCE_TYPE = "past_dev"


def _passthrough(value: Any) -> Any:
    return value


class _NoLocalStore:
    """Stands in for CrewAI's local vector store, which past dev replaces.

    past dev keeps memory on its servers, so the local browse and edit
    operations (``tree``, ``info``, ``list_records``, ``update`` ...) have
    nothing to read. They raise with a pointer to what to use instead.
    """

    _MESSAGE = (
        "past dev keeps memory on its servers, not in a local store. "
        "Use recall() to read, remember() to ingest, forget(record_ids=[...]) "
        "to delete data points, and the past dev console to browse."
    )

    def _unsupported(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(self._MESSAGE)

    save = search = delete = update = get_record = list_records = _unsupported
    get_scope_info = list_scopes = list_categories = count = reset = _unsupported
    asave = asearch = adelete = _unsupported

    def __deepcopy__(self, memo: dict[int, Any]) -> _NoLocalStore:
        return self


class PastDevMemory(Memory):
    """CrewAI memory backed by past dev.

    Saves are past dev Ingests and searches are past dev Recalls, for one
    fixed identity. The identity is the id of the person (or account) the
    memory belongs to; your code sets it, never the model.

    Args:
        identity: The past dev identity every Ingest and Recall uses.
        api_key: A project API key (``past_sk_...``). Defaults to the
            ``PAST_API_KEY`` environment variable.
        api_host: Defaults to ``PAST_API_HOST``, else ``https://api.past.dev``.
        audience: An audience slug for ingested memories. Omit it for
            project-visible memory.
        label: An optional short title stored with each ingested data point.
        recall_level: The recall evidence budget: ``low`` (default),
            ``medium``, ``high`` or ``extra-high``.
        recall_max_tokens: An explicit evidence budget in tokens, instead of
            ``recall_level``.
        client: A ready :class:`PastDevClient`, instead of ``api_key`` and
            ``api_host``.

    past dev extracts memories on its side, so ``extract_memories`` does not
    call an LLM: a crew's task result is ingested as one data point, as
    written. CrewAI scopes and categories are kept in the data point's
    metadata; recall does not filter on them.
    """

    identity: str = Field(description="The past dev identity for every Ingest and Recall.")
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    api_host: str | None = Field(default=None)
    audience: str | None = Field(default=None)
    label: str | None = Field(default=None)
    recall_level: RecallLevel | None = Field(default=None)
    recall_max_tokens: int | None = Field(default=None, ge=1)
    client: Annotated[PastDevClient | None, PlainValidator(_passthrough)] = Field(
        default=None, exclude=True, repr=False
    )
    storage: Annotated[Any, PlainValidator(_passthrough)] = Field(
        default_factory=_NoLocalStore, exclude=True, repr=False
    )

    _client: PastDevClient = PrivateAttr()
    _owns_client: bool = PrivateAttr(default=False)

    @field_validator("identity")
    @classmethod
    def _valid_identity(cls, value: str) -> str:
        return check_identity(value)

    @model_validator(mode="after")
    def _one_budget(self) -> PastDevMemory:
        if self.recall_level is not None and self.recall_max_tokens is not None:
            raise ValueError("Set recall_level or recall_max_tokens, never both.")
        return self

    def model_post_init(self, context: Any, /) -> None:
        super().model_post_init(context)
        self._owns_client = self.client is None
        self._client = make_client(self.client, self.api_key, self.api_host)

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> PastDevMemory:
        # Memory.__deepcopy__ fails on Python 3.12 and earlier. A copy gets its
        # own save thread and shares the HTTP client, which is thread-safe.
        values = {name: getattr(self, name) for name in type(self).model_fields}
        values["client"] = self._client
        clone = type(self)(**values)
        clone._owns_client = False
        return clone

    # -- save: Ingest -------------------------------------------------------

    def extract_memories(self, content: str) -> list[str]:
        """Return the content as one item; past dev extracts memories itself."""
        text = content.strip() if content else ""
        return [text] if text else []

    def remember_many(
        self,
        contents: list[str],
        scope: str | None = None,
        categories: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
        source: str | None = None,
        private: bool = False,
        agent_role: str | None = None,
        root_scope: str | None = None,
    ) -> list[MemoryRecord]:
        # A crew passes the role of the agent that produced the result; keep it.
        if agent_role:
            metadata = {"crewai_agent_role": agent_role, **(metadata or {})}
        return super().remember_many(
            contents,
            scope=scope,
            categories=categories,
            metadata=metadata,
            importance=importance,
            source=source,
            private=private,
            agent_role=agent_role,
            root_scope=root_scope,
        )

    def _encode_batch(
        self,
        contents: list[str],
        scope: str | None = None,
        categories: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: float | None = None,
        source: str | None = None,
        private: bool = False,
        root_scope: str | None = None,
    ) -> list[MemoryRecord]:
        # Called by Memory.remember() and remember_many() on the save thread,
        # so events, the write barrier and drain_writes() work unchanged.
        scope_path: str | None = scope or root_scope
        if root_scope and scope:
            scope_path = join_scope_paths(root_scope, scope)
        sent_metadata = dict(metadata or {})
        if scope_path:
            sent_metadata.setdefault("crewai_scope", scope_path)
        if categories:
            sent_metadata.setdefault("crewai_categories", list(categories))

        records: list[MemoryRecord] = []
        for content in contents:
            if not content or not content.strip():
                continue
            receipt = self._client.ingest(
                content,
                identity=self.identity,
                id=source_id_for(self.identity, content),
                audience=self.audience,
                label=self.label,
                metadata=sent_metadata or None,
            )
            records.append(
                MemoryRecord(
                    id=str(receipt.get("sourceId")),
                    content=content,
                    scope=scope_path or "/",
                    categories=list(categories or []),
                    metadata={
                        **sent_metadata,
                        "ingestion_id": receipt.get("ingestionId"),
                        "status": receipt.get("status"),
                    },
                    importance=importance if importance is not None else self.default_importance,
                    source=source,
                    private=private,
                )
            )
        return records

    # -- search: Recall -----------------------------------------------------

    def recall(
        self,
        query: str,
        scope: str | None = None,
        categories: list[str] | None = None,
        limit: int = 10,
        depth: Literal["shallow", "deep"] = "deep",
        source: str | None = None,
        include_private: bool = False,
    ) -> list[MemoryMatch]:
        """Recall memories for ``query`` through past dev.

        ``limit`` is the number of documents (1 to 200). ``scope``,
        ``categories``, ``depth``, ``source`` and ``include_private`` are
        CrewAI options for its local store; past dev ranks on its own and
        applies the identity's audiences instead.
        """
        self.drain_writes()
        if not query or not query.strip():
            return []
        crewai_event_bus.emit(
            self,
            MemoryQueryStartedEvent(
                query=query, limit=limit, score_threshold=None, source_type=_SOURCE_TYPE
            ),
        )
        start = time.perf_counter()
        try:
            response = self._client.recall(
                query,
                identity=self.identity,
                limit=clamp_limit(limit),
                level=self.recall_level,
                max_tokens=self.recall_max_tokens,
            )
            matches = [_to_match(result) for result in response.get("results") or []]
        except Exception as exc:
            crewai_event_bus.emit(
                self,
                MemoryQueryFailedEvent(
                    query=query,
                    limit=limit,
                    score_threshold=None,
                    error=str(exc),
                    source_type=_SOURCE_TYPE,
                ),
            )
            raise
        crewai_event_bus.emit(
            self,
            MemoryQueryCompletedEvent(
                query=query,
                results=matches,
                limit=limit,
                score_threshold=None,
                query_time_ms=(time.perf_counter() - start) * 1000,
                source_type=_SOURCE_TYPE,
            ),
        )
        return matches

    # -- delete: Delete data point -----------------------------------------

    def forget(
        self,
        scope: str | None = None,
        categories: list[str] | None = None,
        older_than: datetime | None = None,
        metadata_filter: dict[str, Any] | None = None,
        record_ids: list[str] | None = None,
    ) -> int:
        """Delete data points by source id; returns how many were found.

        The ids are the ``MemoryRecord.id`` values that ``remember()``
        returns. past dev deletes by source id only, so the other filters
        are refused.
        """
        if scope is not None or categories or older_than is not None or metadata_filter:
            raise NotImplementedError(
                "past dev deletes data points by source id only: pass record_ids=[...]."
            )
        self.drain_writes()
        deleted = 0
        for record_id in record_ids or []:
            try:
                self._client.delete_data_point(record_id)
            except PastDevError as exc:
                if exc.status == 404:
                    continue
                raise
            deleted += 1
        return deleted

    def update(self, *args: Any, **kwargs: Any) -> MemoryRecord:
        raise NotImplementedError(
            "To change a past dev memory, remember() the new content; "
            "past dev keeps both and marks the earlier statement as superseded."
        )

    def reset(self, scope: str | None = None) -> None:
        raise NotImplementedError(
            "past dev does not erase a project from CrewAI. Delete data points "
            "with forget(record_ids=[...]), or use the past dev console."
        )

    def reset_all(self) -> None:
        self.reset()

    def close(self) -> None:
        super().close()
        if self._owns_client:
            self._client.close()


def _to_match(result: dict[str, Any]) -> MemoryMatch:
    artifact = result.get("artifact") or {}
    sources = result.get("sources") or []
    occurred_at = parse_datetime(result.get("occurredAt"))
    metadata: dict[str, Any] = {
        "occurred_at": result.get("occurredAt"),
        "kind": artifact.get("kind"),
        "superseded_at": artifact.get("supersededAt"),
        "source_ids": [s.get("sourceId") for s in sources] or None,
        "excerpts": [e for s in sources for e in (s.get("excerpts") or [])] or None,
    }
    record_fields: dict[str, Any] = {
        "id": str(result.get("id")),
        "content": str(result.get("content", "")),
        "metadata": {k: v for k, v in metadata.items() if v is not None},
    }
    if occurred_at is not None:
        record_fields["created_at"] = occurred_at
    rank = int(result.get("rank") or 1)
    return MemoryMatch(
        record=MemoryRecord(**record_fields),
        score=1.0 / rank,
        match_reasons=[f"past dev rank {rank}"],
    )
