"""ReplaysService — Phase 1 implementation of the session-replay surface.

Orchestrates the discovery → sign → fetch pipeline against the Mixpanel App API
and the signed CDN. Owned by :class:`Workspace`; not part of the public API.

Phase 1 scope (PR 1):
- ``sign`` — wraps :meth:`MixpanelAPIClient.sign_replays`, attaches a
  ``signed_at`` timestamp, hydrates :class:`SignedReplay` instances.
- ``fetch_files`` / ``walk_cdn_async`` — parallel CDN walker with batched
  ``httpx.AsyncClient`` GETs, 404-as-end-sentinel, 403-as-expiry retry,
  mobile-replay detection, ``max_files`` upper bound.
- ``discover`` / ``events_for`` — Insights-API discovery for
  ``$mp_session_record`` events (delegates to a caller-supplied ``query_fn``
  to avoid a circular dependency on :class:`Workspace`).

Phase 2 (PR 2) layers the rrweb analyzer on top via ``Workspace.fetch_replay``
populating ``Replay.actions``; the service itself stays pure-bytes.
"""

from __future__ import annotations

import asyncio
import logging
import time
import warnings
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any, Literal

import httpx

from mixpanel_headless.exceptions import (
    MixpanelHeadlessError,
    ReplayNotFoundError,
    SignedURLExpiredError,
)
from mixpanel_headless.types import (
    Filter,
    ReplayEvent,
    ReplaySummary,
    SignedReplay,
)

if TYPE_CHECKING:
    from mixpanel_headless._internal.api_client import MixpanelAPIClient

_logger = logging.getLogger(__name__)


# Allowed retention windows — surfaced as a sentinel so the discover-time
# warning path can default a missing $mp_replay_retention_period.
_DEFAULT_RETENTION_DAYS = 30


def _looks_like_rrweb(event: object) -> bool:
    """Heuristic: does this look like an rrweb web-recording event?

    rrweb event shape always includes at minimum ``type`` (int discriminator),
    ``data`` (dict), and ``timestamp`` (int ms). Mobile session replays use a
    different recording format that lacks these keys; we treat absence as
    "not rrweb" and surface a forward-compat ``NotImplementedError``.

    Args:
        event: A single deserialized CDN-file element.

    Returns:
        True when the event carries the three required rrweb keys; False
        otherwise.
    """
    if not isinstance(event, dict):
        return False
    return "type" in event and "data" in event and "timestamp" in event


class ReplaysService:
    """Phase 1 orchestrator for the session-replay pipeline.

    Sits between :class:`Workspace` and :class:`MixpanelAPIClient`; owns the
    async CDN walker that pulls raw rrweb bytes. The service intentionally
    stays pure-bytes — analyzer integration ships in Phase 2 by having
    :meth:`Workspace.fetch_replay` feed ``rrweb_events`` through the vendored
    analyzer when populating :class:`Replay`.

    Construction is dependency-injected: the API client carries auth context,
    the optional ``query_fn`` (typically a bound :meth:`Workspace.query`)
    avoids a circular import while still letting discovery issue Insights
    queries, and ``_async_transport`` lets tests swap in ``httpx.MockTransport``.

    Attributes:
        _api: The bound API client used for signing and Insights calls.
        _query_fn: Optional bound ``Workspace.query`` used by
            :meth:`discover` and :meth:`events_for`. None disables those two
            methods; sign/fetch keep working.
        _logger: Logger; never receives ``query_string`` at any level
            (FR-009).
        _async_transport: Optional ``httpx.AsyncBaseTransport`` injected at
            test time so CDN fetches go through ``httpx.MockTransport``.
    """

    def __init__(
        self,
        api_client: MixpanelAPIClient,
        *,
        query_fn: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
        _async_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            api_client: Authenticated :class:`MixpanelAPIClient`.
            query_fn: Bound :meth:`Workspace.query` for discovery queries.
                Optional — when omitted, :meth:`discover` and
                :meth:`events_for` raise ``RuntimeError``.
            logger: Optional logger; defaults to the module logger.
            _async_transport: Optional async transport for CDN fetches
                (test-only seam).
        """
        self._api = api_client
        self._query_fn = query_fn
        self._logger = logger or _logger
        self._async_transport = _async_transport

    # =========================================================================
    # Sign
    # =========================================================================

    def sign(
        self,
        replay_ids: list[str],
        env: Literal["prod", "dev"] = "prod",
    ) -> list[SignedReplay]:
        """Sign one or more replay IDs for CDN access.

        Captures ``signed_at`` BEFORE issuing the request so callers' expiry
        arithmetic is conservative (the URL stops working slightly before
        ``signed_at + 300`` — the server's stopwatch starts earlier than the
        client's record). Delegates raw signing to
        :meth:`MixpanelAPIClient.sign_replays` which handles the 403→
        :class:`SessionReplayAccessError` mapping.

        Args:
            replay_ids: Replay IDs to sign, in any order.
            env: ``"prod"`` (default) or ``"dev"``.

        Returns:
            List of :class:`SignedReplay`, in input order. The
            ``query_string`` field is a bearer credential — never log it.

        Raises:
            SessionReplayAccessError: Project has
                ``SESSION_RECORDING_SENSITIVE_DATA`` enabled and caller
                lacks ``sensitive_data_replay`` permission.
            APIError: Other 4xx (other than the sensitive-data 403) or
                ``ServerError`` on 5xx.
        """
        signed_at = time.time()
        raw = self._api.sign_replays(replay_ids, env=env)
        return [
            SignedReplay(
                replay_id=str(item["replay_id"]),
                url=str(item["url"]),
                query_string=str(item["query_string"]),
                env=env,
                signed_at=signed_at,
            )
            for item in raw
        ]

    # =========================================================================
    # Fetch / walk
    # =========================================================================

    def fetch_files(
        self,
        signed: SignedReplay,
        *,
        retention_days: int,
        max_files: int = 500,
        concurrency: int = 50,
        re_sign_on_expiry: bool = True,
    ) -> list[dict[str, Any]]:
        """Buffered parallel fetch of all CDN files for a replay.

        Walks ``{signed.url}{N:04d}-{retention_days}.json?{query_string}``
        in batches of ``concurrency`` until either a 404 sentinel terminates
        the walk or ``max_files`` is reached. Returns the concatenated
        rrweb event stream sorted by timestamp.

        Args:
            signed: Signed CDN access handle from :meth:`sign`.
            retention_days: 1, 7, 30, or 90 — drives the file-name suffix
                per FR-013.
            max_files: Hard upper bound on the walk (default 500).
            concurrency: Parallel batch size (default 50).
            re_sign_on_expiry: When True, transparently re-signs once if a
                batch returns 403. When False, raises
                :class:`SignedURLExpiredError`.

        Returns:
            Timestamp-sorted list of raw rrweb event dicts.

        Raises:
            ReplayNotFoundError: First CDN file (``0000-N.json``) was 404.
            SignedURLExpiredError: Re-sign retry also returned 403, or
                ``re_sign_on_expiry=False``.
            NotImplementedError: First event in the walk doesn't look like
                rrweb (mobile replay or unknown format).
            MixpanelHeadlessError: Network errors during CDN fetch.
        """

        async def _runner() -> list[dict[str, Any]]:
            """Collect every event yielded by walk_cdn_async into a buffer."""
            collected: list[dict[str, Any]] = []
            async for ev in self.walk_cdn_async(
                signed,
                retention_days=retention_days,
                max_files=max_files,
                concurrency=concurrency,
                re_sign_on_expiry=re_sign_on_expiry,
            ):
                collected.append(ev)
            return collected

        return asyncio.run(_runner())

    async def walk_cdn_async(
        self,
        signed: SignedReplay,
        *,
        retention_days: int,
        max_files: int = 500,
        concurrency: int = 50,
        re_sign_on_expiry: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Streaming parallel walk of CDN files; yields rrweb events lazily.

        Algorithm (per FR-011, FR-012, FR-014, FR-015):
        1. Fetch files ``[N, N+concurrency)`` in parallel via
           ``asyncio.gather``.
        2. If any 403 hits and ``re_sign_on_expiry=True``, re-sign once and
           retry the batch; otherwise raise :class:`SignedURLExpiredError`.
        3. Walk the batch in file-number order. First file (file_num=0)
           returning 404 raises :class:`ReplayNotFoundError`; any subsequent
           404 terminates the walk cleanly (end-of-replay sentinel).
        4. Within each surviving file, yield events sorted by ``timestamp``.
        5. Continue until termination, exhaustion, or ``max_files``.

        Mobile-replay detection runs once on the very first event of the
        walk: if it lacks rrweb's ``type``/``data``/``timestamp`` keys,
        raises ``NotImplementedError`` per error-messages.md §9.

        Args:
            signed: Signed CDN access handle.
            retention_days: 1, 7, 30, or 90.
            max_files: Hard upper bound on the walk.
            concurrency: Parallel batch size.
            re_sign_on_expiry: Re-sign once on 403; raise otherwise.

        Yields:
            Raw rrweb event dicts in timestamp order.

        Raises:
            ReplayNotFoundError: First CDN file 404.
            SignedURLExpiredError: Expiry retry exhausted or disabled.
            NotImplementedError: First event isn't rrweb-shaped.
            MixpanelHeadlessError: Underlying CDN HTTP error.
        """
        current_signed = signed
        file_num = 0
        mobile_checked = False
        re_signed_once = False

        async with httpx.AsyncClient(
            transport=self._async_transport,
            timeout=120.0,
        ) as client:
            while file_num < max_files:
                batch_end = min(file_num + concurrency, max_files)
                batch_nums = list(range(file_num, batch_end))

                results = await self._fetch_batch(
                    client, current_signed, batch_nums, retention_days
                )

                # 403 retry: re-sign once if any file in the batch expired.
                if any(status == 403 for status, _ in results):
                    if not re_sign_on_expiry or re_signed_once:
                        raise self._build_expired_error(signed)
                    re_signed_once = True
                    fresh = self.sign([signed.replay_id], env=signed.env)
                    current_signed = fresh[0]
                    results = await self._fetch_batch(
                        client, current_signed, batch_nums, retention_days
                    )
                    if any(status == 403 for status, _ in results):
                        raise self._build_expired_error(signed)

                # Walk results in file-number order. A 404 mid-walk is the
                # clean end-of-replay sentinel; a 404 on file 0 means the
                # replay simply doesn't exist on the CDN.
                terminate_at = len(results)
                for i, (status, _events) in enumerate(results):
                    if status == 404:
                        if file_num + i == 0:
                            raise ReplayNotFoundError(
                                (
                                    f"Replay {signed.replay_id} not found on CDN. "
                                    f"The replay may have aged out of its "
                                    f"retention window ({retention_days} days), "
                                    f"never been recorded, or been deleted."
                                ),
                                details={
                                    "replay_id": signed.replay_id,
                                    "retention_days": retention_days,
                                    "cdn_url_prefix": signed.url,
                                },
                                status_code=404,
                            )
                        terminate_at = i
                        break

                # Yield events from the surviving files in timestamp order.
                for i in range(terminate_at):
                    status, events = results[i]
                    if status != 200 or not events:
                        continue
                    if not mobile_checked:
                        mobile_checked = True
                        if not _looks_like_rrweb(events[0]):
                            raise NotImplementedError(
                                f"Replay {signed.replay_id} appears to be a "
                                f"mobile session (non-rrweb format). Mobile "
                                f"session replays are not yet supported by "
                                f"mixpanel-headless. Track upstream at SR-230."
                            )
                    for ev in sorted(events, key=lambda e: int(e.get("timestamp", 0))):
                        yield ev

                if terminate_at < len(results):
                    return
                file_num = batch_end

    async def _fetch_batch(
        self,
        client: httpx.AsyncClient,
        signed: SignedReplay,
        file_nums: list[int],
        retention_days: int,
    ) -> list[tuple[int, list[dict[str, Any]] | None]]:
        """Issue parallel CDN GETs for a batch of file numbers.

        Args:
            client: An ``httpx.AsyncClient`` (created by
                :meth:`walk_cdn_async` with the test-injectable transport).
            signed: The active signed handle (may be a re-signed instance).
            file_nums: File numbers to fetch (e.g. ``[0, 1, 2, ..., 49]``).
            retention_days: 1, 7, 30, or 90 — used in the file-name suffix.

        Returns:
            List of ``(status_code, events_or_none)`` tuples in
            ``file_nums`` order. ``events`` is the decoded JSON list for
            200s, ``None`` for 404 and 403.
        """
        tasks = [self._fetch_one(client, signed, n, retention_days) for n in file_nums]
        return await asyncio.gather(*tasks)

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        signed: SignedReplay,
        file_num: int,
        retention_days: int,
    ) -> tuple[int, list[dict[str, Any]] | None]:
        """Fetch a single CDN file.

        URL pattern per FR-013:
        ``{signed.url}{file_num:04d}-{retention_days}.json?{query_string}``.

        Args:
            client: The active ``httpx.AsyncClient``.
            signed: Signed access handle providing url + credential.
            file_num: Zero-padded file index (0–9999).
            retention_days: Retention suffix.

        Returns:
            ``(status_code, events_or_none)``: events list for 200s,
            ``None`` for 404 and 403, raises for everything else.

        Raises:
            MixpanelHeadlessError: Non-200/404/403 HTTP error or transport
                failure during the CDN fetch.
        """
        # NB: query_string is a bearer credential — never log this URL.
        url = f"{signed.url}{file_num:04d}-{retention_days}.json?{signed.query_string}"
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise MixpanelHeadlessError(
                f"CDN fetch failed for file {file_num:04d}: {exc}",
                code="CDN_FETCH_ERROR",
            ) from exc

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise MixpanelHeadlessError(
                    f"CDN file {file_num:04d} returned non-JSON: {exc}",
                    code="CDN_INVALID_RESPONSE",
                ) from exc
            events = payload if isinstance(payload, list) else []
            return (200, events)
        if response.status_code in (403, 404):
            return (response.status_code, None)
        raise MixpanelHeadlessError(
            f"CDN file {file_num:04d} returned unexpected status "
            f"{response.status_code}",
            code="CDN_UNEXPECTED_STATUS",
        )

    def _build_expired_error(self, signed: SignedReplay) -> SignedURLExpiredError:
        """Construct a canonical :class:`SignedURLExpiredError` for ``signed``.

        Args:
            signed: The signed handle whose URL expired.

        Returns:
            A :class:`SignedURLExpiredError` with the catalog message and
            the ``replay_id``/``signed_at``/``expired_at`` details.
        """
        return SignedURLExpiredError(
            (
                f"Signed URL for replay {signed.replay_id} expired (5-minute "
                f"TTL). Re-sign with sign_replay({signed.replay_id!r}) or use "
                f"the default re_sign_on_expiry=True on stream_replay."
            ),
            details={
                "replay_id": signed.replay_id,
                "signed_at": signed.signed_at,
                "expired_at": signed.expires_at,
            },
            status_code=403,
        )

    # =========================================================================
    # Discovery + events
    # =========================================================================

    def discover(
        self,
        *,
        distinct_id: str | None = None,
        replay_ids: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> list[ReplaySummary]:
        """Discover replays for a user or hydrate explicit IDs.

        Issues exactly one Insights query against ``$mp_session_record``
        grouped on ``$mp_replay_id`` and ``$mp_replay_retention_period``,
        then collapses the result into :class:`ReplaySummary` rows. A
        :class:`UserWarning` fires for any replay missing
        ``$mp_replay_retention_period`` — those default to 30 days per
        error-messages.md §10.

        Args:
            distinct_id: Filter to a single user; mutually exclusive with
                ``replay_ids``. Validated by :meth:`Workspace.list_replays`.
            replay_ids: Hydrate explicit IDs; mutually exclusive with
                ``distinct_id``.
            from_date: ISO date (YYYY-MM-DD).
            to_date: ISO date (YYYY-MM-DD).
            limit: Maximum summaries to return (default 100).

        Returns:
            List of :class:`ReplaySummary`, possibly empty.

        Raises:
            RuntimeError: Service was constructed without a ``query_fn``.
        """
        if self._query_fn is None:
            raise RuntimeError(
                "ReplaysService.discover requires query_fn (typically "
                "Workspace.query) at construction"
            )

        if distinct_id is not None:
            where: Filter | list[Filter] = Filter.equals("$distinct_id", distinct_id)
        elif replay_ids:
            where = Filter.equals("$mp_replay_id", list(replay_ids))
        else:
            return []

        result = self._query_fn(
            "$mp_session_record",
            from_date=from_date,
            to_date=to_date,
            group_by=["$mp_replay_id", "$mp_replay_retention_period"],
            where=where,
            mode="table",
        )

        project_id = int(self._api.project_id)
        return self._parse_summaries(
            result,
            project_id=project_id,
            distinct_id=distinct_id,
            limit=limit,
        )

    def _parse_summaries(
        self,
        result: Any,
        *,
        project_id: int,
        distinct_id: str | None,
        limit: int,
    ) -> list[ReplaySummary]:
        """Collapse a grouped Insights result into :class:`ReplaySummary` rows.

        Walks the result's ``.df`` looking for replay-id / retention /
        timestamp columns under their well-known Mixpanel names. Defaults
        retention to 30 with a :class:`UserWarning` per error-messages.md §10.

        Args:
            result: Output of :func:`Workspace.query`.
            project_id: Project to stamp on each summary.
            distinct_id: When set, used as the ``distinct_id`` on every
                summary; otherwise the parser leaves it ``None``.
            limit: Hard cap on the returned list length.

        Returns:
            Up to ``limit`` :class:`ReplaySummary` rows. Empty when the
            query produced no rows.
        """
        df = getattr(result, "df", None)
        if df is None or df.empty:
            return []

        summaries: list[ReplaySummary] = []
        # The Insights table-mode result groups on the requested keys; pick
        # the columns by name when present, else fall back to the labelled
        # group axes.
        rid_col = _pick_column(df, "$mp_replay_id")
        retention_col = _pick_column(df, "$mp_replay_retention_period")
        time_col = _pick_column(df, "$time") or _pick_column(df, "datetime")

        if rid_col is None:
            return []

        seen: set[str] = set()
        for _, row in df.iterrows():
            replay_id = row[rid_col]
            if replay_id is None or str(replay_id) == "":
                continue
            replay_id_str = str(replay_id)
            if replay_id_str in seen:
                continue
            seen.add(replay_id_str)

            retention_raw = row[retention_col] if retention_col is not None else None
            try:
                retention_days = int(retention_raw) if retention_raw is not None else 0
            except (TypeError, ValueError):
                retention_days = 0
            if retention_days not in (1, 7, 30, 90):
                warnings.warn(
                    (
                        f"UserWarning: replay {replay_id_str} is missing "
                        f"$mp_replay_retention_period; defaulting to 30 days. "
                        f"Upgrade your Mixpanel SDK to stamp this property on "
                        f"new recordings."
                    ),
                    UserWarning,
                    stacklevel=3,
                )
                retention_days = _DEFAULT_RETENTION_DAYS

            start_time_raw = row[time_col] if time_col is not None else None
            start_time = _to_unix_ms(start_time_raw)
            if start_time <= 0:
                # Skip rows that have no usable start time — they can't form
                # a valid ReplaySummary (positive unix-ms is a constructor
                # invariant).
                continue

            summaries.append(
                ReplaySummary(
                    replay_id=replay_id_str,
                    distinct_id=distinct_id,
                    project_id=project_id,
                    start_time=start_time,
                    retention_days=retention_days,
                )
            )
            if len(summaries) >= limit:
                break

        return summaries

    def events_for(
        self,
        replay_ids: list[str],
        *,
        event_properties: list[str] | None = None,
    ) -> dict[str, list[ReplayEvent]]:
        """Mixpanel events for a list of replays in one round-trip.

        Mirrors the upstream
        ``analytics/backend/replays/query_utils.py::build_replay_events_request``:
        queries the ``$all_events`` wildcard grouped on ``$time`` /
        ``$event_name`` / ``$mp_replay_id`` (+ any caller-supplied
        ``event_properties``), filters on ``$mp_replay_id IN replay_ids``,
        and excludes the ``$mp_session_record`` event itself (per the
        contract — these are events that happened DURING the replay
        window, not the recording event).

        Args:
            replay_ids: Replays to look up events for. May be empty.
            event_properties: Up to 5 extra event properties to include as
                group keys.

        Returns:
            Dict mapping replay_id → time-sorted :class:`ReplayEvent` list.
            Replays with no events are omitted.

        Raises:
            RuntimeError: Service was constructed without a ``query_fn``.
        """
        if self._query_fn is None:
            raise RuntimeError(
                "ReplaysService.events_for requires query_fn (typically "
                "Workspace.query) at construction"
            )
        if not replay_ids:
            return {}

        # Group on time + event_name + replay_id (+ any caller extras) so
        # the result has one row per event per replay. Matches upstream's
        # REPLAY_EVENT_BASE_GROUPS.
        group_by: list[str] = ["$time", "$event_name", "$mp_replay_id"]
        if event_properties:
            group_by.extend(event_properties)

        # Two filters: limit to the requested replays AND exclude the
        # recording event itself. Without the exclusion, every replay's
        # event list would have an N-second-resolution duplicate of the
        # recording-start event.
        where = [
            Filter.equals("$mp_replay_id", list(replay_ids)),
            Filter.not_equals("$event_name", "$mp_session_record"),
        ]
        result = self._query_fn(
            "$all_events",
            group_by=group_by,
            where=where,
            mode="table",
        )

        out: dict[str, list[ReplayEvent]] = {}
        df = getattr(result, "df", None)
        if df is None or df.empty:
            return out

        rid_col = _pick_column(df, "$mp_replay_id")
        time_col = _pick_column(df, "$time") or _pick_column(df, "datetime")
        name_col = (
            _pick_column(df, "$event_name")
            or _pick_column(df, "event")
            or _pick_column(df, "$event")
        )

        if rid_col is None:
            return out

        for _, row in df.iterrows():
            replay_id = row[rid_col]
            if replay_id is None:
                continue
            replay_id_str = str(replay_id)
            event_time = _to_unix_seconds(
                row[time_col] if time_col is not None else None
            )
            if event_time <= 0:
                continue
            event_name = str(row[name_col]) if name_col is not None else "(unknown)"
            properties: dict[str, Any] | None = None
            if event_properties:
                properties = {
                    prop: row[prop] for prop in event_properties if prop in df.columns
                }
            out.setdefault(replay_id_str, []).append(
                ReplayEvent(
                    replay_id=replay_id_str,
                    event_name=event_name,
                    event_time=event_time,
                    properties=properties,
                )
            )

        # Match upstream's deterministic time-ordered output per replay.
        for replay_id_str in out:
            out[replay_id_str].sort(key=lambda e: e.event_time)

        return out


def _pick_column(df: Any, name: str) -> str | None:
    """Return ``name`` if it's a column of ``df``, else ``None``.

    Args:
        df: A pandas DataFrame (typed loosely to avoid pandas import here).
        name: Column name to probe.

    Returns:
        ``name`` if present; ``None`` otherwise.
    """
    try:
        if name in df.columns:
            return name
    except (AttributeError, TypeError):
        return None
    return None


def _to_unix_ms(value: Any) -> int:
    """Coerce a Mixpanel ``$time`` value to unix milliseconds.

    Mixpanel's ``$time`` column comes back as an ISO-8601 string, a
    pandas Timestamp, or a unix seconds/ms int depending on the response
    shape. Returns 0 when the value can't be parsed — callers treat that
    as "skip this row".

    Args:
        value: Raw cell from the result DataFrame.

    Returns:
        Unix milliseconds, or 0 when the value isn't interpretable.
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value if value > 10**12 else value * 1000
    if isinstance(value, float):
        ivalue = int(value)
        return ivalue if ivalue > 10**12 else ivalue * 1000
    try:
        import pandas as pd  # local import; pandas already a project dep

        ts = pd.Timestamp(value)
        return int(ts.value // 1_000_000)
    except (ValueError, TypeError, ImportError):
        return 0


def _to_unix_seconds(value: Any) -> int:
    """Coerce a Mixpanel ``$time`` value to unix seconds.

    Mirror of :func:`_to_unix_ms` for the ``ReplayEvent.event_time``
    field (Mixpanel-native seconds).

    Args:
        value: Raw cell from the result DataFrame.

    Returns:
        Unix seconds, or 0 when the value isn't interpretable.
    """
    ms = _to_unix_ms(value)
    return ms // 1000 if ms > 0 else 0
