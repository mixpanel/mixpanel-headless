"""Filter-to-selector translation for the Engage API.

Converts ``Filter`` objects to engage API selector strings. This is the
third translation path alongside ``bookmark_builders.build_filter_entry()``
(bookmark dicts for insights/funnels/retention) and
``segfilter.build_segfilter_entry()`` (segfilter entries for flows).

The engage API uses selector strings like ``properties["plan"] == "premium"``
rather than bookmark filter dicts or segfilter entries.

The Engage profile list and stats endpoints re-parse ``where`` with a
smaller grammar than the full selector language: comparisons, ``in``,
``and`` / ``or`` / ``not``, ``+`` / ``-``, the casts ``defined()``,
``number()``, ``string()``, ``list()``, and ``datetime()``, and the ``NOW``
macro (the current time in Unix seconds). Every selector built here stays
inside that grammar. It has no prefix, suffix, or per-list-item test, so
``Filter.starts_with()``, ``Filter.ends_with()``, and
``Filter.list_contains()`` have no translation.

Functions:
    filter_to_selector: Convert a single Filter to a selector string.
    filters_to_selector: Convert multiple Filters to an AND-combined selector.
    extract_cohort_filter: Extract cohort filter from a Filter list.
"""

from __future__ import annotations

import logging
from typing import Final

from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import Filter, FilterValue

logger = logging.getLogger(__name__)

_SECONDS_PER_UNIT: Final[dict[str, int]] = {
    "hour": 3600,
    "day": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
}
"""Seconds in each relative date unit.

Weeks are 7 days and months are 30 days: the same unit sizes the Insights
backend uses for relative date filters.
"""

_MAX_RELATIVE_SECONDS: Final[int] = 50 * 365 * 86400
"""Longest relative date window the translation accepts (50 years).

The server reads ``datetime(<number>)`` as Unix seconds only for values from
1 to 4294967295. It reads a larger number as milliseconds, and a value of 0
or less is undefined. Either case makes that bound undefined, so its
comparison is false and the filter returns wrong counts without an error.
With this limit, ``NOW - n`` stays positive and ``NOW + n`` stays under the
upper value until the 2050s.
"""

_ABSOLUTE_DATE_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "was since",
        "was before",
        "was on",
        "was not on",
        "was between",
        "was not between",
    }
)
"""Operators that compare a date property with fixed calendar days."""

_RELATIVE_DATE_OPERATORS: Final[dict[str, str]] = {
    "was in the": "Filter.in_the_last()",
    "was not in the": "Filter.not_in_the_last()",
    "was in the next": "Filter.in_the_next()",
}
"""Operators that compare a date property with the current time, by constructor."""


def _format_value(value: str | int | float) -> str:
    """Format a scalar value for use in a selector expression.

    Strings are wrapped in double quotes (with internal quotes escaped).
    Numbers are rendered without quotes.

    Args:
        value: The scalar value to format.

    Returns:
        Formatted string suitable for embedding in a selector expression.
    """
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def _prop_ref(f: Filter) -> str:
    """Build the ``properties["name"]`` reference for a Filter.

    Args:
        f: Filter whose property name to reference.

    Returns:
        String of the form ``properties["<name>"]``.

    Raises:
        ParamValidationError: The filter's property is not a plain string
            (``ES1_PROPERTY_NOT_STRING``).
    """
    if not isinstance(f._property, str):
        raise ParamValidationError(
            f"Engage selector requires a string property name, "
            f"got {type(f._property).__name__}. Custom properties "
            f"are not supported in query_user() filters.",
            code="ES1_PROPERTY_NOT_STRING",
        )
    escaped = f._property.replace("\\", "\\\\").replace('"', '\\"')
    return f'properties["{escaped}"]'


def _is_cohort_filter(f: Filter) -> bool:
    """Return True if *f* is a cohort filter (in_cohort / not_in_cohort).

    Cohort filters store their value as a list of dicts (from
    ``CohortDefinition.to_dict()``), unlike regular filters which use
    str, number, list-of-str, or None. This shape heuristic is safe
    because ``Filter`` only produces list-of-dict values for
    ``in_cohort()`` / ``not_in_cohort()``.

    Args:
        f: Filter to test.

    Returns:
        True when the filter's ``_value`` is a non-empty list of dicts.
    """
    val = f._value
    return isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict)


def _number(op: str, value: FilterValue, code: str) -> str:
    """Format the number a single-number comparison operator compares with.

    Args:
        op: Wire operator, named in the error message.
        value: The Filter's value.
        code: Registry code to raise when the value is not a number.

    Returns:
        The number formatted for the selector.

    Raises:
        ParamValidationError: The value is not an int or float (*code*).
    """
    if not isinstance(value, (int, float)):
        raise ParamValidationError(
            f"Expected int or float for {op!r} operator, got {type(value).__name__}",
            code=code,
        )
    return _format_value(value)


def _number_pair(op: str, value: FilterValue) -> tuple[str, str]:
    """Format the two bounds of a numeric range operator.

    Args:
        op: Wire operator (``"is between"`` or ``"not between"``), named
            in the error message.
        value: The Filter's value.

    Returns:
        The lower and upper bound, formatted for the selector.

    Raises:
        ParamValidationError: The value is not a two-item list
            (``ES10_BETWEEN_EXPECTS_PAIR``), or its lower
            (``ES11_BETWEEN_LOWER_NOT_NUMBER``) or upper
            (``ES12_BETWEEN_UPPER_NOT_NUMBER``) bound is not a number.
    """
    if not isinstance(value, list) or len(value) != 2:
        raise ParamValidationError(
            f"Expected list of length 2 for {op!r} operator, got {type(value).__name__}",
            code="ES10_BETWEEN_EXPECTS_PAIR",
        )
    lo, hi = value[0], value[1]
    if not isinstance(lo, (int, float)):
        raise ParamValidationError(
            f"Expected int or float for lower bound, got {type(lo).__name__}",
            code="ES11_BETWEEN_LOWER_NOT_NUMBER",
        )
    if not isinstance(hi, (int, float)):
        raise ParamValidationError(
            f"Expected int or float for upper bound, got {type(hi).__name__}",
            code="ES12_BETWEEN_UPPER_NOT_NUMBER",
        )
    return _format_value(lo), _format_value(hi)


def _date_bounds(op: str, value: FilterValue) -> tuple[str, str]:
    """Return the first and last day an absolute date operator names.

    Single-date operators name one day, so both items are that day.

    Args:
        op: Wire operator, named in the error message.
        value: The Filter's value: a ``YYYY-MM-DD`` string, or a list of
            two for ``"was between"`` / ``"was not between"``.

    Returns:
        The first and last day as ``YYYY-MM-DD`` strings.

    Raises:
        ParamValidationError: A single-date value is not a string
            (``ES15_DATE_EXPECTS_STR``), a range is not a list of two
            strings (``ES16_DATE_RANGE_EXPECTS_PAIR``), or a date is not a
            valid ``YYYY-MM-DD`` day (``V8_DATE_FORMAT`` /
            ``V8_DATE_INVALID``, the codes the Filter factories use).
    """
    if op in ("was between", "was not between"):
        if isinstance(value, list) and len(value) == 2:
            first, last = value[0], value[1]
            if isinstance(first, str) and isinstance(last, str):
                Filter._validate_date(first)
                Filter._validate_date(last)
                return first, last
        raise ParamValidationError(
            f"Expected a list of two YYYY-MM-DD date strings for {op!r} "
            f"operator, got {value!r}",
            code="ES16_DATE_RANGE_EXPECTS_PAIR",
        )
    if not isinstance(value, str):
        raise ParamValidationError(
            f"Expected a YYYY-MM-DD date string for {op!r} operator, "
            f"got {type(value).__name__}",
            code="ES15_DATE_EXPECTS_STR",
        )
    Filter._validate_date(value)
    return value, value


def _absolute_date_selector(op: str, prop: str, value: FilterValue) -> str:
    """Translate an absolute date filter into day bounds.

    A ``datetime("YYYY-MM-DDTHH:MM:SS")`` literal is read in the project
    timezone, so each day runs from its 00:00:00 to its 23:59:59 in project
    time, as in Insights. The server compares datetimes in whole seconds, so
    ``<= 23:59:59`` matches exactly the same values as ``< next day``. The
    property is cast with ``datetime()`` so a date stored as a string
    compares too.

    Args:
        op: One of :data:`_ABSOLUTE_DATE_OPERATORS`.
        prop: The ``properties["name"]`` reference.
        value: The Filter's value.

    Returns:
        Selector string for the operator.

    Raises:
        ParamValidationError: Propagated from :func:`_date_bounds`
            (``ES15`` / ``ES16`` / ``V8``).
    """
    first, last = _date_bounds(op, value)
    cast = f"datetime({prop})"
    start = f'datetime("{first}T00:00:00")'
    end = f'datetime("{last}T23:59:59")'
    if op == "was since":
        return f"{cast} >= {start}"
    if op == "was before":
        return f"{cast} < {start}"
    if op in ("was on", "was between"):
        return f"{cast} >= {start} and {cast} <= {end}"
    # "was not on" / "was not between": a set value outside the days.
    return f"({cast} < {start} or {cast} > {end})"


def _relative_seconds(f: Filter) -> int:
    """Return the length in seconds of a relative date filter's window.

    Args:
        f: Filter with an operator in :data:`_RELATIVE_DATE_OPERATORS`.

    Returns:
        Quantity times the seconds in the date unit.

    Raises:
        ParamValidationError: The quantity is not a positive ``int`` or
            the window is longer than 50 years
            (``ES17_RELATIVE_QUANTITY_INVALID``), or the date unit is not
            ``hour``, ``day``, ``week``, or ``month``
            (``ES18_RELATIVE_UNIT_INVALID``).
    """
    op = f._operator
    quantity = f._value
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ParamValidationError(
            f"Expected a positive int quantity for {op!r} operator, got {quantity!r}",
            code="ES17_RELATIVE_QUANTITY_INVALID",
        )
    unit = f._date_unit
    per_unit = _SECONDS_PER_UNIT.get(unit) if isinstance(unit, str) else None
    if per_unit is None:
        raise ParamValidationError(
            f"Expected date unit 'hour', 'day', 'week', or 'month' for {op!r} "
            f"operator, got {unit!r}",
            code="ES18_RELATIVE_UNIT_INVALID",
        )
    seconds = quantity * per_unit
    if seconds > _MAX_RELATIVE_SECONDS:
        raise ParamValidationError(
            f"{_RELATIVE_DATE_OPERATORS[op]} can span at most 50 years "
            f"(18250 days) in query_user(where=...), got {quantity} {unit}(s). "
            "Use Filter.since(), Filter.before(), or Filter.date_between() "
            "with explicit dates for a longer range.",
            code="ES17_RELATIVE_QUANTITY_INVALID",
        )
    return seconds


def _relative_date_selector(f: Filter, prop: str) -> str:
    """Translate a relative date filter into a window around ``NOW``.

    ``NOW`` is an Engage selector macro that the server replaces with the
    current time in Unix seconds when it runs the query. The window is
    rolling: it starts exactly N units before (or ends N units after) that
    moment and is not aligned to calendar days. The bounds match Insights:
    the past window ends before now, and "not in the last" also matches
    values in the future.

    Args:
        f: Filter with an operator in :data:`_RELATIVE_DATE_OPERATORS`.
        prop: The ``properties["name"]`` reference.

    Returns:
        Selector string for the operator.

    Raises:
        ParamValidationError: Propagated from :func:`_relative_seconds`
            (``ES17`` / ``ES18``).
    """
    seconds = _relative_seconds(f)
    cast = f"datetime({prop})"
    now = "datetime(NOW)"
    # Keep the spaces around "-": the server lexes "NOW -604800" as NOW
    # followed by a negative number, which is a syntax error.
    if f._operator == "was in the":
        return f"{cast} >= datetime(NOW - {seconds}) and {cast} < {now}"
    if f._operator == "was not in the":
        return f"({cast} < datetime(NOW - {seconds}) or {cast} >= {now})"
    return f"{cast} >= {now} and {cast} < datetime(NOW + {seconds})"


def _no_selector_equivalent(f: Filter) -> ParamValidationError:
    """Build the error for a Filter constructor the Engage selector cannot express.

    The message names the public constructor and the closest workaround.

    Args:
        f: Filter whose operator is ``"starts with"``, ``"ends with"``, or
            ``"list_contains"``, with a string property.

    Returns:
        A ``ParamValidationError`` with code ``ES14_NO_SELECTOR_EQUIVALENT``.
    """
    name = f._property
    value = f._value
    if f._operator == "list_contains":
        message = (
            "Filter.list_contains() is not supported in query_user(where=...): "
            "the Engage profile selector cannot test the items of a list of "
            "objects, so a raw selector string cannot express it either. For a "
            f'list of strings, Filter.contains({name!r}, "<value>") matches '
            "profiles whose list holds that value. Otherwise fetch the profiles "
            'with mode="profiles" and filter result.df.'
        )
    else:
        method, test, verb = (
            ("starts_with", "prefix", "starts")
            if f._operator == "starts with"
            else ("ends_with", "suffix", "ends")
        )
        message = (
            f"Filter.{method}() is not supported in query_user(where=...): the "
            f"Engage profile selector has no {test} test, so a raw selector "
            "string cannot express it either. Narrow the query with "
            f"Filter.contains({name!r}, {value!r}), then keep the rows of "
            f'result.df (mode="profiles") whose value {verb} with {value!r}.'
        )
    return ParamValidationError(message, code="ES14_NO_SELECTOR_EQUIVALENT")


def filter_to_selector(f: Filter) -> str:
    """Convert a single Filter to an engage API selector string.

    Translates the Filter's internal operator to the equivalent engage
    selector syntax. Each operator maps to a specific selector pattern.

    Date operators cast the property with ``datetime()``. Absolute dates
    (``on``, ``not_on``, ``before``, ``since``, ``date_between``,
    ``date_not_between``) are whole days in the project timezone; ``before``
    excludes its day and the others include theirs. Relative dates
    (``in_the_last``, ``not_in_the_last``, ``in_the_next``) are rolling
    windows measured from the server's clock through the ``NOW`` macro, with
    7-day weeks and 30-day months, and span at most 50 years.

    Args:
        f: A Filter object (constructed via class methods like
            ``Filter.equals()``, ``Filter.greater_than()``, etc.).

    Returns:
        Selector string for the engage API ``where`` parameter.

    Raises:
        ParamValidationError: If the Filter's property is not a string
            (``ES1_PROPERTY_NOT_STRING``); its value has the wrong shape
            for the operator (``ES2``–``ES12``, ``ES15``–``ES20``, or the
            factories' ``V8_DATE_FORMAT`` / ``V8_DATE_INVALID`` for a bad
            date string); it is ``Filter.starts_with()``,
            ``Filter.ends_with()``, or ``Filter.list_contains()``, which
            the Engage selector cannot express
            (``ES14_NO_SELECTOR_EQUIVALENT``); or the operator is unknown
            (``ES13_UNSUPPORTED_OPERATOR``).

    Example:
        ```python
        from mixpanel_headless.types import Filter
        from mixpanel_headless._internal.query.user_builders import filter_to_selector

        selector = filter_to_selector(Filter.equals("plan", "premium"))
        # 'properties["plan"] == "premium"'

        filter_to_selector(Filter.since("$last_seen", "2026-09-01"))
        # 'datetime(properties["$last_seen"]) >= datetime("2026-09-01T00:00:00")'

        filter_to_selector(Filter.in_the_last("$last_seen", 7, "day"))
        # 'datetime(properties["$last_seen"]) >= datetime(NOW - 604800)
        #  and datetime(properties["$last_seen"]) < datetime(NOW)'
        ```
    """
    op = f._operator
    prop = _prop_ref(f)
    value = f._value

    if op == "equals":
        if not isinstance(value, list):
            raise ParamValidationError(
                f"Expected list for 'equals' operator, got {type(value).__name__}",
                code="ES2_EQUALS_EXPECTS_LIST",
            )
        parts = [
            f"{prop} == {_format_value(v)}"
            for v in value
            if isinstance(v, (str, int, float))
        ]
        dropped = [v for v in value if not isinstance(v, (str, int, float))]
        if dropped:
            logger.warning(
                "Filter.equals() dropped %d non-scalar value(s): %r",
                len(dropped),
                dropped,
            )
        if not parts:
            raise ParamValidationError(
                f"Filter.equals() produced no valid selector terms. "
                f"All values were non-scalar: {value!r}",
                code="ES3_EQUALS_NO_TERMS",
            )
        if len(parts) > 1:
            return f"({' or '.join(parts)})"
        return parts[0]

    if op == "does not equal":
        if not isinstance(value, list):
            raise ParamValidationError(
                f"Expected list for 'does not equal' operator, got {type(value).__name__}",
                code="ES4_NOT_EQUALS_EXPECTS_LIST",
            )
        parts = [
            f"{prop} != {_format_value(v)}"
            for v in value
            if isinstance(v, (str, int, float))
        ]
        dropped = [v for v in value if not isinstance(v, (str, int, float))]
        if dropped:
            logger.warning(
                "Filter.not_equals() dropped %d non-scalar value(s): %r",
                len(dropped),
                dropped,
            )
        if not parts:
            raise ParamValidationError(
                f"Filter.not_equals() produced no valid selector terms. "
                f"All values were non-scalar: {value!r}",
                code="ES5_NOT_EQUALS_NO_TERMS",
            )
        # AND-combine: "!= a AND != b" means "not in [a, b]"
        # (contrast: equals uses OR — "== a OR == b" means "in [a, b]")
        return " and ".join(parts)

    if op == "contains":
        if not isinstance(value, str):
            raise ParamValidationError(
                f"Expected str for 'contains' operator, got {type(value).__name__}",
                code="ES6_CONTAINS_EXPECTS_STR",
            )
        return f"{_format_value(value)} in {prop}"

    if op == "does not contain":
        if not isinstance(value, str):
            raise ParamValidationError(
                f"Expected str for 'does not contain' operator, got {type(value).__name__}",
                code="ES7_NOT_CONTAINS_EXPECTS_STR",
            )
        return f"not {_format_value(value)} in {prop}"

    if op == "is greater than":
        return f"{prop} > {_number(op, value, 'ES8_GT_EXPECTS_NUMBER')}"

    if op == "is less than":
        return f"{prop} < {_number(op, value, 'ES9_LT_EXPECTS_NUMBER')}"

    if op == "is at least":
        return f"{prop} >= {_number(op, value, 'ES19_AT_LEAST_EXPECTS_NUMBER')}"

    if op == "is at most":
        return f"{prop} <= {_number(op, value, 'ES20_AT_MOST_EXPECTS_NUMBER')}"

    if op == "is between":
        lo, hi = _number_pair(op, value)
        return f"{prop} >= {lo} and {prop} <= {hi}"

    if op == "not between":
        lo, hi = _number_pair(op, value)
        return f"({prop} < {lo} or {prop} > {hi})"

    if op == "is set":
        return f"defined({prop})"

    if op == "is not set":
        return f"not defined({prop})"

    if op == "true":
        return f"{prop} == true"

    if op == "false":
        return f"{prop} == false"

    if op in _ABSOLUTE_DATE_OPERATORS:
        return _absolute_date_selector(op, prop, value)

    if op in _RELATIVE_DATE_OPERATORS:
        return _relative_date_selector(f, prop)

    if op in ("starts with", "ends with", "list_contains"):
        raise _no_selector_equivalent(f)

    raise ParamValidationError(
        f"Unsupported filter operator: {op!r}. Pass a raw Engage selector "
        "string instead, for example "
        'where=\'properties["plan"] == "premium"\'.',
        code="ES13_UNSUPPORTED_OPERATOR",
    )


def filters_to_selector(filters: list[Filter]) -> str:
    """Convert multiple Filters to an AND-combined selector string.

    Each Filter is translated individually via ``filter_to_selector()``,
    then combined with `` and `` operators.

    Args:
        filters: List of Filter objects to AND-combine.

    Returns:
        AND-combined selector string. Returns empty string if list is empty.

    Raises:
        ParamValidationError: Propagated from ``filter_to_selector()`` for
            any invalid or unsupported Filter (``ES1``–``ES20`` family
            codes, or ``V8_DATE_FORMAT`` / ``V8_DATE_INVALID``).

    Example:
        ```python
        from mixpanel_headless.types import Filter
        from mixpanel_headless._internal.query.user_builders import filters_to_selector

        selector = filters_to_selector([
            Filter.equals("plan", "premium"),
            Filter.is_set("email"),
        ])
        # 'properties["plan"] == "premium" and defined(properties["email"])'
        ```
    """
    if not filters:
        return ""
    return " and ".join(filter_to_selector(f) for f in filters)


def extract_cohort_filter(
    filters: list[Filter],
) -> tuple[list[Filter], Filter | None]:
    """Extract a cohort filter from a list of Filters.

    Separates ``Filter.in_cohort()`` entries from regular property filters.
    At most one cohort filter is expected (validated by U13).

    Args:
        filters: List of Filter objects, possibly containing a cohort filter.

    Returns:
        Tuple of (remaining_filters, cohort_filter_or_none).

    Example:
        ```python
        from mixpanel_headless.types import Filter
        from mixpanel_headless._internal.query.user_builders import extract_cohort_filter

        filters = [
            Filter.equals("plan", "premium"),
            Filter.in_cohort(123),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        # remaining = [Filter.equals("plan", "premium")]
        # cohort = Filter.in_cohort(123)
        ```
    """
    remaining: list[Filter] = []
    cohort: Filter | None = None
    for f in filters:
        if _is_cohort_filter(f):
            if cohort is None:
                cohort = f
            else:
                # U13 guarantees at most one cohort filter; extra
                # cohorts stay in remaining as a defensive measure
                logger.warning(
                    "Multiple cohort filters found; first used as cohort, "
                    "extras moved to remaining filters"
                )
                remaining.append(f)
        else:
            remaining.append(f)
    return remaining, cohort
