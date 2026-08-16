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
from typing import Any, Literal, cast

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
    CohortBreakdown,
    CohortCriteria,
    CohortDefinition,
    CohortMetric,
    CustomPropertyRef,
    Exclusion,
    Filter,
    Formula,
    FrequencyBreakdown,
    FrequencyFilter,
    GroupBy,
    InlineCustomProperty,
    ListItemGroupMode,
    Metric,
    PropertyInput,
    Replay,
    ReplayEvent,
    TimeComparison,
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


def _filter_calls(
    api: str, filters: st.SearchStrategy[Filter] | None = None
) -> st.SearchStrategy[FuzzCall]:
    """Build a single-Filter call strategy for one translation api.

    Args:
        api: The dotted registry name taking a single ``f: Filter`` kwarg.
        filters: Optional Filter source. Defaults to the imported suite
            strategy; the B3-K4 selector targets widen it with
            :func:`_escaping_filters` (b3-packets.md §"R10.9 harness spec
            (K4)" — the MANDATORY adversarial escaping extension).

    Returns:
        A strategy of ``(api, {"f": <Filter>})`` probes.
    """
    source = filter_strategy() if filters is None else filters

    def make(f: Filter) -> FuzzCall:
        """Wrap one drawn Filter as a probe call.

        Args:
            f: The drawn Filter.

        Returns:
            The ``(api, kwargs)`` probe.
        """
        return (api, {"f": f})

    return source.map(make)


def _filter_edges(api: str) -> tuple[FuzzCall, ...]:
    """Attach the shared edge Filters to one translation api.

    Args:
        api: The dotted registry name taking a single ``f: Filter`` kwarg.

    Returns:
        One edge probe per :data:`_EDGE_FILTERS` member.
    """
    return tuple((api, {"f": f}) for f in _EDGE_FILTERS)


# ---------------------------------------------------------------------------
# B3-K4 escaping-biased Filter material (b3-packets.md §"R10.9 harness spec
# (K4)": "Adversarial escaping extension (MANDATORY)")
#
# The imported ``filter_strategy`` draws alphanumeric property names and
# `L`/`N`/`Zs` values on purpose — its own suite counts operator substrings.
# The selector path is semantic-trap watchlist #2 (escaping is char-for-char
# contract, no canonicalizer rescue), so the two ``user_builders`` selector
# targets draw from that strategy UNION the escaping-biased one below.
# ---------------------------------------------------------------------------

_ESCAPE_FRAGMENTS: tuple[str, ...] = (
    "",
    "a",
    "plan",
    "$city",
    "with space",
    "\\",  # lone backslash
    "\\\\",  # doubled backslash
    "a\\",  # trailing backslash
    '"',  # bare quote
    '\\"',  # escaped-quote sequence
    '\\\\"',  # backslash-quote compound
    "'",  # single quote
    "' or '",  # operator-injection shape
    "' and '",
    'properties["',  # selector-injection shape (accessor text)
    'properties["x"] == "y"',
    "\n",
    "\t",
    "\r",
    "\U0001d4b3",  # non-BMP
    "\U0001f389️",  # emoji + variation selector
    "é",  # combining mark
    "﻿",  # BOM
    "​",  # zero-width space
    "日本語",
)
"""Fragment alphabet for the K4 escaping bias (packet list, verbatim)."""

_ESCAPING_TEXT: st.SearchStrategy[str] = st.lists(
    st.sampled_from(_ESCAPE_FRAGMENTS), min_size=0, max_size=4
).map("".join)
"""Strings assembled from :data:`_ESCAPE_FRAGMENTS`."""

_ESCAPING_NUMBERS: st.SearchStrategy[int | float | bool] = st.sampled_from(
    (0, 1, -10, 18.0, 1.5, -0.0, 9.99, 1e16, 1e-5, True, False)
)
"""Numeric bias: integral floats, ``-0.0``, the ``pythonFloatStr`` exponent
switch points, and booleans (Python ``bool`` IS an ``int``, so they pass every
``isinstance(..., (int, float))`` gate in the selector module and render
``"True"``/``"False"`` — ratified Discrepancy #8 makes this in-annotation)."""

_SELECTOR_OPERATORS: tuple[str, ...] = (
    "equals",
    "does not equal",
    "contains",
    "does not contain",
    "is greater than",
    "is less than",
    "is between",
    "is set",
    "is not set",
    "true",
    "false",
    # Unsupported spellings — the ES13 fallthrough. ``list_contains`` is
    # deliberately absent: ``Filter.__post_init__`` rejects it without
    # ``_list_item_filters``, so the draw would fail at CONSTRUCTION and
    # never reach the translation under test.
    "",
    "was frobnicated",
    "is within",
)


@st.composite
def _escaping_filters(draw: st.DrawFn) -> Filter:
    """Draw a Filter with escaping-biased property names and values.

    Filters are built through the dataclass constructor (not the typed
    factories) so the drawn operator/value combinations can be mismatched
    on purpose — every ES guard must be reachable.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A Filter whose property name and string values come from the
        adversarial alphabet.
    """
    operator = draw(st.sampled_from(_SELECTOR_OPERATORS))
    scalars = st.one_of(_ESCAPING_TEXT, _ESCAPING_NUMBERS)
    if operator in ("equals", "does not equal"):
        value: object = draw(
            st.one_of(st.lists(scalars, max_size=3), scalars, st.none())
        )
    elif operator in ("contains", "does not contain"):
        value = draw(st.one_of(_ESCAPING_TEXT, _ESCAPING_NUMBERS, st.none()))
    elif operator in ("is greater than", "is less than"):
        value = draw(st.one_of(_ESCAPING_NUMBERS, _ESCAPING_TEXT, st.none()))
    elif operator == "is between":
        value = draw(
            st.one_of(
                st.tuples(scalars, scalars).map(list),
                st.lists(scalars, max_size=3),
                st.none(),
            )
        )
    else:
        value = draw(st.one_of(st.none(), _ESCAPING_TEXT))
    return Filter(
        _property=draw(_ESCAPING_TEXT),
        _operator=operator,  # type: ignore[arg-type]
        _value=value,  # type: ignore[arg-type]
    )


_SELECTOR_FILTERS: st.SearchStrategy[Filter] = st.one_of(
    filter_strategy(), _escaping_filters()
)
"""The widened Filter domain for the two K4 selector entry points."""

_K4_ESCAPE_EDGE_FILTERS: tuple[Filter, ...] = tuple(
    Filter(_property=text, _operator="equals", _value=[text])
    for text in (
        "\\",
        "a\\",
        "\\\\",
        '"',
        '\\"',
        '\\\\"',
        "' or '",
        'properties["x"] == "y" or ',
        "\n\t\r",
        "\U0001d4b3",
    )
) + (
    # Numeric edges rendered through `_format_value`'s `str()` branch.
    Filter(_property="p", _operator="equals", _value=[18.0, True, -0.0, 1e16]),
    Filter(_property="p", _operator="is between", _value=[18.0, 1e-5]),
)
"""Verbatim escaping / numeric edge probes for the selector targets
(b3-packets.md §K4 "Mandatory edge set")."""


def _k4_escape_edges(api: str) -> tuple[FuzzCall, ...]:
    """Attach the K4 escaping edge Filters to one selector api.

    Args:
        api: ``user_builders.filter_to_selector`` (single-Filter shape).

    Returns:
        One edge probe per :data:`_K4_ESCAPE_EDGE_FILTERS` member.
    """
    return tuple((api, {"f": f}) for f in _K4_ESCAPE_EDGE_FILTERS)


# ---------------------------------------------------------------------------
# Targets 1-4 — the three Filter translation dialects (design D4.2 item 1)
# ---------------------------------------------------------------------------

_FILTER_TO_SELECTOR = FuzzTarget(
    name="filter_to_selector",
    calls=_filter_calls("user_builders.filter_to_selector", _SELECTOR_FILTERS),
    edge_calls=(
        *_filter_edges("user_builders.filter_to_selector"),
        *_k4_escape_edges("user_builders.filter_to_selector"),
    ),
)

_FILTERS_LIST: st.SearchStrategy[list[Filter]] = st.lists(
    _SELECTOR_FILTERS, min_size=0, max_size=4
)
"""Filter lists for the AND-combining selector path (empty list included —
R10.9; the escaping-biased draws enter through
:data:`_SELECTOR_FILTERS`)."""


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
        # B3-K4: every escaping edge Filter as a singleton list.
        *(
            ("user_builders.filters_to_selector", {"filters": [f]})
            for f in _K4_ESCAPE_EDGE_FILTERS
        ),
        # B3-K4 generator-order lock: the SECOND element errors, so the
        # first must already have been translated (`user_builders.py:275`
        # joins a GENERATOR — a `.map()`-then-join port would surface a
        # later element's error first).
        (
            "user_builders.filters_to_selector",
            {
                "filters": [
                    Filter.is_set("p"),
                    Filter("p", "was frobnicated", None),  # type: ignore[arg-type]
                ]
            },
        ),
        # ... and first-error-wins when BOTH elements are invalid.
        (
            "user_builders.filters_to_selector",
            {
                "filters": [
                    Filter(123, "is set", None),  # type: ignore[arg-type]
                    Filter("p", "was frobnicated", None),  # type: ignore[arg-type]
                ]
            },
        ),
    ),
)


def _segfilter_row_sweep() -> tuple[FuzzCall, ...]:
    """Deterministic per-row sweep of the three segfilter operator maps.

    B3-K3 mandate (b3-packets.md §"R10.9 harness spec (K3)"): the drawn
    Filter domain must reach EVERY operator row of ``STRING_OPERATOR_MAP``
    / ``NUMBER_OPERATOR_MAP`` / ``DATETIME_OPERATOR_MAP`` — the free draw
    alone provably leaves rows uncovered (the K3 module harness measured
    ``datetime|was since`` missing at seed 7), so this sweep closes every
    row structurally: one probe per operator on its matching property
    type (setness ops with ``None``, range ops with two-element lists,
    relative datetime ops across the ``date_unit`` grid incl. ``None``),
    the boolean dialect's two operators, and every ``RESOURCE_TYPE_MAP``
    row plus the ``.get(rt, rt)`` fallback-to-self branch. Wired as
    ``@example`` edge probes so every fuzz corpus provably contains them
    (K3-notes §7.4 deferral to the binder — landed at B3-BIND).

    Returns:
        One ``(api, {"f": Filter})`` probe per table row.
    """
    api = "segfilter.build_segfilter_entry"
    calls: list[FuzzCall] = []
    setness = ("is set", "is not set")
    for str_op in (
        "equals",
        "does not equal",
        "contains",
        "does not contain",
        *setness,
    ):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        # Drawn from a plain str tuple; every spelling is a
                        # FilterOperator member.
                        _operator=str_op,  # type: ignore[arg-type]
                        _value=None if str_op in setness else "v",
                        _property_type="string",
                    )
                },
            )
        )
    for num_op in (
        "is greater than",
        "is less than",
        "is equal to",
        "equals",
        "does not equal",
        "is at least",
        "is at most",
        *setness,
    ):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        # "is equal to" is a NUMBER_OPERATOR_MAP row the
                        # FilterOperator literal does not spell — the map
                        # is deliberately wider (segfilter.py:59-70).
                        _operator=num_op,  # type: ignore[arg-type]
                        _value=None if num_op in setness else 5,
                        _property_type="number",
                    )
                },
            )
        )
    range_value: list[int | float] = [1, 10]
    for range_op in ("is between", "between", "not between"):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        # "between" is a NUMBER_OPERATOR_MAP row outside
                        # the FilterOperator literal (see above).
                        _operator=range_op,  # type: ignore[arg-type]
                        _value=range_value,
                        _property_type="number",
                    )
                },
            )
        )
    for bool_op in ("true", "false"):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        _operator=bool_op,
                        _value=None,
                        _property_type="boolean",
                    )
                },
            )
        )
    for dt_op in ("was on", "was not on", "was before", "was since"):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        _operator=dt_op,
                        _value="2026-01-15",
                        _property_type="datetime",
                    )
                },
            )
        )
    for rel_op in ("was in the", "was not in the"):
        for date_unit in (None, "day", "hour", "week", "month"):
            calls.append(
                (
                    api,
                    {
                        "f": Filter(
                            _property="p",
                            _operator=rel_op,
                            _value=7,
                            _property_type="datetime",
                            _date_unit=date_unit,
                        )
                    },
                )
            )
    for dt_range_op in ("was between", "was not between"):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        _operator=dt_range_op,
                        _value=["2026-01-01", "2026-02-02"],
                        _property_type="datetime",
                    )
                },
            )
        )
    # RESOURCE_TYPE_MAP rows + the `.get(rt, rt)` fallback-to-self branch
    # (`segfilter.py:297` — an unknown resource type passes through).
    for resource_type in ("events", "people", "cohorts", "other", "custom_src"):
        calls.append(
            (
                api,
                {
                    "f": Filter(
                        _property="p",
                        _operator="equals",
                        _value="v",
                        _property_type="string",
                        _resource_type=resource_type,  # type: ignore[arg-type]
                    )
                },
            )
        )
    return tuple(calls)


_BUILD_SEGFILTER_ENTRY = FuzzTarget(
    name="build_segfilter_entry",
    calls=_filter_calls("segfilter.build_segfilter_entry"),
    edge_calls=(
        *_filter_edges("segfilter.build_segfilter_entry"),
        # B3-BIND: the K3 operator-row sweep (see its docstring).
        *_segfilter_row_sweep(),
    ),
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
        # bool <: int — Python's `isinstance(cohort, int)` saved-id split
        # accepts booleans (True passes CF1, False fires it); drawn since
        # the B3 arbiter fix F1 (b3-review-resolution.md 2026-08-15).
        cohort = draw(
            st.one_of(
                st.integers(min_value=-10, max_value=1_000_000),
                st.booleans(),
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
        # bool <: int (B3 arbiter fix F1): True -> saved id entry, False
        # -> CF1 at the shared guard, on BOTH sides.
        ("types.Filter.in_cohort", {"cohort": True, "name": None}),
        ("types.Filter.not_in_cohort", {"cohort": False, "name": "VIPs"}),
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
                # bool <: int (B3 arbiter fix F1, b3-review-resolution.md
                # 2026-08-15): CohortBreakdown(True) constructs and takes
                # the saved-id branch; CohortBreakdown(False) fires CB1 —
                # both sides, via the bool-inclusive isinstance-int guard.
                "cohort": st.one_of(
                    st.integers(min_value=-10, max_value=1_000_000),
                    st.booleans(),
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


# ---------------------------------------------------------------------------
# Phase-3 B2 targets — the validator families (b2-packets.md §"R10.9 harness
# spec" for V1a/V1b/V2, formalized by the (b′) binding task per the
# B2-M1/M2/M3 deferral notes; oracle-ts answers these apis through the
# shared bindings registration).
#
# Domain notes (documented omissions, module-header rule / :253-257 style):
# - NON-FINITE floats are unshippable through ``encode_input_kwargs``
#   (D6 rule 5, ``_reject_bad_float`` rejects them in EVERY position), so
#   the branches that need NaN/Infinity INPUT — V24_BUCKET_NOT_FINITE,
#   the V12/V18 NaN-probe arms, B20B_FILTER_VALUE_NOT_FINITE, and the
#   sorting ``finite_number`` route — are locked by the authored corpus
#   vectors + the module Layer-3 twins instead (the module tasks'
#   throwaway harnesses hand-built those payloads; this table cannot).
# - Constructor-guarded instances cannot be GENERATED here (Python raises
#   at strategy-definition time): GroupBy V12/V18 orderings, Exclusion
#   EX1/EX2 shapes, control-char Exclusion events, Metric property-math
#   guards, inline-cohort CohortMetric. The validator codes those inputs
#   would hit (V12_BUCKET_SIZE_POSITIVE, V13_METRIC_MATH_PROPERTY,
#   V18_BUCKET_ORDER, CM5_INLINE_COHORT_METRIC, F4_CONTROL_CHAR_EXCLUSION,
#   F4_EMPTY_EXCLUSION_EVENT, F4_EXCLUSION_NEGATIVE_STEP) are unreachable
#   post-Phase-2 (B2-M1 notes); each is pinned by its nearest reachable
#   arm below.
# - OUT-OF-ANNOTATION scalars are excluded from every B2 domain as a CLASS
#   (B2 arbiter ruling, playbook Discrepancy #8 / b2-review-resolution.md
#   F2, 2026-08-15 — supersedes the earlier lone ``workers=None`` note):
#   values violating a validator's declared parameter annotation (e.g.
#   ``last="30"`` for ``last: int``, ``params=5.0`` for
#   ``dict[str, Any]``, a str element in ``segment_by: list[int]``) make
#   CPython raise TypeError/AttributeError at guard-free comparison /
#   ``.strip()`` / ``len()`` sites while the TS port (whose compile-time
#   types reject them outright) returns normally. The port's contract
#   stops at the annotation boundary; IN-annotation raise behavior
#   (``dict[str, Any]`` interiors — the requireHashable sites) IS
#   contract and stays in-domain. ``workers=None`` is one member of this
#   class.
# - Plain dicts (and every JSON value) INSIDE ``dict[str, Any]`` params
#   are in-domain, including floats/instances at dict-expected positions
#   and dicts carrying a literal ``"spelling"`` key (the F1 arbiter fix
#   locks the carrier-vs-dict discrimination; see the bookmark/sorting/
#   user_params edge sets below).
# - Integer-like UNKNOWN chart-type keys (e.g. ``{"1": {}}``) are excluded
#   from the sorting domain: JS objects order integer-like keys first, so
#   the S4 warning EMISSION ORDER flips (playbook Discrepancy #9 — blessed;
#   plain-object inputs cannot preserve insertion order in TS at all).
# - B0_MISSING_FIELD / B0_VALIDATOR_ERROR are unreachable through
#   ``validate_sorting_block`` (B2-M2 probe finding 5); their nearest
#   reachable neighbours are pinned in the sorting edge set.
# ---------------------------------------------------------------------------

_B2_NON_BMP = "\U0001d4b3"
"""The R10.9 non-BMP edge string ("𝒳")."""

_B2_NUL = "\x00"
"""Control character for the *_CONTROL_CHAR_* branches."""

_B2_ZWSP = "​"
"""Zero-width space for the *_INVISIBLE_* branches."""

_ABSENT = object()
"""Sentinel: drop this key from a generated kwargs/params dict."""


def _b2_compact(entries: dict[str, Any]) -> dict[str, Any]:
    """Drop :data:`_ABSENT` values so a key is truly absent (R3.5).

    Args:
        entries: Drawn key/value pairs, absent keys carrying the sentinel.

    Returns:
        The dict without sentinel-valued keys.
    """
    return {key: value for key, value in entries.items() if value is not _ABSENT}


def _b2_maybe(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Wrap a strategy so the drawn key may be absent entirely.

    Args:
        strategy: The value strategy.

    Returns:
        A strategy drawing either :data:`_ABSENT` or a value.
    """
    return st.one_of(st.just(_ABSENT), strategy)


_B2_DATES: st.SearchStrategy[Any] = st.one_of(
    st.none(),
    st.dates().map(str),
    st.sampled_from(
        [
            "2024-01-01",
            "2024-12-31",
            "2024-02-29",
            "2023-02-29",
            "2024-02-30",
            "0000-01-01",
            "9999-12-31",
            "01/01/2024",
            "not-a-date",
            "",
            "2024-1-1",
            "20240101",
            "2024-01-01\n",
            _B2_NON_BMP,
            "٢٠٢٤-٠١-٠١",
        ]
    ),
)
"""Date mix: valid, malformed-family, None, junk (V8/V9/V10/V15 space)."""

_B2_LAST: st.SearchStrategy[Any] = st.sampled_from(
    (-100, -1, 0, 1, 29, 30, 31, 3650, 3651, 5000, True, 1.5, 30.0)
)
"""``last`` pool: bounds, bool, fractional, integral float (carrier probe)."""

_B2_EVENTS: st.SearchStrategy[str] = st.sampled_from(
    (
        "Login",
        "Purchase",
        "",
        "   ",
        f"A{_B2_NUL}B",
        _B2_ZWSP,
        _B2_NON_BMP,
        "­",
        "⁠",
        "\t",
    )
)
"""Event-name pool: valid, blank, control-char, invisible, non-BMP."""

_B2_DGID: st.SearchStrategy[Any] = st.sampled_from(
    (None, 1, 0, -1, True, False, 1.5, 2.0, "3", ())
)
"""``data_group_id`` pool (DG1 branch coverage; 2.0 rides as the carrier)."""

_B2_GROUP_BY_POOL: tuple[Any, ...] = (
    None,
    "country",
    "",
    "  ",
    _B2_NON_BMP,
    ["country", "platform"],
    ["", _B2_NON_BMP],
    GroupBy(
        property="revenue",
        property_type="number",
        bucket_size=50,
        bucket_min=0,
        bucket_max=500,
    ),
    GroupBy(
        property="revenue",
        property_type="number",
        bucket_size=10.0,
        bucket_min=0.0,
        bucket_max=100.0,
    ),
    GroupBy(
        property="revenue",
        property_type="number",
        bucket_size=1.5,
        bucket_min=0,
        bucket_max=10,
    ),
    GroupBy(property="a", bucket_min=0),  # V11_BUCKET_REQUIRES_SIZE
    GroupBy(  # V12B_BUCKET_REQUIRES_NUMBER
        property="a",
        property_type="string",
        bucket_size=10,
        bucket_min=0,
        bucket_max=20,
    ),
    GroupBy(property="a", property_type="number", bucket_size=10),  # V12C
    GroupBy(property=_B2_NON_BMP, property_type="datetime"),
    GroupBy(property=CustomPropertyRef(id=0)),  # CP1_INVALID_ID
    GroupBy(property=CustomPropertyRef(id=7)),
    GroupBy(  # CP2_EMPTY_FORMULA
        property=InlineCustomProperty(
            formula="   ", inputs={"A": PropertyInput(name="p")}
        )
    ),
    GroupBy(property=InlineCustomProperty(formula="A", inputs={})),  # CP3
    GroupBy(  # CP4_INVALID_INPUT_KEY
        property=InlineCustomProperty(
            formula="A", inputs={"aa": PropertyInput(name="p")}
        )
    ),
    GroupBy(  # CP6_EMPTY_INPUT_NAME
        property=InlineCustomProperty(
            formula="A", inputs={"A": PropertyInput(name="  ")}
        )
    ),
    [GroupBy(property="a", bucket_min=0), "platform"],
)
"""Prebuilt breakdowns: every constructible V11/V12B/V12C/CP* shape."""

_B2_GROUP_BY_SCALARS: tuple[Any, ...] = tuple(
    member for member in _B2_GROUP_BY_POOL if not isinstance(member, list)
)
"""Pool members legal as list ELEMENTS (no nested lists)."""

_B2_GROUP_BY: st.SearchStrategy[Any] = st.one_of(
    st.sampled_from(_B2_GROUP_BY_POOL),
    st.lists(st.sampled_from(_B2_GROUP_BY_SCALARS), max_size=3),
)
"""Breakdown strategy: the prebuilt pool + generated mixed lists (the
combinatorial space keeps the family above the >=500-example budget —
a bare ``sampled_from`` exhausts after ~pool-size unique examples)."""

_B2_COHORT_GROUP_BY: st.SearchStrategy[Any] = st.one_of(
    _B2_GROUP_BY,
    st.sampled_from(
        (
            [CohortBreakdown(cohort=123, name="PU")],
            [CohortBreakdown(cohort=123, name="PU"), "platform"],  # CB3
        )
    ),
)
"""Retention breakdowns: the shared pool + CohortBreakdown mixes (CB3)."""


def _b2_call(api: str) -> Any:
    """Build a kwargs→probe mapper for one validator api.

    Args:
        api: The dotted registry api name.

    Returns:
        A mapper suitable for ``strategy.map(...)``.
    """

    def make(kwargs: dict[str, Any]) -> FuzzCall:
        """Wrap drawn kwargs as a probe.

        Args:
            kwargs: The drawn kwargs.

        Returns:
            The ``(api, kwargs)`` probe.
        """
        return (api, kwargs)

    return make


_TIME_ARGS_API = "validation.validate_time_args"
_GROUP_BY_API = "validation.validate_group_by_args"
_QUERY_ARGS_API = "validation.validate_query_args"
_FUNNEL_ARGS_API = "validation.validate_funnel_args"
_RETENTION_ARGS_API = "validation.validate_retention_args"
_FLOW_ARGS_API = "validation.validate_flow_args"
_BOOKMARK_API = "validation.validate_bookmark"
_FLOW_BOOKMARK_API = "validation.validate_flow_bookmark"
_SORTING_API = "validation.validate_sorting_block"
_USER_ARGS_API = "user_validators.validate_user_args"
_USER_PARAMS_API = "user_validators.validate_user_params"

_B2_TIME_BASE: dict[str, Any] = {"from_date": None, "to_date": None, "last": 30}
"""All-valid time kwargs (edge-call base)."""

_B2_QUERY_BASE: dict[str, Any] = {
    "events": ["Login"],
    "math": "total",
    "math_property": None,
    "per_user": None,
    "from_date": None,
    "to_date": None,
    "last": 30,
    "has_formula": False,
    "rolling": None,
    "cumulative": False,
    "group_by": None,
}
"""All-valid query kwargs (edge-call base)."""

_B2_FUNNEL_BASE: dict[str, Any] = {
    "steps": ["Signup", "Purchase"],
    "conversion_window": 14,
    "conversion_window_unit": "day",
    "math": "conversion_rate_unique",
    "math_property": None,
    "exclusions": None,
    "holding_constant": None,
    "from_date": None,
    "to_date": None,
    "last": 30,
    "group_by": None,
}
"""All-valid funnel kwargs (edge-call base)."""

_B2_RETENTION_BASE: dict[str, Any] = {
    "born_event": "Signup",
    "return_event": "Login",
    "retention_unit": "week",
    "alignment": "birth",
    "bucket_sizes": None,
    "math": "retention_rate",
    "mode": "curve",
    "unit": "day",
    "from_date": None,
    "to_date": None,
    "last": 30,
    "group_by": None,
}
"""All-valid retention kwargs (edge-call base)."""

_B2_FLOW_BASE: dict[str, Any] = {
    "steps": ["Purchase"],
    "forward": 3,
    "reverse": 0,
    "count_type": "unique",
    "mode": "sankey",
    "cardinality": 3,
    "conversion_window": 7,
    "from_date": None,
    "to_date": None,
    "last": 30,
}
"""All-valid flow kwargs (edge-call base)."""


def _b2_edge(api: str, base: dict[str, Any], **over: Any) -> FuzzCall:
    """Build one edge probe from a base kwargs dict plus overrides.

    Args:
        api: The dotted registry api name.
        base: The family's all-valid kwargs base.
        over: Overriding kwargs.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (api, {**base, **over})


_TIME_ARGS_FAMILY = FuzzTarget(
    name="time_args_family",
    calls=st.fixed_dictionaries(
        {"from_date": _B2_DATES, "to_date": _B2_DATES, "last": _B2_LAST}
    ).map(_b2_call(_TIME_ARGS_API)),
    # Codes V7/V8(x2)/V9/V10/V15/V20 + the R10.9 value edges (integral
    # float 18.0 arrives as the PyFloat carrier on the TS side; True /
    # fractional / empty-string / non-BMP / all-None per input domain).
    edge_calls=(
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, last=18.0),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, last=1.5),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, last=True),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, from_date=""),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, from_date=_B2_NON_BMP),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, last=0),  # V7
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, from_date="01/01/2024"),  # V8
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, from_date="2024-02-30"),  # V8b
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, to_date="2024-01-31"),  # V9
        _b2_edge(  # V10
            _TIME_ARGS_API, _B2_TIME_BASE, from_date="2024-01-01", last=7
        ),
        (  # V15
            _TIME_ARGS_API,
            {"from_date": "2024-02-01", "to_date": "2024-01-01", "last": 30},
        ),
        _b2_edge(_TIME_ARGS_API, _B2_TIME_BASE, last=5000),  # V20
    ),
)

_GROUP_BY_ARGS_FAMILY = FuzzTarget(
    name="group_by_args_family",
    calls=st.fixed_dictionaries({"group_by": _B2_GROUP_BY}).map(
        _b2_call(_GROUP_BY_API)
    ),
    # V11/V12B/V12C + CP1..CP6 (CP5 below) ride the prebuilt pool; V24 /
    # V12 / V18 need non-finite floats (unshippable — see section header).
    edge_calls=(
        (_GROUP_BY_API, {"group_by": None}),
        (_GROUP_BY_API, {"group_by": []}),
        (_GROUP_BY_API, {"group_by": ""}),
        (_GROUP_BY_API, {"group_by": _B2_NON_BMP}),
        (_GROUP_BY_API, {"group_by": _B2_GROUP_BY_POOL[8]}),  # 10.0 carriers
        (_GROUP_BY_API, {"group_by": _B2_GROUP_BY_POOL[9]}),  # 1.5 buckets
        (_GROUP_BY_API, {"group_by": _B2_GROUP_BY_POOL[10]}),  # V11
        (_GROUP_BY_API, {"group_by": _B2_GROUP_BY_POOL[11]}),  # V12B
        (_GROUP_BY_API, {"group_by": _B2_GROUP_BY_POOL[12]}),  # V12C
        (  # CP5_FORMULA_TOO_LONG (codepoint length > 20_000, R11.6)
            _GROUP_BY_API,
            {
                "group_by": GroupBy(
                    property=InlineCustomProperty(
                        formula=_B2_NON_BMP * 20_001,
                        inputs={"A": PropertyInput(name="p")},
                    )
                )
            },
        ),
        *(
            (_GROUP_BY_API, {"group_by": member})
            for member in _B2_GROUP_BY_POOL[14:20]  # CP1..CP6 shapes
        ),
    ),
)

_B2_QUERY_EVENTS: st.SearchStrategy[Any] = st.one_of(
    st.lists(_B2_EVENTS, max_size=3),
    st.sampled_from(
        (
            [123],  # V21_INVALID_EVENT_TYPE
            [Metric(event="P", math="total")],
            [Metric(event="P", math="unique", property="amount")],  # V14
            [CohortMetric(cohort=42, name="c")],
            [CohortMetric(cohort=True)],  # F3: bool cohort, no CM5
            # F3: float cohort, no CM5 (out-of-declared-type but
            # ctor-accepted in BOTH languages — the point of the arm).
            [CohortMetric(cohort=5.0)],  # type: ignore[arg-type]
            ["a", Metric(event="P", math="dau"), _B2_NON_BMP],
        )
    ),
)
"""Query events: strings, bad types, Metric/CohortMetric instances."""

_B2_FORMULAS: st.SearchStrategy[Any] = st.sampled_from(
    (
        None,
        (),
        (Formula(expression="A + B"),),
        (Formula(expression="1 + 2"),),  # V16_FORMULA_SYNTAX
        (Formula(expression="A + Z"),),  # V19_FORMULA_BOUNDS
        (Formula(expression=_B2_NON_BMP),),
        (Formula(expression="A"), Formula(expression="ZZ")),
    )
)
"""Formula pool (V16/V19 + valid shapes)."""

_QUERY_ARGS_FAMILY = FuzzTarget(
    name="query_args_family",
    calls=st.fixed_dictionaries(
        {
            "events": _B2_QUERY_EVENTS,
            "math": st.sampled_from(
                (
                    "total",
                    "unique",
                    "average",
                    "median",
                    "p99",
                    "dau",
                    "wau",
                    "mau",
                    "histogram",
                    "percentile",
                    "totl",
                    "",
                    _B2_NON_BMP,
                )
            ),
            "math_property": st.sampled_from((None, "amount", "", _B2_NON_BMP)),
            "per_user": st.sampled_from((None, "total", "average", "min", "max")),
            "percentile_value": st.sampled_from((None, 95, 1.5)),
            "from_date": _B2_DATES,
            "to_date": _B2_DATES,
            "last": _B2_LAST,
            "has_formula": st.booleans(),
            "rolling": st.sampled_from((None, 0, 7, 400, -1, 1.5, True, 7.0)),
            "cumulative": st.booleans(),
            "group_by": _B2_GROUP_BY,
            "formulas": _B2_FORMULAS,
            "data_group_id": _B2_DGID,
        }
    ).map(_b2_call(_QUERY_ARGS_API)),
    edge_calls=(
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, events=[]),  # V0
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, events=[""]),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, events=[_B2_NON_BMP]),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, math="average"),  # V1
        _b2_edge(  # V2
            _QUERY_ARGS_API, _B2_QUERY_BASE, math="unique", math_property="amount"
        ),
        _b2_edge(  # V3
            _QUERY_ARGS_API, _B2_QUERY_BASE, math="dau", per_user="average"
        ),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, per_user="average"),  # V3B
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, has_formula=True),  # V4
        _b2_edge(  # V5
            _QUERY_ARGS_API, _B2_QUERY_BASE, rolling=7, cumulative=True
        ),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, rolling=0),  # V6
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, rolling=7.0),  # carrier
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, rolling=1.5),
        _b2_edge(  # V16
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=["a", "b"],
            has_formula=True,
            formulas=(Formula(expression="1 + 2"),),
        ),
        _b2_edge(  # V19 (source-only in the corpus)
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=["a", "b"],
            has_formula=True,
            formulas=(Formula(expression="A + Z"),),
        ),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, events=[123]),  # V21
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, events=["   "]),  # V17
        _b2_edge(  # V22_CONTROL_CHAR_EVENT
            _QUERY_ARGS_API, _B2_QUERY_BASE, events=[f"Log{_B2_NUL}in"]
        ),
        _b2_edge(  # V22_INVISIBLE_EVENT
            _QUERY_ARGS_API, _B2_QUERY_BASE, events=[_B2_ZWSP]
        ),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, rolling=400),  # V23
        _b2_edge(  # V26_PERCENTILE_REQUIRES_VALUE
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            math="percentile",
            math_property="amount",
        ),
        _b2_edge(  # V27_HISTOGRAM_REQUIRES_PER_USER
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            math="histogram",
            math_property="amount",
        ),
        _b2_edge(  # V14_METRIC_REJECTS_PROPERTY
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=[Metric(event="P", math="unique", property="amount")],
        ),
        _b2_edge(  # V13 unreachable (Metric ctor guard); pins the ok arm
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=[Metric(event="P", math="total")],
        ),
        _b2_edge(  # CM5 unreachable (inline defs rejected by ctor); ok arm
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=[CohortMetric(cohort=42, name="c")],
        ),
        _b2_edge(  # F3 arbiter lock: bool cohort is NOT a CohortDefinition
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=[CohortMetric(cohort=True)],
        ),
        _b2_edge(  # F3 arbiter lock: float cohort (carrier in TS) — no CM5
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            # Out-of-declared-type but ctor-accepted in BOTH languages.
            events=[CohortMetric(cohort=5.0)],  # type: ignore[arg-type]
        ),
        _b2_edge(  # F3 arbiter lock: mixed list positioning
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            events=["Login", CohortMetric(cohort=True)],
        ),
        _b2_edge(_QUERY_ARGS_API, _B2_QUERY_BASE, data_group_id=0),  # DG1
        _b2_edge(  # CP1 via the shared scan
            _QUERY_ARGS_API,
            _B2_QUERY_BASE,
            group_by=GroupBy(property=CustomPropertyRef(id=0)),
        ),
    ),
)

_B2_EXCLUSIONS: st.SearchStrategy[Any] = st.sampled_from(
    (
        None,
        (),
        (Exclusion(event="X", from_step=0, to_step=5),),  # F4 bounds
        (Exclusion(event="Logout", from_step=2, to_step=None),),
        (Exclusion(event="X", from_step=0, to_step=1),),
    )
)
"""Constructible exclusions (EX1/EX2/control-char shapes cannot exist)."""

_FUNNEL_ARGS_FAMILY = FuzzTarget(
    name="funnel_args_family",
    calls=st.fixed_dictionaries(
        {
            "steps": st.lists(_B2_EVENTS, max_size=4),
            "conversion_window": st.sampled_from(
                (0, 1, 2, 14, 368, -1, 1.5, True, None, 14.0, "7")
            ),
            "conversion_window_unit": st.sampled_from(
                (
                    "second",
                    "minute",
                    "hour",
                    "day",
                    "week",
                    "month",
                    "session",
                    "hou",
                    "",
                    _B2_NON_BMP,
                )
            ),
            "math": st.sampled_from(
                (
                    "conversion_rate_unique",
                    "conversion_rate_session",
                    "unique",
                    "total",
                    "average",
                    "median",
                    "p99",
                    "uniqe",
                    "",
                )
            ),
            "math_property": st.sampled_from((None, "amount", "", _B2_NON_BMP)),
            "exclusions": _B2_EXCLUSIONS,
            "holding_constant": st.sampled_from(
                (None, (), ("a",), ("a", "b", "c", "d"), ("", "b"), (1,))
            ),
            "from_date": _B2_DATES,
            "to_date": _B2_DATES,
            "last": _B2_LAST,
            "group_by": _B2_GROUP_BY,
            "reentry_mode": st.sampled_from(
                (None, "default", "basic", "aggressive", "optimized", "invalid", "")
            ),
            "data_group_id": _B2_DGID,
        }
    ).map(_b2_call(_FUNNEL_ARGS_API)),
    edge_calls=(
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE),
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=[]),  # F1_MIN
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=["A"]),  # F1_MIN
        _b2_edge(  # F1_MAX_STEPS
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=["A"] * 101
        ),
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=["", "B"]),  # F2
        _b2_edge(  # F2_CONTROL_CHAR_STEP_EVENT
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=[f"A{_B2_NUL}B", "C"]
        ),
        _b2_edge(  # F2_INVISIBLE_STEP_EVENT
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, steps=[_B2_ZWSP, "C"]
        ),
        _b2_edge(  # F3_CONVERSION_WINDOW_POSITIVE
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=0
        ),
        _b2_edge(  # F3_CONVERSION_WINDOW_MAX
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=368
        ),
        _b2_edge(  # F3_CONVERSION_WINDOW_TYPE (fractional)
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=14.5
        ),
        _b2_edge(  # F3 TYPE via integral float (carrier stays a carrier)
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=14.0
        ),
        _b2_edge(  # F3 TYPE via bool
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=True
        ),
        _b2_edge(  # F3 TYPE via None
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window=None
        ),
        _b2_edge(  # F4_EXCLUSION_STEP_BOUNDS
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            exclusions=(Exclusion(event="X", from_step=0, to_step=5),),
        ),
        _b2_edge(  # F4 order arm reachable through validator re-check
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            exclusions=(Exclusion(event="X", from_step=0, to_step=1),),
        ),
        _b2_edge(  # F7_INVALID_WINDOW_UNIT (+ _suggest content path)
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, conversion_window_unit="hou"
        ),
        _b2_edge(  # F7_SECOND_MIN_WINDOW
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            conversion_window=1,
            conversion_window_unit="second",
        ),
        _b2_edge(  # F8_MAX_HOLDING_CONSTANT
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            holding_constant=("a", "b", "c", "d"),
        ),
        _b2_edge(  # F8_EMPTY_HOLDING_CONSTANT_PROPERTY (source-only)
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, holding_constant=("", "b")
        ),
        _b2_edge(  # F9_SESSION_WINDOW_REQUIRES_ONE
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            conversion_window_unit="session",
            conversion_window=2,
        ),
        _b2_edge(  # F9_SESSION_MATH_REQUIRES_SESSION_WINDOW
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, math="conversion_rate_session"
        ),
        _b2_edge(  # F10_MATH_MISSING_PROPERTY
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, math="average"
        ),
        _b2_edge(  # F11_MATH_REJECTS_PROPERTY
            _FUNNEL_ARGS_API,
            _B2_FUNNEL_BASE,
            math="unique",
            math_property="amount",
        ),
        _b2_edge(  # F12_INVALID_REENTRY_MODE
            _FUNNEL_ARGS_API, _B2_FUNNEL_BASE, reentry_mode="invalid"
        ),
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE, data_group_id=0),  # DG1
        _b2_edge(_FUNNEL_ARGS_API, _B2_FUNNEL_BASE, last=18.0),  # carrier
    ),
)

_RETENTION_ARGS_FAMILY = FuzzTarget(
    name="retention_args_family",
    calls=st.fixed_dictionaries(
        {
            "born_event": _B2_EVENTS,
            "return_event": _B2_EVENTS,
            "retention_unit": st.sampled_from(
                ("day", "week", "month", "wek", "Week", "", _B2_NON_BMP)
            ),
            "alignment": st.sampled_from(
                ("birth", "interval_start", "brith", "", _B2_NON_BMP)
            ),
            "bucket_sizes": st.one_of(
                st.none(),
                st.lists(
                    st.sampled_from(
                        (1, 2, 3, 7, 0, -1, 1.5, True, False, 2.0, "3", None, 731)
                    ),
                    max_size=6,
                ),
            ),
            "math": st.sampled_from(
                (
                    "retention_rate",
                    "unique",
                    "total",
                    "average",
                    "uniue",
                    "",
                    _B2_NON_BMP,
                )
            ),
            "mode": st.sampled_from(
                ("curve", "trends", "table", "curv", None, "", _B2_NON_BMP)
            ),
            "unit": st.sampled_from(("day", "week", "month", "dya", "", _B2_NON_BMP)),
            "from_date": _B2_DATES,
            "to_date": _B2_DATES,
            "last": _B2_LAST,
            "group_by": _B2_COHORT_GROUP_BY,
            "unbounded_mode": st.sampled_from(
                (
                    None,
                    "none",
                    "carry_back",
                    "carry_forward",
                    "consecutive_forward",
                    "invalid",
                    "",
                )
            ),
            "data_group_id": _B2_DGID,
        }
    ).map(_b2_call(_RETENTION_ARGS_API)),
    edge_calls=(
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, born_event=""),  # R1
        _b2_edge(  # R1_CONTROL_CHAR_BORN_EVENT
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, born_event=f"S{_B2_NUL}p"
        ),
        _b2_edge(  # R1_INVISIBLE_BORN_EVENT
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, born_event=_B2_ZWSP
        ),
        _b2_edge(  # R2 family
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, return_event=""
        ),
        _b2_edge(
            _RETENTION_ARGS_API,
            _B2_RETENTION_BASE,
            return_event=f"L{_B2_NUL}n",
        ),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, return_event=_B2_ZWSP),
        _b2_edge(  # R5_BUCKET_SIZES_INTEGER (fractional + carrier + bool)
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[1.5, 3]
        ),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[1.0, 3]),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[True, 3]),
        _b2_edge(  # R5_BUCKET_SIZES_POSITIVE
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[0, 3]
        ),
        _b2_edge(  # R5_BUCKET_SIZES_TOO_MANY (> _MAX_RETENTION_BUCKETS)
            _RETENTION_ARGS_API,
            _B2_RETENTION_BASE,
            bucket_sizes=list(range(1, 1001)),
        ),
        _b2_edge(  # R6_BUCKET_SIZES_ASCENDING
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[7, 3, 1]
        ),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, bucket_sizes=[]),
        _b2_edge(  # R7 (+ suggestion content "week")
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, retention_unit="wek"
        ),
        _b2_edge(  # R8
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, alignment="brith"
        ),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, math="uniue"),  # R9
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, mode="curv"),  # R10
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, unit="dya"),  # R11
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, group_by=""),  # R12
        _b2_edge(  # R13
            _RETENTION_ARGS_API, _B2_RETENTION_BASE, unbounded_mode="invalid"
        ),
        _b2_edge(  # CB3_RETENTION_MIXED_BREAKDOWN
            _RETENTION_ARGS_API,
            _B2_RETENTION_BASE,
            group_by=[CohortBreakdown(cohort=123, name="PU"), "platform"],
        ),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, data_group_id=0),
        _b2_edge(_RETENTION_ARGS_API, _B2_RETENTION_BASE, last=18.0),
        _b2_edge(
            _RETENTION_ARGS_API,
            _B2_RETENTION_BASE,
            born_event=_B2_NON_BMP,
            return_event=_B2_NON_BMP,
        ),
    ),
)

_FLOW_ARGS_FAMILY = FuzzTarget(
    name="flow_args_family",
    calls=st.fixed_dictionaries(
        {
            "steps": st.lists(_B2_EVENTS, max_size=3),
            "forward": st.sampled_from((-1, 0, 1, 3, 5, 6, True, 1.5, 3.0)),
            "reverse": st.sampled_from((-1, 0, 1, 5, 6, True)),
            "count_type": st.sampled_from(
                ("unique", "total", "session", "uniqe", "", _B2_NON_BMP)
            ),
            "mode": st.sampled_from(
                ("sankey", "paths", "tree", "sanke", "", _B2_NON_BMP)
            ),
            "cardinality": st.sampled_from((0, 1, 3, 50, 51, -1, 1.5)),
            "conversion_window": st.sampled_from((0, 1, 7, 366, 367, 400, -1, 1.5)),
            "conversion_window_unit": st.sampled_from(
                ("day", "week", "month", "session", "dya", "", _B2_NON_BMP)
            ),
            "from_date": _B2_DATES,
            "to_date": _B2_DATES,
            "last": _B2_LAST,
            "time_comparison": st.sampled_from(
                (None, TimeComparison(type="relative", unit="month"))
            ),
            "data_group_id": _B2_DGID,
        }
    ).map(_b2_call(_FLOW_ARGS_API)),
    edge_calls=(
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, steps=[]),  # FL1
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, steps=[""]),  # FL2
        _b2_edge(  # FL2_CONTROL_CHAR_STEP_EVENT
            _FLOW_ARGS_API, _B2_FLOW_BASE, steps=[f"{_B2_NUL}Login"]
        ),
        _b2_edge(  # FL2_INVISIBLE_STEP_EVENT
            _FLOW_ARGS_API, _B2_FLOW_BASE, steps=[_B2_ZWSP]
        ),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, steps=[_B2_NON_BMP]),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, forward=6),  # FL3
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, reverse=-1),  # FL4
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, forward=0, reverse=0),  # FL5
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, cardinality=51),  # FL6
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, cardinality=3.0),  # carrier
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, cardinality=1.5),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, conversion_window=0),  # FL7
        _b2_edge(  # FL7_CONVERSION_WINDOW_MAX
            _FLOW_ARGS_API, _B2_FLOW_BASE, conversion_window=400
        ),
        _b2_edge(  # FL9_SESSION_REQUIRES_SESSION_WINDOW
            _FLOW_ARGS_API, _B2_FLOW_BASE, count_type="session"
        ),
        _b2_edge(  # FL10_SESSION_WINDOW_REQUIRES_ONE
            _FLOW_ARGS_API,
            _B2_FLOW_BASE,
            count_type="session",
            conversion_window_unit="session",
            conversion_window=7,
        ),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, count_type="uniqe"),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, mode="sanke"),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, conversion_window_unit="dya"),
        _b2_edge(  # FL_TIME_COMPARISON_NOT_SUPPORTED
            _FLOW_ARGS_API,
            _B2_FLOW_BASE,
            time_comparison=TimeComparison(type="relative", unit="month"),
        ),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, forward=True),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, data_group_id=None),
        _b2_edge(_FLOW_ARGS_API, _B2_FLOW_BASE, last=18.0),
    ),
)

# ---- V1b — bookmark / flow-bookmark / sorting families --------------------


def _b2_bookmark(**over: Any) -> dict[str, Any]:
    """Build the minimal valid insights bookmark params dict.

    Mirrors ``tests/unit/test_validation.py::_minimal_bookmark`` (the
    B2-M2 harness base).

    Args:
        over: Top-level key overrides.

    Returns:
        A fresh params dict.
    """
    params: dict[str, Any] = {
        "sections": {
            "show": [
                {
                    "behavior": {
                        "type": "event",
                        "resourceType": "events",
                        "value": {"name": "Login"},
                    },
                    "measurement": {"math": "total"},
                }
            ],
            "time": [{"unit": "day", "dateRangeType": "in the last", "value": 30}],
            "filter": [],
            "group": [],
        },
        "displayOptions": {"chartType": "line", "analysis": "linear"},
    }
    params.update(over)
    return params


def _b2_bm_show(clause: Any) -> dict[str, Any]:
    """Bookmark params with one replaced show clause.

    Args:
        clause: The show-clause value.

    Returns:
        The params dict.
    """
    base = _b2_bookmark()
    base["sections"] = {**base["sections"], "show": [clause]}
    return base


def _b2_bm_section(section: str, clause: Any) -> dict[str, Any]:
    """Bookmark params with one clause in the given section.

    Args:
        section: ``"filter"`` / ``"group"`` / ``"time"``.
        clause: The clause value.

    Returns:
        The params dict.
    """
    base = _b2_bookmark()
    base["sections"] = {**base["sections"], section: [clause]}
    return base


def _b2_cohort_show(
    behavior: dict[str, Any], measurement: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Bookmark params with a cohort-flavored show clause (B22-B26).

    Args:
        behavior: The behavior dict.
        measurement: The measurement dict (default ``{"math": "unique"}``).

    Returns:
        The params dict.
    """
    return _b2_bm_show(
        {"behavior": behavior, "measurement": measurement or {"math": "unique"}}
    )


def _b2_flow_bookmark(**over: Any) -> dict[str, Any]:
    """Build the minimal valid flow bookmark params dict.

    Mirrors ``tests/test_validation_flow.py::_valid_flow_bookmark``.

    Args:
        over: Top-level key overrides.

    Returns:
        A fresh params dict.
    """
    params: dict[str, Any] = {
        "steps": [{"event": "Purchase", "forward": 3, "reverse": 0}],
        "date_range": {
            "type": "in the last",
            "from_date": {"unit": "day", "value": 30},
            "to_date": "$now",
        },
        "chartType": "sankey",
        "count_type": "unique",
        "version": 2,
    }
    params.update(over)
    return params


_B2_STRS: st.SearchStrategy[Any] = st.sampled_from(
    ("Login", "", "  ", _B2_NON_BMP, f"A{_B2_NUL}B", _B2_ZWSP, "country")
)
"""Generic string pool for bookmark clause fields."""

_B2_SORT_BY: st.SearchStrategy[Any] = st.sampled_from(
    ("value", "column", "label", "liftComparisonValue", "bogus", "", None, (), 5)
)
"""``sortBy`` pool: every discriminator route + near-misses + bad types."""

_B2_SORT_ORDER: st.SearchStrategy[Any] = st.sampled_from(
    ("asc", "desc", "ascending", "", None, 3)
)
"""``sortOrder`` pool (S6/S9 space)."""

_B2_VIEWN: st.SearchStrategy[Any] = st.sampled_from(
    (None, 5, 0, -1, 5.5, True, "5", "x", " 5 ", "1_0", "5.0", 5.0, (), {})
)
"""``viewNLimit`` pool: pydantic lax int coercion space (B0_WRONG_TYPE)."""

_B2_VALUE_FIELD: st.SearchStrategy[Any] = st.sampled_from(
    (None, "averageValue", "", 3, True, _B2_NON_BMP, ())
)
"""``valueField`` pool (string_type route)."""

_B2_CHART_KEYS: st.SearchStrategy[str] = st.sampled_from(
    (
        "bar",
        "table",
        "line",
        "pie",
        "insights-metric",
        "retention-curve",
        "funnel-steps",
        "sankey",
        "column",
        "barz",
        "",
        _B2_NON_BMP,
    )
)
"""Sorting chart-type keys: the seven modeled + S4 near-misses."""


@st.composite
def _b2_flat_sort_attr(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one ``colSortAttrs`` element (flat sort config).

    Args:
        draw: Hypothesis draw function.

    Returns:
        A flat sort-attribute dict (keys possibly absent).
    """
    return _b2_compact(
        {
            "sortBy": draw(_b2_maybe(_B2_SORT_BY)),
            "sortOrder": draw(_b2_maybe(_B2_SORT_ORDER)),
            "valueField": draw(_b2_maybe(_B2_VALUE_FIELD)),
            "viewNLimit": draw(_b2_maybe(_B2_VIEWN)),
            "zz": draw(_b2_maybe(st.just(1))),
        }
    )


@st.composite
def _b2_sort_config(draw: st.DrawFn) -> Any:
    """Draw one per-chart-type sorting config.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A config dict, or a non-dict poison value (S5 route).
    """
    if draw(st.integers(0, 11)) == 0:
        return draw(st.sampled_from(("asc", 5, (), None, True)))
    return _b2_compact(
        {
            "sortBy": draw(_b2_maybe(_B2_SORT_BY)),
            "sortOrder": draw(_b2_maybe(_B2_SORT_ORDER)),
            "valueField": draw(_b2_maybe(_B2_VALUE_FIELD)),
            "viewNLimit": draw(_b2_maybe(_B2_VIEWN)),
            "sortColumn": draw(
                _b2_maybe(st.sampled_from((None, "Linear", "sum", "value", "nope")))
            ),
            "colSortAttrs": draw(
                _b2_maybe(
                    st.one_of(
                        st.lists(_b2_flat_sort_attr(), max_size=2),
                        st.sampled_from(("x", {}, None, (None,))),
                    )
                )
            ),
            "segmentation": draw(_b2_maybe(st.just("value"))),
        }
    )


@st.composite
def _b2_sorting(draw: st.DrawFn) -> Any:
    """Draw one whole ``sorting`` block.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A sorting dict keyed by chart type, or a poison value.
    """
    if draw(st.integers(0, 15)) == 0:
        # F1: 5.0 is an in-annotation non-dict sorting block (S5).
        return draw(st.sampled_from(("asc", (), None, 5, True, 5.0)))
    out: dict[str, Any] = {}
    for _ in range(draw(st.integers(0, 3))):
        key = draw(_B2_CHART_KEYS)
        out[key] = (
            # F1: float / spelling-dict at the per-chart config position.
            draw(st.sampled_from((None, 5.0, {"spelling": "5.0"})))
            if draw(st.integers(0, 9)) == 0
            else draw(_b2_sort_config())
        )
    return out


@st.composite
def _b2_filter_clause(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one bookmark filter clause (B14-B21 space).

    Args:
        draw: Hypothesis draw function.

    Returns:
        A filter-clause dict (keys possibly absent).
    """
    return _b2_compact(
        {
            "filterType": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            None,
                            "string",
                            "number",
                            "boolean",
                            "datetime",
                            "list",
                            "FAKE",
                            "",
                        )
                    )
                )
            ),
            "filterOperator": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            None,
                            "equals",
                            "contains",
                            "does not contain",
                            "in",
                            "approximately",
                            "was on",
                            "",
                            _B2_NON_BMP,
                        )
                    )
                )
            ),
            "value": draw(
                _b2_maybe(
                    st.one_of(_B2_STRS, st.sampled_from(("$cohorts", None, 0, (), {})))
                )
            ),
            "propertyName": draw(_b2_maybe(_B2_STRS)),
            "customPropertyId": draw(
                _b2_maybe(
                    st.sampled_from((None, 0, 1, -3, True, False, 1.5, 42.0, "42", ()))
                )
            ),
            "customProperty": draw(
                _b2_maybe(st.sampled_from((None, {"displayFormula": "A"})))
            ),
            "resourceType": draw(
                _b2_maybe(
                    st.sampled_from(
                        (None, "events", "people", "cohorts", "BOGUS", "", 4)
                    )
                )
            ),
            # NOTE: non-finite filterValue members (B20B) are unshippable
            # here (section header) — locked by the authored corpus pair.
            "filterValue": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            None,
                            (),
                            ("US",),
                            (1, 2, 3),
                            "2024-01-01",
                            5,
                            ({"cohort": {"id": 1}},),
                            ({"notcohort": 1},),
                            {},
                        )
                    )
                )
            ),
        }
    )


@st.composite
def _b2_behavior(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one show-clause behavior dict (B6-B8, B19, B22-B23 space).

    Args:
        draw: Hypothesis draw function.

    Returns:
        A behavior dict (keys possibly absent).
    """
    return _b2_compact(
        {
            "type": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            "event",
                            "simple",
                            "custom-event",
                            "cohort",
                            "funnel",
                            "formula",
                            "evnt",
                            None,
                            "",
                            7,
                        )
                    )
                )
            ),
            "name": draw(_b2_maybe(_B2_STRS)),
            "value": draw(
                _b2_maybe(
                    st.sampled_from(({"name": "Login"}, {}, None, "x", {"name": None}))
                )
            ),
            "id": draw(
                _b2_maybe(st.sampled_from((1, 0, -1, True, False, None, 1.5, 3.0, "7")))
            ),
            "raw_cohort": draw(_b2_maybe(st.sampled_from((None, {"selector": {}})))),
            "resourceType": draw(
                _b2_maybe(
                    st.sampled_from((None, "events", "people", "cohorts", "BOGUS", ""))
                )
            ),
            "filtersDeterminer": draw(
                _b2_maybe(st.sampled_from((None, "all", "any", "some", 3)))
            ),
            "filters": draw(
                _b2_maybe(
                    st.one_of(
                        st.lists(_b2_filter_clause(), max_size=1),
                        st.just("x"),
                    )
                )
            ),
        }
    )


@st.composite
def _b2_show_clause(draw: st.DrawFn) -> Any:
    """Draw one show clause (B6-B11 space).

    Args:
        draw: Hypothesis draw function.

    Returns:
        A show-clause dict or a poison value.
    """
    if draw(st.integers(0, 15)) == 0:
        return draw(st.sampled_from(("x", None, 5, ())))
    return _b2_compact(
        {
            "formula": draw(_b2_maybe(st.sampled_from(("", {"definition": "A/B"})))),
            "type": draw(_b2_maybe(st.sampled_from(("formula", "metric", None)))),
            "behavior": draw(
                _b2_maybe(st.one_of(_b2_behavior(), st.sampled_from((None, "x", {}))))
            ),
            "measurement": draw(
                _b2_maybe(
                    st.builds(
                        lambda math, prop, pua: _b2_compact(
                            {
                                "math": math,
                                "property": prop,
                                "perUserAggregation": pua,
                            }
                        ),
                        st.sampled_from(
                            (
                                "total",
                                "unique",
                                "average",
                                "median",
                                "dau",
                                "retention_rate",
                                "conversion_rate_unique",
                                "totl",
                                "",
                                _B2_NON_BMP,
                                None,
                                5,
                                (),
                            )
                        ),
                        _b2_maybe(
                            st.sampled_from(
                                (
                                    None,
                                    {"type": "number", "resourceType": "events"},
                                    "x",
                                )
                            )
                        ),
                        _b2_maybe(st.sampled_from((None, "total", "average", "nope"))),
                    )
                )
            ),
        }
    )


@st.composite
def _b2_bookmark_params(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one ``validate_bookmark`` kwargs bag.

    Args:
        draw: Hypothesis draw function.

    Returns:
        ``{"params": ..., "bookmark_type"?: ...}`` kwargs.
    """
    sections: Any = _b2_compact(
        {
            "show": draw(
                _b2_maybe(
                    st.one_of(
                        st.lists(_b2_show_clause(), max_size=2),
                        st.sampled_from(("x", None)),
                    )
                )
            ),
            "time": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            (),
                            ({"unit": "day", "dateRangeType": "in the last"},),
                            ({"unit": "fortnite"},),
                            ({"unit": "day", "dateRangeType": "whenever"},),
                            "x",
                            (None,),
                            (5.0,),  # F1: float at a dict position
                        )
                    )
                )
            ),
            "filter": draw(
                _b2_maybe(
                    st.one_of(
                        st.lists(_b2_filter_clause(), max_size=2),
                        st.sampled_from(
                            (
                                "x",
                                (None,),
                                # F1: float / class instance / spelling-dict
                                # at dict positions.
                                (5.0,),
                                (Filter.equals("a", "b"),),
                                ({"value": {"spelling": "hi"}},),
                            )
                        ),
                    )
                )
            ),
            "group": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            (),
                            ({"propertyName": "p", "propertyType": "string"},),
                            ({"propertyName": "p", "propertyType": "FAKE"},),
                            ({"propertyName": "p", "resourceType": "BOGUS"},),
                            ({"propertyName": "p", "cohorts": ()},),
                            ({"propertyName": "p", "cohorts": ({"id": 1},)},),
                            ({"propertyName": "p", "cohorts": "x"},),
                            ("nope",),
                            (None,),
                            (5.0,),  # F1: float at a dict position
                        )
                    )
                )
            ),
        }
    )
    if draw(st.integers(0, 9)) == 0:
        # F1: floats and spelling-dicts are in-annotation section values.
        sections = draw(st.sampled_from(("x", None, (), 5.0, {"spelling": "5.0"})))
    params = _b2_compact(
        {
            "sections": sections,
            "displayOptions": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            {"chartType": "line"},
                            {"chartType": "barchart"},
                            {"chartType": ""},
                            {"analysis": "linear"},
                            {},
                            "x",
                            None,
                            5.0,  # F1: float at a dict position
                        )
                    )
                )
            ),
            "sorting": draw(_b2_maybe(_b2_sorting())),
        }
    )
    return _b2_compact(
        {
            "params": params,
            "bookmark_type": draw(
                _b2_maybe(
                    st.sampled_from(("insights", "funnels", "retention", "bogus"))
                )
            ),
        }
    )


_BOOKMARK_FAMILY = FuzzTarget(
    name="bookmark_family",
    calls=_b2_bookmark_params().map(_b2_call(_BOOKMARK_API)),
    edge_calls=(
        # R10.9 value edges (B20B non-finite arms are corpus-authored —
        # unshippable here, see the section header).
        (_BOOKMARK_API, {"params": _b2_bookmark()}),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"value": "c", "filterValue": 18.0})},
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"value": "c", "filterValue": 1.5})},
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter", {"value": True, "customPropertyId": True}
                )
            },
        ),
        (_BOOKMARK_API, {"params": {"sections": None, "displayOptions": None}}),
        # F1 arbiter locks (b2-review-resolution.md, 2026-08-15): floats,
        # class instances and spelling-dicts at dict-expected positions —
        # Python's isinstance(x, dict) is False for the first two and
        # True for the third.
        (
            _BOOKMARK_API,
            {"params": {"sections": 5.0, "displayOptions": {"chartType": "line"}}},
        ),
        (
            _BOOKMARK_API,
            {
                "params": {
                    "sections": {"spelling": "5.0"},
                    "displayOptions": {"chartType": "line"},
                }
            },
        ),
        (_BOOKMARK_API, {"params": _b2_bm_section("time", 5.0)}),
        (_BOOKMARK_API, {"params": _b2_bm_section("group", 5.0)}),
        (_BOOKMARK_API, {"params": _b2_bm_section("filter", Filter.equals("a", "b"))}),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"value": {"spelling": "hi"}})},
        ),
        (_BOOKMARK_API, {"params": _b2_bm_show({"behavior": 5.0})}),
        (_BOOKMARK_API, {"params": _b2_bookmark(displayOptions=5.0)}),
        (
            _BOOKMARK_API,
            {"params": _b2_bookmark(displayOptions={"chartType": {"spelling": "2.0"}})},
        ),
        (
            _BOOKMARK_API,
            {"params": {"sections": {"show": []}, "displayOptions": {}}},
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"value": "", "propertyName": ""})},
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {
                            "type": _B2_NON_BMP,
                            "value": {"name": _B2_NON_BMP},
                        },
                        "measurement": {"math": _B2_NON_BMP},
                    }
                )
            },
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bookmark(), "bookmark_type": _B2_NON_BMP},
        ),
        # One call per B* code.
        (_BOOKMARK_API, {"params": {"displayOptions": {"chartType": "line"}}}),
        (
            _BOOKMARK_API,
            {"params": {"sections": ["x"], "displayOptions": {"chartType": "line"}}},
        ),
        (
            _BOOKMARK_API,
            {"params": {"sections": {"show": [{"behavior": {"type": "event"}}]}}},
        ),
        (
            _BOOKMARK_API,
            {
                "params": {
                    "sections": {"time": [], "filter": []},
                    "displayOptions": {"chartType": "line"},
                }
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": {
                    "sections": {"show": []},
                    "displayOptions": {"chartType": "line"},
                }
            },
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bookmark(displayOptions={"chartType": "barchart"})},
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bookmark(displayOptions={"analysis": "linear"})},
        ),
        (_BOOKMARK_API, {"params": _b2_bm_show({"measurement": {"math": "total"}})}),
        (_BOOKMARK_API, {"params": _b2_bm_show("nope")}),
        (_BOOKMARK_API, {"params": _b2_bm_show({"behavior": "nope"})}),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {"behavior": {"type": "evnt", "value": {"name": "L"}}}
                )
            },
        ),
        (_BOOKMARK_API, {"params": _b2_bm_show({"behavior": {"type": "event"}})}),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {"type": "event", "value": {"name": "L"}},
                        "measurement": {"math": "totl"},
                    }
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {"type": "event", "value": {"name": "L"}},
                        "measurement": {"math": "average"},
                    }
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {"type": "event", "value": {"name": "L"}},
                        "measurement": {"math": "total", "perUserAggregation": "nope"},
                    }
                )
            },
        ),
        (_BOOKMARK_API, {"params": _b2_bm_section("time", {"unit": "fortnite"})}),
        (_BOOKMARK_API, {"params": _b2_bm_section("time", "nope")}),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "time", {"unit": "day", "dateRangeType": "whenever"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter",
                    {
                        "filterType": "nope",
                        "filterOperator": "equals",
                        "value": "country",
                        "filterValue": ["US"],
                    },
                )
            },
        ),
        (_BOOKMARK_API, {"params": _b2_bm_section("filter", "nope")}),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter",
                    {
                        "filterType": "string",
                        "filterOperator": "approximately",
                        "value": "country",
                        "filterValue": ["US"],
                    },
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "group", {"propertyName": "p", "resourceType": "BOGUS"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "group", {"propertyName": "p", "propertyType": "FAKE"}
                )
            },
        ),
        (_BOOKMARK_API, {"params": _b2_bm_section("group", "nope")}),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter",
                    {
                        "filterType": "string",
                        "filterOperator": "equals",
                        "filterValue": ["US"],
                    },
                )
            },
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"customPropertyId": 0})},
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"customPropertyId": 42.0})},
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("filter", {"customPropertyId": True})},
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {
                            "type": "event",
                            "value": {"name": "L"},
                            "filtersDeterminer": "some",
                        }
                    }
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter", {"value": "country", "filterValue": []}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter",
                    {"value": "c", "filterValue": [f"v{i}" for i in range(1001)]},
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_cohort_show(
                    {"type": "cohort", "id": 0, "resourceType": "cohorts"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_cohort_show(
                    {"type": "cohort", "id": True, "resourceType": "cohorts"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_cohort_show(
                    {"type": "cohort", "id": False, "resourceType": "cohorts"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_cohort_show({"type": "cohort", "resourceType": "cohorts"})},
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_cohort_show(
                    {"type": "cohort", "id": 1, "resourceType": "events"}
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_cohort_show(
                    {"type": "cohort", "id": 1, "resourceType": "cohorts"},
                    {"math": "total"},
                )
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_section(
                    "filter",
                    {
                        "resourceType": "events",
                        "filterType": "list",
                        "value": "wrong",
                        "filterOperator": "contains",
                        "filterValue": [
                            {"cohort": {"id": 1, "name": "PU", "negated": False}}
                        ],
                    },
                )
            },
        ),
        (
            _BOOKMARK_API,
            {"params": _b2_bm_section("group", {"propertyName": "p", "cohorts": []})},
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {"behavior": {"type": "funnel"}, "measurement": {"math": "dau"}}
                ),
                "bookmark_type": "funnels",
            },
        ),
        (
            _BOOKMARK_API,
            {
                "params": _b2_bm_show(
                    {
                        "behavior": {"type": "event", "value": {"name": "S"}},
                        "measurement": {"math": "dau"},
                    }
                ),
                "bookmark_type": "retention",
            },
        ),
        # Emission-order pin (Caution §11): every section contributes.
        (
            _BOOKMARK_API,
            {
                "params": {
                    "sections": {
                        "show": [{"behavior": {"type": "bogus"}}, {"measurement": {}}],
                        "time": [{"unit": "nope"}],
                        "filter": [{"filterType": "nope"}],
                        "group": [{"propertyType": "nope"}],
                    },
                    "displayOptions": {"chartType": "nope"},
                    "sorting": {"bar": {"sortBy": "nope"}},
                }
            },
        ),
    ),
)

_FLOW_BOOKMARK_FAMILY = FuzzTarget(
    name="flow_bookmark_family",
    calls=st.builds(
        lambda steps, date_range, chart, count, version: {
            "params": _b2_compact(
                {
                    "steps": steps,
                    "date_range": date_range,
                    "chartType": chart,
                    "count_type": count,
                    "version": version,
                }
            )
        },
        st.one_of(
            st.just(_ABSENT),
            st.sampled_from(
                (
                    (),
                    ({"event": "Login"},),
                    ({"event": ""}, {"event": "Buy"}),
                    (None,),
                    ("Purchase",),
                    "Purchase",
                    ({},),
                )
            ),
        ),
        st.one_of(
            st.just(_ABSENT),
            st.sampled_from((None, {"type": "in the last"}, "x")),
        ),
        st.one_of(
            st.just(_ABSENT),
            st.sampled_from(
                ("sankey", "top-paths", "tree", "sanke", "", None, _B2_NON_BMP, 5)
            ),
        ),
        st.one_of(
            st.just(_ABSENT),
            st.sampled_from(("unique", "total", "session", "uniqe", "", None, 7)),
        ),
        st.one_of(
            st.just(_ABSENT),
            st.sampled_from((2, 1, 3, "2", True, None, 2.0, 2.5)),
        ),
    ).map(_b2_call(_FLOW_BOOKMARK_API)),
    edge_calls=(
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark()}),
        # F1 arbiter lock: a float step is skipped by the isinstance gate.
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark(steps=[5.0])}),
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark(version=2.0)}),
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark(version=1.5)}),
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark(version=True)}),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(count_type=None, chartType=None)},
        ),
        (_FLOW_BOOKMARK_API, {"params": _b2_flow_bookmark(steps=[])}),  # FLB1
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(steps="Purchase")},
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(steps=[{"event": "   "}])},  # FLB2
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(steps=[{"event": f"A{_B2_NUL}B"}])},
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(steps=[{"event": _B2_ZWSP}])},
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(steps=[{"event": _B2_NON_BMP}])},
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(count_type="uniqe")},  # FLB3
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(chartType="sanke")},  # FLB4
        ),
        (  # FLB5_MISSING_DATE_RANGE
            _FLOW_BOOKMARK_API,
            {
                "params": {
                    key: value
                    for key, value in _b2_flow_bookmark().items()
                    if key != "date_range"
                }
            },
        ),
        (
            _FLOW_BOOKMARK_API,
            {"params": _b2_flow_bookmark(version=1)},  # FLB6
        ),
    ),
)


def _b2_sorting_probe(config: Any) -> FuzzCall:
    """Wrap one bar-chart sorting config as a sorting probe.

    Args:
        config: The per-chart-type config value.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (_SORTING_API, {"sorting": {"bar": config}})


_B2_INT_COERCION_STRINGS: tuple[str, ...] = (
    "5",
    " 5 ",
    " 5",
    "﻿5",
    "​5",
    "+5",
    "-5",
    "1_0",
    "1__0",
    "_1",
    "1_",
    "0x5",
    "5.0",
    "5.",
    ".5",
    "1e3",
    "10.01",
    "1.0_0",
    "٤٢",
    "９",
    "",
    "  ",
    "9007199254740993",
    "1.000000000000000000000000",
    "1.0000000000000001",
    "  +1_0.0  ",
    "5​",
)
"""B2-M2 probe-pinned lax ``str -> int`` grammar corners (third-parser
carve-out; the twin's accept/reject decisions are pinned to these)."""

_SORTING_FAMILY = FuzzTarget(
    name="sorting_family",
    calls=st.fixed_dictionaries({"sorting": _b2_sorting()}).map(_b2_call(_SORTING_API)),
    # NOTE: the ``finite_number`` route needs a non-finite viewNLimit —
    # unshippable here (section header); B0_MISSING_FIELD /
    # B0_VALIDATOR_ERROR are unreachable (B2-M2 probe finding 5) and
    # their nearest reachable neighbours are pinned below.
    edge_calls=(
        (_SORTING_API, {"sorting": None}),
        (_SORTING_API, {"sorting": []}),
        (_SORTING_API, {"sorting": {}}),
        (_SORTING_API, {"sorting": ""}),
        # F1 arbiter locks: float / spelling-dict at dict positions
        # (S5 vs the model walk).
        (_SORTING_API, {"sorting": 5.0}),
        (_SORTING_API, {"sorting": {"bar": 5.0}}),
        (_SORTING_API, {"sorting": {"bar": {"spelling": "1.5"}}}),
        (
            _SORTING_API,
            {"sorting": {"table": {"sortBy": "column", "colSortAttrs": [5.0]}}},
        ),
        (_SORTING_API, {"sorting": {"": {}}}),
        (_SORTING_API, {"sorting": {_B2_NON_BMP: {}}}),
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": 5.0,
            }
        ),
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": 1.5,
            }
        ),
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": True,
            }
        ),
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "valueField": _B2_NON_BMP,
            }
        ),
        _b2_sorting_probe({"sortBy": "totally bogus", "colSortAttrs": []}),  # S1
        _b2_sorting_probe({"sortBy": "value"}),  # S2
        _b2_sorting_probe(
            {"sortBy": "value", "colSortAttrs": [], "segmentation": "x"}
        ),  # S3
        (_SORTING_API, {"sorting": {"sankey": {"sortBy": "value"}}}),  # S3/S4
        (
            _SORTING_API,
            {"sorting": {"barz": {"sortBy": "column", "colSortAttrs": []}}},
        ),  # S4 (severity "warning")
        (_SORTING_API, {"sorting": ["asc"]}),  # S5
        _b2_sorting_probe("asc"),  # S5 config
        _b2_sorting_probe({"sortBy": "column", "colSortAttrs": ["x"]}),  # S5 elem
        _b2_sorting_probe(
            {"sortBy": "value", "sortOrder": "ascending", "colSortAttrs": []}
        ),  # S6
        _b2_sorting_probe({"sortBy": "column", "colSortAttrs": {}}),  # S7
        _b2_sorting_probe({"sortBy": "column", "colSortAttrs": None}),  # S7
        _b2_sorting_probe(
            {"sortBy": "column", "colSortAttrs": [{"sortOrder": "asc"}]}
        ),  # S8
        _b2_sorting_probe(
            {"sortBy": "column", "colSortAttrs": [{"sortBy": "label"}]}
        ),  # S9
        _b2_sorting_probe(
            {"sortBy": "value", "sortOrder": "asc", "colSortAttrs": [], "valueField": 3}
        ),  # B0_WRONG_TYPE string_type
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": "x",
            }
        ),  # B0_WRONG_TYPE int_parsing
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": [],
            }
        ),  # B0_WRONG_TYPE int_type
        (
            _SORTING_API,
            {
                "sorting": {
                    "table": {
                        "sortBy": "value",
                        "sortOrder": "asc",
                        "sortColumn": "nope",
                        "colSortAttrs": [],
                    }
                }
            },
        ),  # B0_INVALID_LITERAL
        _b2_sorting_probe(
            {
                "sortBy": "value",
                "sortOrder": "asc",
                "colSortAttrs": [],
                "viewNLimit": 5.5,
            }
        ),  # VALIDATION_ERROR int_from_float
        (
            _SORTING_API,
            {
                "sorting": {
                    "table": {
                        "sortColumn": None,
                        "sortOrder": "asc",
                        "colSortAttrs": [],
                    }
                }
            },
        ),  # B0_MISSING_FIELD nearest-reachable
        (
            _SORTING_API,
            {
                "sorting": {
                    "table": {
                        "sortBy": "value",
                        "sortOrder": "asc",
                        "sortColumn": None,
                        "colSortAttrs": [],
                    }
                }
            },
        ),  # B0_VALIDATOR_ERROR nearest-reachable
        # Emission-order pins (B2-M2 probe finding 1).
        (
            _SORTING_API,
            {
                "sorting": {
                    "pie": {"sortBy": "nope", "colSortAttrs": []},
                    "sankey": {},
                    "bar": {"sortBy": "nope", "colSortAttrs": []},
                    "funnel-steps": {"sortBy": "nope", "colSortAttrs": []},
                    "column": {},
                    "table": {"sortBy": "nope", "colSortAttrs": []},
                    "barz": {},
                }
            },
        ),
        (
            _SORTING_API,
            {
                "sorting": {
                    "bar": {"zz": 1, "sortBy": "nope", "aa": 2, "colSortAttrs": []}
                }
            },
        ),
        _b2_sorting_probe(
            {
                "sortBy": "column",
                "colSortAttrs": [
                    {"sortBy": "label"},
                    {"sortBy": "value", "sortOrder": "x"},
                    {},
                ],
            }
        ),
        # Lax int-coercion grammar corners (B2-M2 probe finding 4).
        *(
            _b2_sorting_probe(
                {
                    "sortBy": "value",
                    "sortOrder": "asc",
                    "colSortAttrs": [],
                    "viewNLimit": text,
                }
            )
            for text in _B2_INT_COERCION_STRINGS
        ),
    ),
)

# ---- V2 — user validator families ------------------------------------------

_B2_COHORT_DEF_AND = CohortDefinition.all_of(
    CohortCriteria.did_event("Purchase", at_least=1, within_days=30)
)
"""Valid AND-combined inline cohort definition (U2/U24 happy path)."""

_B2_COHORT_DEF_OR = CohortDefinition.any_of(
    CohortCriteria.did_event("Purchase", at_least=1, within_days=30),
    CohortCriteria.did_event("Login", at_least=2, within_days=7),
)
"""Valid OR-combined inline cohort definition."""

_B2_USER_STRS: tuple[Any, ...] = (
    "",
    "   ",
    "$last_seen",
    _B2_NON_BMP,
    _B2_ZWSP,
    "a\nb",
)
"""String pool for the user-args str-typed fields."""

_B2_WHERE_POOL: tuple[Any, ...] = (
    None,
    "",
    'properties["a"] == 1',
    Filter.equals("plan", "premium"),
    Filter.equals("", "x"),
    Filter.equals(_B2_NON_BMP, "x"),
    Filter.equals(CustomPropertyRef(id=9), "x"),
    Filter.in_cohort(1),
    Filter.not_in_cohort(2),
    (),
    (Filter.equals("plan", "pro"),),
    (Filter.in_cohort(1), Filter.in_cohort(2)),
    (Filter.in_cohort(1), Filter.not_in_cohort(2)),
    (Filter.equals("a", "b"), "not-a-filter"),
    ("not-a-filter",),
    (42,),
    (Filter.equals(CustomPropertyRef(id=1), "x"), Filter.equals("", "y")),
)
"""``where`` pool: str/Filter/list shapes incl. cohort filters (U0/U12/U13/U25)."""

_B2_USER_NUMS: tuple[Any, ...] = (
    0,
    1,
    -1,
    5,
    6,
    100,
    -100,
    True,
    False,
    1.5,
    -1.5,
    0.0,
    5.0,
    None,
)
"""Numeric pool for limit/percentile (non-finite floats unshippable)."""

_B2_AS_OF_POOL: tuple[Any, ...] = (
    "2026-01-14",
    "2026-01-15",
    "2026-01-16",
    "2025-12-31",
    "2027-01-01",
    "2026-02-30",
    "2026-13-01",
    "2026-00-10",
    "20260114",
    "2026-1-4",
    "2026-01-14\n",
    "٢٠٢٦-٠١-١٤",
    "0000-01-01",
    "9999-12-31",
    "not-a-date",
    "",
    _B2_NON_BMP,
    1700000000,
    0,
    -1,
    18.0,
    True,
    None,
)
"""``as_of`` pool: frozen-clock boundary dates + grammar corners (U6/U8)."""


@st.composite
def _b2_user_args(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one ``validate_user_args`` kwargs bag.

    Args:
        draw: Hypothesis draw function.

    Returns:
        Kwargs with keys possibly absent (Python defaults apply).
    """
    return _b2_compact(
        {
            "mode": draw(
                st.sampled_from(("profiles", "aggregate", "Profiles", "", None))
            ),
            "aggregate": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            "count",
                            "extremes",
                            "percentile",
                            "numeric_summary",
                            "Count",
                            "",
                            None,
                        )
                    )
                )
            ),
            "aggregate_property": draw(
                _b2_maybe(st.sampled_from((*_B2_USER_STRS, None)))
            ),
            "percentile": draw(_b2_maybe(st.sampled_from(_B2_USER_NUMS))),
            "limit": draw(_b2_maybe(st.sampled_from(_B2_USER_NUMS))),
            # workers=None is outside both signatures (section header).
            "workers": draw(
                _b2_maybe(
                    st.sampled_from(tuple(v for v in _B2_USER_NUMS if v is not None))
                )
            ),
            "segment_by": draw(
                _b2_maybe(
                    st.sampled_from(
                        (
                            None,
                            (),
                            (1, 2),
                            (0,),
                            (-1,),
                            (1, 0, -1),
                            (2.0,),
                            (-1.5,),
                            (True,),
                        )
                    )
                )
            ),
            "where": draw(_b2_maybe(st.sampled_from(_B2_WHERE_POOL))),
            "cohort": draw(
                _b2_maybe(
                    st.sampled_from(
                        (None, 1, 0, -3, _B2_COHORT_DEF_AND, _B2_COHORT_DEF_OR)
                    )
                )
            ),
            "properties": draw(
                _b2_maybe(
                    st.sampled_from(
                        (None, (), ("$email",), ("", "a"), (_B2_NON_BMP,), ("   ",))
                    )
                )
            ),
            "sort_by": draw(_b2_maybe(st.sampled_from((*_B2_USER_STRS, None)))),
            "search": draw(_b2_maybe(st.sampled_from((*_B2_USER_STRS, None)))),
            "distinct_id": draw(_b2_maybe(st.sampled_from((*_B2_USER_STRS, None)))),
            "distinct_ids": draw(
                _b2_maybe(st.sampled_from((None, (), ("u1",), ("u1", "u2"))))
            ),
            "group_id": draw(_b2_maybe(st.sampled_from((*_B2_USER_STRS, None)))),
            "as_of": draw(_b2_maybe(st.sampled_from(_B2_AS_OF_POOL))),
            "parallel": draw(_b2_maybe(st.booleans())),
            "include_all_users": draw(_b2_maybe(st.booleans())),
            "sort_order": draw(
                _b2_maybe(st.sampled_from(("ascending", "descending", "asc")))
            ),
        }
    )


_B2_ACTION_POOL: tuple[Any, ...] = (
    "count()",
    "count()\n",
    "count()\n\n",
    'extremes(properties["ltv"])',
    'extremes(properties[""])',
    f'extremes(properties["{_B2_NON_BMP}"])',
    'extremes(properties["a\nb"])',
    'extremes(properties["a\rb"])',
    'numeric_summary(properties["revenue"])',
    'percentile(properties["age"], 50)',
    'percentile(properties["age"],50)',
    'percentile(properties["age"],\t50)',
    'percentile(properties["age"], 50)',
    'percentile(properties["age"], 50)',
    'percentile(properties["age"],﻿50)',
    'percentile(properties["age"], ٠١)',
    'percentile(properties["age"], ..)',
    'percentile(properties["age"], 5"], 7)',
    'percentile(properties["age"], )',
    "median(ltv)",
    "",
    "  count()  ",
    42,
    None,
    True,
    ("count()",),
)
"""``action`` pool: UP4 grammar corners (\\s/\\d/./$ Python semantics)."""

_B2_FBC_POOL: tuple[Any, ...] = (
    None,
    {},
    {"id": 1},
    {"raw_cohort": {"selector": {}}},
    {"name": "x"},
    {"id": None},
    '{"id": 1}',
    '{"name": "x"}',
    "123",
    "NaN",
    "Infinity",
    "nope",
    "{",
    "[]",
    "[{}]",
    (),
    ({"id": 1},),
    42,
    True,
    "",
    _B2_NON_BMP,
)
"""``filter_by_cohort`` pool: dict / JSON-string / bad-JSON shapes (UP2)."""

_B2_OP_POOL: tuple[Any, ...] = (
    None,
    (),
    ("$email",),
    "[]",
    '["$email"]',
    "notjson",
    "{}",
    '{"a":1}',
    "",
    42,
    True,
    {},
)
"""``output_properties`` pool (UP3 JSON round-trips)."""


@st.composite
def _b2_user_params(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one ``validate_user_params`` kwargs bag.

    Args:
        draw: Hypothesis draw function.

    Returns:
        ``{"params": ...}`` kwargs.
    """
    return {
        "params": _b2_compact(
            {
                "sort_order": draw(
                    _b2_maybe(
                        st.sampled_from(
                            (
                                "ascending",
                                "descending",
                                "asc",
                                "",
                                None,
                                1,
                                True,
                                _B2_NON_BMP,
                            )
                        )
                    )
                ),
                "filter_by_cohort": draw(_b2_maybe(st.sampled_from(_B2_FBC_POOL))),
                "output_properties": draw(_b2_maybe(st.sampled_from(_B2_OP_POOL))),
                "action": draw(_b2_maybe(st.sampled_from(_B2_ACTION_POOL))),
                "distinct_id": draw(_b2_maybe(st.just("u1"))),
            }
        )
    }


def _ua(**kwargs: Any) -> FuzzCall:
    """Shorthand for one ``validate_user_args`` probe.

    Args:
        kwargs: The call kwargs.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (_USER_ARGS_API, kwargs)


def _up(params: dict[str, Any]) -> FuzzCall:
    """Shorthand for one ``validate_user_params`` probe.

    Args:
        params: The engage params dict.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    return (_USER_PARAMS_API, {"params": params})


_USER_ARGS_FAMILY = FuzzTarget(
    name="user_args_family",
    calls=_b2_user_args().map(_b2_call(_USER_ARGS_API)),
    # One call per code U0-U30 (no U9 — call-site rule; U24 unreachable
    # from a serialisable input, B2-M3 notes — its nearest arms are the
    # cohortdef happy paths) + the R10.9 value edges + the frozen-clock
    # U8 boundary + the as_of grammar corners (B2-M3 finding 1).
    edge_calls=(
        _ua(where=["not-a-filter"], mode="profiles"),  # U0
        _ua(distinct_id="a", distinct_ids=["b"], mode="profiles"),  # U1
        _ua(cohort=7, where=[Filter.in_cohort(1)], mode="profiles"),  # U2
        _ua(limit=0, mode="profiles"),  # U3
        _ua(distinct_ids=[], mode="profiles"),  # U4
        _ua(sort_by="   ", mode="profiles"),  # U5
        _ua(as_of="2025-02-30", mode="profiles"),  # U6
        _ua(include_all_users=True, mode="profiles"),  # U7
        _ua(as_of="2026-06-01", mode="profiles"),  # U8
        _ua(where=Filter.equals("", "t"), mode="profiles"),  # U10
        _ua(properties=["ok", "  "], mode="profiles"),  # U11
        _ua(where=Filter.not_in_cohort(3), mode="profiles"),  # U12
        _ua(  # U13
            where=[Filter.in_cohort(1), Filter.in_cohort(2)], mode="profiles"
        ),
        _ua(mode="aggregate", aggregate="extremes"),  # U14
        _ua(mode="aggregate", aggregate="count", aggregate_property="ltv"),  # U15
        _ua(segment_by=[1], mode="profiles"),  # U16
        _ua(segment_by=[0], mode="aggregate", aggregate="count"),  # U17
        _ua(parallel=True, mode="aggregate", aggregate="count"),  # U18
        _ua(sort_by="s", mode="aggregate", aggregate="count"),  # U19
        _ua(search="j", mode="aggregate", aggregate="count"),  # U20
        _ua(distinct_id="u", mode="aggregate", aggregate="count"),  # U21
        _ua(properties=["p"], mode="aggregate", aggregate="count"),  # U22
        _ua(workers=9, mode="profiles"),  # U23
        _ua(  # U25
            where=Filter.equals(CustomPropertyRef(id=42), "x"), mode="profiles"
        ),
        _ua(mode="aggregate", aggregate="percentile", aggregate_property="a"),  # U26
        _ua(mode="aggregate", aggregate="count", percentile=50),  # U27
        _ua(  # U28
            mode="aggregate",
            aggregate="percentile",
            aggregate_property="a",
            percentile=0,
        ),
        _ua(properties=[], mode="profiles"),  # U29
        _ua(as_of="2025-01-01", mode="aggregate", aggregate="count"),  # U30
        # R10.9 value edges (carrier probes on the numeric args).
        _ua(limit=18.0, mode="profiles"),
        _ua(workers=18.0, mode="profiles"),
        _ua(
            mode="aggregate",
            aggregate="percentile",
            aggregate_property="a",
            percentile=50.0,
        ),
        _ua(segment_by=[2.0], mode="aggregate", aggregate="count"),
        _ua(as_of=18.0, mode="profiles"),
        _ua(cohort=18.0, mode="profiles"),
        _ua(limit=1.5, mode="profiles"),
        _ua(workers=1.5, mode="profiles"),
        _ua(
            mode="aggregate",
            aggregate="percentile",
            aggregate_property="a",
            percentile=1.5,
        ),
        _ua(segment_by=[-1.5], mode="aggregate", aggregate="count"),
        _ua(parallel=True, mode="profiles"),
        _ua(include_all_users=True, cohort=1),
        _ua(limit=True, mode="profiles"),
        _ua(workers=True, mode="profiles"),
        _ua(
            mode="aggregate",
            aggregate="percentile",
            aggregate_property="a",
            percentile=True,
        ),
        _ua(segment_by=[True], mode="aggregate", aggregate="count"),
        _ua(),
        _ua(
            where=None,
            cohort=None,
            properties=None,
            sort_by=None,
            limit=None,
            search=None,
            distinct_id=None,
            distinct_ids=None,
            group_id=None,
            as_of=None,
            aggregate_property=None,
            percentile=None,
            segment_by=None,
            mode="profiles",
        ),
        _ua(where=[], mode="profiles"),
        _ua(properties=[], mode="profiles"),
        _ua(distinct_ids=[], mode="profiles"),
        _ua(segment_by=[], mode="aggregate", aggregate="count"),
        _ua(sort_by="", mode="profiles"),
        _ua(search="", mode="profiles"),
        _ua(as_of="", mode="profiles"),
        _ua(where="", mode="profiles"),
        _ua(distinct_id="", mode="profiles"),
        _ua(properties=[""], mode="profiles"),
        _ua(where=Filter.equals("", "v"), mode="profiles"),
        _ua(sort_by=_B2_NON_BMP, mode="profiles"),
        _ua(properties=[_B2_NON_BMP], mode="profiles"),
        _ua(as_of=_B2_NON_BMP, mode="profiles"),
        _ua(where=Filter.equals(_B2_NON_BMP, _B2_NON_BMP), mode="profiles"),
        _ua(search=_B2_NON_BMP, mode="profiles"),
        # today-seam boundary (frozen-1 / frozen / frozen+1).
        _ua(as_of="2026-01-14", mode="profiles"),
        _ua(as_of="2026-01-15", mode="profiles"),
        _ua(as_of="2026-01-16", mode="profiles"),
        # _DATE_RE / fromisoformat grammar corners (B2-M3 finding 1).
        _ua(as_of="20260114", mode="profiles"),
        _ua(as_of="2026-1-4", mode="profiles"),
        _ua(as_of="2026-01-14\n", mode="profiles"),
        _ua(as_of="٢٠٢٦-٠١-١٤", mode="profiles"),
        _ua(as_of="0000-01-01", mode="profiles"),
        _ua(as_of="2024-02-29", mode="profiles"),
        _ua(as_of="2025-02-29", mode="profiles"),
        # Inline cohort definitions (U2/U24 happy path).
        _ua(cohort=_B2_COHORT_DEF_AND, mode="profiles"),
        _ua(cohort=_B2_COHORT_DEF_OR, mode="profiles"),
    ),
)

_USER_PARAMS_FAMILY = FuzzTarget(
    name="user_params_family",
    calls=_b2_user_params().map(_b2_call(_USER_PARAMS_API)),
    edge_calls=(
        _up({"sort_order": "asc"}),  # UP1
        _up({"filter_by_cohort": {}}),  # UP2
        _up({"output_properties": []}),  # UP3
        _up({"action": "median(x)"}),  # UP4
        _up({}),
        _up({"sort_order": 18.0}),
        _up({"output_properties": 1.5}),
        _up({"sort_order": True, "action": True}),
        _up(
            {
                "sort_order": None,
                "filter_by_cohort": None,
                "output_properties": None,
                "action": None,
            }
        ),
        _up({"output_properties": [], "filter_by_cohort": []}),
        _up(
            {
                "sort_order": "",
                "filter_by_cohort": "",
                "output_properties": "",
                "action": "",
            }
        ),
        _up(
            {
                "sort_order": _B2_NON_BMP,
                "action": f'extremes(properties["{_B2_NON_BMP}"])',
            }
        ),
        _up({"filter_by_cohort": '{"id": 1}'}),
        _up({"filter_by_cohort": "123"}),
        # F1 arbiter locks: a float is not a dict (no UP2); a plain dict
        # carrying a literal "spelling" key IS a dict (UP2).
        _up({"filter_by_cohort": 5.0}),
        _up({"filter_by_cohort": {"spelling": "5.0"}}),
        _up({"filter_by_cohort": "NaN"}),  # json.loads pythonConstants
        _up({"filter_by_cohort": "nope", "action": "bad", "sort_order": "x"}),
        _up({"output_properties": "[]"}),
        _up({"output_properties": '["$email"]'}),
        _up({"output_properties": "notjson"}),
        _up({"action": "count()"}),
        _up({"action": "count()\n"}),
        _up({"action": "count()\n\n"}),
        _up({"action": 'percentile(properties["a"], 50)'}),
        _up({"action": 'percentile(properties["a"],\t50)'}),
        _up({"action": 'percentile(properties["a"], 50)'}),
        _up({"action": 'percentile(properties["a"],﻿50)'}),
        _up({"action": 'percentile(properties["a"], ٠١)'}),
        _up({"action": 'percentile(properties["a"], ..)'}),
        _up({"action": 'percentile(properties["a"], 5"], 7)'}),
        _up({"action": 'extremes(properties["a\rb"])'}),
        _up({"action": 'extremes(properties["a\nb"])'}),
        _up({"action": 'extremes(properties[""])'}),
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


# ---------------------------------------------------------------------------
# Phase-3 B3-K1 — bookmark_schema families (b3-packets.md §"R10.9 harness
# spec (K1)")
#
# ``validate_with_pydantic`` takes a MODEL CLASS, which is not
# JSON-transportable, so both the recorder registry and these strategies
# address models by NAME; the (b′) binding task points the registry entry
# at the name-resolving adapter in ``conformance/record/adapters.py`` and
# forwards with the DEFAULT code mapper (the ``_sorting_code_mapper`` path
# is already fuzz-covered through ``validation.validate_sorting_block``,
# bound at B2). Until that adapter lands these two targets are declared
# but unserved — the same "registered at (b′)" posture the B2 validator
# families were declared under.
#
# Reference semantics are pydantic-core in LAX mode, pinned by the B3-K1
# CPython probe (``context/phase3/notes/B3-K1-notes.md`` §Probe).
# ---------------------------------------------------------------------------

_BOOKMARK_SCHEMA_API = "bookmark_schema.validate_with_pydantic"
_ROOT_MODEL_API = "bookmark_schema.get_root_model_for_bookmark_type"

_B3_MODEL_NAMES: tuple[str, ...] = (
    "InsightsBookmarkSortConfig",
    "InsightsBookmarkParams",
    "FlowsBookmarkParams",
    "Sections",
    "DisplayOptions",
)
"""The five models the (b′) adapter resolves by name."""


def _b3_sections_base() -> dict[str, Any]:
    """Return a minimal VALID ``Sections`` dict."""
    return {
        "show": [
            {
                "type": "metric",
                "behavior": {"type": "event", "name": "Login"},
                "measurement": {"math": "total"},
            }
        ],
        "time": [],
    }


def _b3_display_base() -> dict[str, Any]:
    """Return a minimal VALID ``DisplayOptions`` dict."""
    return {"chartType": "bar", "plotStyle": "standard"}


def _b3_insights_base() -> dict[str, Any]:
    """Return a minimal VALID ``InsightsBookmarkParams`` dict."""
    return {"displayOptions": _b3_display_base(), "sections": _b3_sections_base()}


def _b3_flows_base() -> dict[str, Any]:
    """Return a minimal VALID ``FlowsBookmarkParams`` dict."""
    return {
        "steps": [{"event": "Login", "forward": 1}],
        "date_range": {"from_date": "2025-01-01"},
    }


def _b3_sorting_base() -> dict[str, Any]:
    """Return a minimal VALID ``InsightsBookmarkSortConfig`` dict."""
    return {"bar": {"sortBy": "column", "colSortAttrs": []}}


_B3_BASES: dict[str, Any] = {
    "InsightsBookmarkSortConfig": _b3_sorting_base,
    "InsightsBookmarkParams": _b3_insights_base,
    "FlowsBookmarkParams": _b3_flows_base,
    "Sections": _b3_sections_base,
    "DisplayOptions": _b3_display_base,
}

_B3_LEAF_PATHS: dict[str, tuple[tuple[Any, ...], ...]] = {
    "InsightsBookmarkSortConfig": (
        ("bar",),
        ("bar", "sortBy"),
        ("bar", "colSortAttrs"),
        ("table",),
        ("line",),
    ),
    "InsightsBookmarkParams": (
        ("name",),
        ("versions",),
        ("sorting",),
        ("icon",),
        ("id",),
        ("isNewQBEnabled",),
        ("displayOptions", "chartType"),
        ("displayOptions", "rollingWindowSize"),
        ("displayOptions", "queryTimeSampling"),
        ("displayOptions", "statSigControl"),
        ("displayOptions", "funnelStepsSelectedTableColumns"),
        ("sections", "show"),
        ("sections", "time"),
    ),
    "FlowsBookmarkParams": (
        ("steps",),
        ("date_range",),
        ("version",),
        ("alignment",),
        ("hidden_events",),
        ("collapse_repeated",),
        ("chartType",),
    ),
    "Sections": (
        ("show",),
        ("time",),
        ("filter",),
        ("globalDataGroupId",),
        ("metricLevelDataGroups",),
    ),
    "DisplayOptions": (
        ("chartType",),
        ("plotStyle",),
        ("rollingWindowSize",),
        ("queryTimeSampling",),
        ("annotationOptions",),
        ("statSigControl",),
        ("axisAssignments",),
        ("theme",),
    ),
}
"""Leaf positions worth poking, per model."""

_B3_LEAF_VALUES: tuple[Any, ...] = (
    # R10.9 mandatory edge set.
    18.0,
    1.5,
    True,
    None,
    [],
    "",
    _B2_NON_BMP,
    # Coercion corners (probe `probe-grammar.py`).
    0,
    1,
    2,
    -1,
    "5",
    " 5 ",
    "﻿5",
    "\xa05",
    "٥",
    "1_0",
    "1__0",
    "0x5",
    "1e3",
    "inf",
    "nan",
    "true",
    "TRUE",
    " true ",
    # NON-FINITE FLOATS OMITTED (B3-BIND): `float("inf")`/`float("nan")`
    # are unshippable through `encode_input_kwargs` (`_reject_bad_float`,
    # D6 rule 5) — the same standing omission as the B2 `finite_number`
    # arms (§B2 domain notes). The K1 module throwaway harness
    # (`throwaway/b3-k1/`, its own `__pyfloat__` transport) covered the
    # `finite_number` pydantic row directly; through the oracle bridges
    # the nearest reachable neighbours are the huge-magnitude finite
    # floats below (`int_parsing_size`).
    1e300,
    # Model-shaped values.
    {},
    {"k": 1},
    [{}],
    "bar",
    "column",
    "metric",
)
"""Leaf substitutions: the mandatory edges plus the lax-coercion corners."""

_B3_MANDATORY_EDGES: tuple[Any, ...] = (18.0, 1.5, True, None, [], "", _B2_NON_BMP)
"""The R10.9 mandatory edge set, verbatim (integral float, fractional
float, True, None, empty list, empty string, non-BMP)."""

_B3_GRAFT_SHOW_CLAUSES: tuple[Any, ...] = (
    {"type": "metric", "behavior": {"behaviors": [{"behaviors": [{}]}]}},
    {"formula": "A/B", "measurement": {"multiAttribution": {"type": "custom"}}},
    {
        "type": "metric",
        "goals": [{"id": "g", "label": "L", "checkpoints": [["a", 1.0]]}],
    },
    {"type": "metric", "statsig": {"control_key": "c", "exposures": {"a": {"b": 1}}}},
    {"type": "metric", "behavior": {"exclusions": [{"steps": {"from": 1}}]}},
    {"type": "metric", "display": {"precision": 9}},
    5,
    None,
)
"""Deep `show`-clause grafts: discriminator, plain-union, tuple and
recursive-nesting routes."""


def _b3_set_path(obj: Any, path: tuple[Any, ...], value: Any) -> None:
    """Set ``value`` at ``path``, creating intermediate dicts.

    Never writes an int key into a dict: such an input is not
    JSON-transportable, so the two bridges would not see the same value.

    Args:
        obj: The container to mutate in place.
        path: Key/index path.
        value: The value to store.
    """
    cur = obj
    for key in path[:-1]:
        if isinstance(cur, dict):
            if isinstance(key, int):
                return
            if key not in cur or not isinstance(cur[key], (dict, list)):
                cur[key] = {}
            cur = cur[key]
        elif isinstance(cur, list):
            if not isinstance(key, int) or key >= len(cur):
                return
            cur = cur[key]
        else:
            return
    last = path[-1]
    if isinstance(cur, dict) and not isinstance(last, int):
        cur[last] = value


@st.composite
def _b3_schema_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one near-valid / mutated ``validate_with_pydantic`` probe.

    Args:
        draw: Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe.
    """
    model = draw(st.sampled_from(_B3_MODEL_NAMES))
    value: Any = _B3_BASES[model]()
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        choice = draw(st.integers(min_value=0, max_value=5))
        if choice == 0:
            path = draw(st.sampled_from(_B3_LEAF_PATHS[model]))
            _b3_set_path(value, path, draw(st.sampled_from(_B3_LEAF_VALUES)))
        elif choice == 1:
            path = draw(st.sampled_from(_B3_LEAF_PATHS[model]))
            cur = value
            for key in path[:-1]:
                cur = cur.get(key) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if isinstance(cur, dict):
                cur.pop(path[-1], None)
        elif choice == 2:
            # Integer-like unknown keys ("1", "42", …) are EXCLUDED by
            # construction: JS objects hoist array-index-like keys, so
            # mixed integer-like/non-integer-like extras on an
            # extra="forbid" model emit `extra_forbidden` in a different
            # ORDER (content identical) — playbook Discrepancy #10
            # (arbiter ruling on K1-D1, b3-review-resolution.md
            # 2026-08-15; same JS-engine limitation as Discrepancy #9,
            # documented-omission pattern per strategies.py §B2 notes).
            key = draw(st.sampled_from(("zzz", "aaa", "b", _B2_NON_BMP, "_idx")))
            if isinstance(value, dict):
                value[key] = draw(st.sampled_from(_B3_LEAF_VALUES))
        elif choice == 3:
            graft = json.loads(
                json.dumps(draw(st.sampled_from(_B3_GRAFT_SHOW_CLAUSES)))
            )
            if model == "Sections" and isinstance(value, dict):
                value["show"] = [graft]
            elif (
                model == "InsightsBookmarkParams"
                and isinstance(value, dict)
                and isinstance(value.get("sections"), dict)
            ):
                value["sections"]["show"] = [graft]
            else:
                _b3_set_path(value, draw(st.sampled_from(_B3_LEAF_PATHS[model])), graft)
        elif choice == 4:
            key = draw(
                st.sampled_from(("alignment", "icon", "id", "isNewQBEnabled", "title"))
            )
            if isinstance(value, dict):
                value[key] = draw(st.sampled_from(_B3_LEAF_VALUES))
        else:
            value = draw(st.sampled_from(_B3_LEAF_VALUES))
    kwargs: dict[str, Any] = {"model": model, "value": value}
    if draw(st.booleans()):
        kwargs["path_prefix"] = draw(
            st.sampled_from(("", "params", "params.sections", _B2_NON_BMP))
        )
    return (_BOOKMARK_SCHEMA_API, kwargs)


def _b3_schema_edge(model: str, value: Any, **over: Any) -> FuzzCall:
    """Build one ``validate_with_pydantic`` edge probe.

    Args:
        model: The model name.
        value: The raw value to validate.
        over: Extra kwargs (``path_prefix``).

    Returns:
        The ``(api, kwargs)`` probe.
    """
    kwargs: dict[str, Any] = {"model": model, "value": value}
    kwargs.update(over)
    return (_BOOKMARK_SCHEMA_API, kwargs)


def _b3_ibp(**over: Any) -> dict[str, Any]:
    """Insights params with top-level overrides.

    Args:
        over: Key overrides.

    Returns:
        A fresh params dict.
    """
    base = _b3_insights_base()
    base.update(over)
    return base


def _b3_do(**over: Any) -> dict[str, Any]:
    """DisplayOptions with overrides.

    Args:
        over: Key overrides.

    Returns:
        A fresh options dict.
    """
    base = _b3_display_base()
    base.update(over)
    return base


def _b3_beh(behavior: Any) -> dict[str, Any]:
    """Sections carrying one behavior.

    Args:
        behavior: The behavior value.

    Returns:
        A sections dict.
    """
    return {"show": [{"type": "metric", "behavior": behavior}], "time": []}


_BOOKMARK_SCHEMA_FAMILY = FuzzTarget(
    name="bookmark_schema_family",
    calls=_b3_schema_calls(),
    # One probe per ``_DEFAULT_CODE_MAP`` row reachable through the
    # NON-sorting models, plus the R10.9 mandatory edge set as (i) raw
    # values and (ii) leaves inside an otherwise-valid params dict.
    # UNREACHABLE rows (B3-K1 probe finding 3): ``enum`` (no Enum types in
    # the module), ``union_tag_invalid`` / ``union_tag_not_found`` (the
    # ShowClause / sort discriminators are plain callables that always
    # return a declared Tag) and ``value_error`` (no custom validators) —
    # their nearest reachable neighbours are the ``model_type`` and
    # ``literal_error`` probes below.
    edge_calls=(
        # _DEFAULT_CODE_MAP coverage.
        _b3_schema_edge("InsightsBookmarkParams", {}),  # missing
        _b3_schema_edge("DisplayOptions", _b3_do(zzz=1)),  # extra_forbidden
        _b3_schema_edge("DisplayOptions", {"chartType": "nope"}),  # literal_error
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(name=5)),  # string_type
        _b3_schema_edge("DisplayOptions", _b3_do(rollingWindowSize=[])),  # int_type
        _b3_schema_edge(
            "DisplayOptions", _b3_do(rollingWindowSize="abc")
        ),  # int_parsing
        _b3_schema_edge("DisplayOptions", _b3_do(queryTimeSampling=[])),  # bool_type
        _b3_schema_edge(
            "DisplayOptions", _b3_do(queryTimeSampling="nope")
        ),  # bool_parsing
        _b3_schema_edge(
            "Sections", _b3_beh({"customBucket": {"bucketSize": []}})
        ),  # float_type
        _b3_schema_edge(
            "Sections", _b3_beh({"customBucket": {"bucketSize": "abc"}})
        ),  # float_parsing
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(versions=5)),  # list_type
        _b3_schema_edge(
            "FlowsBookmarkParams", {"steps": [], "date_range": 5}
        ),  # dict_type
        _b3_schema_edge("DisplayOptions", _b3_do(annotationOptions=5)),  # model_type
        # Unmapped-but-reachable rows (generic VALIDATION_ERROR).
        _b3_schema_edge(
            "DisplayOptions", _b3_do(rollingWindowSize=1.5)
        ),  # int_from_float
        # `finite_number` probe (`rollingWindowSize=float("inf")`) OMITTED:
        # non-finite floats are unshippable through `encode_input_kwargs`
        # (D6 rule 5; see the `_B3_LEAF_VALUES` note). The row stays
        # locked by the K1 throwaway harness + Layer-3; the 1e300 probe
        # below is the nearest bridge-reachable neighbour.
        _b3_schema_edge("DisplayOptions", _b3_do(rollingWindowSize=1e300)),
        _b3_schema_edge(
            "Sections",
            {
                "show": [
                    {
                        "type": "metric",
                        "goals": [
                            {"id": "g", "label": "L", "checkpoints": [["a", 1, 2]]}
                        ],
                    }
                ],
                "time": [],
            },
        ),  # too_long
        _b3_schema_edge(
            "Sections",
            {
                "show": [
                    {
                        "type": "metric",
                        "goals": [{"id": "g", "label": "L", "checkpoints": [5]}],
                    }
                ],
                "time": [],
            },
        ),  # tuple_type
        # Plain-union (MultiAttribution) both-member error emission.
        _b3_schema_edge(
            "Sections",
            {
                "show": [
                    {
                        "type": "metric",
                        "measurement": {"multiAttribution": {"type": "nope"}},
                    }
                ],
                "time": [],
            },
        ),
        # extra="allow" tolerance on the flows root.
        _b3_schema_edge(
            "FlowsBookmarkParams", {**_b3_flows_base(), "totally_unknown": 1}
        ),
        # Ignore[T]: JsonValue tolerates junk, the TYPED three do not.
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(alignment={"a": [1]})),
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(icon=12345)),
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(id="notanint")),
        _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(isNewQBEnabled=2)),
        # Alias vs python-name collision (populate_by_name).
        _b3_schema_edge(
            "DisplayOptions",
            _b3_do(
                funnelStepsSelectedTableColumns={
                    "conv-first-step": True,
                    "conv_first_step": False,
                }
            ),
        ),
        # path_prefix plumbing.
        _b3_schema_edge("InsightsBookmarkParams", {}, path_prefix="params"),
        _b3_schema_edge("Sections", {}, path_prefix=_B2_NON_BMP),
        # R10.9 mandatory edge set — raw values, every model.
        *(
            _b3_schema_edge(model, value)
            for model in _B3_MODEL_NAMES
            for value in _B3_MANDATORY_EDGES
        ),
        # R10.9 mandatory edge set — as a leaf in an otherwise-valid dict.
        *(
            _b3_schema_edge("InsightsBookmarkParams", _b3_ibp(name=value))
            for value in _B3_MANDATORY_EDGES
        ),
        *(
            _b3_schema_edge("DisplayOptions", _b3_do(rollingWindowSize=value))
            for value in _B3_MANDATORY_EDGES
        ),
        *(
            _b3_schema_edge("Sections", _b3_beh({"id": value}))
            for value in _B3_MANDATORY_EDGES
        ),
        *(
            _b3_schema_edge(
                "FlowsBookmarkParams",
                {"steps": [{"forward": value}], "date_range": {}},
            )
            for value in _B3_MANDATORY_EDGES
        ),
    ),
)

_ROOT_MODEL_FAMILY = FuzzTarget(
    name="get_root_model_family",
    calls=st.fixed_dictionaries(
        {
            "bookmark_type": st.one_of(
                st.sampled_from(("insights", "funnels", "retention", "flows", "user")),
                st.text(max_size=20),
            )
        }
    ).map(_b2_call(_ROOT_MODEL_API)),
    edge_calls=(
        (_ROOT_MODEL_API, {"bookmark_type": "insights"}),
        (_ROOT_MODEL_API, {"bookmark_type": "funnels"}),
        (_ROOT_MODEL_API, {"bookmark_type": "retention"}),
        (_ROOT_MODEL_API, {"bookmark_type": "flows"}),
        (_ROOT_MODEL_API, {"bookmark_type": "user"}),
        (_ROOT_MODEL_API, {"bookmark_type": ""}),
        (_ROOT_MODEL_API, {"bookmark_type": "insightz"}),
        (_ROOT_MODEL_API, {"bookmark_type": "USER"}),
        (_ROOT_MODEL_API, {"bookmark_type": _B2_NON_BMP}),
        (_ROOT_MODEL_API, {"bookmark_type": "sorting"}),
    ),
)


# ---------------------------------------------------------------------------
# B3-K2 — bookmark_builders families (b3-packets.md §"R10.9 harness spec (K2)")
# ---------------------------------------------------------------------------

_BB_FILTER_SECTION_API = "bookmark_builders.build_filter_section"
_BB_GROUP_SECTION_API = "bookmark_builders.build_group_section"
_BB_FLOW_PROPERTY_API = "bookmark_builders.build_flow_property_filter"
_BB_FLOW_COHORT_API = "bookmark_builders.build_flow_cohort_filter"
_BB_FREQ_FILTER_API = "bookmark_builders.build_frequency_filter_entry"
_BB_TIME_SECTION_API = "bookmark_builders.build_time_section"
_BB_DATE_RANGE_API = "bookmark_builders.build_date_range"

_BB_FOREIGN: tuple[Any, ...] = (42, None, 1.5, True, [], {}, " x", "")
"""Foreign elements: BB1 material for ``build_group_section`` and
skip-branch material for ``build_filter_section`` (which has NO ``else``
and silently drops them, ``bookmark_builders.py:200-204``)."""


@st.composite
def _bb_frequency_filter(draw: st.DrawFn) -> FrequencyFilter:
    """Draw a FrequencyFilter across the operator x value x label x
    date_range x event_filters grid.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A constructed ``FrequencyFilter`` (FF1-FF5 all satisfied).
    """
    paired = draw(st.booleans())
    return FrequencyFilter(
        event=draw(st.sampled_from(("Login", "Purchase", _B2_NON_BMP))),
        value=draw(st.sampled_from((0, 1, 5, 18.0, 1.5, True))),
        operator=draw(
            st.sampled_from(
                (
                    "is at least",
                    "is at most",
                    "is equal to",
                    "is greater than",
                    "is less than",
                )
            )
        ),
        date_range_value=draw(st.sampled_from((7, 30))) if paired else None,
        date_range_unit=(
            draw(st.sampled_from(("day", "week", "month"))) if paired else None
        ),
        event_filters=draw(
            st.one_of(st.none(), st.lists(filter_strategy(), max_size=2))
        ),
        label=draw(st.sampled_from((None, "", "Active Users", _B2_NON_BMP))),
    )


@st.composite
def _bb_group_element(draw: st.DrawFn) -> Any:
    """Draw one ``build_group_section`` element.

    Covers str / GroupBy plain / GroupBy+CustomPropertyRef /
    GroupBy+InlineCustomProperty / GroupBy list_item mode /
    CohortBreakdown (saved + inline, +/- include_negated) /
    FrequencyBreakdown / BB1 foreign values.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A group-by element (valid) or a foreign value (BB1 material).
    """
    kind = draw(
        st.sampled_from(
            (
                "str",
                "plain",
                "ref",
                "inline",
                "list_item",
                "cohort",
                "frequency",
                "foreign",
            )
        )
    )
    bucket_size = draw(st.sampled_from((None, 1, 10, 2.5)))
    bucket_min = draw(st.sampled_from((None, 0, -5)))
    bucket_max = draw(st.sampled_from((None, 100, 1000.5)))
    property_type = cast(
        'Literal["string", "number", "boolean", "datetime"]',
        draw(st.sampled_from(("string", "number", "boolean", "datetime"))),
    )
    if kind == "str":
        return draw(st.sampled_from(("country", "$browser", _B2_NON_BMP)))
    if kind == "foreign":
        return draw(st.sampled_from(_BB_FOREIGN))
    if kind == "list_item":
        # GB4 forbids bucketing on list-item mode; draw it unbucketed.
        return GroupBy(
            property=draw(st.sampled_from(("cart", _B2_NON_BMP))),
            _list_item_mode=ListItemGroupMode(
                sub=draw(st.sampled_from(("Brand", "Price", _B2_NON_BMP))),
                sub_type=property_type,
            ),
        )
    if kind == "cohort":
        # bool <: int (B3 arbiter fix F1): True is the one constructible
        # boolean id (False fires CB1 at construction, so it cannot be
        # drawn here); it must take the SAVED branch — id: true,
        # groups: [] — on both sides.
        return CohortBreakdown(
            cohort=draw(
                st.one_of(
                    st.just(True),
                    st.integers(min_value=1, max_value=99999),
                    definition_trees(),
                )
            ),
            name=draw(st.sampled_from((None, "PU", _B2_NON_BMP))),
            include_negated=draw(st.booleans()),
        )
    if kind == "frequency":
        return FrequencyBreakdown(
            event=draw(st.sampled_from(("Purchase", _B2_NON_BMP))),
            bucket_size=draw(st.sampled_from((1, 5))),
            bucket_min=draw(st.sampled_from((0, 2))),
            bucket_max=draw(st.sampled_from((10, 50))),
            label=draw(st.sampled_from((None, "", "Buy Count", _B2_NON_BMP))),
        )
    if kind == "ref":
        prop: Any = CustomPropertyRef(id=draw(st.integers(min_value=1, max_value=999)))
    elif kind == "inline":
        prop = InlineCustomProperty(
            formula=draw(st.sampled_from(("A", "A * B"))),
            inputs={
                "A": PropertyInput(
                    name=draw(st.sampled_from(("price", _B2_NON_BMP))),
                    type="number",
                )
            },
            property_type=draw(
                st.sampled_from((None, "string", "number", "boolean", "datetime"))
            ),
            resource_type=draw(st.sampled_from(("events", "people"))),
        )
    else:
        prop = draw(st.sampled_from(("revenue", "$browser", _B2_NON_BMP)))
    # V12/V18 reject non-positive sizes and inverted min/max at
    # construction; keep the draw inside the constructible domain.
    assume(bucket_size is None or bucket_size > 0)
    assume(bucket_min is None or bucket_max is None or bucket_min < bucket_max)
    return GroupBy(
        property=prop,
        property_type=property_type,
        bucket_size=bucket_size,
        bucket_min=bucket_min,
        bucket_max=bucket_max,
    )


_BB_COHORT_SHAPES: tuple[Any, ...] = (
    [{"cohort": {"negated": False, "name": "PU", "id": 123}}],
    [{"cohort": {"negated": True, "name": "Bots", "id": 7}}],
    [{"cohort": {"name": _B2_NON_BMP, "raw_cohort": {"selector": {}}}}],
    [{"cohort": {"id": 1, "raw_cohort": {"a": 1}, "name": None}}],
    [{"cohort": {}}],
    [{"cohort": None}],
    [{"nope": {}}],
    [{}],
    [42],
    ["cohort"],
    [],
    "oops",
    None,
    17,
)
"""``_value`` shapes for the ``$cohorts`` Filter: the first four are
well-formed (saved id / negated / inline raw_cohort / both keys), the rest
are the BB6 / BB7 / BB8 malformed material, reachable only by direct field
construction (``Filter.in_cohort`` always builds a well-formed value)."""


@st.composite
def _bb_cohort_shaped_filter(draw: st.DrawFn) -> Filter:
    """Draw a ``$cohorts`` Filter, well-formed or malformed.

    The malformed ``_value`` shapes are the BB6 / BB7 / BB8 material;
    they are reachable only by direct field construction (the
    ``Filter.in_cohort`` factory always builds a well-formed value).

    Args:
        draw: Hypothesis draw function.

    Returns:
        A Filter whose ``_property`` is ``"$cohorts"``.
    """
    shape: Any = draw(st.sampled_from(_BB_COHORT_SHAPES))
    return Filter(
        _property="$cohorts",
        _operator=draw(st.sampled_from(("contains", "does not contain"))),
        _value=shape,
        _property_type="list",
        _resource_type="events",
    )


_BUILD_FILTER_SECTION_FAMILY = FuzzTarget(
    name="build_filter_section_family",
    calls=st.fixed_dictionaries(
        {
            "where": st.one_of(
                st.none(),
                filter_strategy(),
                _bb_frequency_filter(),
                st.lists(
                    st.one_of(
                        filter_strategy(),
                        _bb_frequency_filter(),
                        st.sampled_from(_BB_FOREIGN),
                    ),
                    max_size=4,
                ),
            )
        }
    ).map(_b2_call(_BB_FILTER_SECTION_API)),
    edge_calls=(
        (_BB_FILTER_SECTION_API, {"where": None}),
        (_BB_FILTER_SECTION_API, {"where": []}),
        # The skip branch: foreign elements are DROPPED, not rejected.
        (_BB_FILTER_SECTION_API, {"where": list(_BB_FOREIGN)}),
        (
            _BB_FILTER_SECTION_API,
            {"where": [_EDGE_FILTERS[0], 42, None, _EDGE_FILTERS[1]]},
        ),
        *(
            (_BB_FILTER_SECTION_API, {"where": edge_filter})
            for edge_filter in _EDGE_FILTERS
        ),
        (_BB_FILTER_SECTION_API, {"where": list(_EDGE_FILTERS)}),
    ),
)

_BUILD_GROUP_SECTION_FAMILY = FuzzTarget(
    name="build_group_section_family",
    calls=st.fixed_dictionaries(
        {
            "group_by": st.one_of(
                st.none(),
                _bb_group_element(),
                st.lists(_bb_group_element(), max_size=4),
            ),
            "data_group_id": st.sampled_from((None, 0, 5, 42)),
        }
    ).map(_b2_call(_BB_GROUP_SECTION_API)),
    edge_calls=(
        (_BB_GROUP_SECTION_API, {"group_by": None, "data_group_id": 5}),
        (_BB_GROUP_SECTION_API, {"group_by": [], "data_group_id": None}),
        # BB1: every foreign shape, bare and inside a list.
        *(
            (_BB_GROUP_SECTION_API, {"group_by": foreign, "data_group_id": None})
            for foreign in _BB_FOREIGN
        ),
        (
            _BB_GROUP_SECTION_API,
            {"group_by": ["country", 42], "data_group_id": None},
        ),
        # customBucket conditional-insert matrix (R4.11).
        (
            _BB_GROUP_SECTION_API,
            {
                "group_by": GroupBy("a", property_type="number", bucket_size=10),
                "data_group_id": None,
            },
        ),
        (
            _BB_GROUP_SECTION_API,
            {
                "group_by": GroupBy(
                    "a", property_type="number", bucket_size=10, bucket_min=0
                ),
                "data_group_id": None,
            },
        ),
        (
            _BB_GROUP_SECTION_API,
            {
                "group_by": GroupBy(
                    "a", property_type="number", bucket_size=10, bucket_max=9
                ),
                "data_group_id": None,
            },
        ),
        (
            _BB_GROUP_SECTION_API,
            {
                "group_by": GroupBy(
                    "a",
                    property_type="number",
                    bucket_size=10,
                    bucket_min=0,
                    bucket_max=9,
                ),
                "data_group_id": 7,
            },
        ),
        # Cohort entries: saved vs inline, +/- include_negated, and the
        # empty-name label collapse (`name = cb.name or ""`).
        (
            _BB_GROUP_SECTION_API,
            {"group_by": CohortBreakdown(123, "PU"), "data_group_id": 7},
        ),
        (
            _BB_GROUP_SECTION_API,
            {
                "group_by": CohortBreakdown(123, "PU", include_negated=False),
                "data_group_id": None,
            },
        ),
        (
            _BB_GROUP_SECTION_API,
            {"group_by": CohortBreakdown(7), "data_group_id": None},
        ),
        # bool <: int (B3 arbiter fix F1): a boolean saved id must emit
        # `id: true, groups: []` — the pre-fix TS crashed TypeError here.
        (
            _BB_GROUP_SECTION_API,
            {"group_by": CohortBreakdown(True, "N"), "data_group_id": None},
        ),
        # Non-BMP / empty string properties.
        (_BB_GROUP_SECTION_API, {"group_by": _B2_NON_BMP, "data_group_id": None}),
        (
            _BB_GROUP_SECTION_API,
            {"group_by": GroupBy.list_item("cart", "Brand"), "data_group_id": 5},
        ),
    ),
)

_BUILD_FLOW_PROPERTY_FILTER_FAMILY = FuzzTarget(
    name="build_flow_property_filter_family",
    calls=st.fixed_dictionaries(
        {"filters": st.lists(filter_strategy(), max_size=3)}
    ).map(_b2_call(_BB_FLOW_PROPERTY_API)),
    edge_calls=(
        # BB2.
        (_BB_FLOW_PROPERTY_API, {"filters": []}),
        # BB3 (both non-string property kinds; the raise happens AFTER
        # build_filter_entry succeeds, so an earlier error wins).
        (
            _BB_FLOW_PROPERTY_API,
            {
                "filters": [
                    Filter(
                        _property=CustomPropertyRef(id=123),
                        _operator="equals",
                        _value=["high"],
                    )
                ]
            },
        ),
        (
            _BB_FLOW_PROPERTY_API,
            {
                "filters": [
                    Filter(
                        _property=InlineCustomProperty(
                            formula="A",
                            inputs={"A": PropertyInput("plan")},
                            property_type="string",
                        ),
                        _operator="equals",
                        _value=["a"],
                    )
                ]
            },
        ),
        # A good filter FOLLOWED by a BB3 filter — order lock.
        (
            _BB_FLOW_PROPERTY_API,
            {
                "filters": [
                    Filter.equals("country", "US"),
                    Filter(
                        _property=CustomPropertyRef(id=1),
                        _operator="equals",
                        _value=["x"],
                    ),
                ]
            },
        ),
        *(
            (_BB_FLOW_PROPERTY_API, {"filters": [edge_filter]})
            for edge_filter in _EDGE_FILTERS
        ),
    ),
)

_BB_COHORT_EDGE_SHAPES: tuple[Any, ...] = (
    "oops",
    [],
    None,
    [42],
    ["cohort"],
    [{}],
    [{"cohort": "nope"}],
    [{"cohort": {"id": 9}}],
    [{"cohort": {"name": "n"}}],
)
"""One malformed (or minimal) ``_value`` per BB6 / BB7 / BB8 branch plus the
two ``cohort_data.get("name", "")`` / conditional-``id`` shapes."""


_BUILD_FLOW_COHORT_FILTER_FAMILY = FuzzTarget(
    name="build_flow_cohort_filter_family",
    calls=st.fixed_dictionaries(
        {
            "where": st.one_of(
                _bb_cohort_shaped_filter(),
                filter_strategy(),
                st.lists(
                    st.one_of(_bb_cohort_shaped_filter(), filter_strategy()),
                    max_size=3,
                ),
            )
        }
    ).map(_b2_call(_BB_FLOW_COHORT_API)),
    edge_calls=(
        # Empty list -> None (NOT an error).
        (_BB_FLOW_COHORT_API, {"where": []}),
        # Saved id vs raw_cohort, negated operator.
        (_BB_FLOW_COHORT_API, {"where": Filter.in_cohort(123, "PU")}),
        (_BB_FLOW_COHORT_API, {"where": Filter.not_in_cohort(123, "Bots")}),
        # BB4 (bare and second-in-list: BB4 wins over BB5).
        (_BB_FLOW_COHORT_API, {"where": [Filter.equals("country", "US")]}),
        (
            _BB_FLOW_COHORT_API,
            {"where": [Filter.in_cohort(1, "A"), Filter.equals("country", "US")]},
        ),
        # BB5.
        (
            _BB_FLOW_COHORT_API,
            {"where": [Filter.in_cohort(1, "A"), Filter.in_cohort(2, "B")]},
        ),
        # BB6 / BB7 / BB8 malformed `_value` shapes.
        *(
            (
                _BB_FLOW_COHORT_API,
                {
                    "where": Filter(
                        _property="$cohorts",
                        _operator="contains",
                        _value=shape,
                        _property_type="list",
                    )
                },
            )
            for shape in _BB_COHORT_EDGE_SHAPES
        ),
    ),
)

_BUILD_FREQUENCY_FILTER_ENTRY_FAMILY = FuzzTarget(
    name="build_frequency_filter_entry_family",
    calls=st.fixed_dictionaries({"ff": _bb_frequency_filter()}).map(
        _b2_call(_BB_FREQ_FILTER_API)
    ),
    edge_calls=(
        # R10.7 bug-compat grid: every conditional key, present + absent.
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=5)}),
        (
            _BB_FREQ_FILTER_API,
            {
                "ff": FrequencyFilter(
                    "Login", value=5, date_range_value=30, date_range_unit="day"
                )
            },
        ),
        (
            _BB_FREQ_FILTER_API,
            {"ff": FrequencyFilter("Login", value=5, event_filters=[])},
        ),
        (
            _BB_FREQ_FILTER_API,
            {
                "ff": FrequencyFilter(
                    "Login", value=5, event_filters=list(_EDGE_FILTERS[:3])
                )
            },
        ),
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=5, label="L")}),
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=5, label="")}),
        # R10.12: integral float / fractional float / bool thresholds pass
        # through `filterValue` natively.
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=18.0)}),
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=1.5)}),
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter("Login", value=True)}),
        (_BB_FREQ_FILTER_API, {"ff": FrequencyFilter(_B2_NON_BMP, value=0)}),
    ),
)

_BB_DATES: tuple[str | None, ...] = (None, "2026-01-01", "1999-12-31", "")
_BB_LASTS: tuple[int, ...] = (0, 1, 7, 30, 365, -5)

_BUILD_TIME_SECTION_FAMILY = FuzzTarget(
    name="build_time_section_family",
    calls=st.fixed_dictionaries(
        {
            "from_date": st.sampled_from(_BB_DATES),
            "to_date": st.sampled_from(_BB_DATES),
            "last": st.sampled_from(_BB_LASTS),
            "unit": st.sampled_from(("hour", "day", "week", "month", "quarter")),
        }
    ).map(_b2_call(_BB_TIME_SECTION_API)),
    edge_calls=(
        # The from-only branch is the module's ONLY clock read; the
        # recorder's frozen epoch makes it deterministic (D1.4).
        (
            _BB_TIME_SECTION_API,
            {
                "from_date": "2026-01-01",
                "to_date": None,
                "last": 30,
                "unit": "day",
            },
        ),
        (
            _BB_TIME_SECTION_API,
            {
                "from_date": "2026-01-01",
                "to_date": "2026-02-01",
                "last": 30,
                "unit": "week",
            },
        ),
        (
            _BB_TIME_SECTION_API,
            {"from_date": None, "to_date": None, "last": 7, "unit": "hour"},
        ),
        (
            _BB_TIME_SECTION_API,
            {
                "from_date": None,
                "to_date": "2026-02-01",
                "last": 14,
                "unit": "day",
            },
        ),
        (
            _BB_TIME_SECTION_API,
            {"from_date": "", "to_date": None, "last": 0, "unit": "quarter"},
        ),
    ),
)

_BUILD_DATE_RANGE_FAMILY = FuzzTarget(
    name="build_date_range_family",
    calls=st.fixed_dictionaries(
        {
            "from_date": st.sampled_from(_BB_DATES),
            "to_date": st.sampled_from(_BB_DATES),
            "last": st.sampled_from(_BB_LASTS),
        }
    ).map(_b2_call(_BB_DATE_RANGE_API)),
    edge_calls=(
        (
            _BB_DATE_RANGE_API,
            {"from_date": "2026-01-01", "to_date": "2026-02-01", "last": 30},
        ),
        # From-only falls back to the RELATIVE shape here (unlike
        # build_time_section, which fills `to_date` from the clock).
        (_BB_DATE_RANGE_API, {"from_date": "2026-01-01", "to_date": None, "last": 14}),
        (_BB_DATE_RANGE_API, {"from_date": None, "to_date": None, "last": 30}),
        (_BB_DATE_RANGE_API, {"from_date": None, "to_date": "2026-02-01", "last": 0}),
        (_BB_DATE_RANGE_API, {"from_date": "", "to_date": "", "last": -5}),
    ),
)

PHASE3_B3_K2_TARGETS: tuple[FuzzTarget, ...] = (
    _BUILD_FILTER_SECTION_FAMILY,
    _BUILD_GROUP_SECTION_FAMILY,
    _BUILD_FLOW_PROPERTY_FILTER_FAMILY,
    _BUILD_FLOW_COHORT_FILTER_FAMILY,
    _BUILD_FREQUENCY_FILTER_ENTRY_FAMILY,
    _BUILD_TIME_SECTION_FAMILY,
    _BUILD_DATE_RANGE_FAMILY,
)
"""The Phase-3 B3-K2 ``bookmark_builders`` families (b3-packets.md
§"R10.9 harness spec (K2)"). ``build_filter_entry`` needs no new target —
the Phase-1 ``_BUILD_FILTER_ENTRY`` target already drives it and starts
ANSWERING once the (b′) binding task registers the TS side.

**Documented omissions (no registry name, so not oracle-fuzzable — same
posture as the note at the ``normalize_on_expression`` target):**
``build_time_comparison``, ``build_frequency_group_entry``,
``patch_custom_property_filters_for_transform`` and
``_build_composed_properties`` are unregistered helpers. They are locked
by the translated Layer-3 suite now, by the B5
``workspace.build_*params`` vectors later, and — for this batch — by the
K2 module task's throwaway harness (``throwaway/b3-k2/``, TS repo), which
drives all twelve entry points including these four against the same
CPython reference. The two ``build_time_comparison`` ``AssertionError``
branches are unreachable by ``TimeComparison.__post_init__`` (TC1/TC2)
and are deliberately NOT fuzzed for."""


# ---------------------------------------------------------------------------
# B3-K3 — `transforms` families (b3-packets.md §"R10.9 harness spec (K3)";
# K3-notes §7.4 deferred these to the binder so the CUMULATIVE gate
# regression exercises them — landed at B3-BIND).
#
# Domain notes (K3-notes §5, carried over verbatim):
# - `time` values cap at |t| <= 1e12 — CPython's platform `gmtime` raises
#   `OSError` (errno 84) for very large in-int64 timestamps BEFORE the year
#   check, a band the TS twin reports as `ValueError` (documented exclusion
#   #2; `TODO(port)` at the site).
# - `properties` draws as dict-or-absent-or-small-pair-iterable; the
#   `dict(iterable-of-pairs)` grammar (incl. the `dict("ab")` ValueError
#   branch) is emulated by `pythonDictCopy` and probed via edge calls.
# ---------------------------------------------------------------------------

_TRANSFORM_EVENT_API = "transforms.transform_event"
_TRANSFORM_PROFILE_API = "transforms.transform_profile"

_B3_K3_TIME: st.SearchStrategy[Any] = st.one_of(
    st.integers(min_value=-(10**12), max_value=10**12),
    st.floats(
        allow_nan=False,
        allow_infinity=False,
        min_value=-1e12,
        max_value=1e12,
    ),
    st.booleans(),  # bool <: int (Caution 11): fromtimestamp(True) == 1s
)
"""Timestamps: ints, µs-representable floats (round-half-even parity
proven by the K3 module harness), and booleans; |t| capped at 1e12
(domain note above)."""

_B3_K3_KEYS: st.SearchStrategy[str] = st.sampled_from(
    ("plan", "$city", "email", "日本語", "\U0001d4b3", "", "a b")
)
"""Property keys, incl. non-BMP and empty (R10.9 edge material)."""

_B3_K3_LEAVES: st.SearchStrategy[Any] = st.sampled_from(
    (18.0, 1.5, True, None, "", "\U0001d4b3", 0, 42, "free", [], {"a": 1})
)
"""Leaf values: the verbatim R10.9 mandatory edge scalars plus plain
carriers (integral floats ride the raw-token → PyFloat path on the TS
bridge and must pass through to `properties` unchanged)."""


@st.composite
def _transform_event_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one ``transforms.transform_event`` probe.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe: an event dict with optional
        ``event`` name, optional ``properties`` (dict or pair-iterable),
        and optional reserved keys (``distinct_id`` / ``time`` /
        ``$insert_id`` — absent, explicit-null, and value arms).
    """
    props: dict[str, Any] = {}
    if draw(st.booleans()):
        props["distinct_id"] = draw(_B3_K3_LEAVES)
    if draw(st.booleans()):
        props["time"] = draw(_B3_K3_TIME)
    if draw(st.booleans()):
        # `is None` fill branch: explicit null takes it too.
        props["$insert_id"] = draw(st.sampled_from(("abc-123", None, "")))
    for key in draw(st.lists(_B3_K3_KEYS, max_size=3, unique=True)):
        props[key] = draw(_B3_K3_LEAVES)
    event: dict[str, Any] = {}
    if draw(st.booleans()):
        event["event"] = draw(st.sampled_from(("Login", "", "\U0001d4b3", "日本語")))
    shape = draw(st.sampled_from(("dict", "pairs", "absent")))
    if shape == "dict":
        event["properties"] = props
    elif shape == "pairs":
        # dict(iterable-of-pairs) grammar — both sides build the same
        # dict from [key, value] two-lists.
        event["properties"] = [[key, value] for key, value in props.items()]
    return (_TRANSFORM_EVENT_API, {"event": event})


_TRANSFORM_EVENT_FAMILY = FuzzTarget(
    name="transform_event_family",
    calls=_transform_event_calls(),
    edge_calls=(
        # R10.9: empty dict (every default fires: "", time 0, uuid fill).
        (_TRANSFORM_EVENT_API, {"event": {}}),
        # Docstring example (transforms.py:36-55).
        (
            _TRANSFORM_EVENT_API,
            {
                "event": {
                    "event": "Sign Up",
                    "properties": {
                        "distinct_id": "user123",
                        "time": 1704067200,
                        "$insert_id": "abc123",
                        "plan": "premium",
                    },
                }
            },
        ),
        # R10.9 carriers: integral float 18.0 (PyFloat on the TS bridge,
        # NO .ffffff — probe row) and fractional 1.5 (µs rendering).
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": 18.0}}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": 1.5}}}),
        # Negative + µs round-half-even probe rows (K3-notes §2).
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": -1.5}}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": 5e-07}}}),
        # bool <: int.
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": True}}}),
        # Explicit-null $insert_id takes the uuid-fill branch.
        (
            _TRANSFORM_EVENT_API,
            {"event": {"properties": {"$insert_id": None, "time": 0}}},
        ),
        # Two uuid fills NEVER happen in one call — but the counter seam
        # is per-call; a second event key set exercises key preservation.
        (
            _TRANSFORM_EVENT_API,
            {"event": {"event": "\U0001d4b3", "properties": {"\U0001d4b3": ""}}},
        ),
        # Error branches (uncoded builtin raises, bare-class compare):
        # out-of-range year (ValueError both sides), non-numeric time
        # (TypeError), malformed properties iterables (`dict("ab")` →
        # ValueError; `dict(5)` → TypeError; short pair → ValueError).
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": 253402300800}}}),
        (
            _TRANSFORM_EVENT_API,
            {"event": {"properties": {"time": -62135596801}}},
        ),
        (_TRANSFORM_EVENT_API, {"event": {"properties": {"time": "soon"}}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": "ab"}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": 5}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": [["a", "b"], ["abc"]]}}),
        (_TRANSFORM_EVENT_API, {"event": {"properties": [["a", "b"]]}}),
    ),
)


@st.composite
def _transform_profile_calls(draw: st.DrawFn) -> FuzzCall:
    """Draw one ``transforms.transform_profile`` probe.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        The ``(api, kwargs)`` probe: a profile dict over the
        ``$distinct_id`` / ``$properties`` / ``$last_seen``
        present-absent grid, plus ignored extra top-level keys.
    """
    props: dict[str, Any] = {}
    if draw(st.booleans()):
        props["$last_seen"] = draw(
            st.sampled_from(("2024-01-15T10:30:00", None, "", 0))
        )
    for key in draw(st.lists(_B3_K3_KEYS, max_size=3, unique=True)):
        props[key] = draw(_B3_K3_LEAVES)
    profile: dict[str, Any] = {}
    if draw(st.booleans()):
        profile["$distinct_id"] = draw(_B3_K3_LEAVES)
    shape = draw(st.sampled_from(("dict", "pairs", "absent")))
    if shape == "dict":
        profile["$properties"] = props
    elif shape == "pairs":
        profile["$properties"] = [[key, value] for key, value in props.items()]
    if draw(st.booleans()):
        # Extra top-level keys are DROPPED (only $distinct_id/$properties
        # are read) — lock the drop on both sides.
        profile["$extra"] = draw(_B3_K3_LEAVES)
    return (_TRANSFORM_PROFILE_API, {"profile": profile})


_TRANSFORM_PROFILE_FAMILY = FuzzTarget(
    name="transform_profile_family",
    calls=_transform_profile_calls(),
    edge_calls=(
        # The two corpus-vector shapes (R10.9: empty dict / missing id).
        (_TRANSFORM_PROFILE_API, {"profile": {}}),
        (_TRANSFORM_PROFILE_API, {"profile": {"$properties": {"plan": "free"}}}),
        # Docstring example (transforms.py:100-118).
        (
            _TRANSFORM_PROFILE_API,
            {
                "profile": {
                    "$distinct_id": "user123",
                    "$properties": {
                        "$last_seen": "2024-01-15T10:30:00",
                        "plan": "premium",
                        "email": "alice@example.com",
                    },
                }
            },
        ),
        # Explicit-null $last_seen vs absent (both -> null output).
        (_TRANSFORM_PROFILE_API, {"profile": {"$properties": {"$last_seen": None}}}),
        # Non-BMP everywhere.
        (
            _TRANSFORM_PROFILE_API,
            {
                "profile": {
                    "$distinct_id": "\U0001d4b3",
                    "$properties": {"\U0001d4b3": "\U0001d4b3"},
                }
            },
        ),
        # dict(iterable-of-pairs) grammar + error branches.
        (_TRANSFORM_PROFILE_API, {"profile": {"$properties": [["a", "b"]]}}),
        (_TRANSFORM_PROFILE_API, {"profile": {"$properties": "ab"}}),
        (_TRANSFORM_PROFILE_API, {"profile": {"$properties": 5}}),
    ),
)

PHASE3_B3_K3_TARGETS: tuple[FuzzTarget, ...] = (
    _TRANSFORM_EVENT_FAMILY,
    _TRANSFORM_PROFILE_FAMILY,
)
"""The Phase-3 B3-K3 ``transforms`` families (b3-packets.md §"R10.9
harness spec (K3)"), declared at the (b′) binding task per the K3-notes
§7.4 deferral. `build_segfilter_entry` / `normalize_on_expression` need
no new target — the Phase-1 targets already drive them (this task added
the operator-row sweep to the segfilter target's edge set)."""


# ---------------------------------------------------------------------------
# B3-K4 — `user_builders.extract_cohort_filter` (b3-packets.md §"R10.9
# harness spec (K4)": the one NEW family; the two selector entry points reuse
# the Phase-1 targets, whose Filter domain this shard widened above).
# ---------------------------------------------------------------------------

_EXTRACT_COHORT_API = "user_builders.extract_cohort_filter"

_COHORT_FILTERS: st.SearchStrategy[Filter] = st.one_of(
    st.integers(min_value=1, max_value=999).map(Filter.in_cohort),
    st.integers(min_value=1, max_value=999).map(Filter.not_in_cohort),
    # Malformed list-of-dict shapes — `_is_cohort_filter` is a pure SHAPE
    # heuristic (non-empty list whose FIRST element is a dict), so these
    # still classify as cohorts and must do so identically on both sides.
    st.sampled_from(
        (
            Filter("$cohorts", "contains", [{}]),  # type: ignore[arg-type]
            Filter("$cohorts", "contains", [{"a": 1}, {"b": 2}]),
            Filter("$cohorts", "contains", [{"a": 1}, "b"]),  # type: ignore[arg-type]
        )
    ),
)
"""Cohort-shaped Filters (saved id, negated, and malformed shapes)."""

_EXTRACT_LIST: st.SearchStrategy[list[Filter]] = st.lists(
    st.one_of(_SELECTOR_FILTERS, _COHORT_FILTERS), min_size=0, max_size=5
)
"""Mixed lists: property filters plus zero, one or several cohort filters at
arbitrary positions (relative order of the non-cohorts, and of the extras
beyond the first cohort, is contract)."""

_PROP_FILTER = Filter.is_set("p")
_COHORT_A = Filter.in_cohort(123, "A")
_COHORT_B = Filter.not_in_cohort(456, "B")

_EXTRACT_COHORT_FILTER_FAMILY = FuzzTarget(
    name="extract_cohort_filter_family",
    calls=_EXTRACT_LIST.map(
        lambda filters: (_EXTRACT_COHORT_API, {"filters": filters})
    ),
    edge_calls=(
        # R10.9: empty list.
        (_EXTRACT_COHORT_API, {"filters": []}),
        # No cohort at all.
        (_EXTRACT_COHORT_API, {"filters": [_PROP_FILTER]}),
        # Exactly one cohort, in each position.
        (_EXTRACT_COHORT_API, {"filters": [_COHORT_A]}),
        (_EXTRACT_COHORT_API, {"filters": [_COHORT_A, _PROP_FILTER]}),
        (_EXTRACT_COHORT_API, {"filters": [_PROP_FILTER, _COHORT_A]}),
        # Two and three cohorts — first wins, extras go to `remaining` in
        # encounter order.
        (_EXTRACT_COHORT_API, {"filters": [_COHORT_A, _COHORT_B]}),
        (
            _EXTRACT_COHORT_API,
            {"filters": [_PROP_FILTER, _COHORT_A, _PROP_FILTER, _COHORT_B]},
        ),
        (_EXTRACT_COHORT_API, {"filters": [_COHORT_A, _COHORT_B, _COHORT_A]}),
        # Shape-heuristic boundary: `_value` shapes that do and do not
        # classify as cohorts (empty list, list-of-str, str-then-dict).
        (
            _EXTRACT_COHORT_API,
            {
                "filters": [
                    Filter("$cohorts", "contains", []),
                    Filter("$cohorts", "contains", ["a"]),
                    Filter("$cohorts", "contains", ["a", {"b": 1}]),  # type: ignore[arg-type]
                    Filter("$cohorts", "contains", [{"b": 1}, "a"]),  # type: ignore[arg-type]
                ]
            },
        ),
        # The shared R10.9 edge Filters (incl. `Filter.in_cohort(123)`)
        # as one list — none of them raises here: `extract_cohort_filter`
        # has no guards, so the whole edge set is a single probe.
        (_EXTRACT_COHORT_API, {"filters": list(_EDGE_FILTERS)}),
    ),
)

PHASE3_B3_K4_TARGETS: tuple[FuzzTarget, ...] = (_EXTRACT_COHORT_FILTER_FAMILY,)
"""The Phase-3 B3-K4 ``user_builders`` family (b3-packets.md §"R10.9 harness
spec (K4)"). The two selector entry points need no new target — the Phase-1
``filter_to_selector`` / ``filters_to_selector`` targets already drive them and
start ANSWERING once the (b′) binding task registers the TS side; this shard
widened their drawn Filter domain with the mandatory escaping bias
(:data:`_SELECTOR_FILTERS`, :data:`_K4_ESCAPE_EDGE_FILTERS`) and added the
generator-order edge probes.

Budget note (P3-6 K4 mandate): the two selector families run at **≥1,000**
examples, every other family at ≥500. Until (b′) lands, the K4 differential
runs through the module task's throwaway harness (``throwaway/b3-k4/``, TS
repo), which drives the same three entry points plus ``_format_value``
against the same CPython reference at that doubled budget."""


PHASE3_B3_TARGETS: tuple[FuzzTarget, ...] = (
    _BOOKMARK_SCHEMA_FAMILY,
    _ROOT_MODEL_FAMILY,
    *PHASE3_B3_K2_TARGETS,
    *PHASE3_B3_K3_TARGETS,
    *PHASE3_B3_K4_TARGETS,
)
"""ALL Phase-3 B3 families (K1 `bookmark_schema` + K2 `bookmark_builders`
+ K3 `transforms` + K4 `extract_cohort_filter`), in shard order. SERVED
since the B3-BIND (b′) task landed the name-resolving
``validate_with_pydantic`` adapter (`conformance/record/adapters.py`),
retargeted the registry entry, and registered every B3 name in the
shared TS bindings module — oracle-ts answers these apis through
`registerBuilderBindings` (`conformance-runner/src/bindings.ts`)."""


PHASE3_B2_TARGETS: tuple[FuzzTarget, ...] = (
    _TIME_ARGS_FAMILY,
    _GROUP_BY_ARGS_FAMILY,
    _QUERY_ARGS_FAMILY,
    _FUNNEL_ARGS_FAMILY,
    _RETENTION_ARGS_FAMILY,
    _FLOW_ARGS_FAMILY,
    _BOOKMARK_FAMILY,
    _FLOW_BOOKMARK_FAMILY,
    _SORTING_FAMILY,
    _USER_ARGS_FAMILY,
    _USER_PARAMS_FAMILY,
)
"""The Phase-3 B2 validator families (b2-packets.md R10.9 harness specs;
``time_args_family`` supersets the Phase-1 ``validators_by_code`` target
with the carrier/bool value edges). Registered at the (b′) binding task —
oracle-ts answers these apis through the shared bindings registration."""


ALL_TARGETS: tuple[FuzzTarget, ...] = (
    *PHASE1_TARGETS,
    *PHASE2_TARGETS,
    *PHASE3_TARGETS,
    *PHASE3_B2_TARGETS,
    *PHASE3_B3_TARGETS,
)
"""Every registered fuzz target (Phases 1-3), in phase order."""

TARGETS_BY_NAME: dict[str, FuzzTarget] = {target.name: target for target in ALL_TARGETS}
"""Lookup for the harness ``--targets`` selector."""
