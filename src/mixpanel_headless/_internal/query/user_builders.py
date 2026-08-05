"""Filter-to-selector translation for the Engage API.

Converts ``Filter`` objects to engage API selector strings. This is the
third translation path alongside ``bookmark_builders.build_filter_entry()``
(bookmark dicts for insights/funnels/retention) and
``segfilter.build_segfilter_entry()`` (segfilter entries for flows).

The engage API uses selector strings like ``properties["plan"] == "premium"``
rather than bookmark filter dicts or segfilter entries.

Functions:
    filter_to_selector: Convert a single Filter to a selector string.
    filters_to_selector: Convert multiple Filters to an AND-combined selector.
    extract_cohort_filter: Extract cohort filter from a Filter list.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeGuard

from mixpanel_headless.types import AbstractFilter, ContainmentFilter

logger = logging.getLogger(__name__)


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


def _prop_ref(f: AbstractFilter) -> str:
    """Build the ``properties["name"]`` reference for a Filter.

    Args:
        f: Filter whose property name to reference.

    Returns:
        String of the form ``properties["<name>"]``.
    """
    if not isinstance(f.property, str):
        raise ValueError(
            f"Engage selector requires a string property name, "
            f"got {type(f.property).__name__}. Custom properties "
            f"are not supported in query_user() filters."
        )
    escaped = f.property.replace("\\", "\\\\").replace('"', '\\"')
    return f'properties["{escaped}"]'


def _is_cohort_filter(f: AbstractFilter) -> TypeGuard[ContainmentFilter]:
    """Return True if *f* is a cohort filter (in_cohort / not_in_cohort).

    Cohort membership is the one thing ``ContainmentFilter`` carries
    besides a substring, and it is the only filter whose value is a list
    of :class:`~mixpanel_headless.types.CohortRef`. That makes this an
    exact test — it used to be a "value is a list of dicts" heuristic,
    which was as close as an untyped payload allowed.

    Args:
        f: Filter to test.

    Returns:
        True when the filter carries cohort membership. A ``TypeGuard``,
        so callers narrow to :class:`ContainmentFilter` and need no
        second check of their own.
    """
    return isinstance(f, ContainmentFilter) and isinstance(f.value, list)


def filter_to_selector(f: AbstractFilter) -> str:
    """Convert a single Filter to an engage API selector string.

    Translates the Filter's internal operator to the equivalent engage
    selector syntax. Each operator maps to a specific selector pattern.

    Args:
        f: A Filter object (constructed via class methods like
            ``FilterFactory.equals()``, ``FilterFactory.greater_than()``, etc.).

    Returns:
        Selector string for the engage API ``where`` parameter.

    Raises:
        ValueError: If the Filter has an unsupported operator.

    Example:
        ```python
        from mixpanel_headless.types import Filter
        from mixpanel_headless._internal.query.user_builders import filter_to_selector

        selector = filter_to_selector(FilterFactory.equals("plan", "premium"))
        # 'properties["plan"] == "premium"'
        ```
    """
    op = f.operator
    prop = _prop_ref(f)
    value = f.value

    if op == "equals":
        # A numeric/bool-typed equals leaves _value scalar (the bookmark and
        # segfilter paths accept it); wrap it so the selector emits one term,
        # like a string equals (already list-wrapped in __post_init__).
        items = [value] if not isinstance(value, list) else value
        parts = [
            f"{prop} == {_format_value(v)}"
            for v in items
            if isinstance(v, (str, int, float))
        ]
        dropped = [v for v in items if not isinstance(v, (str, int, float))]
        if dropped:
            logger.warning(
                "FilterFactory.equals() dropped %d non-scalar value(s): %r",
                len(dropped),
                dropped,
            )
        if not parts:
            raise ValueError(
                f"FilterFactory.equals() produced no valid selector terms. "
                f"All values were non-scalar: {items!r}"
            )
        if len(parts) > 1:
            return f"({' or '.join(parts)})"
        return parts[0]

    if op == "does not equal":
        # Wrap a scalar like the equals branch above (numeric/bool-typed
        # not-equals leaves _value scalar; the selector still emits one term).
        items = [value] if not isinstance(value, list) else value
        parts = [
            f"{prop} != {_format_value(v)}"
            for v in items
            if isinstance(v, (str, int, float))
        ]
        dropped = [v for v in items if not isinstance(v, (str, int, float))]
        if dropped:
            logger.warning(
                "FilterFactory.not_equals() dropped %d non-scalar value(s): %r",
                len(dropped),
                dropped,
            )
        if not parts:
            raise ValueError(
                f"FilterFactory.not_equals() produced no valid selector terms. "
                f"All values were non-scalar: {items!r}"
            )
        # AND-combine: "!= a AND != b" means "not in [a, b]"
        # (contrast: equals uses OR — "== a OR == b" means "in [a, b]")
        return " and ".join(parts)

    if op == "contains":
        if not isinstance(value, str):
            raise ValueError(
                f"Expected str for 'contains' operator, got {type(value).__name__}"
            )
        return f"{_format_value(value)} in {prop}"

    if op == "does not contain":
        if not isinstance(value, str):
            raise ValueError(
                f"Expected str for 'does not contain' operator, got {type(value).__name__}"
            )
        return f"not {_format_value(value)} in {prop}"

    if op == "is greater than":
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"Expected int or float for 'is greater than' operator, got {type(value).__name__}"
            )
        return f"{prop} > {_format_value(value)}"

    if op == "is less than":
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"Expected int or float for 'is less than' operator, got {type(value).__name__}"
            )
        return f"{prop} < {_format_value(value)}"

    if op == "is between":
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(
                f"Expected list of length 2 for 'is between' operator, got {type(value).__name__}"
            )
        lo, hi = value[0], value[1]
        if not isinstance(lo, (int, float)):
            raise ValueError(
                f"Expected int or float for lower bound, got {type(lo).__name__}"
            )
        if not isinstance(hi, (int, float)):
            raise ValueError(
                f"Expected int or float for upper bound, got {type(hi).__name__}"
            )
        return f"{prop} >= {_format_value(lo)} and {prop} <= {_format_value(hi)}"

    if op == "is set":
        return f"defined({prop})"

    if op == "is not set":
        return f"not defined({prop})"

    if op == "true":
        return f"{prop} == true"

    if op == "false":
        return f"{prop} == false"

    raise ValueError(f"Unsupported filter operator: {op!r}")


def filters_to_selector(filters: Sequence[AbstractFilter]) -> str:
    """Convert multiple Filters to an AND-combined selector string.

    Each Filter is translated individually via ``filter_to_selector()``,
    then combined with `` and `` operators.

    Args:
        filters: List of Filter objects to AND-combine.

    Returns:
        AND-combined selector string. Returns empty string if list is empty.

    Example:
        ```python
        from mixpanel_headless.types import Filter
        from mixpanel_headless._internal.query.user_builders import filters_to_selector

        selector = filters_to_selector([
            FilterFactory.equals("plan", "premium"),
            FilterFactory.is_set("email"),
        ])
        # 'properties["plan"] == "premium" and defined(properties["email"])'
        ```
    """
    if not filters:
        return ""
    return " and ".join(filter_to_selector(f) for f in filters)


def extract_cohort_filter(
    filters: Sequence[AbstractFilter],
) -> tuple[list[AbstractFilter], ContainmentFilter | None]:
    """Extract a cohort filter from a list of Filters.

    Separates ``FilterFactory.in_cohort()`` entries from regular property filters.
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
            FilterFactory.equals("plan", "premium"),
            FilterFactory.in_cohort(123),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        # remaining = [FilterFactory.equals("plan", "premium")]
        # cohort = FilterFactory.in_cohort(123)
        ```
    """
    remaining: list[AbstractFilter] = []
    cohort: ContainmentFilter | None = None
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
