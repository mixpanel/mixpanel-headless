"""Generate the authored built-in help vectors.

Emits ``conformance/vectors/authored/help/reference.jsonl``: authored
vectors for the pure layer of the built-in help (``help.*`` registry
adapters in ``help_adapters.py``) — query grammar, tokens and hints,
domain matching, suggestions, tiered search over a supplied index, the
three renderers, the miss rendering, and the two error types. Every
``expect`` value is computed by a call to the registered adapter, so the
frozen outputs come from the library and are never typed by hand.

The render inputs are real ``reference.describe()`` / ``reference.search()``
outputs, frozen in ``help_entries.json`` next to this script so that an
ordinary docstring edit does not change the bundle; only a renderer change
does. Refresh them deliberately with ``--refresh-entries`` (then regenerate
the bundle in the same change).

Usage:
    ```bash
    uv run python -m conformance.record.gen_help_vectors \\
        --commit <40-hex SHA on main>
    # write elsewhere (e.g. to test a port before the re-pin):
    uv run python -m conformance.record.gen_help_vectors \\
        --commit <SHA> --out /tmp/help-vectors/reference.jsonl
    # re-capture the frozen describe()/search() inputs:
    uv run python -m conformance.record.gen_help_vectors --refresh-entries
    ```

The stamp must be the main commit whose ``src/`` holds the help code: the
squash SHA of the library pull request, not a branch SHA. The
stamp-provenance guard (``check_stamps.py``) rejects a new authored bundle
whose stamp is not reachable from main.

Deterministic: a re-run with the same stamp writes the same bytes.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from conformance.record import help_adapters

OUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "vectors"
    / "authored"
    / "help"
    / "reference.jsonl"
)

SOURCE_FILE = "conformance/vectors/authored/help/reference.jsonl"

ENTRIES_PATH = Path(__file__).resolve().parent / "help_entries.json"
"""Frozen ``describe()`` / ``search()`` outputs used as render inputs."""

FORMATS: tuple[str, ...] = ("text", "markdown", "json")

ENTRY_QUERIES: tuple[tuple[str, str | None, str | None, int | None], ...] = (
    ("method-segmentation", "Workspace.segmentation", None, None),
    ("method-query-funnel", "Workspace.query_funnel", None, None),
    ("function-accounts-add", "accounts.add", None, None),
    ("function-url-normalizer", "url_normalizer", None, None),
    ("property-project", "Workspace.project", None, None),
    ("parameter-query-math", "Workspace.query.math", None, None),
    ("class-query-meta", "QueryMeta", None, None),
    ("model-create-dashboard-params", "CreateDashboardParams", None, None),
    ("dataclass-filter", "Filter", None, None),
    ("enum-feature-flag-status", "FeatureFlagStatus", None, None),
    ("literal-math-type", "MathType", None, None),
    ("alias-account", "Account", None, None),
    ("exception-api-error", "APIError", None, None),
    ("exception-leaf", "RateLimitError", None, None),
    ("module-accounts", "accounts", None, None),
    ("constant-enum-member", "FeatureFlagStatus.ENABLED", None, None),
    ("constant-int", "BUSINESS_CONTEXT_MAX_CHARS", None, None),
    ("listing-workspace-dashboards", "Workspace", "dashboards", None),
    ("listing-exceptions", "exceptions", None, None),
    ("listing-types-trimmed", "types", None, 2),
    ("overview", None, None, None),
)
"""``(slug, query, domain, items kept per group)`` for each frozen entry.

``types`` lists every public type, so its groups are cut to the first two
items each (a still-valid entry); the ``Workspace`` listing is filtered to
one domain for the same reason.
"""

SEARCH_QUERIES: tuple[tuple[str, str, int | None], ...] = (
    ("cohort", "cohort", 8),
    ("enabled-member-tier", "enabled", 6),
    ("filtr-miss", "Filtr", None),
)
"""``(slug, term, limit)`` for each frozen ``reference.search()`` result."""


# =============================================================================
# Frozen describe()/search() inputs
# =============================================================================


def capture_entries() -> dict[str, Any]:
    """Capture the render inputs from the live library.

    Returns:
        ``{"entries": [{slug, query, domain, entry}], "search_results":
        [{slug, term, limit, result}]}`` with every model in ``to_dict()``
        form.
    """
    import dataclasses

    from mixpanel_headless import reference

    entries: list[dict[str, Any]] = []
    for slug, query, domain, keep in ENTRY_QUERIES:
        entry = reference.describe(query, domain=domain)
        if keep is not None:
            entry = dataclasses.replace(
                entry,
                groups=tuple(
                    dataclasses.replace(group, items=group.items[:keep])
                    for group in entry.groups
                ),
            )
        entries.append(
            {"slug": slug, "query": query, "domain": domain, "entry": entry.to_dict()}
        )
    results = [
        {
            "slug": slug,
            "term": term,
            "limit": limit,
            "result": reference.search(term, limit=limit).to_dict(),
        }
        for slug, term, limit in SEARCH_QUERIES
    ]
    return {"entries": entries, "search_results": results}


def load_entries() -> dict[str, Any]:
    """Load the frozen render inputs.

    Returns:
        The parsed ``help_entries.json``.
    """
    loaded: dict[str, Any] = json.loads(ENTRIES_PATH.read_text(encoding="utf-8"))
    return loaded


def write_entries() -> None:
    """Re-capture the render inputs and write ``help_entries.json``."""
    text = json.dumps(capture_entries(), indent=1, ensure_ascii=True)
    ENTRIES_PATH.write_text(text + "\n", encoding="utf-8")


# =============================================================================
# Synthetic inputs
# =============================================================================


def _row(category: str, name: str, summary: str = "", *members: str) -> dict[str, Any]:
    """Build one raw search-index row.

    Args:
        category: Display category.
        name: Display name.
        summary: One-line summary.
        *members: Member texts (``value x`` / ``member NAME = 'x'``).

    Returns:
        The row in the ``help.search`` input shape.
    """
    return {
        "category": category,
        "name": name,
        "summary": summary,
        "members": list(members),
    }


_INDEX: list[dict[str, Any]] = [
    _row("model", "CohortDefinition", "A saved cohort definition."),
    _row("class", "RetentionCohortData", "Per-cohort retention rows."),
    _row(
        "literal",
        "TimeUnit",
        "Bucket size per day, week, or month.",
        "value day",
        "value week",
        "value month",
    ),
    _row(
        "literal",
        "FlowWindowUnit",
        "Conversion window unit.",
        "value day",
        "value hour",
    ),
    _row(
        "enum",
        "FeatureFlagStatus",
        "Lifecycle status of a feature flag.",
        "member ENABLED = 'enabled'",
        "member DISABLED = 'disabled'",
    ),
    _row("method", "Workspace.cohorts", "List saved cohorts."),
    _row("method", "Workspace.query", "Run an insights query."),
    _row("property", "Workspace.project", "The active project."),
    _row("method", "Workspace.cohorts", "A later duplicate that must lose."),
    _row("dataclass", "cohortLowercase", ""),
    _row("dataclass", "Cohort_Upper", "Sorts before lowercase names."),
    _row("function", "accounts.add", "Add an account; not a cohort helper."),
    _row("module", "accounts", "Account management | pipes stay verbatim."),
]
"""A synthetic raw index: every tier, a duplicate key, and code-point ordering."""

_CANDIDATES: list[list[str]] = [
    ["Filter", "Filter"],
    ["DropFilter", "DropFilter"],
    ["FilterOperator", "FilterOperator"],
    ["FilterDateUnit", "FilterDateUnit"],
    ["FrequencyFilter", "FrequencyFilter"],
    ["Filters", "Filters"],
    ["query", "Workspace.query"],
    ["query_funnel", "Workspace.query_funnel"],
    ["query_flow", "Workspace.query_flow"],
    ["cohorts", "Workspace.cohorts"],
]
"""Root-level suggestion candidates ``[key, display]`` (more than five close)."""

_SYNTHETIC_HITS: list[dict[str, Any]] = [
    {
        "category": "method",
        "name": "Workspace.query",
        "summary": "Run an insights query | with a pipe.",
        "matched_on": "name",
    },
    {"category": "literal", "name": "MathType", "summary": "", "matched_on": "doc"},
    {
        "category": "enum",
        "name": "FeatureFlagStatus",
        "summary": "member ENABLED = 'enabled'",
        "matched_on": "member",
    },
]


def _search_results(frozen: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """List the ``SearchResult`` render inputs.

    Args:
        frozen: The loaded ``help_entries.json``.

    Returns:
        ``(slug, result dict)`` pairs: the frozen real results, then
        synthetic hit / miss shapes.
    """
    real = [(f"real-{row['slug']}", row["result"]) for row in frozen["search_results"]]
    synthetic = [
        ("synthetic-hits", {"term": "q", "hits": _SYNTHETIC_HITS, "suggestions": []}),
        (
            "miss-with-suggestions",
            {"term": "Filtr", "hits": [], "suggestions": ["Filter", "DropFilter"]},
        ),
        ("miss-no-suggestions", {"term": "zzqq", "hits": [], "suggestions": []}),
    ]
    return real + synthetic


# =============================================================================
# Cases
# =============================================================================


def _cases() -> list[tuple[str, str, dict[str, Any]]]:
    """List every vector case as ``(api, slug, input kwargs)``.

    Returns:
        The cases, in output order.
    """
    frozen = load_entries()
    cases: list[tuple[str, str, dict[str, Any]]] = []
    for slug, text in (
        ("blank", ""),
        ("whitespace", "   "),
        ("bare-search", "search"),
        ("search-term", "search cohort"),
        ("search-collapses-spaces", "  search   many   words "),
        ("capital-search-is-describe", "Search cohort"),
        ("searching-is-describe", "searching"),
        ("dotted", "Workspace.query"),
        ("describe-rejoins-tokens", "  Workspace   query "),
    ):
        cases.append(("help.parse_query", slug, {"text": text}))
    for slug, query in (
        ("dotted", "Workspace.query_funnel"),
        ("three-segments", "Workspace.query.math"),
        ("whitespace-and-search", "  search   cohort "),
        ("empty-segments", "a..b"),
        ("blank", ""),
    ):
        cases.append(("help.tokens", slug, {"query": query}))
    for slug, query_tokens, kind in (
        ("workspace-class", ["Workspace"], "class"),
        ("workspace-lowercase-listing", ["workspace"], "listing"),
        ("types-listing", ["types"], "listing"),
        ("listing-suppresses", ["Workspace", "query"], "listing"),
        ("funnel-engine-before-insights", ["Workspace", "query_funnel"], "method"),
        ("whole-token-saved-report", ["Workspace", "query_saved_report"], "method"),
        ("insights", ["Workspace", "query"], "method"),
        ("case-insensitive", ["filter"], "dataclass"),
        ("first-rule-wins", ["Dashboard", "query_funnel"], "model"),
        ("no-rule", ["nothing_here"], "function"),
    ):
        cases.append(("help.hints_for", slug, {"tokens": query_tokens, "kind": kind}))
    for slug, domain in (
        ("exact", "dashboards"),
        ("case-folded", "DASHBOARDS"),
        ("unique-prefix", "dash"),
        ("collapsed-spaces", "  session   replay "),
        ("ambiguous-prefix", "se"),
        ("unknown", "nope"),
        ("blank", ""),
    ):
        cases.append(("help.match_domain", slug, {"domain": domain}))
    for slug, query in (
        ("capped-at-five", "Filtr"),
        ("workspace-member-display", "qury"),
        ("none-close", "zzzz"),
    ):
        cases.append(
            ("help.suggestions", slug, {"candidates": _CANDIDATES, "query": query})
        )
    members = ["events", "event_counts", "properties", "from_date"]
    for slug, wanted in (("close", "evnts"), ("none-close-falls-back", "zzzz")):
        cases.append(
            (
                "help.child_suggestions",
                slug,
                {"wanted": wanted, "candidates": members, "parent": "Workspace.query"},
            )
        )
    for slug, extra in (
        ("tiers-and-order", {"term": "cohort"}),
        ("case-insensitive", {"term": "COHORT"}),
        ("term-echoed-stripped-for-matching", {"term": "  cohort  "}),
        ("doc-beats-member", {"term": "day"}),
        ("member-tier-shows-member-text", {"term": "enabled"}),
        ("inner-space-is-part-of-needle", {"term": "per day"}),
        ("limit-two", {"term": "cohort", "limit": 2}),
        ("limit-zero", {"term": "cohort", "limit": 0}),
        (
            "miss-with-candidates",
            {"term": "Filtr", "suggestion_candidates": _CANDIDATES},
        ),
        ("miss-without-candidates", {"term": "Filtr"}),
        ("blank-term", {"term": "   "}),
    ):
        cases.append(("help.search", slug, {"index": _INDEX, **extra}))
    for row in frozen["entries"]:
        for fmt in FORMATS:
            cases.append(
                (
                    "help.render",
                    f"{row['slug']}-{fmt}",
                    {"entry": row["entry"], "format": fmt},
                )
            )
    method = frozen["entries"][0]["entry"]
    cases.append(
        (
            "help.render",
            "method-segmentation-markdown-code-lang-ts",
            {"entry": method, "format": "markdown", "code_lang": "ts"},
        )
    )
    for slug, result in _search_results(frozen):
        for fmt in FORMATS:
            cases.append(
                (
                    "help.render_search",
                    f"{slug}-{fmt}",
                    {"result": result, "format": fmt},
                )
            )
    many_hits = frozen["search_results"][0]["result"]["hits"]
    miss_cases: list[tuple[str, dict[str, Any]]] = [
        (
            "suggestions-and-hits-capped",
            {"query": "cohrt", "suggestions": ["Cohort"], "hits": many_hits},
        ),
        (
            "suggestions-only",
            {"query": "Filtr", "suggestions": ["Filter", "DropFilter"]},
        ),
        ("bare", {"query": "zzqq"}),
    ]
    for slug, extra in miss_cases:
        for fmt in FORMATS:
            cases.append(
                ("help.render_miss", f"{slug}-{fmt}", {**extra, "format": fmt})
            )
    for fmt in FORMATS:
        cases.append(("help.search_usage", fmt, {"format": fmt}))
    lookup_cases: list[tuple[str, dict[str, Any]]] = [
        (
            "with-suggestions",
            {"query": "Filtr", "suggestions": ["Filter", "DropFilter"]},
        ),
        ("bare", {"query": "zzqq"}),
        ("empty-query", {"query": ""}),
        ("with-hits", {"query": "q", "hits": _SYNTHETIC_HITS}),
    ]
    for slug, kwargs in lookup_cases:
        cases.append(("help.lookup_error", slug, kwargs))
    domain_cases: list[tuple[str, dict[str, Any]]] = [
        (
            "unknown",
            {
                "query": "Workspace",
                "domain": "nope",
                "domains": ["dashboards", "session replay"],
                "reason": "unknown",
            },
        ),
        (
            "ambiguous",
            {
                "query": "Workspace",
                "domain": "se",
                "domains": ["session and switching", "session replay"],
                "reason": "ambiguous",
            },
        ),
        (
            "not-workspace",
            {"query": "Filter", "domain": "dashboards", "reason": "not_workspace"},
        ),
        (
            "not-workspace-overview",
            {"query": "", "domain": "dashboards", "reason": "not_workspace"},
        ),
    ]
    for slug, kwargs in domain_cases:
        cases.append(("help.domain_error", slug, kwargs))
    return cases


_ADAPTERS: dict[str, Callable[..., Any]] = {
    "help.parse_query": help_adapters.parse_query,
    "help.tokens": help_adapters.tokens,
    "help.hints_for": help_adapters.hints_for,
    "help.match_domain": help_adapters.match_domain,
    "help.suggestions": help_adapters.suggestions,
    "help.child_suggestions": help_adapters.child_suggestions,
    "help.search": help_adapters.search,
    "help.render": help_adapters.render,
    "help.render_search": help_adapters.render_search,
    "help.render_miss": help_adapters.render_miss,
    "help.search_usage": help_adapters.search_usage,
    "help.lookup_error": help_adapters.lookup_error,
    "help.domain_error": help_adapters.domain_error,
}
"""The registry adapter behind each api (see ``registry.py``)."""


def build_vectors() -> list[dict[str, Any]]:
    """Build every vector, with ``expect.output`` computed by the adapter.

    Returns:
        The vector objects, in case order.
    """
    vectors: list[dict[str, Any]] = []
    for api, slug, kwargs in _cases():
        output = _ADAPTERS[api](**kwargs)
        vectors.append(
            {
                "call": {"api": api, "input": kwargs},
                "capability": "help",
                "expect": {"output": output},
                "id": f"help/{api}/authored-{slug}",
                "kind": "builder",
                "origin": "authored",
                "schema_version": "1.0",
            }
        )
    return vectors


def render_bundle(commit: str) -> str:
    """Render the whole bundle file: the ``$bundle`` header and the vectors.

    Args:
        commit: The ``$bundle.source_commit`` stamp.

    Returns:
        The JSONL text, with a trailing newline.
    """
    vectors = build_vectors()
    header = {
        "$bundle": {
            "count": len(vectors),
            "source_commit": commit,
            "source_file": SOURCE_FILE,
        }
    }
    lines = [
        json.dumps(header, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    ]
    lines.extend(
        json.dumps(vector, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
        for vector in vectors
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the bundle, or re-capture the frozen render inputs.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, 2 on a usage error).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        help="$bundle source_commit stamp: a 40-hex SHA reachable from main.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help="Bundle path (default: conformance/vectors/authored/help/reference.jsonl).",
    )
    parser.add_argument(
        "--refresh-entries",
        action="store_true",
        help="Re-capture help_entries.json from the live library instead.",
    )
    args = parser.parse_args(argv)
    if args.refresh_entries:
        write_entries()
        print(f"wrote {ENTRIES_PATH}")
        return 0
    if not args.commit:
        parser.error("--commit is required unless --refresh-entries is given")
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render_bundle(args.commit)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10)) - 1} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
