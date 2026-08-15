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

from dataclasses import dataclass
from typing import Any

from hypothesis import strategies as st
from tests.test_user_query_pbt import filter_strategy

from mixpanel_headless.types import Filter

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

TARGETS_BY_NAME: dict[str, FuzzTarget] = {
    target.name: target for target in PHASE1_TARGETS
}
"""Lookup for the harness ``--targets`` selector."""
