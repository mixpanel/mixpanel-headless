#!/usr/bin/env python3
"""Live probe of the saved metrics and saved behaviors App API.

Sends one request per probe to ``/api/app/projects/{pid}/metrics``,
``/behaviors``, ``/shared-entities``, and ``/api/query/insights``, and records
the request, the status code, and the exact response body of each one. The
results feed the unit tests of the saved metric and saved behavior support:
the script writes redacted response bodies to ``tests/fixtures/saved_metrics/``
and a redacted log of every probe to a file in the temp directory.

Safety rules (the script enforces each one):

- Writes go only to the scratch project named by ``MP_LIVE_WRITE_PROJECT``,
  through the account named by ``MP_LIVE_ACCOUNT``. Both settings are
  required and have no default. The script checks the account and the
  project before every write, and refuses to run otherwise.
- Every entity it creates has a name prefix that is unique to the run:
  ``zz-probe-<UTC timestamp>-<random hex>-``.
- The project is shared with other users. Before the first write, the script
  saves the metric and behavior ids of the project to a snapshot file.
- Every PATCH, DELETE, and share upsert goes through a target check first.
  The check reads the ids from the request itself. Each id must not be in the
  start snapshot, and must be an id that this run's POSTs returned or an
  unrecorded entity of this run (see the next rule). If the check fails, the
  script stops and does not send the request.
- A ``finally`` block deletes every entity that this run recorded, through the
  bulk DELETE routes. A create can succeed on the server but leave no usable
  response (a timeout, for example), so the block then lists the project and
  also deletes each row that has this run's prefix, is not in the start
  snapshot, and was not recorded. It reports those rows.
- At the end, the script lists the project again and checks that no entity of
  this run is still active: no recorded id, and no row outside the start
  snapshot with this run's prefix.

This script is **not** in CI. It touches the live Mixpanel API. Run it by hand
when the server contract needs a new recording.

Usage:

```
export MP_LIVE_ACCOUNT=<account> MP_LIVE_WRITE_PROJECT=<scratch project id>
uv run python scripts/probe_saved_metrics.py --gate-only   # one POST, then delete
uv run python scripts/probe_saved_metrics.py               # the full probe
uv run python scripts/probe_saved_metrics.py --time-list   # read-only list timing
```

``--time-list`` needs only ``MP_LIVE_ACCOUNT``. It sends one GET of the
metric list of that account's project, and writes and saves nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import mixpanel_headless as mp
from mixpanel_headless.exceptions import MixpanelHeadlessError

ACCOUNT_ENV = "MP_LIVE_ACCOUNT"
"""Environment variable that names the account of every run."""

WRITE_PROJECT_ENV = "MP_LIVE_WRITE_PROJECT"
"""Environment variable that names the only project a run may write to."""

REDACTED_EMAIL = "user@example.com"
"""Replacement for every email address in a recorded body."""

REDACTED_NAME = "Example User"
"""Replacement for every person name in a recorded body."""

FAKE_USER_ID_BASE = 1_000_001
"""First fake user id. Real user ids map to stable fake ids from here."""

USER_KEYS = ("created_by", "owned_by", "last_verified_by", "owner")
"""Keys whose dict value is a user object (``{id, email, name}``)."""

EVENT_A = "document created"
"""First event with data on the scratch project."""

EVENT_B = "document shared"
"""Second event with data on the scratch project."""

EVENT_C = "document opened"
"""Return event for the retention probes."""

QUERY_FROM = "2024-09-01"
"""Start date of the query probes. The scratch project clock reads 2024-09-15."""

QUERY_TO = "2024-09-07"
"""End date of the query probes."""

UNKNOWN_ID = 999_999_999
"""An id that no metric or behavior has. Used only by read probes."""

DEFAULT_OUT = Path("tests/fixtures/saved_metrics")
"""Output directory of the redacted fixtures."""


class ProbeRefusedError(RuntimeError):
    """A write would go to an account or a project other than the scratch pair."""


@dataclass(frozen=True)
class ScratchTarget:
    """The account and the project that a write run may use."""

    account: str
    project_id: str


def _live_account() -> str:
    """Return the account name from ``MP_LIVE_ACCOUNT``.

    Returns:
        The account name.

    Raises:
        ProbeRefusedError: If the variable is unset or empty.
    """
    account = os.environ.get(ACCOUNT_ENV, "").strip()
    if not account:
        raise ProbeRefusedError(f"{ACCOUNT_ENV} is not set; name the account to use")
    return account


def scratch_target() -> ScratchTarget:
    """Read the scratch account and project from the environment.

    Returns:
        The target that every write must match.

    Raises:
        ProbeRefusedError: If ``MP_LIVE_ACCOUNT`` or ``MP_LIVE_WRITE_PROJECT``
            is unset or empty.
    """
    account = _live_account()
    project = os.environ.get(WRITE_PROJECT_ENV, "").strip()
    if not project:
        raise ProbeRefusedError(
            f"{WRITE_PROJECT_ENV} is not set; name the scratch project id that "
            f"this run may write to"
        )
    return ScratchTarget(account=account, project_id=project)


@dataclass
class ProbeRecord:
    """One recorded request and its response."""

    name: str
    method: str
    path: str
    request_body: Any
    status: int | None
    response_body: Any
    note: str = ""


@dataclass
class ProbeRun:
    """The state of one probe run: the workspace, the log, and the created ids."""

    ws: mp.Workspace
    prefix: str
    target: ScratchTarget
    records: list[ProbeRecord] = field(default_factory=list)
    comparisons: list[dict[str, Any]] = field(default_factory=list)
    created_metrics: list[int] = field(default_factory=list)
    created_behaviors: list[int] = field(default_factory=list)
    start_metrics: set[int] = field(default_factory=set)
    start_behaviors: set[int] = field(default_factory=set)
    swept_metrics: dict[int, str] = field(default_factory=dict)
    swept_behaviors: dict[int, str] = field(default_factory=dict)
    last_status: int | None = None
    last_body: Any = None

    @property
    def pid(self) -> str:
        """Return the project id of the bound session.

        Returns:
            The project id as a string.
        """
        return str(self.ws.api.project_id)


def _utc_stamp() -> str:
    """Return a compact UTC timestamp for entity names.

    Returns:
        A string like ``20260930T081500Z``.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_prefix() -> str:
    """Return the name prefix of one run: a UTC timestamp plus random hex.

    The random part keeps two runs in the same second apart, so a row with
    this prefix belongs to this run only.

    Returns:
        A string like ``zz-probe-20260930T081500Z-3f9a1c-``.
    """
    return f"zz-probe-{_utc_stamp()}-{secrets.token_hex(3)}-"


def _assert_scratch(run: ProbeRun, path: str) -> None:
    """Refuse a write unless it goes to the scratch account and project.

    Args:
        run: The probe run.
        path: The App API path of the write.

    Raises:
        ProbeRefusedError: If the account, the project, or the path is not
            the scratch target.
    """
    account = run.ws.account.name
    if account != run.target.account:
        raise ProbeRefusedError(f"refusing write: account is {account!r}")
    if run.pid != run.target.project_id:
        raise ProbeRefusedError(f"refusing write: project is {run.pid}")
    if not path.startswith(f"/projects/{run.target.project_id}/"):
        raise ProbeRefusedError(f"refusing write: path {path!r}")


_ENTRY_PATH = re.compile(r"^/projects/\d+/(metrics|behaviors)/(\d+)/?$")
"""A single-entity path: ``/projects/{pid}/metrics/{id}``."""

_COLLECTION_PATH = re.compile(r"^/projects/\d+/(metrics|behaviors)/?$")
"""A collection path: ``/projects/{pid}/metrics``."""

_SHARE_PATH = re.compile(
    r"^/projects/\d+/shared-entities/(metric|behavior)/(\d+)/upsert/?$"
)
"""A share upsert path: ``/projects/{pid}/shared-entities/metric/{id}/upsert``."""


def write_targets(
    method: str, path: str, body: dict[str, Any] | None
) -> tuple[str, list[int]] | None:
    """Return the entity kind and the ids that a write request touches.

    The ids come from the request itself (the path and the body), not from
    the caller, so the target check sees exactly what the server sees.

    Args:
        method: The HTTP method.
        path: The App API path.
        body: The JSON body, if any.

    Returns:
        ``(kind, ids)`` with kind ``"metric"`` or ``"behavior"``, or ``None``
        for a create (a POST to a collection path).

    Raises:
        ProbeRefusedError: If the write has a shape that the script does not
            know. Such a write is never sent.
    """
    entry = _ENTRY_PATH.match(path)
    collection = _COLLECTION_PATH.match(path)
    share = _SHARE_PATH.match(path)
    if collection and method == "POST":
        return None
    if entry and method in ("PATCH", "DELETE"):
        ids = [int(entry.group(2))]
        if body and "id" in body:
            ids.append(int(body["id"]))
        return entry.group(1).rstrip("s"), ids
    if collection and method in ("PATCH", "DELETE") and body is not None:
        key = collection.group(1)
        items = body.get(key)
        if not isinstance(items, list) or set(body) != {key}:
            raise ProbeRefusedError(f"refusing write: unknown body for {path!r}")
        return key.rstrip("s"), [int(item["id"]) for item in items]
    if share and method == "POST":
        ids = [int(share.group(2))]
        if body and "id" in body:
            ids.append(int(body["id"]))
        return share.group(1), ids
    raise ProbeRefusedError(f"refusing write: unknown write {method} {path!r}")


def _assert_own_targets(
    run: ProbeRun, method: str, path: str, body: dict[str, Any] | None
) -> None:
    """Refuse a write that touches an entity that this run did not create.

    Every target id must not be in the start snapshot of the project. It must
    also be an id that this run's POSTs returned, or an unrecorded entity of
    this run: an id that ``sweep_unrecorded`` found in a list with a name
    that starts with this run's prefix. The check reads that name again here.

    Args:
        run: The probe run.
        method: The HTTP method.
        path: The App API path.
        body: The JSON body, if any.

    Raises:
        ProbeRefusedError: If a target id fails the check, or if the write
            touches no id at all.
    """
    targets = write_targets(method, path, body)
    if targets is None:
        return
    kind, ids = targets
    created = set(run.created_metrics if kind == "metric" else run.created_behaviors)
    swept = run.swept_metrics if kind == "metric" else run.swept_behaviors
    start = run.start_metrics if kind == "metric" else run.start_behaviors
    if not ids:
        raise ProbeRefusedError(f"refusing write: no target ids in {method} {path!r}")
    for target in ids:
        swept_name = swept.get(target)
        own = target in created or (
            swept_name is not None and swept_name.startswith(run.prefix)
        )
        if target in start or not own:
            raise ProbeRefusedError(
                f"refusing write: {kind} {target} is not an entity of this run"
            )


def _install_response_hook(run: ProbeRun) -> None:
    """Record the status and body of every HTTP response of the workspace.

    ``app_request`` returns the parsed body only, so an httpx response hook
    keeps the exact status code and body of each response. The hook uses the
    private ``_ensure_client`` accessor, which is acceptable for dev tooling.

    Args:
        run: The probe run whose ``last_status`` and ``last_body`` the hook
            sets.
    """

    def on_response(response: httpx.Response) -> None:
        """Store the status code and the parsed body of one response.

        Args:
            response: The httpx response.
        """
        response.read()
        run.last_status = response.status_code
        try:
            run.last_body = response.json()
        except ValueError:
            run.last_body = response.text

    client = run.ws.api._ensure_client()
    hooks = client.event_hooks
    hooks["response"].append(on_response)
    client.event_hooks = hooks


def call_app(
    run: ProbeRun,
    name: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    note: str = "",
) -> ProbeRecord:
    """Send one App API request and record it.

    Every method other than GET is a write, and goes through the scratch
    check first. A write that is not a create goes through the target check:
    each id that the request touches must be an id that this run created.
    A 2xx POST to ``/metrics`` or ``/behaviors`` adds the returned ids to the
    created lists, so the cleanup deletes them.

    Args:
        run: The probe run.
        name: The probe name (also the fixture key).
        method: The HTTP method.
        path: The App API path, for example ``/projects/{pid}/metrics``.
        body: The JSON body, if any.
        note: A short free-text note for the log.

    Returns:
        The recorded request and response.

    Raises:
        ProbeRefusedError: If a write fails the scratch check or the target
            check. The request is not sent.
    """
    if method != "GET":
        _assert_scratch(run, path)
        _assert_own_targets(run, method, path, body)
    run.last_status = None
    run.last_body = None
    try:
        run.ws.api.app_request(method, path, json_body=body, _raw=True)
    except MixpanelHeadlessError as exc:
        if run.last_status is None:
            run.last_body = f"{type(exc).__name__}: {exc}"
    record = ProbeRecord(
        name=name,
        method=method,
        path=path,
        request_body=body,
        status=run.last_status,
        response_body=run.last_body,
        note=note,
    )
    run.records.append(record)
    _track_created(run, record)
    print(f"  {name}: {method} {path} -> {record.status}", flush=True)
    return record


def _track_created(run: ProbeRun, record: ProbeRecord) -> None:
    """Add the ids of a successful create to the cleanup lists.

    Args:
        run: The probe run.
        record: A recorded request and response.
    """
    if record.method != "POST" or record.status is None or record.status >= 300:
        return
    results = _results(record)
    if record.path.rstrip("/").endswith("/metrics"):
        run.created_metrics.extend(int(k) for k in results)
    elif record.path.rstrip("/").endswith("/behaviors"):
        run.created_behaviors.extend(int(k) for k in results)


def _results(record: ProbeRecord) -> dict[str, Any]:
    """Return the ``results`` map of a recorded response, or an empty map.

    Args:
        record: A recorded request and response.

    Returns:
        The ``results`` map keyed by id.
    """
    body = record.response_body
    if isinstance(body, dict):
        results = body.get("results")
        if isinstance(results, dict):
            return results
    return {}


def _only_result(record: ProbeRecord) -> dict[str, Any]:
    """Return the one entity of a one-entry ``results`` map.

    Args:
        record: A recorded create, get, or update response.

    Returns:
        The entity dict.

    Raises:
        RuntimeError: If the response does not hold exactly one entity.
    """
    results = _results(record)
    if len(results) != 1:
        raise RuntimeError(f"{record.name}: expected one result, got {record.status}")
    return next(iter(results.values()))


def _created_id(record: ProbeRecord) -> int | None:
    """Return the id of a successful create, or ``None`` if it failed.

    A failed create skips only the probes that need its id, so one surprise
    does not stop the rest of the run.

    Args:
        record: A recorded create.

    Returns:
        The new entity id, or ``None``.
    """
    results = _results(record)
    if record.status is None or record.status >= 300 or len(results) != 1:
        return None
    return int(next(iter(results.values()))["id"])


def call_query(
    run: ProbeRun,
    name: str,
    show: list[dict[str, Any]],
    *,
    note: str = "",
) -> ProbeRecord:
    """Run one inline insights query with the given show clauses and record it.

    The params come from ``Workspace.build_params`` of the current library,
    with ``sections.show`` replaced by ``show``.

    Args:
        run: The probe run.
        name: The probe name.
        show: The show clauses to send.
        note: A short free-text note for the log.

    Returns:
        The recorded request and response.
    """
    params = run.ws.build_params(EVENT_A, from_date=QUERY_FROM, to_date=QUERY_TO)
    params["sections"]["show"] = show
    body = {
        "bookmark": params,
        "project_id": int(run.pid),
        "queryLimits": {"limit": 3000},
    }
    run.last_status = None
    run.last_body = None
    try:
        run.ws.api.insights_query(body, inject_workspace_id=False)
    except MixpanelHeadlessError as exc:
        if run.last_status is None:
            run.last_body = f"{type(exc).__name__}: {exc}"
    record = ProbeRecord(
        name=name,
        method="POST",
        path="/api/query/insights",
        request_body={"sections.show": show},
        status=run.last_status,
        response_body=run.last_body,
        note=note,
    )
    run.records.append(record)
    print(f"  {name}: POST /api/query/insights -> {record.status}", flush=True)
    return record


def _series(record: ProbeRecord) -> dict[str, list[Any]]:
    """Return each series of a query response as values ordered by date.

    Args:
        record: A recorded insights query.

    Returns:
        A map from series label to the list of its values, ordered by date.
        Empty when the response has no ``series``.
    """
    body = record.response_body
    if not isinstance(body, dict) or not isinstance(body.get("series"), dict):
        return {}
    out: dict[str, list[Any]] = {}
    for label, points in body["series"].items():
        if isinstance(points, dict):
            out[label] = [points[k] for k in sorted(points)]
        else:
            out[label] = [points]
    return out


def compare(
    run: ProbeRun,
    name: str,
    left: ProbeRecord,
    right: ProbeRecord,
    *,
    pick: Callable[[dict[str, list[Any]]], list[Any] | None] | None = None,
) -> None:
    """Compare the numbers of two query probes and log the result.

    Args:
        run: The probe run.
        name: The comparison name.
        left: The first query probe.
        right: The second query probe.
        pick: Picks the series to compare from a series map. The default
            takes the only series, or ``None`` if there is not exactly one.
    """

    def only(series: dict[str, list[Any]]) -> list[Any] | None:
        """Return the only series of a map.

        Args:
            series: A map from series label to values.

        Returns:
            The values, or ``None`` if the map does not hold one series.
        """
        return next(iter(series.values())) if len(series) == 1 else None

    chooser = pick or only
    left_values = chooser(_series(left))
    right_values = chooser(_series(right))
    entry = {
        "name": name,
        "left": left.name,
        "right": right.name,
        "left_labels": sorted(_series(left)),
        "right_labels": sorted(_series(right)),
        "left_values": left_values,
        "right_values": right_values,
        "equal": left_values is not None and left_values == right_values,
    }
    run.comparisons.append(entry)
    print(f"  compare {name}: equal={entry['equal']}", flush=True)


def _pick_label(fragment: str) -> Callable[[dict[str, list[Any]]], list[Any] | None]:
    """Build a series chooser that takes the one label holding a fragment.

    Args:
        fragment: Text that the wanted series label contains.

    Returns:
        A chooser for ``compare``.
    """

    def pick(series: dict[str, list[Any]]) -> list[Any] | None:
        """Return the values of the one label that holds the fragment.

        Args:
            series: A map from series label to values.

        Returns:
            The values, or ``None`` if not exactly one label matches.
        """
        hits = [v for k, v in series.items() if fragment in k]
        return hits[0] if len(hits) == 1 else None

    return pick


def _step(event: str) -> dict[str, Any]:
    """Return one event step of a behavior, in the web app's stored shape.

    Args:
        event: The event name.

    Returns:
        The step dict.
    """
    return {"type": "event", "name": event, "filters": [], "filtersDeterminer": "all"}


def _library_clause(ws: mp.Workspace, metric: mp.Metric | mp.CohortMetric) -> Any:
    """Return the show clause that the current library writes for a metric.

    Args:
        ws: The workspace.
        metric: An inline metric.

    Returns:
        The first show clause of ``build_params``.
    """
    params = ws.build_params(metric, from_date=QUERY_FROM, to_date=QUERY_TO)
    return params["sections"]["show"][0]


def _definition(clause: dict[str, Any]) -> dict[str, Any]:
    """Return the saved behavior metric definition of a show clause.

    Args:
        clause: A behavior show clause.

    Returns:
        ``{behavior, measurement}`` of the clause.
    """
    return {"behavior": clause["behavior"], "measurement": clause["measurement"]}


def _operand(clause: dict[str, Any]) -> dict[str, Any]:
    """Return a formula operand (a behavior show clause) from a show clause.

    Args:
        clause: A behavior show clause.

    Returns:
        ``{type, behavior, measurement}`` of the clause.
    """
    return {"type": "metric", **_definition(clause)}


def funnel_behavior() -> dict[str, Any]:
    """Return a two-step funnel behavior, in the engine's default shape.

    Returns:
        The behavior dict, without ``name``.
    """
    return {
        "type": "funnel",
        "conversionWindowDuration": 7,
        "conversionWindowUnit": "day",
        "funnelOrder": "loose",
        "aggregateBy": [],
        "exclusions": [],
        "resourceType": "events",
        "behaviors": [_step(EVENT_A), _step(EVENT_B)],
    }


def retention_behavior() -> dict[str, Any]:
    """Return a birth retention behavior, in the engine's default shape.

    Returns:
        The behavior dict, without ``name``.
    """
    return {
        "type": "retention",
        "retentionType": "birth",
        "retentionAlignmentType": "birth",
        "retentionUnit": "day",
        "retentionUnboundedMode": "none",
        "retentionCustomBucketSizes": [],
        "resourceType": "events",
        "behaviors": [_step(EVENT_A), _step(EVENT_C)],
    }


def simple_behavior() -> dict[str, Any]:
    """Return a simple behavior over two events.

    Returns:
        The behavior dict, without ``name``.
    """
    return {
        "type": "simple",
        "resourceType": "events",
        "behaviors": [_step(EVENT_A), _step(EVENT_B)],
    }


FUNNEL_MEASUREMENT: dict[str, Any] = {
    "math": "conversion_rate_unique",
    "cumulative": False,
    "perUserAggregation": None,
    "property": None,
    "segmentMethod": None,
    "stepIndex": None,
}
"""Measurement of the funnel metric probes (the engine's default shape)."""

RETENTION_MEASUREMENT: dict[str, Any] = {
    "math": "retention_rate",
    "property": None,
    "retentionBucketIndex": 1,
}
"""Measurement of the retention metric probes."""


def _list_rows(run: ProbeRun, collection: str) -> dict[int, dict[str, Any]]:
    """List the active rows of ``/metrics`` or ``/behaviors``, keyed by id.

    Args:
        run: The probe run.
        collection: ``"metrics"`` or ``"behaviors"``.

    Returns:
        A map from entity id to the entity dict.
    """
    rows = run.ws.api.app_request("GET", f"/projects/{run.pid}/{collection}")
    return {int(k): v for k, v in rows.items() if isinstance(v, dict)}


def _is_own_row(run: ProbeRun, row: dict[str, Any]) -> bool:
    """Return whether a listed row has this run's name prefix.

    Args:
        run: The probe run.
        row: One entity dict from a list response.

    Returns:
        ``True`` if the row's name starts with this run's prefix.
    """
    name = row.get("name")
    return isinstance(name, str) and name.startswith(run.prefix)


def snapshot_ids(run: ProbeRun) -> tuple[set[int], set[int]]:
    """List the active metric and behavior ids of the project.

    Args:
        run: The probe run.

    Returns:
        ``(metric_ids, behavior_ids)``.
    """
    return set(_list_rows(run, "metrics")), set(_list_rows(run, "behaviors"))


def save_snapshot(run: ProbeRun, path: Path) -> None:
    """Write the start id sets of the project to a JSON file.

    Args:
        run: The probe run, with the start sets filled in.
        path: The snapshot file path.
    """
    snapshot = {
        "project_id": run.pid,
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "prefix": run.prefix,
        "metric_ids": sorted(run.start_metrics),
        "behavior_ids": sorted(run.start_behaviors),
    }
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"  wrote {path}")


def final_check(run: ProbeRun) -> bool:
    """List the project again and check that every entity of this run is gone.

    An entity of this run is a recorded id, a swept id, or a row outside the
    start snapshot whose name starts with this run's prefix. Other users can
    change the shared project during a run, so the check that decides the
    result is on this run's entities only. A difference from the start
    snapshot is reported as information.

    Args:
        run: The probe run.

    Returns:
        ``True`` if no entity of this run is still active.
    """
    metric_rows = _list_rows(run, "metrics")
    behavior_rows = _list_rows(run, "behaviors")
    end_metrics, end_behaviors = set(metric_rows), set(behavior_rows)
    own_metrics = set(run.created_metrics) | set(run.swept_metrics)
    own_behaviors = set(run.created_behaviors) | set(run.swept_behaviors)
    left_metrics = sorted(
        i
        for i, row in metric_rows.items()
        if i in own_metrics or (i not in run.start_metrics and _is_own_row(run, row))
    )
    left_behaviors = sorted(
        i
        for i, row in behavior_rows.items()
        if i in own_behaviors
        or (i not in run.start_behaviors and _is_own_row(run, row))
    )
    print(
        f"project {run.pid}: {len(end_metrics)} metrics, "
        f"{len(end_behaviors)} behaviors at end "
        f"(start {len(run.start_metrics)} / {len(run.start_behaviors)})"
    )
    print(
        f"  created this run: {len(set(run.created_metrics))} metrics, "
        f"{len(set(run.created_behaviors))} behaviors recorded; "
        f"{len(run.swept_metrics)} metrics, {len(run.swept_behaviors)} behaviors "
        f"unrecorded; still active: metrics {left_metrics}, "
        f"behaviors {left_behaviors}"
    )
    if end_metrics != run.start_metrics or end_behaviors != run.start_behaviors:
        print(
            "  note: id sets differ from the start snapshot: "
            f"metrics +{sorted(end_metrics - run.start_metrics)} "
            f"-{sorted(run.start_metrics - end_metrics)}; "
            f"behaviors +{sorted(end_behaviors - run.start_behaviors)} "
            f"-{sorted(run.start_behaviors - end_behaviors)}"
        )
    return not left_metrics and not left_behaviors


def probe_gate(run: ProbeRun) -> ProbeRecord:
    """POST one event metric with math "total" (checks the ``formulas`` saving gate).

    Args:
        run: The probe run.

    Returns:
        The recorded create.
    """
    clause = _library_clause(run.ws, mp.Metric(EVENT_A, math="total"))
    return call_app(
        run,
        "create_metric_event_total",
        "POST",
        f"/projects/{run.pid}/metrics",
        {
            "type": "metric",
            "name": f"{run.prefix}event-total",
            "description": "Scratch metric of an automated API probe.",
            "definition": _definition(clause),
        },
        note="definition is {behavior, measurement} of the library show clause",
    )


def probe_full(run: ProbeRun, *, warehouse: bool) -> None:
    """Run every write, error, and query probe after a successful gate.

    Args:
        run: The probe run.
        warehouse: Also POST a warehouse metric when a source exists.
    """
    pid = run.pid
    metrics_path = f"/projects/{pid}/metrics"
    behaviors_path = f"/projects/{pid}/behaviors"

    event_rec = next(r for r in run.records if r.name == "create_metric_event_total")
    event_metric = _only_result(event_rec)
    event_id = int(event_metric["id"])
    me = event_metric["created_by"]

    call_app(run, "get_metric", "GET", f"{metrics_path}/{event_id}")

    # Metric kinds.
    simple_rec = call_app(
        run,
        "create_metric_simple_two_events",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}simple-two-events",
            "definition": {
                "behavior": {"name": None, **simple_behavior()},
                "measurement": {"math": "unique"},
            },
            "verified": True,
            "owned_by": {"id": me["id"], "name": me["name"], "email": me["email"]},
        },
        note="POST body also sets verified and owned_by",
    )
    simple_id = _created_id(simple_rec)
    funnel_def = {
        "behavior": {"name": None, **funnel_behavior()},
        "measurement": dict(FUNNEL_MEASUREMENT),
    }
    funnel_rec = call_app(
        run,
        "create_metric_funnel",
        "POST",
        metrics_path,
        {"type": "metric", "name": f"{run.prefix}funnel", "definition": funnel_def},
    )
    funnel_id = _created_id(funnel_rec)
    retention_def = {
        "behavior": {"name": None, **retention_behavior()},
        "measurement": dict(RETENTION_MEASUREMENT),
    }
    call_app(
        run,
        "create_metric_retention",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}retention",
            "definition": retention_def,
        },
    )
    cohort = next((c for c in run.ws.cohorts() if (c.count or 0) > 0), None)
    if cohort is not None:
        cohort_clause = _library_clause(run.ws, mp.CohortMetric(cohort.id, cohort.name))
        call_app(
            run,
            "create_metric_cohort",
            "POST",
            metrics_path,
            {
                "type": "metric",
                "name": f"{run.prefix}cohort",
                "definition": _definition(cohort_clause),
            },
            note="definition is {behavior, measurement} of the CohortMetric clause",
        )
    op_a = _operand(_library_clause(run.ws, mp.Metric(EVENT_A, math="total")))
    op_b = _operand(_library_clause(run.ws, mp.Metric(EVENT_B, math="unique")))
    formula_inline_rec = call_app(
        run,
        "create_formula_inline_operands",
        "POST",
        metrics_path,
        {
            "type": "formula",
            "name": f"{run.prefix}formula-inline",
            "definition": {
                "formula": {"definition": "A / B", "referencedMetrics": [op_a, op_b]}
            },
        },
    )
    formula_inline_id = _created_id(formula_inline_rec)
    formula_ids_id: int | None = None
    if simple_id is not None:
        formula_ids_rec = call_app(
            run,
            "create_formula_id_operands",
            "POST",
            metrics_path,
            {
                "type": "formula",
                "name": f"{run.prefix}formula-id-operands",
                "definition": {
                    "formula": {
                        "definition": "A / B",
                        "referencedMetrics": [
                            {"id": event_id, "type": "metric"},
                            {"id": simple_id, "type": "metric"},
                        ],
                    }
                },
            },
        )
        formula_ids_id = _created_id(formula_ids_rec)

    probe_warehouse(run, create=warehouse)

    # Behavior types.
    call_app(
        run,
        "create_behavior_simple",
        "POST",
        behaviors_path,
        {
            "type": "simple",
            "name": f"{run.prefix}behavior-simple",
            "description": "Scratch behavior of an automated API probe.",
            "definition": {"behavior": simple_behavior()},
        },
    )
    funnel_beh_rec = call_app(
        run,
        "create_behavior_funnel",
        "POST",
        behaviors_path,
        {
            "type": "funnel",
            "name": f"{run.prefix}behavior-funnel",
            "definition": {"behavior": funnel_behavior()},
        },
    )
    funnel_beh_id = _created_id(funnel_beh_rec)
    call_app(
        run,
        "create_behavior_retention",
        "POST",
        behaviors_path,
        {
            "type": "retention",
            "name": f"{run.prefix}behavior-retention",
            "definition": {"behavior": retention_behavior()},
        },
    )
    beh_ref_metric_id: int | None = None
    if funnel_beh_id is not None:
        beh_ref_rec = call_app(
            run,
            "create_metric_funnel_behavior_ref",
            "POST",
            metrics_path,
            {
                "type": "metric",
                "name": f"{run.prefix}funnel-behavior-ref",
                "definition": {
                    "behavior": {"type": "funnel", "id": funnel_beh_id},
                    "measurement": {"math": "conversion_rate_unique"},
                },
            },
            note="behavior is a saved-behavior reference with no behaviors key",
        )
        beh_ref_metric_id = _created_id(beh_ref_rec)

    # Error bodies.
    bad_key = _definition(_library_clause(run.ws, mp.Metric(EVENT_A, math="total")))
    bad_key["behavior"]["bogusKey"] = True
    call_app(
        run,
        "error_400_unknown_key",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}bad-key",
            "definition": bad_key,
        },
    )
    bad_math = _definition(_library_clause(run.ws, mp.Metric(EVENT_A, math="total")))
    bad_math["measurement"]["math"] = "not_a_math"
    call_app(
        run,
        "error_400_bad_math",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}bad-math",
            "definition": bad_math,
        },
    )
    call_app(
        run,
        "error_409_duplicate_name",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}event-total",
            "definition": _definition(
                _library_clause(run.ws, mp.Metric(EVENT_A, math="total"))
            ),
        },
        note="same name as create_metric_event_total",
    )
    call_app(
        run,
        "error_global_access_type",
        "POST",
        metrics_path,
        {
            "type": "metric",
            "name": f"{run.prefix}access-off",
            "definition": _definition(
                _library_clause(run.ws, mp.Metric(EVENT_A, math="total"))
            ),
            "global_access_type": "off",
        },
        note='"off" creates no share even if the schema accepts the key',
    )
    call_app(
        run,
        "error_409_duplicate_behavior_name",
        "POST",
        behaviors_path,
        {
            "type": "simple",
            "name": f"{run.prefix}behavior-simple",
            "definition": {"behavior": simple_behavior()},
        },
        note="same name as create_behavior_simple",
    )
    bad_behavior = simple_behavior()
    bad_behavior["bogusKey"] = True
    call_app(
        run,
        "error_400_behavior_unknown_key",
        "POST",
        behaviors_path,
        {
            "type": "simple",
            "name": f"{run.prefix}behavior-bad-key",
            "definition": {"behavior": bad_behavior},
        },
    )

    # Follow-up PATCH after POST.
    call_app(
        run,
        "patch_metric_verified",
        "PATCH",
        f"{metrics_path}/{event_id}",
        {"verified": True},
    )
    call_app(
        run,
        "patch_metric_owned_by",
        "PATCH",
        f"{metrics_path}/{event_id}",
        {"owned_by": {"id": me["id"]}},
    )
    call_app(
        run,
        "patch_metric_unverified",
        "PATCH",
        f"{metrics_path}/{event_id}",
        {"verified": False},
    )
    if funnel_beh_id is not None:
        call_app(
            run,
            "patch_behavior_verified",
            "PATCH",
            f"{behaviors_path}/{funnel_beh_id}",
            {"verified": True},
        )

    # Lists (filtered to this run's ids when written as fixtures).
    call_app(run, "list_metrics", "GET", metrics_path)
    call_app(run, "list_behaviors", "GET", behaviors_path)

    # Query-time behavior.
    inline_total = call_query(run, "query_inline_event_total", [op_a])
    ref_total = call_query(run, "query_ref_event", [{"id": event_id, "type": "metric"}])
    ref_no_type = call_query(run, "query_ref_event_no_type", [{"id": event_id}])
    compare(run, "ref_vs_inline_total", ref_total, inline_total)
    compare(run, "ref_no_type_vs_inline_total", ref_no_type, inline_total)
    ref_override = call_query(
        run,
        "query_ref_event_override_unique",
        [
            {
                "id": event_id,
                "type": "metric",
                "overrides": {"measurement": {"math": "unique"}},
            }
        ],
    )
    inline_unique = call_query(
        run,
        "query_inline_event_unique",
        [_operand(_library_clause(run.ws, mp.Metric(EVENT_A, math="unique")))],
    )
    compare(run, "ref_override_vs_inline_unique", ref_override, inline_unique)
    compare(run, "ref_override_vs_inline_total", ref_override, inline_total)

    formula_inline = call_query(
        run,
        "query_formula_inline_operands",
        [
            {
                "type": "formula",
                "definition": "A / B",
                "referencedMetrics": [op_a, op_b],
                "measurement": {},
                "name": "probe ratio",
            }
        ],
    )
    library_formula_params = run.ws.build_params(
        [
            mp.Metric(EVENT_A, math="total"),
            mp.Metric(EVENT_B, math="unique"),
            mp.Formula("A / B", label="probe ratio"),
        ],
        from_date=QUERY_FROM,
        to_date=QUERY_TO,
    )
    formula_library = call_query(
        run,
        "query_formula_library_form",
        library_formula_params["sections"]["show"],
        note="current library form: two hidden metrics plus a formula clause",
    )
    compare(
        run,
        "formula_inline_operands_vs_library_form",
        formula_inline,
        formula_library,
        pick=_pick_label("probe ratio"),
    )
    call_query(
        run,
        "query_event_funnel_retention",
        [
            op_a,
            {"type": "metric", **funnel_def},
            {"type": "metric", **retention_def},
        ],
    )
    inline_funnel = call_query(
        run, "query_inline_funnel", [{"type": "metric", **funnel_def}]
    )
    if funnel_id is not None:
        ref_funnel = call_query(
            run, "query_ref_funnel_metric", [{"id": funnel_id, "type": "metric"}]
        )
        compare(run, "ref_funnel_vs_inline_funnel", ref_funnel, inline_funnel)
    if funnel_beh_id is not None:
        beh_ref = call_query(
            run,
            "query_behavior_ref_funnel",
            [
                {
                    "type": "metric",
                    "behavior": {"type": "funnel", "id": funnel_beh_id},
                    "measurement": {"math": "conversion_rate_unique"},
                }
            ],
        )
        compare(run, "behavior_ref_vs_inline_funnel", beh_ref, inline_funnel)
    if beh_ref_metric_id is not None:
        beh_ref_metric = call_query(
            run,
            "query_ref_funnel_behavior_ref_metric",
            [{"id": beh_ref_metric_id, "type": "metric"}],
        )
        compare(
            run, "behavior_ref_metric_vs_inline_funnel", beh_ref_metric, inline_funnel
        )
    if formula_inline_id is not None:
        ref_formula_inline = call_query(
            run,
            "query_ref_formula_inline_operands",
            [{"id": formula_inline_id, "type": "formula"}],
        )
        compare(
            run, "ref_formula_vs_inline_formula", ref_formula_inline, formula_inline
        )
    if formula_ids_id is not None:
        call_query(
            run,
            "query_ref_formula_id_operands",
            [{"id": formula_ids_id, "type": "formula"}],
        )

    # Unknown ids, the single DELETE, and the shared-entities route.
    call_app(run, "error_unknown_metric", "GET", f"{metrics_path}/{UNKNOWN_ID}")
    call_app(run, "error_unknown_behavior", "GET", f"{behaviors_path}/{UNKNOWN_ID}")
    call_app(run, "error_single_delete", "DELETE", f"{metrics_path}/{event_id}")
    call_app(
        run,
        "shared_entity_upsert",
        "POST",
        f"/projects/{pid}/shared-entities/metric/{event_id}/upsert",
        {"id": event_id},
        note="no share lists: an upsert that changes nothing",
    )


def probe_warehouse(run: ProbeRun, *, create: bool) -> None:
    """List the warehouse sources, and create one warehouse metric if asked.

    Only the source count is logged, because the sources belong to other
    users of the shared project. The create omits ``aggregation`` and
    ``syncInterval``, to show whether the server stores its defaults. A
    create runs no SQL: the SQL runs only when a query uses the metric, and
    this probe never queries it.

    Args:
        run: The probe run.
        create: Create a warehouse metric when a source exists.
    """
    sources = call_app(
        run,
        "list_warehouse_sources",
        "GET",
        f"/projects/{run.pid}/warehouse-sources/sources",
    )
    body = sources.response_body
    source_list = body.get("results") if isinstance(body, dict) else None
    sources.response_body = {
        "status": sources.status,
        "source_count": len(source_list) if isinstance(source_list, list) else None,
    }
    if not create or not isinstance(source_list, list) or not source_list:
        return
    record = call_app(
        run,
        "create_metric_warehouse",
        "POST",
        f"/projects/{run.pid}/metrics",
        {
            "type": "warehouse",
            "name": f"{run.prefix}warehouse",
            "warehouse_source_id": int(source_list[0]["id"]),
            "definition": {
                "query": "SELECT 1 AS value",
                "metricType": "numeric",
                "valueColumn": "value",
            },
        },
        note="definition omits aggregation and syncInterval",
    )
    warehouse_id = _created_id(record)
    if warehouse_id is not None:
        call_app(
            run,
            "get_metric_warehouse",
            "GET",
            f"/projects/{run.pid}/metrics/{warehouse_id}",
        )


def cleanup(run: ProbeRun) -> None:
    """Delete every entity that this run created, through the bulk routes.

    Sends only ids that this run's POSTs returned. Also records a second
    bulk DELETE of an already deleted metric, and a GET of a deleted metric.

    Args:
        run: The probe run.
    """
    pid = run.pid
    metric_ids = sorted(set(run.created_metrics))
    behavior_ids = sorted(set(run.created_behaviors))
    if metric_ids:
        call_app(
            run,
            "delete_metrics_bulk",
            "DELETE",
            f"/projects/{pid}/metrics",
            {"metrics": [{"id": i} for i in metric_ids]},
        )
        call_app(
            run,
            "delete_metrics_bulk_again",
            "DELETE",
            f"/projects/{pid}/metrics",
            {"metrics": [{"id": metric_ids[0]}]},
            note="a metric that this run already deleted",
        )
        call_app(
            run,
            "error_deleted_metric",
            "GET",
            f"/projects/{pid}/metrics/{metric_ids[0]}",
        )
    if behavior_ids:
        call_app(
            run,
            "delete_behaviors_bulk",
            "DELETE",
            f"/projects/{pid}/behaviors",
            {"behaviors": [{"id": i} for i in behavior_ids]},
        )


def sweep_unrecorded(run: ProbeRun) -> tuple[list[int], list[int]]:
    """Delete the entities of this run whose create was never recorded.

    A create can succeed on the server and still leave no id in the created
    lists, for example when the POST times out or the response has no usable
    ``results`` map. This function lists metrics and behaviors, and deletes
    each row whose name starts with this run's prefix, whose id is not in the
    start snapshot, and whose id is not recorded. The prefix holds the run
    timestamp and a random part, so such a row belongs to this run. The
    delete goes through the target check, which reads the prefix again.

    Args:
        run: The probe run.

    Returns:
        ``(metric_ids, behavior_ids)`` of the unrecorded rows found.
    """
    found: dict[str, list[int]] = {}
    for collection in ("metrics", "behaviors"):
        is_metric = collection == "metrics"
        created = set(run.created_metrics if is_metric else run.created_behaviors)
        start = run.start_metrics if is_metric else run.start_behaviors
        swept = run.swept_metrics if is_metric else run.swept_behaviors
        new_ids: list[int] = []
        for entity_id, row in _list_rows(run, collection).items():
            if entity_id in start or entity_id in created or entity_id in swept:
                continue
            if _is_own_row(run, row):
                swept[entity_id] = str(row["name"])
                new_ids.append(entity_id)
        new_ids.sort()
        found[collection] = new_ids
        if new_ids:
            print(f"  unrecorded {collection} of this run: {new_ids}", flush=True)
            call_app(
                run,
                f"delete_unrecorded_{collection}",
                "DELETE",
                f"/projects/{run.pid}/{collection}",
                {collection: [{"id": i} for i in new_ids]},
                note="rows with this run's prefix that no create response recorded",
            )
    return found["metrics"], found["behaviors"]


def _fake_user_id(real: int, user_ids: dict[int, int]) -> int:
    """Map a real user id to a stable fake id.

    Args:
        real: The real user id.
        user_ids: The map of ids seen so far (updated in place).

    Returns:
        The fake id.
    """
    if real not in user_ids:
        user_ids[real] = FAKE_USER_ID_BASE + len(user_ids)
    return user_ids[real]


def redact(value: Any, user_ids: dict[int, int]) -> Any:
    """Replace emails, person names, and user ids in a JSON value.

    A dict with an ``email`` key, or the value of a user key (``created_by``,
    ``owned_by``, ``last_verified_by``, ``owner``), is a user object. Its
    ``email``, ``name``, and ``id`` are replaced. Every ``email`` value and
    every string in ``contacts`` becomes ``user@example.com``. Keys and
    structure stay the same.

    Args:
        value: A parsed JSON value.
        user_ids: The real-to-fake user id map (updated in place).

    Returns:
        The redacted copy.
    """
    if isinstance(value, list):
        return [redact(v, user_ids) for v in value]
    if not isinstance(value, dict):
        return value
    is_user = "email" in value
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == "email" and isinstance(item, str):
            out[key] = REDACTED_EMAIL
        elif is_user and key == "name" and isinstance(item, str):
            out[key] = REDACTED_NAME
        elif is_user and key == "id" and isinstance(item, int):
            out[key] = _fake_user_id(item, user_ids)
        elif key in USER_KEYS and isinstance(item, dict) and "email" not in item:
            # A user reference without an email (a PATCH ``owned_by``); a user
            # dict with an email takes the ``is_user`` path when it recurses.
            user = dict(item)
            if isinstance(user.get("id"), int):
                user["id"] = _fake_user_id(user["id"], user_ids)
            out[key] = redact(user, user_ids)
        elif key == "contacts" and isinstance(item, list):
            out[key] = [REDACTED_EMAIL if isinstance(x, str) else x for x in item]
        else:
            out[key] = redact(item, user_ids)
    return out


def _filter_results(body: Any, keep: Iterable[int]) -> Any:
    """Keep only the given ids in the ``results`` map of a list response.

    The project is shared, so a list fixture keeps only this run's entities.
    The envelope keys stay the same.

    Args:
        body: A list response body.
        keep: The ids to keep.

    Returns:
        The filtered copy.
    """
    if not isinstance(body, dict) or not isinstance(body.get("results"), dict):
        return body
    wanted = {str(i) for i in keep}
    return {
        **body,
        "results": {k: v for k, v in body["results"].items() if k in wanted},
    }


def _own_body(run: ProbeRun, record: ProbeRecord) -> Any:
    """Return a response body with list results cut to this run's entities.

    Args:
        run: The probe run.
        record: A recorded request and response.

    Returns:
        The body. A metric or behavior list keeps only the ids that this
        run created; other bodies are returned as they are.
    """
    if record.name == "list_metrics":
        return _filter_results(record.response_body, run.created_metrics)
    if record.name == "list_behaviors":
        return _filter_results(record.response_body, run.created_behaviors)
    return record.response_body


FIXTURES: dict[str, str] = {
    "create_metric_event_total": "create_metric.json",
    "get_metric": "get_metric.json",
    "create_metric_simple_two_events": "create_metric_post_drops_verified_owner.json",
    "create_formula_id_operands": "create_formula_id_operands.json",
    "create_behavior_funnel": "create_behavior.json",
    "patch_metric_verified": "patch_metric_verified.json",
    "patch_metric_owned_by": "patch_metric_owned_by.json",
    "patch_metric_unverified": "patch_metric_unverified.json",
    "patch_behavior_verified": "patch_behavior_verified.json",
    "list_metrics": "list_metrics.json",
    "list_behaviors": "list_behaviors.json",
    "error_400_unknown_key": "error_{status}_unknown_key.json",
    "error_400_bad_math": "error_{status}_bad_math.json",
    "error_409_duplicate_name": "error_{status}_duplicate_name.json",
    "error_global_access_type": "error_{status}_global_access_type.json",
    "error_409_duplicate_behavior_name": "error_{status}_duplicate_behavior_name.json",
    "error_400_behavior_unknown_key": "error_{status}_behavior_unknown_key.json",
    "error_unknown_metric": "error_{status}_unknown_metric.json",
    "error_unknown_behavior": "error_{status}_unknown_behavior.json",
    "error_single_delete": "error_{status}_single_delete.json",
    "error_deleted_metric": "error_{status}_deleted_metric.json",
    "delete_metrics_bulk": "delete_metrics_bulk.json",
    "delete_behaviors_bulk": "delete_behaviors_bulk.json",
    "shared_entity_upsert": "shared_entity_upsert.json",
    "query_ref_event": "query_insights_metric_reference.json",
    "create_metric_warehouse": "create_metric_warehouse.json",
}
"""Probe name to fixture file name. ``{status}`` takes the recorded status."""


def write_outputs(
    run: ProbeRun,
    out_dir: Path | None,
    log_path: Path,
    *,
    only: set[str] | None = None,
) -> None:
    """Write the redacted fixtures and the redacted probe log.

    Error fixtures are written only for 4xx and 5xx responses, so that an
    unexpected success never lands under an ``error_`` name.

    Args:
        run: The probe run.
        out_dir: The fixture directory, or ``None`` to write the log only.
        log_path: The log file path.
        only: If set, write only the fixtures of these probe names.
    """
    user_ids: dict[int, int] = {}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        by_name = {r.name: r for r in run.records}
        for name, file_name in FIXTURES.items():
            if only is not None and name not in only:
                continue
            record = by_name.get(name)
            if record is None or record.status is None:
                continue
            if name.startswith("error_") and record.status < 400:
                continue
            target = out_dir / file_name.format(status=record.status)
            body = redact(_own_body(run, record), user_ids)
            target.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"  wrote {target}")

    log = {
        "prefix": run.prefix,
        "project_id": run.pid,
        "records": [
            redact({**asdict(r), "response_body": _own_body(run, r)}, user_ids)
            for r in run.records
        ],
        "comparisons": run.comparisons,
    }
    log_path.write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {log_path}")


def time_list() -> int:
    """Time one read-only GET of the metric list on the ``MP_LIVE_ACCOUNT`` account.

    Prints the project, the metric count, and the seconds. Saves nothing.

    Returns:
        The process exit code: 0 on success, 1 when ``MP_LIVE_ACCOUNT`` is unset.
    """
    try:
        account = _live_account()
    except ProbeRefusedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ws = mp.Workspace(account=account)
    try:
        pid = ws.api.project_id
        start = time.monotonic()
        metrics = ws.api.app_request("GET", f"/projects/{pid}/metrics")
        seconds = time.monotonic() - start
        print(f"project={pid} metrics={len(metrics)} seconds={seconds:.2f}")
    finally:
        ws.close()
    return 0


def main() -> int:
    """CLI entry point.

    Returns:
        The process exit code: 0 on success, 1 when a setting is missing or a
        check fails, 2 when the ``formulas`` saving gate (a 403) refuses the
        first create.
    """
    parser = argparse.ArgumentParser(
        description="Probe the saved metrics and saved behaviors App API."
    )
    parser.add_argument(
        "--gate-only",
        action="store_true",
        help="Send only the first create (the saving-gate check), then delete it.",
    )
    parser.add_argument(
        "--time-list",
        action="store_true",
        help="Time one read-only metric list (needs only MP_LIVE_ACCOUNT), then exit.",
    )
    parser.add_argument(
        "--warehouse",
        action="store_true",
        help="Also create a warehouse metric when the project has a source.",
    )
    parser.add_argument(
        "--warehouse-only",
        action="store_true",
        help="Create only a warehouse metric (after the gate), then delete both.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Fixture directory (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(tempfile.gettempdir()) / "probe_saved_metrics_log.json",
        help="Redacted probe log path (default: in the temp directory).",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(tempfile.gettempdir()) / "probe_saved_metrics_snapshot.json",
        help="Start snapshot of the project ids (default: in the temp directory).",
    )
    args = parser.parse_args()

    if args.time_list:
        return time_list()

    try:
        target = scratch_target()
    except ProbeRefusedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ws = mp.Workspace(account=target.account, project=target.project_id)
    run = ProbeRun(ws=ws, prefix=_run_prefix(), target=target)
    exit_code = 0
    try:
        if run.pid != target.project_id or ws.account.name != target.account:
            raise ProbeRefusedError(
                f"refusing to run: account {ws.account.name!r}, project {run.pid}"
            )
        _install_response_hook(run)
        run.start_metrics, run.start_behaviors = snapshot_ids(run)
        save_snapshot(run, args.snapshot)
        print(
            f"project {run.pid}: {len(run.start_metrics)} metrics, "
            f"{len(run.start_behaviors)} behaviors at start; prefix {run.prefix}"
        )
        try:
            gate = probe_gate(run)
            if gate.status == 403:
                print(
                    "the formulas saving gate refused the first create; no further writes"
                )
                exit_code = 2
            elif gate.status is None or gate.status >= 300:
                print(f"first create failed with {gate.status}; no further writes")
                exit_code = 1
            elif args.warehouse_only:
                probe_warehouse(run, create=True)
            elif not args.gate_only:
                probe_full(run, warehouse=args.warehouse)
        finally:
            try:
                cleanup(run)
            finally:
                sweep_unrecorded(run)
            if not final_check(run):
                exit_code = 1
            write_outputs(
                run,
                None if args.gate_only else args.out,
                args.log,
                only={"create_metric_warehouse"} if args.warehouse_only else None,
            )
    finally:
        ws.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
