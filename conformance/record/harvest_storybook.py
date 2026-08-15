"""Storybook mock harvester — parse-kind vectors from analytics fixtures.

Implements user ruling E1 (``context/phase1/design/escalation-resolutions.md``,
APPROVED with scrubbing) over design D3.1: reads the READ-ONLY analytics
storybook mock tree (``iron/.storybook/mocks/api/``, 81 files), unwraps the
9 ``{body, init}`` fetch-mock wrapper files, SCRUBS internal identifiers
(demo project/workspace ids, the 5 employee emails, creator ids/names) to
synthetic values, routes each body to the library entry point whose
response it mocks, replays the call through the SAME transport/target
machinery the corpus runner uses, and emits ``kind: "parse"`` vectors with
``origin: "authored"`` under ``conformance/vectors/authored/parse/storybook/``.

Bodies with no sensible entry point (the ``query/metrics`` timeseries API
is not implemented in ``mixpanel_headless``) are skipped with a logged
reason, never forced. Provenance: each bundle's ``$bundle`` header carries
a ``sources`` map naming the analytics-relative source path per vector.

Usage:
    ```bash
    uv run python -m conformance.record.harvest_storybook \
        --source /path/to/analytics/iron/.storybook/mocks/api \
        --out conformance/vectors/authored/parse/storybook
    ```
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from conformance.record.emit import _encode_error
from conformance.record.registry import REGISTRY_BY_API
from conformance.runner.execute import (
    _encode_result,
    _execute_wire_call,
    _isolated_home,
    _ReplayContext,
    _serialize_actual_request,
)
from conformance.runner.transport import VectorTransport

DEFAULT_SOURCE = Path(
    "/Users/jaredmcfarland/Developer/analytics/iron/.storybook/mocks/api"
)
"""The read-only analytics storybook mock tree (recon parse-fixtures §6)."""

DEFAULT_OUT = (
    Path(__file__).resolve().parents[1] / "vectors" / "authored" / "parse" / "storybook"
)
"""Where the emitted bundles land (ruling E1 mandated location)."""

_SCHEMA_VERSION = "1.0"
"""Vector schema version stamped on every emitted vector."""

_SCRUB_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Employee emails (ruling E1: the 5 identities observed by recon).
    (re.compile(r"alix\.becker@mixpanel\.com", re.IGNORECASE), "user1@example.com"),
    (re.compile(r"areeb\.iqbal@mixpanel\.com", re.IGNORECASE), "user2@example.com"),
    (re.compile(r"mack\.duan@mixpanel\.com", re.IGNORECASE), "user3@example.com"),
    (re.compile(r"pablo\.fierro@mixpanel\.com", re.IGNORECASE), "user4@example.com"),
    (re.compile(r"test@mixpanel\.com", re.IGNORECASE), "user5@example.com"),
    # Creator/modifier display names — longest variant first so partial
    # forms never fire inside already-replaced text.
    (re.compile(r"Alix Becker", re.IGNORECASE), "User One"),
    (re.compile(r"Alix B\.", re.IGNORECASE), "User O."),
    (re.compile(r"\bAlix\b", re.IGNORECASE), "UserOne"),
    (re.compile(r"\bBecker\b", re.IGNORECASE), "One"),
    (re.compile(r"Iqbal, Areeb", re.IGNORECASE), "Two, User"),
    (re.compile(r"Iqbal, A\.", re.IGNORECASE), "Two, U."),
    (re.compile(r"\bAreeb\b", re.IGNORECASE), "UserTwo"),
    (re.compile(r"\bIqbal\b", re.IGNORECASE), "Two"),
    (re.compile(r"Duan, Mack", re.IGNORECASE), "Three, User"),
    (re.compile(r"Duan, M\.", re.IGNORECASE), "Three, U."),
    (re.compile(r"\bMack\b", re.IGNORECASE), "UserThree"),
    (re.compile(r"\bDuan\b", re.IGNORECASE), "Three"),
    (re.compile(r"\bPablo\b", re.IGNORECASE), "UserFour"),
    (re.compile(r"\bFierro\b", re.IGNORECASE), "Four"),
    # Demo project/workspace ids → the synthetic ids the authored corpus
    # already uses (12345 / 67890, phase008 convention). Digit-boundary
    # lookarounds keep longer numbers containing these as substrings safe.
    (re.compile(r"(?<!\d)3018488(?!\d)"), "12345"),
    (re.compile(r"(?<!\d)3536632(?!\d)"), "67890"),
    (re.compile(r"(?<!\d)2855068(?!\d)"), "12345"),
    (re.compile(r"(?<!\d)3387988(?!\d)"), "67890"),
    # Creator / last_modified_by numeric user ids.
    (re.compile(r"(?<!\d)766035(?!\d)"), "90001"),
    (re.compile(r"(?<!\d)1430181(?!\d)"), "90002"),
    (re.compile(r"(?<!\d)3023601(?!\d)"), "90003"),
    (re.compile(r"(?<!\d)5035079(?!\d)"), "90004"),
)
"""Ordered scrub table: emails, then name variants longest-first, then ids."""

_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"@mixpanel\.com", re.IGNORECASE),
    re.compile(r"\balix\b", re.IGNORECASE),
    re.compile(r"\bbecker\b", re.IGNORECASE),
    re.compile(r"\bareeb\b", re.IGNORECASE),
    re.compile(r"\biqbal\b", re.IGNORECASE),
    re.compile(r"\bmack\b", re.IGNORECASE),
    re.compile(r"\bduan\b", re.IGNORECASE),
    re.compile(r"\bpablo\b", re.IGNORECASE),
    re.compile(r"\bfierro\b", re.IGNORECASE),
    re.compile(r"(?<!\d)3018488(?!\d)"),
    re.compile(r"(?<!\d)3536632(?!\d)"),
    re.compile(r"(?<!\d)2855068(?!\d)"),
    re.compile(r"(?<!\d)3387988(?!\d)"),
    re.compile(r"(?<!\d)766035(?!\d)"),
    re.compile(r"(?<!\d)1430181(?!\d)"),
    re.compile(r"(?<!\d)3023601(?!\d)"),
    re.compile(r"(?<!\d)5035079(?!\d)"),
    re.compile(r'"(?:project_id|workspace_id)"\s*:\s*"?\d{7,}'),
    re.compile(r"(?:project_id|workspace_id)=\d{7,}"),
)
"""Residue detectors for the post-scrub verification pass (ruling E1)."""

_QUERY_SESSION: dict[str, Any] = {
    "type": "service_account",
    "region": "us",
    "project_id": "12345",
    "username": "test_user",
    "secret": "test_secret",
}
"""Synthetic query-API session (matches the phase008 authored convention)."""

_APP_SESSION: dict[str, Any] = {**_QUERY_SESSION, "workspace_id": 67890}
"""Synthetic App API session — workspace-scoped so ``maybe_scoped_path``
builds ``/workspaces/67890/...`` paths, matching the scrubbed body ids."""


class HarvestError(Exception):
    """Raised when the harvest cannot produce a trustworthy corpus.

    Covers a missing source tree, an unreadable mock file, scrub residue
    surviving into emitted text, and duplicate vector ids — every case is
    a stop-the-world bug, never something to paper over.
    """


@dataclass(frozen=True)
class HarvestRoute:
    """Routing decision for one mock file (design D3.1).

    Attributes:
        api: Dotted library entry point whose response the body mocks.
        input_kwargs: ``call.input`` keyword arguments for the entry point.
        session: Encoded ``call.session`` for the replay client.
        bundle: Output bundle stem (one bundle per source directory group).
    """

    api: str
    input_kwargs: dict[str, Any]
    session: dict[str, Any]
    bundle: str


@dataclass(frozen=True)
class HarvestReport:
    """Outcome summary of one harvest run.

    Attributes:
        emitted: Number of vectors written across all bundles.
        skipped: ``(source-relative path, reason)`` pairs for every file
            deliberately not harvested.
        bundles: Written bundle paths.
    """

    emitted: int
    skipped: list[tuple[str, str]] = field(default_factory=list)
    bundles: list[Path] = field(default_factory=list)


def unwrap_mock(payload: Any) -> tuple[Any, int]:
    """Unwrap a storybook ``{body, init}`` fetch-mock wrapper (D3.1).

    9 of the 81 mock files wrap the API body in a fetch-mock envelope
    carrying the HTTP status; serving the wrapper itself would poison the
    parse vector (recon ``copy_concerns_flags``). Anything that is not
    EXACTLY the wrapper shape passes through untouched as a 200 body.

    Args:
        payload: The decoded JSON mock file content.

    Returns:
        ``(body, status)`` — the response body to serve and its HTTP
        status code (200 for non-wrapper files).
    """
    if (
        isinstance(payload, dict)
        and "body" in payload
        and "init" in payload
        and set(payload) <= {"body", "init"}
    ):
        init = payload["init"]
        status = int(init.get("status", 200)) if isinstance(init, dict) else 200
        return payload["body"], status
    return payload, 200


def scrub_text(text: str) -> str:
    """Re-key every internal identifier in one pass over JSON text.

    Applies the ordered ruling-E1 scrub table: employee emails →
    ``userN@example.com``, creator names → synthetic ``User One``-style
    names, demo project/workspace ids → ``12345``/``67890``, creator ids →
    ``9000N``.

    Args:
        text: Serialized JSON to scrub.

    Returns:
        The scrubbed text.
    """
    for pattern, replacement in _SCRUB_RULES:
        text = pattern.sub(replacement, text)
    return text


def verify_scrub_clean(text: str) -> list[str]:
    """Report any internal-identifier residue in emitted text (ruling E1).

    Args:
        text: The text to verify (typically a whole emitted bundle).

    Returns:
        The patterns that still match, as strings; empty when clean.
    """
    return [pattern.pattern for pattern in _FORBIDDEN_PATTERNS if pattern.search(text)]


def _trailing_int(stem: str, prefix: str) -> int | None:
    """Extract the numeric id from a mock filename stem.

    Args:
        stem: The filename without extension (e.g. ``bookmark_60327233_exclude``).
        prefix: Required stem prefix (``""``, ``board_``, or ``bookmark_``).

    Returns:
        The first integer after the prefix, or None when the stem does not
        match ``<prefix><digits>[_variant...]``.
    """
    match = re.fullmatch(re.escape(prefix) + r"(\d+)(?:_.*)?", stem)
    return int(match.group(1)) if match else None


def route_for(rel: PurePosixPath) -> HarvestRoute | None:
    """Map one source-relative mock path to its library entry point.

    Routing (recon parse-fixtures inventory × ``conformance/vectors/api-index.json``):

    - ``app/bookmarks/{id}.json`` → ``workspace.get_bookmark`` (App API
      single-bookmark GET).
    - ``app/boards/board_{id}.json`` → ``workspace.get_dashboard``.
    - ``query/insights/bookmark_{id}[_variant].json`` →
      ``workspace.query_saved_report`` (GET ``/api/query/insights``).
    - ``query/arb_funnels/bookmark_{id}[_variant].json`` →
      ``workspace.query_saved_flows`` (GET ``/api/query/arb_funnels``).
    - ``query/metrics/*`` → None: the metrics timeseries API has no
      ``mixpanel_headless`` entry point (skipped, never forced).

    Args:
        rel: Mock path relative to the source root.

    Returns:
        The route, or None when no sensible entry point exists.
    """
    group = str(rel.parent)
    stem = rel.stem
    if group == "app/bookmarks":
        bookmark_id = _trailing_int(stem, "")
        if bookmark_id is not None:
            return HarvestRoute(
                api="workspace.get_bookmark",
                input_kwargs={"bookmark_id": bookmark_id},
                session=dict(_APP_SESSION),
                bundle="bookmarks",
            )
    if group == "app/boards":
        dashboard_id = _trailing_int(stem, "board_")
        if dashboard_id is not None:
            return HarvestRoute(
                api="workspace.get_dashboard",
                input_kwargs={"dashboard_id": dashboard_id},
                session=dict(_APP_SESSION),
                bundle="boards",
            )
    if group == "query/insights":
        bookmark_id = _trailing_int(stem, "bookmark_")
        if bookmark_id is not None:
            return HarvestRoute(
                api="workspace.query_saved_report",
                input_kwargs={"bookmark_id": bookmark_id},
                session=dict(_QUERY_SESSION),
                bundle="insights",
            )
    if group == "query/arb_funnels":
        bookmark_id = _trailing_int(stem, "bookmark_")
        if bookmark_id is not None:
            return HarvestRoute(
                api="workspace.query_saved_flows",
                input_kwargs={"bookmark_id": bookmark_id},
                session=dict(_QUERY_SESSION),
                bundle="arb_funnels",
            )
    return None


def _vector_id(route: HarvestRoute, rel: PurePosixPath) -> str:
    """Build the deterministic vector id for one harvested file.

    Args:
        route: The file's routing decision.
        rel: The source-relative mock path.

    Returns:
        ``parse/<api>/authored-storybook-<slug>`` with the slug derived
        from the full relative path (unique per source file).
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(rel.with_suffix("")).lower()).strip("-")
    return f"parse/{route.api}/authored-storybook-{slug}"


def _replay(
    route: HarvestRoute, body: Any, status: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the routed call against the scrubbed body and record it.

    Uses the corpus runner's own replay machinery (``VectorTransport`` +
    ``_execute_wire_call``) so the emitted expectation can never disagree
    with what the runner reproduces.

    Args:
        route: The file's routing decision.
        body: The scrubbed response body to serve.
        status: The HTTP status to serve it with.

    Returns:
        ``(interaction, expectation)`` — the recorded request/response
        pair and the ``expect`` fragment (``{"result": ...}`` or
        ``{"error": ...}``).

    Raises:
        HarvestError: When the call raises an exception the corpus cannot
            encode structurally (no coded library error), when it makes no
            request at all, or when its traffic exceeds one interaction.
    """
    interaction: dict[str, Any] = {
        "request": {"method": "GET", "path": "/harvest-placeholder"},
        "response": {
            "status": status,
            "headers": {"content-type": "application/json"},
            "body": body,
        },
    }
    transport = VectorTransport([interaction])
    context = _ReplayContext(
        transport=transport,
        interactions=[interaction],
        session_encoded=route.session,
        workspace_session_encoded=None,
        client_options=None,
    )
    raised: BaseException | None = None
    result: Any = None
    with _isolated_home():
        try:
            result = _execute_wire_call(
                context, route.api, route.input_kwargs, measured=True
            )
        except Exception as exc:  # noqa: BLE001 - encoded structurally below
            raised = exc
    if transport.extra_requests or transport.unconsumed_indexes():
        raise HarvestError(
            f"{route.api}: replay traffic did not consume exactly the one "
            f"served interaction (extra={len(transport.extra_requests)}, "
            f"unconsumed={transport.unconsumed_indexes()})"
        )
    expectation: dict[str, Any]
    if raised is not None:
        encoded_error = _encode_error(raised)
        if encoded_error is None:
            raise HarvestError(
                f"{route.api}: raised unencodable {type(raised).__name__}: {raised}"
            )
        expectation = {"error": encoded_error}
    else:
        expectation = {"result": _encode_result(REGISTRY_BY_API.get(route.api), result)}
    served = transport.pairs
    interaction["request"] = _serialize_actual_request(served[0][1])
    return interaction, expectation


def _harvest_file(
    route: HarvestRoute, rel: PurePosixPath, payload: Any
) -> dict[str, Any]:
    """Turn one mock file into a parse vector (unwrap → scrub → replay).

    Args:
        route: The file's routing decision.
        rel: The source-relative mock path (provenance + id slug).
        payload: The decoded JSON file content.

    Returns:
        The complete vector object, schema-shaped and scrub-clean.

    Raises:
        HarvestError: If scrub residue survives in the vector, or the
            replay fails (propagated from :func:`_replay`).
    """
    body, status = unwrap_mock(payload)
    scrubbed = json.loads(scrub_text(json.dumps(body, ensure_ascii=False)))
    interaction, expectation = _replay(route, scrubbed, status)
    vector = {
        "schema_version": _SCHEMA_VERSION,
        "id": _vector_id(route, rel),
        "origin": "authored",
        "capability": "parse",
        "kind": "parse",
        "call": {
            "api": route.api,
            "input": route.input_kwargs,
            "session": route.session,
        },
        "expect": {"interactions": [interaction], **expectation},
    }
    residue = verify_scrub_clean(json.dumps(vector, ensure_ascii=False))
    if residue:
        raise HarvestError(f"{rel}: scrub residue in emitted vector: {residue}")
    return vector


def harvest(source_root: Path, out_dir: Path) -> HarvestReport:
    """Harvest the whole mock tree into per-group JSONL bundles.

    Args:
        source_root: The analytics storybook mock root (read-only).
        out_dir: Output directory for the emitted bundles.

    Returns:
        The emitted/skipped report.

    Raises:
        HarvestError: On a missing source tree, unreadable mock file,
            duplicate vector id, replay failure, or scrub residue.
    """
    if not source_root.is_dir():
        raise HarvestError(f"source root {source_root} is not a directory")
    by_bundle: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    skipped: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for path in sorted(source_root.rglob("*.json")):
        rel = PurePosixPath(path.relative_to(source_root).as_posix())
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HarvestError(f"{rel}: unreadable JSON: {exc}") from exc
        route = route_for(rel)
        if route is None:
            skipped.append(
                (str(rel), "no library entry point mocks this response shape")
            )
            continue
        vector = _harvest_file(route, rel, payload)
        vector_id = str(vector["id"])
        if vector_id in seen_ids:
            raise HarvestError(f"duplicate vector id {vector_id!r} from {rel}")
        seen_ids.add(vector_id)
        by_bundle.setdefault(route.bundle, []).append((vector_id, str(rel), vector))
    out_dir.mkdir(parents=True, exist_ok=True)
    emitted = 0
    bundles: list[Path] = []
    for bundle_name in sorted(by_bundle):
        entries = by_bundle[bundle_name]
        bundle_path = out_dir / f"{bundle_name}.jsonl"
        header = {
            "$bundle": {
                "count": len(entries),
                "generator": "conformance/record/harvest_storybook.py",
                "provenance": (
                    "Scrubbed copies of analytics storybook mocks "
                    "(iron/.storybook/mocks/api), user ruling E1 "
                    "(escalation-resolutions.md): internal project/"
                    "workspace ids, employee emails, and creator "
                    "ids/names re-keyed to synthetic values."
                ),
                "source_root": "analytics/iron/.storybook/mocks/api",
                "sources": {vector_id: source for vector_id, source, _ in entries},
            }
        }
        lines = [json.dumps(header, sort_keys=True, ensure_ascii=False)]
        lines.extend(
            json.dumps(vector, sort_keys=True, ensure_ascii=False)
            for _, _, vector in entries
        )
        text = "\n".join(lines) + "\n"
        residue = verify_scrub_clean(text)
        if residue:
            raise HarvestError(
                f"{bundle_path.name}: scrub residue in bundle text: {residue}"
            )
        bundle_path.write_text(text, encoding="utf-8")
        bundles.append(bundle_path)
        emitted += len(entries)
    return HarvestReport(emitted=emitted, skipped=skipped, bundles=bundles)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: harvest, report emitted/skipped, exit 0 on success.

    Args:
        argv: Argument vector (None → ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success; 1 on any harvest error).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="analytics storybook mock root (read-only)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="output directory for the emitted JSONL bundles",
    )
    args = parser.parse_args(argv)
    try:
        report = harvest(args.source, args.out)
    except HarvestError as exc:
        print(f"[harvest_storybook] ERROR: {exc}", file=sys.stderr)
        return 1
    for bundle in report.bundles:
        print(f"[harvest_storybook] wrote {bundle}")
    print(f"[harvest_storybook] emitted={report.emitted} skipped={len(report.skipped)}")
    for source, reason in report.skipped:
        print(f"[harvest_storybook]   skipped {source}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
