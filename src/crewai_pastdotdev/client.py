"""A small HTTP client for the past dev Memory API.

Only the operations this package uses: Ingest, Recall, Delete data point,
and the two list reads (audiences, identities). See
https://past.dev/docs/memory-api/api-reference for the full API.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx

from crewai_pastdotdev._version import __version__

DEFAULT_API_HOST = "https://api.past.dev"

RecallLevel = Literal["low", "medium", "high", "extra-high"]
RecallSort = Literal["relevance", "chronological"]

# A 429 with one of these codes is a monthly or billing-period cap.
# Waiting a few seconds does not lift it, so it is not retried.
_CAP_CODES = frozenset({"project-cap-reached", "spend-cap-reached"})


class PastDevError(Exception):
    """An error response from the past dev API, or a failed request.

    ``code`` is the API's stable kebab-case code (for example
    ``out-of-credits``), ``status`` the HTTP status (0 when no response came
    back) and ``request_id`` the ``X-Request-Id`` header, which past dev
    support can trace.
    """

    def __init__(
        self,
        code: str,
        status: int,
        message: str | None = None,
        request_id: str | None = None,
        data: Any = None,
    ) -> None:
        self.code = code
        self.status = status
        self.message = message
        self.request_id = request_id
        self.data = data
        text = f"past dev error {code} (HTTP {status})"
        if message:
            text += f": {message}"
        if request_id:
            text += f" [request id {request_id}]"
        super().__init__(text)


def _iso(value: datetime | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _compact(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if v is not None}


class PastDevClient:
    """Synchronous client for the past dev Memory API.

    Args:
        api_key: A project API key (``past_sk_...``). Read from the
            ``PAST_API_KEY`` environment variable when omitted.
        api_host: The API host. Read from ``PAST_API_HOST`` when omitted,
            else ``https://api.past.dev``. Set it when past dev runs in your
            own cloud.
        timeout: Seconds before a request times out.
        max_retries: How many times a rate-limited request (HTTP 429) is
            sent again, after the wait the server asks for. Other errors are
            never retried.
        transport: An ``httpx`` transport, for tests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_host: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = api_key or os.environ.get("PAST_API_KEY")
        if not key:
            raise ValueError(
                "past dev needs a project API key: pass api_key or set PAST_API_KEY."
            )
        host = (api_host or os.environ.get("PAST_API_HOST") or DEFAULT_API_HOST).rstrip("/")
        self.api_host = host
        self.max_retries = max_retries
        self._http = httpx.Client(
            base_url=host,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": f"crewai-pastdotdev/{__version__}",
                "Accept": "application/json",
            },
        )

    def __repr__(self) -> str:
        return f"PastDevClient(api_host={self.api_host!r})"

    def __deepcopy__(self, memo: dict[int, Any]) -> PastDevClient:
        # CrewAI deep-copies agents and memory. The HTTP pool is thread-safe,
        # so copies share it instead of opening a second one.
        return self

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PastDevClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- operations ---------------------------------------------------------

    def ingest(
        self,
        content: str,
        *,
        identity: str | None = None,
        id: str | None = None,
        timestamp: datetime | str | None = None,
        audience: str | None = None,
        label: str | None = None,
        metadata: Any = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ingest one data point. ``POST /api/v1/ingest``.

        Returns the receipt: ``projectId``, ``ingestionId``, ``sourceId``,
        ``status`` (``queued`` or ``completed``) and ``unchanged``.
        """
        body = _compact(
            {
                "content": content,
                "identity": identity,
                "id": id,
                "timestamp": _iso(timestamp),
                "audience": audience,
                "label": label,
                "metadata": metadata,
                "idempotencyKey": idempotency_key,
            }
        )
        return self._request("POST", "/api/v1/ingest", json=body)

    def recall(
        self,
        query: str,
        *,
        identity: str,
        limit: int | None = None,
        level: RecallLevel | None = None,
        max_tokens: int | None = None,
        query_timestamp: datetime | str | None = None,
        occurred_from: datetime | str | None = None,
        occurred_to: datetime | str | None = None,
        sort: RecallSort | None = None,
    ) -> dict[str, Any]:
        """Recall ranked memory documents. ``POST /api/v1/recall``.

        Returns ``asOf``, ``usedEvidenceTokens`` and ``results``; each result
        carries ``id``, ``rank``, ``occurredAt``, ``content``, ``artifact``
        and ``sources``.
        """
        if level is not None and max_tokens is not None:
            raise ValueError("Send level or max_tokens, never both.")
        body = _compact(
            {
                "query": query,
                "identity": identity,
                "limit": limit,
                "level": level,
                "maxTokens": max_tokens,
                "queryTimestamp": _iso(query_timestamp),
                "occurredFrom": _iso(occurred_from),
                "occurredTo": _iso(occurred_to),
                "sort": sort,
            }
        )
        return self._request("POST", "/api/v1/recall", json=body)

    def delete_data_point(self, source_id: str) -> dict[str, Any]:
        """Delete one data point by its source id.
        ``DELETE /api/v1/data-points/{sourceId}``.

        Returns the deletion receipt (``operationId``, ``ids``). The purge
        completes in the background.
        """
        return self._request("DELETE", f"/api/v1/data-points/{quote(source_id, safe='')}")

    def list_audiences(self) -> list[dict[str, Any]]:
        """List the project's audiences. ``GET /api/v1/audiences``.

        Costs no credits, so it also serves as a connection test.
        """
        return list(self._request("GET", "/api/v1/audiences").get("audiences", []))

    def list_identities(self, *, page_size: int = 100) -> Iterator[dict[str, Any]]:
        """Iterate over every identity of the project, page by page.
        ``GET /api/v1/identities``.
        """
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": page_size}
            if after:
                params["after"] = after
            page = self._request("GET", "/api/v1/identities", params=params)
            yield from page.get("identities", [])
            after = page.get("endCursor")
            if not page.get("hasMore") or not after:
                return

    def check_connection(self) -> None:
        """Raise :class:`PastDevError` unless the key and host work.

        Calls ``GET /api/v1/audiences``, which costs no credits.
        """
        self.list_audiences()

    # -- transport ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise PastDevError("network-error", 0, str(exc)) from exc
            if response.status_code < 400:
                if not response.content:
                    return {}
                return dict(response.json())
            error = _error_from(response)
            if (
                response.status_code == 429
                and error.code not in _CAP_CODES
                and attempt < self.max_retries
            ):
                attempt += 1
                time.sleep(_retry_after(response, attempt))
                continue
            raise error


def _error_from(response: httpx.Response) -> PastDevError:
    request_id = response.headers.get("X-Request-Id")
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "code" in body:
        return PastDevError(
            str(body["code"]),
            int(body.get("status") or response.status_code),
            body.get("debugMessage"),
            request_id,
            body.get("data"),
        )
    code = "rate-limited" if response.status_code == 429 else f"http-{response.status_code}"
    return PastDevError(code, response.status_code, response.text or None, request_id)


def _retry_after(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(max(float(header), 0.0), 60.0)
        except ValueError:
            pass
    return float(min(2 ** (attempt - 1), 8))
