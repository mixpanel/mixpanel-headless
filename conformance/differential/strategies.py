"""Fuzz-target strategy table for the differential harness (design D14).

Defines the Phase-1 priority targets (plan Layer 2, design D14): the three
Filter translation dialects (``filter_to_selector`` / ``filters_to_selector``
escaping, ``build_segfilter_entry``, ``build_filter_entry``), the
validators-by-code entry, ``normalize_on_expression``, and pythonCompat.

Strategy sourcing per design D14:

- **Imported directly from test modules where cleanly importable**: the
  Filter strategy comes from ``tests/test_user_query_pbt.py`` (module-level
  ``@st.composite``, zero fixture entanglement; ``tests`` is an importable
  package).
- **Vendored with provenance where import is not clean**: the
  ``normalize_on_expression`` strategies live in
  ``tests/unit/_internal/test_expressions_pbt.py``, and ``tests/unit/_internal``
  has NO ``__init__.py`` (not an importable package) — vendored below with a
  provenance comment naming the source file + lines, kept in sync manually.

Every target's generated corpus includes the R10.9 mandatory edge set
(integral float, fractional float, True, None, empty list, empty string,
non-BMP string, every reachable error branch) as explicit example calls —
the harness attaches them as Hypothesis ``@example`` decorators. Where an
edge-set item is outside a target's input domain (e.g. ``True`` for the
str-typed ``normalize_on_expression``) or an error branch is unshippable
through vector JSON (``build_filter_entry`` with a non-finite filter value —
D6 rule 5 rejects NaN at the codec), the omission is documented on the
target's edge tuple.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import gzip
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from hypothesis import assume
from hypothesis import strategies as st
from pydantic import SecretStr
from tests.test_cohort_definition_pbt import (
    any_criteria,
    definition_trees,
    valid_did_event_params,
)
from tests.test_user_query_pbt import filter_strategy

from conformance.record.codecs import decode_input_kwargs
from mixpanel_headless.types import (
    Filter,
    Replay,
    ReplayEvent,
    UserAction,
)

FuzzCall = tuple[str, dict[str, Any]]
"""One differential probe: ``(api, kwargs)`` — the api's dotted registry
name and the RAW Python kwargs (encoded via the shared codec table by the
harness before crossing the bridge)."""


@dataclass(frozen=True)
class FuzzTarget:
    """One fuzz target: a strategy over calls plus its mandatory edge set.

    Attributes:
        name: Harness-facing target name (``--targets`` selector; the
            design D14 Phase-1 priority-target vocabulary).
        calls: Strategy generating ``(api, kwargs)`` probes.
        edge_calls: The R10.9 mandatory edge set for this target, attached
            by the harness as explicit ``@example`` decorators so every
            generated corpus provably contains them.
    """

    name: str
    calls: st.SearchStrategy[FuzzCall]
    edge_calls: tuple[FuzzCall, ...]


# ---------------------------------------------------------------------------
# Shared Filter material (imported strategy + edge fixtures)
# ---------------------------------------------------------------------------

_EDGE_FILTERS: tuple[Filter, ...] = (
    Filter.greater_than("p", 18.0),  # R10.9: integral float
    Filter.less_than("p", 1.5),  # R10.9: fractional float
    Filter.is_true("p"),  # R10.9: True (boolean-operator filter)
    Filter.is_not_set("p"),  # R10.9: None — a raw None VALUE is outside the
    # typed Filter constructor domain (str | list[str]), so the None-
    # semantics operator stands in (documented omission per module rules).
    Filter.equals("p", []),  # R10.9: empty list (selector error branch)
    Filter.equals("p", ""),  # R10.9: empty string
    Filter.equals("p", "\U0001f40d"),  # R10.9: non-BMP string
    Filter.in_cohort(123),  # error branch: cohort filters are rejected by
    # the selector and segfilter dialects (uncoded ValueError — compared
    # as bare class per oracle-protocol.md §4.1).
)
"""Edge Filters shared by the three single-Filter translation targets.

The remaining R10.9 item — "every error branch" — is covered as far as the
public ``Filter`` constructors can reach: ``build_filter_entry``'s
non-finite-value branch (B20B) needs a NaN operand, which vector JSON
rejects at the codec (D6 rule 5), so it stays corpus-authored (design D4.3)
rather than fuzzed."""


def _filter_calls(api: str) -> st.SearchStrategy[FuzzCall]:
    """Build a single-Filter call strategy for one translation api.

    Args:
        api: The dotted registry name taking a single ``f: Filter`` kwarg.

    Returns:
        A strategy of ``(api, {"f": <Filter>})`` probes over the imported
        suite strategy (all eleven operators).
    """

    def make(f: Filter) -> FuzzCall:
        """Wrap one drawn Filter as a probe call.

        Args:
            f: The drawn Filter.

        Returns:
            The ``(api, kwargs)`` probe.
        """
        return (api, {"f": f})

    return filter_strategy().map(make)


def _filter_edges(api: str) -> tuple[FuzzCall, ...]:
    """Attach the shared edge Filters to one translation api.

    Args:
        api: The dotted registry name taking a single ``f: Filter`` kwarg.

    Returns:
        One edge probe per :data:`_EDGE_FILTERS` member.
    """
    return tuple((api, {"f": f}) for f in _EDGE_FILTERS)


# ---------------------------------------------------------------------------
# Targets 1-4 — the three Filter translation dialects (design D4.2 item 1)
# ---------------------------------------------------------------------------

_FILTER_TO_SELECTOR = FuzzTarget(
    name="filter_to_selector",
    calls=_filter_calls("user_builders.filter_to_selector"),
    edge_calls=_filter_edges("user_builders.filter_to_selector"),
)

_FILTERS_LIST: st.SearchStrategy[list[Filter]] = st.lists(
    filter_strategy(), min_size=0, max_size=4
)
"""Filter lists for the AND-combining selector path (empty list included —
R10.9)."""


def _filters_call(filters: list[Filter]) -> FuzzCall:
    """Wrap one drawn Filter list as a ``filters_to_selector`` probe.

    Args:
        filters: The drawn Filter list.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("user_builders.filters_to_selector", {"filters": filters})


_FILTERS_TO_SELECTOR = FuzzTarget(
    name="filters_to_selector",
    calls=_FILTERS_LIST.map(_filters_call),
    edge_calls=(
        # R10.9: empty list (yields the empty selector).
        ("user_builders.filters_to_selector", {"filters": []}),
        # Every shared edge Filter as a singleton list.
        *(
            ("user_builders.filters_to_selector", {"filters": [f]})
            for f in _EDGE_FILTERS
        ),
        # The full edge set AND-combined (first error branch dominates).
        ("user_builders.filters_to_selector", {"filters": list(_EDGE_FILTERS)}),
    ),
)

_BUILD_SEGFILTER_ENTRY = FuzzTarget(
    name="build_segfilter_entry",
    calls=_filter_calls("segfilter.build_segfilter_entry"),
    edge_calls=_filter_edges("segfilter.build_segfilter_entry"),
)

_BUILD_FILTER_ENTRY = FuzzTarget(
    name="build_filter_entry",
    calls=_filter_calls("bookmark_builders.build_filter_entry"),
    edge_calls=_filter_edges("bookmark_builders.build_filter_entry"),
)

# ---------------------------------------------------------------------------
# Target 5 — validators by code (design D4.2 item 6, D14 "validators by code")
# ---------------------------------------------------------------------------

_TIME_API = "validation.validate_time_args"

_DATE_ARGS: st.SearchStrategy[str | None] = st.one_of(
    st.none(),
    st.dates().map(str),  # well-formed YYYY-MM-DD dates
    st.sampled_from(
        [
            "2025-02-30",  # V8_DATE_INVALID (well-formed, non-calendar)
            "2025-13-01",  # V8_DATE_INVALID (month out of range)
            "not-a-date",  # V8_DATE_FORMAT
            "",  # V8_DATE_FORMAT (empty string — R10.9)
            "2025-1-1",  # V8_DATE_FORMAT (unpadded)
            "20250101",  # V8_DATE_FORMAT (no separators)
        ]
    ),
    st.text(max_size=12),  # arbitrary junk (format branch)
)
"""Date-argument mix: valid dates, each malformed family, None, junk."""


def _time_call(kwargs: dict[str, Any]) -> FuzzCall:
    """Wrap drawn time-args kwargs as a validator probe.

    Args:
        kwargs: The drawn ``from_date``/``to_date``/``last`` kwargs.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (_TIME_API, kwargs)


_VALIDATORS_BY_CODE = FuzzTarget(
    name="validators_by_code",
    calls=st.fixed_dictionaries(
        {
            "from_date": _DATE_ARGS,
            "to_date": _DATE_ARGS,
            "last": st.integers(min_value=-10, max_value=40_000),
        }
    ).map(_time_call),
    # One explicit example per emitted code path ("every error branch",
    # R10.9; codes per validation.py validate_time_args V7-V10/V15/V20),
    # plus the all-valid and all-None probes. Integral/fractional-float,
    # True, empty-list, and non-BMP edge items are outside this validator's
    # typed input domain (str|None dates, int last) — documented omission.
    edge_calls=(
        (_TIME_API, {"from_date": "2025-01-01", "to_date": "2025-01-31", "last": 30}),
        (_TIME_API, {"from_date": None, "to_date": None, "last": 30}),  # None
        (_TIME_API, {"from_date": None, "to_date": None, "last": 0}),  # V7
        (_TIME_API, {"from_date": "not-a-date", "to_date": None, "last": 30}),  # V8
        (_TIME_API, {"from_date": "", "to_date": None, "last": 30}),  # V8 + ""
        (_TIME_API, {"from_date": "2025-02-30", "to_date": None, "last": 30}),  # V8b
        (_TIME_API, {"from_date": None, "to_date": "2025-01-31", "last": 30}),  # V9
        (_TIME_API, {"from_date": "2025-01-01", "to_date": None, "last": 7}),  # V10
        (
            _TIME_API,
            {"from_date": "2025-02-01", "to_date": "2025-01-01", "last": 30},
        ),  # V15
        (_TIME_API, {"from_date": None, "to_date": None, "last": 100_000}),  # V20
    ),
)

# ---------------------------------------------------------------------------
# Target 6 — normalize_on_expression (design D4.2 item 3, the smoke entry)
# ---------------------------------------------------------------------------

# VENDORED strategies — provenance (design D14 vendor-with-provenance rule):
#   source: tests/unit/_internal/test_expressions_pbt.py lines 11-24
#   reason: tests/unit/_internal has no __init__.py, so the module is not
#           importable as a package member; copied verbatim, renamed with a
#           leading underscore, kept in sync manually.
_BARE_PROPERTY_NAMES: st.SearchStrategy[str] = st.text(min_size=1).filter(
    lambda s: 'properties["' not in s and 'user["' not in s and 'event["' not in s
)
"""Vendored: bare property names (no accessor patterns)."""

_VALID_EXPRESSIONS: st.SearchStrategy[str] = st.sampled_from(
    [
        'properties["Source"]',
        'user["email"]',
        'event["name"]',
        'properties["x"] == "y"',
        'defined(properties["z"])',
    ]
)
"""Vendored: expressions already carrying an accessor (pass-through path)."""

_NORMALIZE_API = "expressions.normalize_on_expression"


def _normalize_call(on: str) -> FuzzCall:
    """Wrap one drawn expression string as a normalize probe.

    Args:
        on: The drawn ``on`` expression.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (_NORMALIZE_API, {"on": on})


_NORMALIZE_ON_EXPRESSION = FuzzTarget(
    name="normalize_on_expression",
    calls=st.one_of(_BARE_PROPERTY_NAMES, _VALID_EXPRESSIONS, st.text()).map(
        _normalize_call
    ),
    # Input domain is a single str: the float/True/None/empty-list edge
    # items are inapplicable (documented omission); the function has no
    # error branch (pure string wrap/pass-through).
    edge_calls=(
        (_NORMALIZE_API, {"on": ""}),  # R10.9: empty string
        (_NORMALIZE_API, {"on": "\U0001f40d"}),  # R10.9: non-BMP string
        (_NORMALIZE_API, {"on": "Source"}),  # bare-name wrap branch
        (_NORMALIZE_API, {"on": 'properties["Source"]'}),  # pass-through
        (_NORMALIZE_API, {"on": 'has "quotes" inside'}),  # escaping branch
    ),
)

# ---------------------------------------------------------------------------
# Target 7 — pythonCompat (design D13 gate module, rulebook R11.1/2/4)
# ---------------------------------------------------------------------------


def _zfill_call(args: tuple[str, int]) -> FuzzCall:
    """Wrap drawn zfill args as a compat probe.

    Args:
        args: ``(value, width)`` as drawn.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.zfill", {"value": args[0], "width": args[1]})


def _python_str_call(value: object) -> FuzzCall:
    """Wrap one drawn value as a ``python_str`` probe.

    Args:
        value: The drawn JSON-shaped value.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.python_str", {"value": value})


def _python_float_str_call(value: float) -> FuzzCall:
    """Wrap one drawn float as a ``python_float_str`` probe.

    Args:
        value: The drawn finite float.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.python_float_str", {"value": value})


_JSON_SCALARS: st.SearchStrategy[object] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=10),
)
"""Scalar universe for ``python_str`` (NaN/Infinity are illegal in vectors,
D6 rule 5, so the strategy never draws them)."""

_PYTHON_STR_VALUES: st.SearchStrategy[object] = st.recursive(
    _JSON_SCALARS,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.dictionaries(st.text(max_size=5), inner, max_size=3),
    ),
    max_leaves=6,
)
"""Nested JSON-shaped values exercising Python container reprs."""

_PYTHONCOMPAT = FuzzTarget(
    name="pythoncompat",
    calls=st.one_of(
        st.tuples(st.text(max_size=20), st.integers(min_value=0, max_value=40)).map(
            _zfill_call
        ),
        _PYTHON_STR_VALUES.map(_python_str_call),
        st.floats(allow_nan=False, allow_infinity=False).map(_python_float_str_call),
    ),
    # The compat wrappers have no reachable error branch inside their
    # contractual domains (CPython str.zfill/str()/repr(float) are total
    # over the drawn inputs) — documented omission of the error-branch item.
    edge_calls=(
        ("compat.zfill", {"value": "-1", "width": 3}),  # D13 sign case
        ("compat.zfill", {"value": "+7", "width": 3}),
        ("compat.zfill", {"value": "", "width": 2}),  # R10.9: empty string
        ("compat.zfill", {"value": "12345", "width": 3}),  # width < len
        ("compat.zfill", {"value": "\U0001f40d", "width": 3}),  # non-BMP
        ("compat.python_str", {"value": True}),  # R10.9: True
        ("compat.python_str", {"value": None}),  # R10.9: None
        ("compat.python_str", {"value": []}),  # R10.9: empty list
        ("compat.python_str", {"value": ""}),
        ("compat.python_str", {"value": 18.0}),  # integral float
        ("compat.python_str", {"value": 1.5}),  # fractional float
        ("compat.python_float_str", {"value": 18.0}),
        ("compat.python_float_str", {"value": 1.5}),
        ("compat.python_float_str", {"value": -0.0}),  # sign-preserving zero
        ("compat.python_float_str", {"value": 1e16}),  # exponent threshold
        ("compat.python_float_str", {"value": 1e-05}),  # two-digit exponent
        ("compat.python_float_str", {"value": 5e-324}),  # min subnormal
    ),
)

PHASE1_TARGETS: tuple[FuzzTarget, ...] = (
    _FILTER_TO_SELECTOR,
    _FILTERS_TO_SELECTOR,
    _BUILD_SEGFILTER_ENTRY,
    _BUILD_FILTER_ENTRY,
    _VALIDATORS_BY_CODE,
    _NORMALIZE_ON_EXPRESSION,
    _PYTHONCOMPAT,
)
"""The design D14 Phase-1 priority targets, in design order."""

# ============================================================================
# Phase-2 targets (P2-9, phase2-design C9) — the 44 `types.*` contract apis
# grouped into api families, plus the protocol-1.1 `codec.roundtrip` surface.
#
# Strategy sourcing per design D14: the Filter strategy and the cohort
# composites are IMPORTED from their suites (`tests/test_user_query_pbt.py`,
# `tests/test_cohort_definition_pbt.py` — both cleanly importable package
# members); the remaining kwargs strategies are written here against the
# measured api-index parameter lists because the corresponding suites test
# INSTANCES (not call kwargs) and entangle with Workspace fixtures.
#
# Probes are deliberately LOOSE (mostly-valid draws with guard-tripping
# values mixed in): an `ok: false` outcome is comparable DATA — both
# bridges must produce the same `{class, code}` (R5.4), so error branches
# are fuzzed, not avoided. The R10.9 "every error branch" item is closed
# EXACTLY by `_harvested_family_edges`: one recorded corpus probe per
# Phase-2 guard code (all 81 — completeness asserted by the unit tests and
# the checked-in `phase2-edge-coverage.json`) plus one probe per `types.*`
# api (all 44).
# ============================================================================

CODEC_ROUNDTRIP_API = "codec.roundtrip"
"""Sentinel api name for protocol-1.1 ``codec.roundtrip`` probes: the
harness routes calls with this name to the ``codec.roundtrip`` method
(oracle-protocol.md §8) instead of ``oracle.call``."""

_CONFORMANCE_DIR = Path(__file__).resolve().parents[1]
"""The ``conformance/`` package directory (artifact + vector roots)."""

_PHASE2_GUARD_PREFIXES = frozenset(
    {
        # C7 query-param families (phase2-design C7).
        "CF",
        "CB",
        "CA",
        "CM",
        "CD",
        "TC",
        "MT",
        "FM",
        "LC",
        "FD",
        "LG",
        "GB",
        "EV",
        "FB",
        "FF",
        "EX",
        "HC",
        "FS",
        "UA",
        # C6-d replay families.
        "RS",
        "SR",
        "RE",
        "RP",
        "RB",
    }
)
"""Alphabetic code-prefix families raisable from Phase-2 constructors
(phase2-design C9: the error-branch edge set is one example per code in
``CODED_GUARD_REGISTRY`` belonging to a C7/C6-d family)."""

_API_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("types.Filter", "filter_family"),
    ("types.ListItemGroupMode", "filter_family"),
    ("types.GroupBy", "metric_group_family"),
    ("types.Metric", "metric_group_family"),
    ("types.CohortMetric", "metric_group_family"),
    ("types.Formula", "metric_group_family"),
    ("types.TimeComparison", "metric_group_family"),
    ("types.CohortCriteria", "cohort_family"),
    ("types.CohortDefinition", "cohort_family"),
    ("types.CohortBreakdown", "cohort_family"),
    ("types._sanitize_raw_cohort", "cohort_family"),
    ("types.FunnelStep", "funnel_family"),
    ("types.Exclusion", "funnel_family"),
    ("types.HoldingConstant", "funnel_family"),
    ("types.RetentionEvent", "retention_flow_family"),
    ("types.FlowStep", "retention_flow_family"),
    ("types.FrequencyBreakdown", "frequency_family"),
    ("types.FrequencyFilter", "frequency_family"),
    ("types.ReplaySummary", "replay_family"),
    ("types.SignedReplay", "replay_family"),
    ("types.UserAction", "replay_family"),
    ("types.ReplayEvent", "replay_family"),
    ("types.Replay", "replay_family"),
    ("types.ReplayBundle", "replay_family"),
)
"""``types.*`` api prefix → fuzz-family assignment (C10 packet grouping:
P2-5a / P2-5b / P2-5c / C6-d)."""


def _family_for_api(api: str) -> str | None:
    """Assign one ``types.*`` api to its fuzz family.

    Args:
        api: The dotted vector api name.

    Returns:
        The family name, or ``None`` for apis outside the Phase-2 table.
    """
    for prefix, family in _API_FAMILY_PREFIXES:
        if api == prefix or api.startswith(prefix + "."):
            return family
    return None


@lru_cache(maxsize=1)
def _literal_alias_values() -> dict[str, tuple[str, ...]]:
    """Load the C2 literal-alias artifact (artifact-driven value domains).

    Returns:
        Alias name → member tuple, from
        ``conformance/contract/literal-aliases.json``.
    """
    payload = json.loads(
        (_CONFORMANCE_DIR / "contract" / "literal-aliases.json").read_text(
            encoding="utf-8"
        )
    )
    aliases: dict[str, Any] = payload["literal_aliases"]
    return {name: tuple(values) for name, values in aliases.items()}


def _alias(name: str) -> st.SearchStrategy[str]:
    """Sample one member of a generated literal alias.

    Args:
        name: The alias name in ``literal-aliases.json``.

    Returns:
        A strategy over the alias's members (declaration order).
    """
    return st.sampled_from(_literal_alias_values()[name])


@lru_cache(maxsize=1)
def phase2_guard_codes() -> tuple[str, ...]:
    """The Phase-2 guard-code universe (C7 + C6-d families), sorted.

    Derived from the generated ``error-codes.json`` registry artifact —
    never from prose lists (phase2-design C7: "the C9 error-branch set is
    derived from ... the generator artifact").

    Returns:
        Every ``CODED_GUARD_REGISTRY`` code whose alphabetic prefix is a
        Phase-2 family prefix.
    """
    payload = json.loads(
        (_CONFORMANCE_DIR / "contract" / "error-codes.json").read_text(encoding="utf-8")
    )
    registry: list[str] = payload["coded_guard_registry"]
    return tuple(
        sorted(
            code for code in registry if _code_prefix(code) in _PHASE2_GUARD_PREFIXES
        )
    )


def _code_prefix(code: str) -> str:
    """Extract the alphabetic family prefix of one guard code.

    Args:
        code: A registry code (e.g. ``"CD9_EMPTY_DEFINITION"``).

    Returns:
        The leading uppercase-letter run (``"CD"``).
    """
    match = re.match(r"[A-Z]+", code)
    return match.group(0) if match else ""


@dataclass(frozen=True)
class HarvestedEdge:
    """One corpus-harvested edge probe with its provenance.

    Attributes:
        vector_id: The source vector id.
        api: The probed api.
        guard_code: The recorded ``expect.error.code``, when the vector is
            a guard-failure case (``None`` for success probes).
        call: The replayable ``(api, kwargs)`` probe (input decoded through
            the shared codec table).
    """

    vector_id: str
    api: str
    guard_code: str | None
    call: FuzzCall


@lru_cache(maxsize=1)
def harvested_edges() -> tuple[HarvestedEdge, ...]:
    """Harvest the Phase-2 edge probes from the committed corpus.

    Selection rule (deterministic: files and lines scanned in sorted
    order): the FIRST vector per Phase-2 guard code (one per "every error
    branch" item, R10.9) plus the FIRST vector per ``types.*`` api (so
    every one of the 44 apis is provably probed at least once). Inputs
    decode through ``decode_input_kwargs`` — the same table the bridges
    use — so re-encoding in the harness is loss-free.

    Returns:
        The deduplicated harvested probes in scan order.

    Raises:
        ValueError: If any Phase-2 guard code has no corpus vector (the
            P2-1 coverage-closure invariant — a re-extraction regression).
    """
    wanted_codes = set(phase2_guard_codes())
    picked: dict[str, tuple[str, str, str | None, dict[str, Any]]] = {}
    seen_codes: set[str] = set()
    seen_apis: set[str] = set()
    for path in sorted((_CONFORMANCE_DIR / "vectors").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            body = json.loads(line)
            call = body.get("call") or {}
            api = str(call.get("api", ""))
            if _family_for_api(api) is None:
                continue
            error = (body.get("expect") or {}).get("error") or {}
            code = error.get("code")
            code = code if isinstance(code, str) else None
            new_code = code in wanted_codes and code not in seen_codes
            new_api = api not in seen_apis
            if not (new_code or new_api):
                continue
            vector_id = str(body.get("id", f"{path.name}:{api}"))
            if vector_id not in picked:
                picked[vector_id] = (
                    vector_id,
                    api,
                    code if code in wanted_codes else None,
                    dict(call.get("input") or {}),
                )
            if new_code and code is not None:
                seen_codes.add(code)
            seen_apis.add(api)
    missing = sorted(wanted_codes - seen_codes)
    if missing:
        raise ValueError(
            f"Phase-2 guard codes without corpus vectors: {missing} "
            "(P2-1 coverage closure regressed?)"
        )
    return tuple(
        HarvestedEdge(
            vector_id=vector_id,
            api=api,
            guard_code=code,
            call=(api, decode_input_kwargs(encoded)),
        )
        for vector_id, api, code, encoded in picked.values()
    )


@lru_cache(maxsize=1)
def _harvested_family_edges() -> Mapping[str, tuple[FuzzCall, ...]]:
    """Group the harvested edge probes by fuzz family.

    Returns:
        Family name → probe tuple (scan order preserved).
    """
    grouped: dict[str, list[FuzzCall]] = {}
    for edge in harvested_edges():
        family = _family_for_api(edge.api)
        if family is not None:
            grouped.setdefault(family, []).append(edge.call)
    return {family: tuple(calls) for family, calls in grouped.items()}


def edge_coverage_report() -> dict[str, Any]:
    """Build the checked-in Phase-2 edge-set coverage report (C10 P2-9).

    Returns:
        A JSON-ready object mapping every Phase-2 guard code to the
        harvested vector id covering it, every ``types.*`` api to a
        covering vector id, and the per-family R10.9 scalar-edge
        dispositions (explicit probe or documented omission).
    """
    by_code: dict[str, str] = {}
    by_api: dict[str, str] = {}
    for edge in harvested_edges():
        if edge.guard_code is not None and edge.guard_code not in by_code:
            by_code[edge.guard_code] = edge.vector_id
        by_api.setdefault(edge.api, edge.vector_id)
    return {
        "guard_codes": dict(sorted(by_code.items())),
        "apis": dict(sorted(by_api.items())),
        "r10_9_scalar_edges": _R10_9_DISPOSITIONS,
    }


_R10_9_DISPOSITIONS: dict[str, dict[str, str]] = {
    "filter_family": {
        "integral_float": "explicit: Filter.in_the_last quantity=18.0",
        "fractional_float": "explicit: Filter.greater_than value 1.5 "
        "(direct-construction probe)",
        "true": "explicit: Filter.is_true direct-construction probe",
        "none": "explicit: types.Filter.in_cohort name=None",
        "empty_list": "explicit: Filter.equals('p', []) direct probe + "
        "list_contains item_filters=[]",
        "empty_string": "explicit: Filter.on property='' (CF-adjacent guard surface)",
        "non_bmp": "explicit: Filter.equals value '\\U0001d4b3'",
        "error_branches": "harvested: every CF/FD/LC/LG code",
    },
    "metric_group_family": {
        "integral_float": "explicit: Metric percentile_value=18.0",
        "fractional_float": "explicit: GroupBy bucket_size=1.5",
        "true": "generated: has no boolean-typed field — CohortBreakdown "
        "include_negated covers booleans in cohort_family (omission)",
        "none": "explicit: Metric property=None / TimeComparison unit=None",
        "empty_list": "explicit: Metric filters=[]",
        "empty_string": "explicit: Formula expression='' / GroupBy property=''",
        "non_bmp": "explicit: Formula label='\\U0001d4b3'",
        "error_branches": "harvested: every CM/TC/MT/FM/GB/EV code",
    },
    "cohort_family": {
        "integral_float": "explicit: has_property value=18.0",
        "fractional_float": "explicit: has_property value=1.5",
        "true": "explicit: CohortBreakdown include_negated=True",
        "none": "explicit: did_not_do_event within_days=None",
        "empty_list": "explicit: CohortDefinition criteria=[] (CD9)",
        "empty_string": "explicit: property_is_set property=''",
        "non_bmp": "explicit: has_property value '\\U0001d4b3'",
        "error_branches": "harvested: every CA/CB/CD code",
    },
    "funnel_family": {
        "integral_float": "outside typed domain (str/int fields) — documented omission",
        "fractional_float": "outside typed domain — documented omission",
        "true": "outside typed domain — documented omission",
        "none": "explicit: FunnelStep label=None / Exclusion to_step=None",
        "empty_list": "explicit: FunnelStep filters=[]",
        "empty_string": "explicit: FunnelStep event='' (FS1)",
        "non_bmp": "explicit: FunnelStep event '\\U0001d4b3'",
        "error_branches": "harvested: every FS/EX/HC code",
    },
    "retention_flow_family": {
        "integral_float": "outside typed domain — documented omission",
        "fractional_float": "outside typed domain — documented omission",
        "true": "outside typed domain (session_event is a str literal) — "
        "documented omission",
        "none": "explicit: FlowStep forward=None",
        "empty_list": "explicit: RetentionEvent filters=[]",
        "empty_string": "explicit: RetentionEvent event=''",
        "non_bmp": "explicit: FlowStep event '\\U0001d4b3'",
        "error_branches": "harvested: every FS-family code recorded on these apis",
    },
    "frequency_family": {
        "integral_float": "explicit: FrequencyFilter value=18.0",
        "fractional_float": "explicit: FrequencyFilter value=1.5",
        "true": "outside typed domain — documented omission",
        "none": "explicit: FrequencyFilter date_range_value=None",
        "empty_list": "explicit: FrequencyFilter event_filters=[]",
        "empty_string": "explicit: FrequencyBreakdown event='' (FB1)",
        "non_bmp": "explicit: FrequencyBreakdown label '\\U0001d4b3'",
        "error_branches": "harvested: every FB/FF code",
    },
    "replay_family": {
        "integral_float": "explicit: SignedReplay signed_at=18.0",
        "fractional_float": "explicit: SignedReplay signed_at=1.5",
        "true": "outside typed domain — documented omission "
        "(metadata dict carries booleans in generated draws)",
        "none": "explicit: ReplaySummary distinct_id=None",
        "empty_list": "explicit: ReplayBundle replays=[]",
        "empty_string": "explicit: ReplaySummary replay_id='' (RS1)",
        "non_bmp": "explicit: UserAction target_desc '\\U0001d4b3'",
        "error_branches": "harvested: every RS/SR/UA/RE/RP/RB code",
    },
    "codec_roundtrip": {
        "integral_float": "explicit: value=18.0 (lossless float-tag round-trip)",
        "fractional_float": "explicit: value=1.5",
        "true": "explicit: value=True",
        "none": "explicit: value=None",
        "empty_list": "explicit: value=[]",
        "empty_string": "explicit: value=''",
        "non_bmp": "explicit: value='\\U0001d4b3'",
        "error_branches": "documented omission: codec.roundtrip error "
        "branches are PROTOCOL-level (-32602/-32000, oracle-protocol.md "
        "§8) — harness-crash semantics, not comparable ok:false data",
    },
}
"""Per-family disposition of the R10.9 mandatory scalar edge items
(explicit probe, generated coverage, or documented omission)."""


# ---------------------------------------------------------------------------
# Phase-2 shared draw material
# ---------------------------------------------------------------------------

_P2_EVENTS: st.SearchStrategy[str] = st.one_of(
    st.sampled_from(("login", "Purchase Complete", "$ae_session", "signup")),
    st.just(""),  # trips the empty-event guard family on both sides
    st.text(min_size=1, max_size=16),
)
"""Event names: plausible, empty (guard-tripping), and arbitrary text."""

_P2_PROPS: st.SearchStrategy[str] = st.one_of(
    st.sampled_from(("plan", "$city", "utm source", "tier_level")),
    st.just(""),
    st.text(min_size=1, max_size=12),
)
"""Property names: plausible, empty (guard-tripping), and arbitrary."""

_P2_DATES: st.SearchStrategy[str] = st.one_of(
    st.dates(min_value=_dt.date(2020, 1, 1), max_value=_dt.date(2026, 12, 31)).map(str),
    st.sampled_from(("not-a-date", "")),
)
"""ISO dates plus malformed junk (error-branch mixing)."""

_P2_LABELS: st.SearchStrategy[str | None] = st.one_of(st.none(), st.text(max_size=10))
"""Optional display labels."""

_P2_FILTER_LISTS: st.SearchStrategy[list[Filter]] = st.lists(
    filter_strategy(), min_size=0, max_size=2
)
"""Filter lists for `filters=` kwargs (empty list included — R10.9)."""

_P2_COMBINATORS: st.SearchStrategy[str] = st.sampled_from(("all", "any"))
"""`FiltersCombinator` members (artifact-checked at import by _alias)."""

_P2_SMALL_JSON: st.SearchStrategy[Any] = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.text(max_size=8),
    ),
    lambda inner: st.one_of(
        st.lists(inner, max_size=2),
        st.dictionaries(st.text(max_size=5), inner, max_size=2),
    ),
    max_leaves=4,
)
"""Small JSON-shaped values for metadata/properties dicts."""


def _call(api: str) -> Any:
    """Build a kwargs→FuzzCall mapper for one api.

    Args:
        api: The dotted api name to attach.

    Returns:
        A callable wrapping drawn kwargs into a ``(api, kwargs)`` probe.
    """

    def wrap(kwargs: dict[str, Any]) -> FuzzCall:
        """Attach the api name to one drawn kwargs bag.

        Args:
            kwargs: The drawn keyword arguments.

        Returns:
            The ``(api, kwargs)`` probe.
        """
        return (api, kwargs)

    return wrap


def _optional(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Mix ``None`` into a value strategy (R3.9 optional-field draws).

    Args:
        strategy: The base value strategy.

    Returns:
        ``None`` or a drawn value.
    """
    return st.one_of(st.none(), strategy)


@st.composite
def _kwargs_bag(
    draw: st.DrawFn,
    required: Mapping[str, st.SearchStrategy[Any]],
    optional: Mapping[str, st.SearchStrategy[Any]],
) -> dict[str, Any]:
    """Draw a kwargs bag: required keys always, optional keys sometimes.

    Absent optional kwargs stay ABSENT (R3.5 — omitting a kwarg is a
    different recorded call than passing its default).

    Args:
        draw: Hypothesis draw function.
        required: Always-present kwargs.
        optional: Independently coin-flipped kwargs.

    Returns:
        The drawn kwargs bag (insertion order: required, then present
        optionals in table order).
    """
    bag: dict[str, Any] = {name: draw(strategy) for name, strategy in required.items()}
    for name, strategy in optional.items():
        if draw(st.booleans()):
            bag[name] = draw(strategy)
    return bag


# ---------------------------------------------------------------------------
# filter_family — types.Filter (+11 factories) + types.ListItemGroupMode
# ---------------------------------------------------------------------------


def _filter_direct_call(f: Filter) -> FuzzCall:
    """Probe the direct `types.Filter` constructor with an instance's bag.

    Args:
        f: A drawn Filter (suite strategy — all eleven operators).

    Returns:
        The ``(api, kwargs)`` probe over all 8 underscore-spelled fields.
    """
    kwargs = {field.name: getattr(f, field.name) for field in dataclasses.fields(f)}
    return ("types.Filter", kwargs)


@st.composite
def _filter_factory_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one `types.Filter.*` factory probe.

    Covers all 11 recorded factory statics with mostly-valid arguments and
    guard-tripping values (empty property, non-positive quantity, invalid
    date) mixed in.

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    kind = draw(
        st.sampled_from(
            (
                "on",
                "before",
                "since",
                "in_the_last",
                "in_the_next",
                "not_in_the_last",
                "date_between",
                "date_not_between",
                "in_cohort",
                "not_in_cohort",
                "list_contains",
            )
        )
    )
    api = f"types.Filter.{kind}"
    if kind in ("on", "before", "since"):
        bag: dict[str, Any] = {
            "property": draw(_P2_PROPS),
            "date": draw(_P2_DATES),
        }
        if draw(st.booleans()):
            bag["resource_type"] = draw(st.sampled_from(("events", "people")))
        return (api, bag)
    if kind in ("in_the_last", "in_the_next", "not_in_the_last"):
        bag = {
            "property": draw(_P2_PROPS),
            "quantity": draw(st.integers(min_value=-2, max_value=60)),
            "date_unit": draw(_alias("FilterDateUnit")),
        }
        return (api, bag)
    if kind in ("date_between", "date_not_between"):
        bag = {
            "property": draw(_P2_PROPS),
            "from_date": draw(_P2_DATES),
            "to_date": draw(_P2_DATES),
        }
        return (api, bag)
    if kind in ("in_cohort", "not_in_cohort"):
        cohort = draw(
            st.one_of(
                st.integers(min_value=-10, max_value=1_000_000),
                definition_trees(),
            )
        )
        return (api, {"cohort": cohort, "name": draw(_optional(st.text(max_size=8)))})
    # list_contains
    bag = {
        "property": draw(_P2_PROPS),
        "item_filters": draw(_P2_FILTER_LISTS),
    }
    if draw(st.booleans()):
        bag["quantifier"] = draw(st.sampled_from(("any", "all")))
    if draw(st.booleans()):
        bag[draw(st.sampled_from(("name", "sku")))] = draw(
            st.one_of(st.text(max_size=6), st.lists(st.text(max_size=4), max_size=2))
        )
    return (api, bag)


_FILTER_FAMILY = FuzzTarget(
    name="filter_family",
    calls=st.one_of(
        filter_strategy().map(_filter_direct_call),
        _filter_factory_calls(),
        _kwargs_bag(
            required={
                "sub": _P2_PROPS,
                "sub_type": st.sampled_from(
                    (*_literal_alias_values()["CustomPropertyType"], "junk")
                ),
            },
            optional={},
        ).map(_call("types.ListItemGroupMode")),
    ),
    edge_calls=(
        _filter_direct_call(Filter.greater_than("p", 1.5)),
        _filter_direct_call(Filter.is_true("p")),
        _filter_direct_call(Filter.equals("p", [])),
        _filter_direct_call(Filter.equals("p", "\U0001d4b3")),
        (
            "types.Filter.in_the_last",
            {"property": "p", "quantity": 18.0, "date_unit": "day"},
        ),
        ("types.Filter.on", {"property": "", "date": "2025-01-01"}),
        ("types.Filter.in_cohort", {"cohort": 123, "name": None}),
        ("types.Filter.list_contains", {"property": "items", "item_filters": []}),
        *_harvested_family_edges().get("filter_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# metric_group_family — Metric, CohortMetric, Formula, GroupBy, TimeComparison
# ---------------------------------------------------------------------------

_METRIC_CALLS = _kwargs_bag(
    required={"event": _P2_EVENTS},
    optional={
        "math": st.sampled_from((*_literal_alias_values()["MathType"], "bogus")),
        "property": _optional(_P2_PROPS),
        "per_user": _optional(_alias("PerUserAggregation")),
        "percentile_value": _optional(st.integers(min_value=-1, max_value=101)),
        "filters": _optional(_P2_FILTER_LISTS),
        "filters_combinator": _P2_COMBINATORS,
        "segment_method": _optional(
            st.sampled_from((*_literal_alias_values()["SegmentMethod"], "junk"))
        ),
    },
).map(_call("types.Metric"))
"""Loose `types.Metric` kwargs (valid + V13/V26/MT2 guard mixes)."""

_GROUPBY_CALLS = _kwargs_bag(
    required={"property": _P2_PROPS},
    optional={
        "property_type": st.sampled_from(
            (*_literal_alias_values()["CustomPropertyType"], "junk")
        ),
        "bucket_size": _optional(
            st.one_of(
                st.integers(min_value=-2, max_value=50),
                st.sampled_from((1.5, 18.0)),
            )
        ),
        "bucket_min": _optional(st.integers(min_value=-5, max_value=20)),
        "bucket_max": _optional(st.integers(min_value=-5, max_value=40)),
    },
).map(_call("types.GroupBy"))
"""Loose `types.GroupBy` kwargs (GB1/V12/V18 guard mixes)."""

_TIME_COMPARISON_CALLS = _kwargs_bag(
    required={
        "type": st.sampled_from(
            (*_literal_alias_values()["TimeComparisonType"], "junk")
        )
    },
    optional={
        "unit": _optional(
            st.sampled_from((*_literal_alias_values()["TimeComparisonUnit"], "junk"))
        ),
        "date": _optional(_P2_DATES),
    },
).map(_call("types.TimeComparison"))
"""Loose `types.TimeComparison` kwargs (TC0-TC7 guard mixes)."""

_METRIC_GROUP_FAMILY = FuzzTarget(
    name="metric_group_family",
    calls=st.one_of(
        _METRIC_CALLS,
        _GROUPBY_CALLS,
        _TIME_COMPARISON_CALLS,
        _kwargs_bag(
            required={
                "cohort": st.one_of(
                    st.integers(min_value=-10, max_value=1_000_000),
                    definition_trees(),
                )
            },
            optional={"name": _optional(st.text(max_size=8))},
        ).map(_call("types.CohortMetric")),
        _kwargs_bag(
            required={
                "expression": st.one_of(
                    st.sampled_from(("A/B", "(A+B)*100", "", "A*")),
                    st.text(max_size=10),
                )
            },
            optional={"label": _P2_LABELS},
        ).map(_call("types.Formula")),
    ),
    edge_calls=(
        (
            "types.Metric",
            {"event": "login", "math": "percentile", "percentile_value": 18.0},
        ),
        ("types.Metric", {"event": "login", "property": None, "filters": []}),
        ("types.GroupBy", {"property": "", "bucket_size": 1.5}),
        ("types.TimeComparison", {"type": "relative", "unit": None}),
        ("types.Formula", {"expression": "", "label": "\U0001d4b3"}),
        *_harvested_family_edges().get("metric_group_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# cohort_family — CohortCriteria factories, CohortDefinition, CohortBreakdown,
# _sanitize_raw_cohort
# ---------------------------------------------------------------------------


@st.composite
def _did_event_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one `did_event` probe: suite-valid params with guard mixes.

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    params = dict(draw(valid_did_event_params()))
    mutation = draw(st.sampled_from(("valid", "empty_event", "conflict")))
    if mutation == "empty_event":
        params["event"] = ""
    elif mutation == "conflict":
        params["at_least"] = 1
        params["at_most"] = 2
        params["exactly"] = 3
    return ("types.CohortCriteria.did_event", params)


_COHORT_CRITERIA_CALLS: st.SearchStrategy[FuzzCall] = st.one_of(
    _did_event_calls(),
    _kwargs_bag(
        required={"event": _P2_EVENTS},
        optional={
            "within_days": _optional(st.integers(min_value=-1, max_value=365)),
            "within_weeks": _optional(st.integers(min_value=1, max_value=52)),
            "from_date": _P2_DATES,
            "to_date": _P2_DATES,
        },
    ).map(_call("types.CohortCriteria.did_not_do_event")),
    _kwargs_bag(
        required={
            "property": _P2_PROPS,
            "value": st.one_of(
                st.text(max_size=8),
                st.integers(min_value=-100, max_value=100),
                st.sampled_from((1.5, 18.0, True)),
                st.lists(st.text(min_size=1, max_size=6), max_size=3),
            ),
        },
        optional={
            "operator": st.sampled_from(
                ("equals", "not_equals", "contains", "greater_than", "junk")
            ),
            "property_type": st.sampled_from(
                (*_literal_alias_values()["CustomPropertyType"], "junk")
            ),
        },
    ).map(_call("types.CohortCriteria.has_property")),
    st.integers(min_value=-5, max_value=1_000_000).map(
        lambda cid: ("types.CohortCriteria.in_cohort", {"cohort_id": cid})
    ),
    st.integers(min_value=-5, max_value=1_000_000).map(
        lambda cid: ("types.CohortCriteria.not_in_cohort", {"cohort_id": cid})
    ),
    _P2_PROPS.map(lambda p: ("types.CohortCriteria.property_is_set", {"property": p})),
    _P2_PROPS.map(
        lambda p: ("types.CohortCriteria.property_is_not_set", {"property": p})
    ),
)
"""All seven `CohortCriteria` factory probes."""

_COHORT_DEFINITION_CALLS: st.SearchStrategy[FuzzCall] = st.one_of(
    st.lists(any_criteria, min_size=0, max_size=3).map(
        lambda cs: ("types.CohortDefinition.all_of", {"criteria": cs})
    ),
    st.lists(any_criteria, min_size=0, max_size=3).map(
        lambda cs: ("types.CohortDefinition.any_of", {"criteria": cs})
    ),
    st.lists(any_criteria, min_size=0, max_size=2).map(
        lambda cs: ("types.CohortDefinition", {"criteria": cs})
    ),
    definition_trees().map(lambda d: ("types.CohortDefinition.to_dict", {"self": d})),
)
"""CohortDefinition construction + serialization probes (CD9 via [])."""

_SANITIZE_RAW_CALLS: st.SearchStrategy[FuzzCall] = _kwargs_bag(
    required={},
    optional={
        "id": st.integers(min_value=1, max_value=10_000),
        "name": st.text(max_size=8),
        "description": st.text(max_size=8),
        "count": st.integers(min_value=0, max_value=500),
        "created": st.text(max_size=10),
        "junk_key": _P2_SMALL_JSON,
    },
).map(lambda raw: ("types._sanitize_raw_cohort", {"raw": raw}))
"""`_sanitize_raw_cohort` probes over loose raw-cohort dicts."""

_COHORT_FAMILY = FuzzTarget(
    name="cohort_family",
    calls=st.one_of(
        _COHORT_CRITERIA_CALLS,
        _COHORT_DEFINITION_CALLS,
        _SANITIZE_RAW_CALLS,
        _kwargs_bag(
            required={
                "cohort": st.one_of(
                    st.integers(min_value=-10, max_value=1_000_000),
                    definition_trees(),
                )
            },
            optional={
                "name": _optional(st.text(max_size=8)),
                "include_negated": st.booleans(),
            },
        ).map(_call("types.CohortBreakdown")),
    ),
    edge_calls=(
        ("types.CohortCriteria.has_property", {"property": "p", "value": 18.0}),
        ("types.CohortCriteria.has_property", {"property": "p", "value": 1.5}),
        ("types.CohortCriteria.has_property", {"property": "p", "value": "\U0001d4b3"}),
        ("types.CohortBreakdown", {"cohort": 7, "include_negated": True}),
        (
            "types.CohortCriteria.did_not_do_event",
            {"event": "login", "within_days": None},
        ),
        ("types.CohortDefinition", {"criteria": []}),
        ("types.CohortCriteria.property_is_set", {"property": ""}),
        *_harvested_family_edges().get("cohort_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# funnel_family — FunnelStep, Exclusion, HoldingConstant
# ---------------------------------------------------------------------------

_FUNNEL_FAMILY = FuzzTarget(
    name="funnel_family",
    calls=st.one_of(
        _kwargs_bag(
            required={"event": _P2_EVENTS},
            optional={
                "label": _P2_LABELS,
                "filters": _optional(_P2_FILTER_LISTS),
                "filters_combinator": _P2_COMBINATORS,
                "order": _optional(st.text(max_size=8)),
            },
        ).map(_call("types.FunnelStep")),
        _kwargs_bag(
            required={"event": _P2_EVENTS},
            optional={
                "from_step": st.integers(min_value=-1, max_value=4),
                "to_step": _optional(st.integers(min_value=-1, max_value=5)),
            },
        ).map(_call("types.Exclusion")),
        _kwargs_bag(
            required={"property": _P2_PROPS},
            optional={"resource_type": st.sampled_from(("events", "people"))},
        ).map(_call("types.HoldingConstant")),
    ),
    edge_calls=(
        ("types.FunnelStep", {"event": "login", "label": None, "filters": []}),
        ("types.FunnelStep", {"event": ""}),
        ("types.FunnelStep", {"event": "\U0001d4b3"}),
        ("types.Exclusion", {"event": "login", "from_step": 0, "to_step": None}),
        *_harvested_family_edges().get("funnel_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# retention_flow_family — RetentionEvent, FlowStep
# ---------------------------------------------------------------------------

_RETENTION_FLOW_FAMILY = FuzzTarget(
    name="retention_flow_family",
    calls=st.one_of(
        _kwargs_bag(
            required={"event": _P2_EVENTS},
            optional={
                "filters": _optional(_P2_FILTER_LISTS),
                "filters_combinator": _P2_COMBINATORS,
            },
        ).map(_call("types.RetentionEvent")),
        _kwargs_bag(
            required={"event": _P2_EVENTS},
            optional={
                "forward": _optional(st.integers(min_value=-1, max_value=5)),
                "reverse": _optional(st.integers(min_value=-1, max_value=5)),
                "label": _P2_LABELS,
                "filters": _optional(_P2_FILTER_LISTS),
                "filters_combinator": _P2_COMBINATORS,
                "session_event": _optional(st.sampled_from(("start", "end", "junk"))),
            },
        ).map(_call("types.FlowStep")),
    ),
    edge_calls=(
        ("types.RetentionEvent", {"event": "login", "filters": []}),
        ("types.RetentionEvent", {"event": ""}),
        ("types.FlowStep", {"event": "login", "forward": None}),
        ("types.FlowStep", {"event": "\U0001d4b3"}),
        *_harvested_family_edges().get("retention_flow_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# frequency_family — FrequencyBreakdown, FrequencyFilter
# ---------------------------------------------------------------------------

_FREQUENCY_FAMILY = FuzzTarget(
    name="frequency_family",
    calls=st.one_of(
        _kwargs_bag(
            required={"event": _P2_EVENTS},
            optional={
                "bucket_size": st.integers(min_value=-1, max_value=20),
                "bucket_min": st.integers(min_value=-2, max_value=5),
                "bucket_max": st.integers(min_value=-2, max_value=30),
                "label": _P2_LABELS,
            },
        ).map(_call("types.FrequencyBreakdown")),
        _kwargs_bag(
            required={
                "event": _P2_EVENTS,
                "value": st.one_of(
                    st.integers(min_value=-2, max_value=50),
                    st.sampled_from((1.5, 18.0)),
                ),
            },
            optional={
                "operator": st.sampled_from(
                    (*_literal_alias_values()["FrequencyFilterOperator"], "junk")
                ),
                "date_range_value": _optional(st.integers(min_value=-1, max_value=90)),
                "date_range_unit": _optional(st.sampled_from(("day", "week", "month"))),
                "event_filters": _optional(_P2_FILTER_LISTS),
                "label": _P2_LABELS,
            },
        ).map(_call("types.FrequencyFilter")),
    ),
    edge_calls=(
        ("types.FrequencyFilter", {"event": "login", "value": 18.0}),
        ("types.FrequencyFilter", {"event": "login", "value": 1.5}),
        (
            "types.FrequencyFilter",
            {"event": "login", "value": 3, "date_range_value": None},
        ),
        ("types.FrequencyFilter", {"event": "login", "value": 3, "event_filters": []}),
        ("types.FrequencyBreakdown", {"event": ""}),
        ("types.FrequencyBreakdown", {"event": "login", "label": "\U0001d4b3"}),
        *_harvested_family_edges().get("frequency_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# replay_family — ReplaySummary, SignedReplay, UserAction, ReplayEvent,
# Replay, ReplayBundle
# ---------------------------------------------------------------------------

_REPLAY_IDS: st.SearchStrategy[str] = st.one_of(
    st.just(""), st.uuids().map(str), st.text(min_size=1, max_size=12)
)
"""Replay ids: empty (RS1/RE1/RP1 guard) + plausible."""

_RETENTION_DAYS: st.SearchStrategy[int] = st.sampled_from((1, 7, 30, 90, 2, -1))
"""Retention days: the valid closed set plus invalid members."""

_VALID_USER_ACTIONS: st.SearchStrategy[UserAction] = st.builds(
    UserAction,
    timestamp=st.integers(min_value=1, max_value=10**12),
    action=st.sampled_from(
        ("click", "input", "scroll", "navigate", "select", "console_error")
    ),
    target_node_id=_optional(st.integers(min_value=1, max_value=500)),
    target_desc=st.text(min_size=1, max_size=8),
    url=_optional(st.text(max_size=12)),
)
"""Always-constructible UserAction instances (nested-field material)."""

_VALID_REPLAY_EVENTS: st.SearchStrategy[ReplayEvent] = st.builds(
    ReplayEvent,
    replay_id=st.text(min_size=1, max_size=8),
    event_name=st.text(min_size=1, max_size=8),
    event_time=st.integers(min_value=1, max_value=10**9),
    properties=_optional(
        st.dictionaries(st.text(max_size=5), _P2_SMALL_JSON, max_size=2)
    ),
)
"""Always-constructible ReplayEvent instances (nested-field material)."""


@st.composite
def _valid_replays(draw: st.DrawFn, project_id: int | None = None) -> Replay:
    """Draw one always-constructible Replay.

    Args:
        draw: Hypothesis draw function.
        project_id: Fixed owning project (drawn when ``None``) — lets the
            bundle strategy hold RB1's project-id invariant.

    Returns:
        A valid Replay instance.
    """
    pid = (
        project_id
        if project_id is not None
        else draw(st.integers(min_value=1, max_value=10**6))
    )
    start = draw(st.integers(min_value=1, max_value=10**12))
    return Replay(
        replay_id=draw(st.text(min_size=1, max_size=8)),
        distinct_id=draw(_optional(st.text(max_size=8))),
        project_id=pid,
        start_time=start,
        end_time=start + draw(st.integers(min_value=0, max_value=10**6)),
        retention_days=draw(st.sampled_from((1, 7, 30, 90))),
        rrweb_events=draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        "type": st.integers(min_value=0, max_value=6),
                        "timestamp": st.integers(min_value=1, max_value=10**12),
                    }
                ),
                max_size=2,
            )
        ),
        actions=draw(st.lists(_VALID_USER_ACTIONS, max_size=2)),
        mixpanel_events=draw(st.lists(_VALID_REPLAY_EVENTS, max_size=2)),
    )


@st.composite
def _replay_bundle_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one `types.ReplayBundle` probe (valid + RB1-tripping mixes).

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    pid = draw(st.integers(min_value=1, max_value=10**6))
    replays = draw(st.lists(_valid_replays(project_id=pid), max_size=2))
    declared = pid if draw(st.booleans()) else pid + 1  # mismatch trips RB1
    return (
        "types.ReplayBundle",
        {
            "replays": replays,
            "computed_at": draw(st.text(max_size=10)),
            "project_id": declared,
        },
    )


@st.composite
def _replay_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one loose `types.Replay` probe (RP1-RP5 guard mixes).

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    start = draw(st.integers(min_value=-2, max_value=10**12))
    return (
        "types.Replay",
        {
            "replay_id": draw(_REPLAY_IDS),
            "distinct_id": draw(_optional(st.text(max_size=8))),
            "project_id": draw(st.integers(min_value=-1, max_value=10**6)),
            "start_time": start,
            "end_time": start + draw(st.integers(min_value=-5, max_value=10**6)),
            "retention_days": draw(_RETENTION_DAYS),
            "actions": draw(st.lists(_VALID_USER_ACTIONS, max_size=1)),
            "mixpanel_events": draw(st.lists(_VALID_REPLAY_EVENTS, max_size=1)),
        },
    )


_REPLAY_FAMILY = FuzzTarget(
    name="replay_family",
    calls=st.one_of(
        _kwargs_bag(
            required={
                "replay_id": _REPLAY_IDS,
                "distinct_id": _optional(st.text(max_size=8)),
                "project_id": st.integers(min_value=-1, max_value=10**6),
                "start_time": st.integers(min_value=-2, max_value=10**12),
                "retention_days": _RETENTION_DAYS,
            },
            optional={},
        ).map(_call("types.ReplaySummary")),
        _kwargs_bag(
            required={
                "replay_id": _REPLAY_IDS,
                "url": st.sampled_from(
                    ("https://cdn.mxpnl.com/r/", "https://cdn.mxpnl.com/r", "")
                ),
                "query_string": st.one_of(
                    st.just(""), st.text(min_size=1, max_size=10)
                ),
                "env": st.sampled_from(("prod", "dev", "stage")),
                "signed_at": st.one_of(
                    st.integers(min_value=-10, max_value=2**31).map(float),
                    st.sampled_from((1.5, 18.0)),
                ),
            },
            optional={},
        ).map(_call("types.SignedReplay")),
        _kwargs_bag(
            required={
                "timestamp": st.integers(min_value=-2, max_value=10**13),
                "action": st.sampled_from(
                    ("click", "input", "scroll", "navigate", "console_error")
                ),
                "target_node_id": _optional(st.integers(min_value=1, max_value=500)),
                "target_desc": st.one_of(st.just(""), st.text(min_size=1, max_size=8)),
                "url": _optional(st.text(max_size=10)),
            },
            optional={
                "metadata": st.dictionaries(
                    st.text(max_size=5), _P2_SMALL_JSON, max_size=2
                ),
                "description": st.text(max_size=10),
            },
        ).map(_call("types.UserAction")),
        _kwargs_bag(
            required={
                "replay_id": _REPLAY_IDS,
                "event_name": _P2_EVENTS,
                "event_time": st.integers(min_value=-2, max_value=10**9),
            },
            optional={
                "properties": _optional(
                    st.dictionaries(st.text(max_size=5), _P2_SMALL_JSON, max_size=2)
                ),
            },
        ).map(_call("types.ReplayEvent")),
        _replay_calls(),
        _replay_bundle_calls(),
    ),
    edge_calls=(
        (
            "types.SignedReplay",
            {
                "replay_id": "r",
                "url": "https://c/",
                "query_string": "q",
                "env": "prod",
                "signed_at": 18.0,
            },
        ),
        (
            "types.SignedReplay",
            {
                "replay_id": "r",
                "url": "https://c/",
                "query_string": "q",
                "env": "prod",
                "signed_at": 1.5,
            },
        ),
        (
            "types.ReplaySummary",
            {
                "replay_id": "",
                "distinct_id": None,
                "project_id": 1,
                "start_time": 1,
                "retention_days": 7,
            },
        ),
        ("types.ReplayBundle", {"replays": [], "computed_at": "", "project_id": 0}),
        (
            "types.UserAction",
            {
                "timestamp": 1,
                "action": "click",
                "target_node_id": None,
                "target_desc": "\U0001d4b3",
                "url": None,
            },
        ),
        *_harvested_family_edges().get("replay_family", ()),
    ),
)

# ---------------------------------------------------------------------------
# codec_roundtrip — protocol 1.1 §8: the codec table as a fuzz surface
# ---------------------------------------------------------------------------


def _construct_for_roundtrip(api: str, kwargs: dict[str, Any]) -> object:
    """Invoke one registry api locally to build a round-trip instance.

    Resolves and binds EXACTLY like the oracle/corpus runner
    (``_resolve_builder_target`` + ``_bind_variadic``) so the instance
    universe matches the call surface.

    Args:
        api: The dotted registry api name.
        kwargs: RAW Python kwargs for the call.

    Returns:
        The constructed library value.

    Raises:
        KeyError: If the api is not registered (a table bug).
        Exception: Whatever the target raises for invalid draws (the
            caller converts failures into ``assume``-rejections).
    """
    from conformance.record.registry import REGISTRY_BY_API
    from conformance.runner.execute import (
        _bind_variadic,
        _resolve_builder_target,
    )

    entry = REGISTRY_BY_API[api]
    decoded = dict(kwargs)
    target = _resolve_builder_target(entry, decoded)
    args, bound = _bind_variadic(target, decoded)
    return target(*args, **bound)


@st.composite
def _roundtrip_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one `codec.roundtrip` probe over a VALID library instance.

    Draws an ``(api, kwargs)`` probe from the seven family strategies,
    constructs the instance locally, and rejects guard-tripping draws
    (round-trip decode failures are protocol errors by design — §8 — so
    only constructible instances cross the bridge).

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(codec.roundtrip, {"value": instance})`` probe.
    """
    api, kwargs = draw(
        st.one_of(
            _FILTER_FAMILY.calls,
            _METRIC_GROUP_FAMILY.calls,
            _COHORT_FAMILY.calls,
            _FUNNEL_FAMILY.calls,
            _RETENTION_FLOW_FAMILY.calls,
            _FREQUENCY_FAMILY.calls,
            _REPLAY_FAMILY.calls,
        )
    )
    try:
        value = _construct_for_roundtrip(api, dict(kwargs))
    except Exception:  # noqa: BLE001 - ANY construction failure rejects the
        # draw (guards raise coded errors, but loose draws can also trip
        # uncoded raises — e.g. has_property's bare KeyError on an unknown
        # operator, R5.5-excluded); the CALL targets fuzz those branches.
        assume(False)
        raise  # pragma: no cover - assume(False) always raises
    return (CODEC_ROUNDTRIP_API, {"value": value})


_CODEC_ROUNDTRIP = FuzzTarget(
    name="codec_roundtrip",
    calls=_roundtrip_calls(),
    edge_calls=(
        (CODEC_ROUNDTRIP_API, {"value": 18.0}),
        (CODEC_ROUNDTRIP_API, {"value": 1.5}),
        (CODEC_ROUNDTRIP_API, {"value": True}),
        (CODEC_ROUNDTRIP_API, {"value": None}),
        (CODEC_ROUNDTRIP_API, {"value": []}),
        (CODEC_ROUNDTRIP_API, {"value": ""}),
        (CODEC_ROUNDTRIP_API, {"value": "\U0001d4b3"}),
        (CODEC_ROUNDTRIP_API, {"value": Filter.equals("plan", "pro")}),
        (
            CODEC_ROUNDTRIP_API,
            {"value": _dt.datetime(2026, 1, 15, 12, 0, 0, tzinfo=_dt.timezone.utc)},
        ),
        (CODEC_ROUNDTRIP_API, {"value": _dt.date(2026, 1, 15)}),
        (CODEC_ROUNDTRIP_API, {"value": b"\x00\x01replay"}),
        (CODEC_ROUNDTRIP_API, {"value": SecretStr("s3cr3t-token")}),
    ),
)

PHASE2_TARGETS: tuple[FuzzTarget, ...] = (
    _FILTER_FAMILY,
    _METRIC_GROUP_FAMILY,
    _COHORT_FAMILY,
    _FUNNEL_FAMILY,
    _RETENTION_FLOW_FAMILY,
    _FREQUENCY_FAMILY,
    _REPLAY_FAMILY,
    _CODEC_ROUNDTRIP,
)
"""The Phase-2 P2-9 differential-gate targets (phase2-design C9), in
C10 packet order: the seven `types.*` api families plus the protocol-1.1
`codec.roundtrip` surface."""


# ============================================================================
# Phase-3 targets (P3-4 packet B0-1) - the pythonCompat completion wrappers.
#
# One target per api family so the playbook's ">=500 examples per api
# family" budget is a per-target `--examples` knob. String inputs are
# biased toward the CPython parse grammar's live edges: digits with
# underscores, hex-ish prefixes, float-ish forms, non-ASCII decimal
# digits, the two pinned whitespace sets (including the U+001C..U+001F
# isspace-vs-numeric trap and U+FEFF), and inf/nan casings.
# ============================================================================

_UNICODE_DIGIT_STRINGS: tuple[str, ...] = (
    "\u0664\u0662",  # Arabic-Indic 42
    "\u0967_\u0966",  # Devanagari 1_0 (underscore between Nd digits)
    "\uff14\uff12",  # fullwidth 42
    "-\u0e51\u0e52\u0e53",  # Thai -123
    "\U0001d7d9\U0001d7da",  # non-BMP double-struck 12
    "\u00b2",  # superscript two: digit-like but NOT decimal (rejects)
    "\u3007",  # ideographic zero: numeric but NOT decimal (rejects)
)
"""Non-ASCII digit probes (accepting and rejecting members both biased)."""

_WS_WRAP_CHARS: tuple[str, ...] = (
    "",
    " ",
    "\t",
    "\n",
    "\x85",
    "\xa0",
    "\u2003",
    "\u3000",
    "\x1c",  # isspace-true but numeric-parse-REJECTED (the B0 trap)
    "\ufeff",  # JS-trim-only; Python always rejects/keeps
)
"""Whitespace-wrap universe: pinned members of BOTH sets plus the traps."""


@st.composite
def _wrapped_numeric_text(draw: st.DrawFn, core: st.SearchStrategy[str]) -> str:
    """Wrap a drawn numeric core with drawn whitespace-universe members.

    Args:
        draw: The Hypothesis draw function.
        core: Strategy for the numeric core text.

    Returns:
        ``left + core + right``.
    """
    left = draw(st.sampled_from(_WS_WRAP_CHARS))
    right = draw(st.sampled_from(_WS_WRAP_CHARS))
    return left + draw(core) + right


_INT_CORE: st.SearchStrategy[str] = st.one_of(
    # Crosses the 2^53 policy boundary in both directions.
    st.integers(min_value=-(2**53) - 10, max_value=2**53 + 10).map(str),
    st.from_regex(r"[+-]?[0-9_]{1,24}", fullmatch=True),
    st.from_regex(r"0[xob][0-9a-fA-F]{1,6}", fullmatch=True),
    st.sampled_from(_UNICODE_DIGIT_STRINGS),
    st.text(alphabet="0123456789_+-. eE", max_size=12),
    st.text(max_size=8),
)
"""Digit-biased core universe for ``python_int`` probes."""

_FLOAT_CORE: st.SearchStrategy[str] = st.one_of(
    st.floats(allow_nan=False, allow_infinity=False).map(repr),
    st.floats(allow_nan=False, allow_infinity=False).map(str),
    st.from_regex(
        r"[+-]?([0-9_]{1,8})?(\.([0-9_]{1,8})?)?([eE][+-]?[0-9_]{1,4})?",
        fullmatch=True,
    ),
    st.from_regex(r"[+-]?(?i:inf|infinity|nan|in|infinit|nans)", fullmatch=True),
    st.sampled_from(_UNICODE_DIGIT_STRINGS),
    st.sampled_from(("1e400", "-1e400", "1e-400", "9" * 400)),
    st.text(max_size=8),
)
"""Grammar-adjacent core universe for ``python_float`` probes."""


def _python_int_call(value: str) -> FuzzCall:
    """Wrap one drawn string as a ``python_int`` probe.

    Args:
        value: The drawn literal.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.python_int", {"value": value})


def _python_float_call(value: str) -> FuzzCall:
    """Wrap one drawn string as a ``python_float`` probe.

    Args:
        value: The drawn literal.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.python_float", {"value": value})


_PYTHON_INT = FuzzTarget(
    name="python_int",
    calls=_wrapped_numeric_text(_INT_CORE).map(_python_int_call),
    # R10.9 edge items outside the str input domain (True/None/empty
    # list/raw floats) are inapplicable - documented omission (module
    # rule, normalize_on_expression precedent). Error branches: invalid
    # literal + unsafe magnitude (the wrapper's full code set).
    edge_calls=(
        ("compat.python_int", {"value": ""}),  # R10.9: empty string + error
        ("compat.python_int", {"value": "\U0001d4b3"}),  # R10.9: non-BMP + error
        ("compat.python_int", {"value": "42"}),
        ("compat.python_int", {"value": "-1_0"}),
        ("compat.python_int", {"value": "  1_5  "}),
        ("compat.python_int", {"value": "\x1c42\x1f"}),  # error: isspace trap
        ("compat.python_int", {"value": "\ufeff42"}),  # error: BOM
        ("compat.python_int", {"value": "\u0664\u0662"}),  # Nd digits
        ("compat.python_int", {"value": "5.5"}),  # error: float form
        ("compat.python_int", {"value": "0x5"}),  # error: hex prefix
        ("compat.python_int", {"value": "9007199254740991"}),
        ("compat.python_int", {"value": "9007199254740992"}),  # error: unsafe
        ("compat.python_int", {"value": "-9007199254740992"}),  # error: unsafe
    ),
)

_PYTHON_FLOAT = FuzzTarget(
    name="python_float",
    calls=_wrapped_numeric_text(_FLOAT_CORE).map(_python_float_call),
    # Same str-domain omissions as python_int. Error branch: invalid
    # literal (overflow is NOT an error - it returns the inf sentinel).
    edge_calls=(
        ("compat.python_float", {"value": ""}),  # R10.9: empty string + error
        ("compat.python_float", {"value": "\U0001d4b3"}),  # R10.9: non-BMP + error
        ("compat.python_float", {"value": "18.0"}),  # R10.9: integral float
        ("compat.python_float", {"value": "1.5"}),  # R10.9: fractional float
        ("compat.python_float", {"value": "-0.0"}),  # sign-preserving zero
        ("compat.python_float", {"value": "5."}),
        ("compat.python_float", {"value": ".5"}),
        ("compat.python_float", {"value": "."}),  # error: bare dot
        ("compat.python_float", {"value": "1_0e1_0"}),
        ("compat.python_float", {"value": "1._5"}),  # error: underscore
        ("compat.python_float", {"value": "-iNf"}),  # sentinel: -inf
        ("compat.python_float", {"value": "+nAn"}),  # sentinel: nan
        ("compat.python_float", {"value": "1e400"}),  # sentinel via overflow
        ("compat.python_float", {"value": "\u0661\u0662.\u0663\u0664"}),  # Nd
    ),
)


def _python_strip_call(value: str) -> FuzzCall:
    """Wrap one drawn string as a ``python_strip`` probe.

    Args:
        value: The drawn string.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.python_strip", {"value": value})


_PYTHON_STRIP = FuzzTarget(
    name="python_strip",
    calls=_wrapped_numeric_text(st.text(max_size=10)).map(_python_strip_call),
    # str-domain omissions as above; total function - no error branch
    # (documented omission).
    edge_calls=(
        ("compat.python_strip", {"value": ""}),  # R10.9: empty string
        ("compat.python_strip", {"value": "\U0001d4b3"}),  # R10.9: non-BMP
        ("compat.python_strip", {"value": " \U0001d4b3 "}),
        ("compat.python_strip", {"value": "\x1chi\x1f"}),  # Python-only strip
        ("compat.python_strip", {"value": "\ufeffhi\ufeff"}),  # JS-only trim
        ("compat.python_strip", {"value": " \t\u3000\x1c"}),  # all-whitespace
        ("compat.python_strip", {"value": "  a \t b  "}),  # interior kept
    ),
)

_SURROGATE_ADJACENT_TEXT: st.SearchStrategy[str] = st.text(
    alphabet=st.one_of(
        st.characters(max_codepoint=0x7F),
        st.characters(min_codepoint=0xD000, max_codepoint=0xD7FF),
        st.characters(min_codepoint=0xE000, max_codepoint=0xFFFF),
        st.characters(min_codepoint=0x10000, max_codepoint=0x10FFFF),
    ),
    max_size=6,
)
"""Strings biased around the surrogate range (R11.5: the UTF-16-unit-order
vs codepoint-order divergence lives at BMP >= U+E000 vs non-BMP)."""


def _sorted_strings_call(values: list[str]) -> FuzzCall:
    """Wrap one drawn string list as a ``sorted_strings`` probe.

    Args:
        values: The drawn list.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.sorted_strings", {"values": values})


_SORTED_STRINGS = FuzzTarget(
    name="sorted_strings",
    calls=st.lists(_SURROGATE_ADJACENT_TEXT, max_size=8).map(_sorted_strings_call),
    # List-of-str domain: True/None/float items inapplicable (documented
    # omission); total function - no error branch.
    edge_calls=(
        ("compat.sorted_strings", {"values": []}),  # R10.9: empty list
        ("compat.sorted_strings", {"values": [""]}),  # R10.9: empty string
        ("compat.sorted_strings", {"values": ["\U0001f600", "\uff61"]}),  # inversion
        ("compat.sorted_strings", {"values": ["\U0001d4b3", "\U0001d4b2", "z"]}),
        ("compat.sorted_strings", {"values": ["abc", "ab", "a", ""]}),  # prefixes
        ("compat.sorted_strings", {"values": ["b", "a", "b", "a"]}),  # stability
        ("compat.sorted_strings", {"values": ["True", "None", "18.0", "1.5"]}),
    ),
)


def _cp_length_call(value: str) -> FuzzCall:
    """Wrap one drawn string as a ``cp_length`` probe.

    Args:
        value: The drawn string.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return ("compat.cp_length", {"value": value})


_CP_LENGTH_TARGET = FuzzTarget(
    name="cp_length",
    calls=_SURROGATE_ADJACENT_TEXT.map(_cp_length_call),
    # str domain; total function - no error branch (documented omission).
    edge_calls=(
        ("compat.cp_length", {"value": ""}),  # R10.9: empty string
        ("compat.cp_length", {"value": "\U0001d4b3"}),  # R10.9: non-BMP
        ("compat.cp_length", {"value": "a\U0001d4b3b\U0001f600"}),
        ("compat.cp_length", {"value": "True"}),
    ),
)


@st.composite
def _cp_slice_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one ``cp_slice`` probe with optional/None/absent bounds.

    Bounds are drawn small (|i| <= 12) so clamping, negatives, and the
    non-BMP cut points are all dense; absent and explicit-``None``
    spellings are both exercised (the tri-state rig note: for this api
    they are the same Python ``None``).

    Returns:
        The ``(api, kwargs)`` probe.
    """
    value = draw(_SURROGATE_ADJACENT_TEXT)
    kwargs: dict[str, Any] = {"value": value}
    bound = st.one_of(st.none(), st.integers(min_value=-12, max_value=12))
    if draw(st.booleans()):
        kwargs["start"] = draw(bound)
    if draw(st.booleans()):
        kwargs["end"] = draw(bound)
    return ("compat.cp_slice", kwargs)


_CP_SLICE_TARGET = FuzzTarget(
    name="cp_slice",
    calls=_cp_slice_calls(),
    # str + int|None domain; slicing is total over it (documented
    # omission of the error-branch item - the non-int TypeError guard is
    # unreachable through vector JSON, which has no non-integral index
    # spelling that decodes to a Python int slot).
    edge_calls=(
        ("compat.cp_slice", {"value": ""}),  # R10.9: empty string
        ("compat.cp_slice", {"value": "\U0001d4b3", "start": 0, "end": 1}),
        ("compat.cp_slice", {"value": "a\U0001d4b3b", "start": 0, "end": 2}),
        ("compat.cp_slice", {"value": "a\U0001d4b3b", "start": -2}),
        ("compat.cp_slice", {"value": "hello", "start": 3, "end": 2}),
        ("compat.cp_slice", {"value": "abc", "start": -500, "end": 500}),
        ("compat.cp_slice", {"value": "hello", "start": None, "end": None}),
        ("compat.cp_slice", {"value": "hello", "end": -1}),
    ),
)

# ---------------------------------------------------------------------------
# Phase-3 B0-2: api_client._iter_jsonl_lines chunk probes (P3-4 packet B0-2)
# ---------------------------------------------------------------------------

_JSONL_LINE_TEXT: st.SearchStrategy[str] = st.one_of(
    st.builds(
        lambda k, v: json.dumps({k: v}),
        st.text(max_size=4),
        st.one_of(
            st.integers(-100, 100),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(max_size=6),
        ),
    ),
    st.text(max_size=10),  # arbitrary text incl. non-BMP / whitespace-ish
    st.sampled_from(("18.0", "1.5", "True", "None", "\U0001d4b3", "")),
    st.sampled_from((" ", "\t", "\x1c", "\x1d\x1e\x1f", "\ufeff")),  # strip set
)
"""One JSONL line's text: JSON-ish, arbitrary unicode, R10.9 literals, and
Python-whitespace-only lines (the ``str.strip()`` vs ``trim()`` trap)."""


@st.composite
def _jsonl_chunks_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one ``api_client._iter_jsonl_lines`` chunk probe.

    Builds a newline-joined payload from drawn lines (LF/CRLF/blank
    terminators, optional missing final newline), optionally injects raw
    invalid-UTF-8 bytes (the ``errors="replace"`` decode contract), splits
    the byte payload at arbitrary positions (chunk boundaries — including
    mid-codepoint — ARE the contract, design D2), and optionally gzips the
    whole payload before splitting (httpx decodes via the
    ``content-encoding: gzip`` header; the TS binding decompresses the
    same way). Invalid-gzip bodies are deliberately NOT generated: a
    corrupted stream raises transport-layer errors with runtime-specific
    classes on both sides (httpx.DecodingError vs the WHATWG
    DecompressionStream error) — a transport concern outside the library
    contract (documented omission per the module rules).

    Returns:
        The ``(api, kwargs)`` probe.
    """
    lines = draw(st.lists(_JSONL_LINE_TEXT, max_size=6))
    terminator = draw(st.sampled_from(("\n", "\r\n")))
    payload = "".join(f"{line}{terminator}" for line in lines)
    if draw(st.booleans()) and payload.endswith(terminator):
        payload = payload[: -len(terminator)]  # final line without newline
    data = payload.encode("utf-8")
    if draw(st.booleans()):
        # Raw byte injection: invalid UTF-8 must decode with replacement,
        # never raise (Python errors="replace" == TextDecoder non-fatal).
        position = draw(st.integers(0, len(data)))
        junk = draw(st.binary(min_size=1, max_size=4))
        data = data[:position] + junk + data[position:]
    headers: dict[str, str] | None = None
    if draw(st.booleans()):
        data = gzip.compress(data, mtime=0)
        headers = {"content-encoding": "gzip"}
    cuts = sorted(
        draw(st.lists(st.integers(0, max(len(data), 0)), max_size=4)),
    )
    chunks: list[bytes] = []
    previous = 0
    for cut in [*cuts, len(data)]:
        chunks.append(data[previous:cut])
        previous = cut
    kwargs: dict[str, Any] = {"chunks": chunks}
    if headers is not None:
        kwargs["headers"] = headers
    return ("api_client._iter_jsonl_lines", kwargs)


_JSONL_CHUNKS = FuzzTarget(
    name="jsonl_chunks",
    calls=_jsonl_chunks_calls(),
    # bytes-domain edge set: the R10.9 literals ride as LINE CONTENT
    # (integral float / fractional float / True / None / empty string /
    # non-BMP); "empty list" maps to the empty chunk list. Total function
    # over well-formed transports — no reachable coded error branch
    # (invalid gzip is a transport error, documented omission above).
    edge_calls=(
        ("api_client._iter_jsonl_lines", {"chunks": []}),  # R10.9: empty list
        ("api_client._iter_jsonl_lines", {"chunks": [b""]}),  # empty chunk
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b'\n\n{"a": 1}\n \n{"b": 2}\n']},  # blank lines skip
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b'{"a": 1}\r\n{"b": 2}\r\n']},  # CRLF strip
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b'{"a": 1}\n{"b', b'": 2}']},  # split + no final \n
        ),
        (
            "api_client._iter_jsonl_lines",
            # 😀 (f0 9f 98 80) split mid-codepoint across chunks.
            {"chunks": [b'{"emoji": "\xf0\x9f', b'\x98\x80"}\n']},
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b"18.0\n1.5\nTrue\nNone\n\xf0\x9d\x92\xb3\n"]},
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b"\x1c\n", b"a\x1c\n"]},  # Python strip set
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b"a\xffb\n"]},  # invalid UTF-8 -> replacement
        ),
        (
            "api_client._iter_jsonl_lines",
            {"chunks": [b"x\xed\xa0\x80y\n"]},  # encoded-surrogate bytes
        ),
        (
            "api_client._iter_jsonl_lines",
            {
                "chunks": [
                    gzip.compress(b'{"a": 1}\n{"b": 2}\n{"c": 3}\n', mtime=0)[:10],
                    gzip.compress(b'{"a": 1}\n{"b": 2}\n{"c": 3}\n', mtime=0)[10:],
                ],
                "headers": {"content-encoding": "gzip"},
            },
        ),
    ),
)


PHASE3_TARGETS: tuple[FuzzTarget, ...] = (
    _PYTHON_INT,
    _PYTHON_FLOAT,
    _PYTHON_STRIP,
    _SORTED_STRINGS,
    _CP_LENGTH_TARGET,
    _CP_SLICE_TARGET,
    _JSONL_CHUNKS,
)
"""The Phase-3 B0 targets: the B0-1 pythonCompat completion families plus
the B0-2 ``api_client._iter_jsonl_lines`` chunk adapter (P3-4 packets; the
>=500-example budget applies per target)."""


ALL_TARGETS: tuple[FuzzTarget, ...] = (
    *PHASE1_TARGETS,
    *PHASE2_TARGETS,
    *PHASE3_TARGETS,
)
"""Every registered fuzz target (Phases 1-3), in phase order."""

TARGETS_BY_NAME: dict[str, FuzzTarget] = {target.name: target for target in ALL_TARGETS}
"""Lookup for the harness ``--targets`` selector."""
