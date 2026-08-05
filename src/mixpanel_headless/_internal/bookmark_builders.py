"""Reusable builder functions for bookmark JSON sections.

Extracted from ``Workspace._build_query_params()`` to enable reuse across
insights, funnels, retention, and flows query builders. Each function
produces a fragment of the Mixpanel bookmark ``params`` JSON structure.

These are internal helpers — import from ``mixpanel_headless._internal.bookmark_builders``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, NoReturn, cast

from mixpanel_headless._literal_types import QueryTimeUnit
from mixpanel_headless.exceptions import BookmarkValidationError, ValidationError
from mixpanel_headless.types import (
    AbstractFilter,
    CohortBreakdown,
    ContainmentFilter,
    CustomPropertyRef,
    Filter,
    FrequencyBreakdown,
    FrequencyFilter,
    GroupBy,
    InlineCustomProperty,
    PayloadFormatError,
    TimeComparison,
    _sanitize_raw_cohort,
)
from mixpanel_headless.types import (
    _build_composed_properties as _build_composed_properties,  # re-export
)


def _reject(path: str, message: str, code: str) -> NoReturn:
    """Raise a single-error ``BookmarkValidationError``.

    Shared scaffolding for builder-level rejections of inputs the payload
    format cannot express, so each call site reads as just the rule
    (path, message, code).

    Args:
        path: JSONPath-like location of the offending input
            (e.g. ``"where[0]"``).
        message: Human-readable explanation of the rejection.
        code: Stable error code (e.g. ``"FL_WHERE_LIST_CONTAINS_UNSUPPORTED"``).

    Raises:
        BookmarkValidationError: Always, wrapping the single error.
    """
    raise BookmarkValidationError(
        [ValidationError(path=path, message=message, code=code)]
    )


def build_time_section(
    *,
    from_date: str | None,
    to_date: str | None,
    last: int,
    unit: QueryTimeUnit,
) -> list[dict[str, Any]]:
    """Build the ``sections.time`` array for bookmark params.

    Produces a single-element list containing one time entry dict.
    Three cases are handled:

    - **Absolute range**: both ``from_date`` and ``to_date`` set.
    - **From-only range**: only ``from_date`` set; ``to_date`` is filled
      with today's date.
    - **Relative range**: neither date set; uses ``last`` days.

    Args:
        from_date: Start date (YYYY-MM-DD) or ``None``.
        to_date: End date (YYYY-MM-DD) or ``None``.
        last: Number of days for relative range (used when no dates given).
        unit: Time granularity (``"hour"``, ``"day"``, ``"week"``,
            ``"month"``, ``"quarter"``).

    Returns:
        Single-element list with one time entry dict. Structure varies
        by case:

        - Absolute: ``{"dateRangeType": "between", "unit": ..., "value": [from, to]}``
        - From-only: same as absolute with ``to_date`` = today
        - Relative: ``{"dateRangeType": "in the last", "unit": ..., "window": {...}}``

    Example:
        ```python
        time = build_time_section(
            from_date="2025-01-01", to_date="2025-01-31",
            last=30, unit="day",
        )
        # [{"dateRangeType": "between", "unit": "day",
        #   "value": ["2025-01-01", "2025-01-31"]}]
        ```
    """
    if from_date is not None:
        effective_to = to_date if to_date is not None else date.today().isoformat()
        time_entry: dict[str, Any] = {
            "dateRangeType": "between",
            "unit": unit,
            "value": [from_date, effective_to],
        }
    else:
        time_entry = {
            "dateRangeType": "in the last",
            "unit": unit,
            "window": {"unit": "day", "value": last},
        }
    return [time_entry]


def build_date_range(
    *,
    from_date: str | None,
    to_date: str | None,
    last: int,
) -> dict[str, Any]:
    """Build a flat date range dict for flows (non-sections format).

    Flows use a flat ``date_range`` object rather than the sections-based
    ``sections.time`` array used by insights. A lone ``from_date`` fills
    today's date for the missing ``to_date`` — the same defaulting
    ``build_time_section`` applies — so an "everything since X" query
    behaves identically across all four query paths.

    Args:
        from_date: Start date (YYYY-MM-DD) or ``None``.
        to_date: End date (YYYY-MM-DD) or ``None``.
        last: Number of days for relative range.

    Returns:
        Date range dict. Structure varies by case:

        - Absolute: ``{"type": "between", "from_date": ..., "to_date": ...}``
          (``to_date`` defaults to today when only ``from_date`` is set)
        - Relative: ``{"type": "in the last", "from_date": {"unit": "day", "value": N}, "to_date": "$now"}``

    Example:
        ```python
        dr = build_date_range(from_date=None, to_date=None, last=30)
        # {"type": "in the last",
        #  "from_date": {"unit": "day", "value": 30},
        #  "to_date": "$now"}
        ```
    """
    if from_date is not None:
        effective_to = to_date if to_date is not None else date.today().isoformat()
        return {
            "type": "between",
            "from_date": from_date,
            "to_date": effective_to,
        }
    return {
        "type": "in the last",
        "from_date": {"unit": "day", "value": last},
        "to_date": "$now",
    }


def build_filter_section(
    where: AbstractFilter
    | FrequencyFilter
    | Sequence[AbstractFilter | FrequencyFilter]
    | None,
) -> list[dict[str, Any]]:
    """Build the ``sections.filter`` array for bookmark params.

    Converts ``None``, a single ``Filter`` or ``FrequencyFilter``, or a
    list of ``Filter`` / ``FrequencyFilter`` objects into the list-of-dicts
    format expected by the Mixpanel bookmark API.

    Args:
        where: Filter specification. ``None`` means no filters,
            a single ``Filter`` or ``FrequencyFilter`` is wrapped in a
            list, a list is processed element-by-element.

    Returns:
        List of filter entry dicts (may be empty).

    Example:
        ```python
        filters = build_filter_section(FilterFactory.equals("country", "US"))
        # [{"resourceType": "events", "filterType": "string", ...}]
        ```
    """
    if where is None:
        return []
    filters_list = list(where) if isinstance(where, (list, tuple)) else [where]
    result: list[dict[str, Any]] = []
    for f in filters_list:
        if isinstance(f, FrequencyFilter):
            result.append(build_frequency_filter_entry(f))
        elif isinstance(f, AbstractFilter):
            # Every AbstractFilter instance is one of the eleven members —
            # nothing constructs the base — but mypy cannot carry that from
            # an isinstance narrowing to the union the callee declares.
            result.append(build_filter_entry(cast("Filter", f)))
    return result


def patch_custom_property_filters_for_transform(
    filter_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add ``value`` sentinel to custom property filters for server compat.

    The server's ``transform_insights_filters_to_funnels()`` does a hard
    ``f["value"]`` access on global ``sections.filter`` entries before
    ``arb_selector`` processes them.  Custom property filters identify
    the property via ``customPropertyId`` or ``customProperty`` instead
    of ``value``, causing a ``KeyError`` and HTTP 500.

    Injecting ``"value": None`` satisfies the hard access.  The
    downstream ``arb_selector`` routes on ``is_custom_property()``, not
    ``propertyName``, so the sentinel is harmless.

    This must **not** be applied to per-step or per-metric filters —
    the insights validator rejects ``value: None`` in those positions.

    Args:
        filter_entries: List of filter dicts from ``build_filter_section()``.

    Returns:
        The same list, mutated in-place, with ``"value": None`` added
        to any entry that has ``customPropertyId`` or ``customProperty``
        but no ``value`` key.
    """
    for entry in filter_entries:
        if "value" not in entry and (
            "customPropertyId" in entry or "customProperty" in entry
        ):
            entry["value"] = None
    return filter_entries


def build_group_section(
    group_by: str
    | GroupBy
    | CohortBreakdown
    | FrequencyBreakdown
    | Sequence[str | GroupBy | CohortBreakdown | FrequencyBreakdown]
    | None,
    *,
    data_group_id: int | None = None,
) -> list[dict[str, Any]]:
    """Build the ``sections.group`` array for bookmark params.

    Converts group-by specifications into the list-of-dicts format
    expected by the Mixpanel bookmark API. Supports strings (simple
    property name), ``GroupBy`` objects (with optional bucketing),
    ``CohortBreakdown`` objects (cohort-based segmentation),
    ``FrequencyBreakdown`` objects (event frequency segmentation),
    and lists mixing all four.

    Args:
        group_by: Group-by specification. ``None`` means no grouping.
            Strings produce default string-typed entries. ``GroupBy``
            objects allow custom property types and numeric bucketing.
            ``CohortBreakdown`` objects produce cohort group entries.
            ``FrequencyBreakdown`` objects produce frequency group entries.
        data_group_id: Optional data group ID for group-level analytics.
            Threads into ``dataGroupId`` fields within group entries
            that support it (custom property refs, inline custom
            properties, cohort breakdowns). Default: ``None``.

    Returns:
        List of group entry dicts (may be empty).

    Raises:
        TypeError: If any element is not ``str``, ``GroupBy``,
            ``CohortBreakdown``, or ``FrequencyBreakdown``.

    Example:
        ```python
        groups = build_group_section(CohortBreakdown(123, "Power Users"))
        # [{"value": ["Power Users", "Not In Power Users"],
        #   "resourceType": "events", ...}]
        ```
    """
    if group_by is None:
        return []

    groups = list(group_by) if isinstance(group_by, (list, tuple)) else [group_by]
    group_section: list[dict[str, Any]] = []

    for g in groups:
        if isinstance(g, str):
            group_section.append(
                {
                    "value": g,
                    "propertyName": g,
                    "resourceType": "events",
                    "propertyType": "string",
                    "propertyDefaultType": "string",
                }
            )
        elif isinstance(g, FrequencyBreakdown):
            group_section.append(
                build_frequency_group_entry(g, data_group_id=data_group_id)
            )
        elif isinstance(g, GroupBy):
            prop = g.property
            if isinstance(prop, CustomPropertyRef):
                group_entry: dict[str, Any] = {
                    "customPropertyId": prop.id,
                    "value": None,
                    "resourceType": "events",
                    "profileType": None,
                    "search": "",
                    "dataGroupId": data_group_id,
                    "dataset": "$mixpanel",
                    "propertyType": g.property_type,
                    "typeCast": None,
                    "unit": None,
                    "isHidden": False,
                }
            elif isinstance(prop, InlineCustomProperty):
                effective_type = (
                    prop.property_type
                    if prop.property_type is not None
                    else g.property_type
                )
                composed = _build_composed_properties(prop.inputs)
                group_entry = {
                    "customProperty": {
                        "displayFormula": prop.formula,
                        "composedProperties": composed,
                        "name": "",
                        "description": "",
                        "propertyType": effective_type,
                        "resourceType": prop.resource_type,
                    },
                    "value": None,
                    "resourceType": prop.resource_type,
                    "profileType": None,
                    "search": "",
                    "dataGroupId": data_group_id,
                    "dataset": "$mixpanel",
                    "propertyType": effective_type,
                    "typeCast": None,
                    "unit": None,
                    "isHidden": False,
                }
            elif g._list_item_mode is not None:
                # resourceType is hardcoded "events" and propertyType is
                # hardcoded "object": GroupBy.list_item is event-only —
                # the Mixpanel UI does not support list-of-object
                # breakdowns for people properties, so the classmethod
                # exposes no resource_type parameter. Asymmetric with
                # FilterFactory.list_contains, which DOES accept
                # resource_type="people" because the payload format permits
                # list-object filters on people properties (just not
                # breakdowns).
                mode = g._list_item_mode
                group_entry = {
                    "dataset": "$mixpanel",
                    "value": prop,
                    "resourceType": "events",
                    "joinPropertyType": "list",
                    "propertyType": "object",
                    "listItemGroup": {
                        "resourceType": "event",
                        "propertyName": mode.sub,
                        "propertyDefaultType": mode.sub_type,
                        "propertyType": mode.sub_type,
                    },
                }
            else:
                group_entry = {
                    "value": prop,
                    "propertyName": prop,
                    "resourceType": "events",
                    "propertyType": g.property_type,
                    "propertyDefaultType": g.property_type,
                }
            if g.bucket_size is not None:
                group_entry["customBucket"] = {
                    "bucketSize": g.bucket_size,
                }
                if g.bucket_min is not None:
                    group_entry["customBucket"]["min"] = g.bucket_min
                if g.bucket_max is not None:
                    group_entry["customBucket"]["max"] = g.bucket_max
            group_section.append(group_entry)
        elif isinstance(g, CohortBreakdown):
            group_section.append(
                _build_cohort_group_entry(g, data_group_id=data_group_id)
            )
        else:
            raise TypeError(
                f"group_by elements must be str, GroupBy, CohortBreakdown, "
                f"or FrequencyBreakdown, got {type(g).__name__}: {g!r}"
            )

    return group_section


def _build_cohort_group_entry(
    cb: CohortBreakdown,
    *,
    data_group_id: int | None = None,
) -> dict[str, Any]:
    """Build a single cohort group entry for sections.group[].

    Produces the cohort-specific group dict with ``cohorts`` array
    containing one or two entries (with/without negated) depending
    on ``include_negated``.

    Args:
        cb: CohortBreakdown specification.
        data_group_id: Optional data group ID for group-level analytics.
            Threads into ``data_group_id`` in cohort entries and
            ``dataGroupId`` in the top-level group entry.
            Default: ``None``.

    Returns:
        Group entry dict with ``cohorts`` array.

    Example:
        ```python
        entry = _build_cohort_group_entry(CohortBreakdown(123, "PU"))
        # {"value": ["PU", "Not In PU"], "cohorts": [...], ...}
        ```
    """
    name = cb.name or ""

    # Build cohort entries — saved vs inline use different API schemas:
    # Schema 1 (saved): allows groups, count, description, etc.
    # Schema 2 (inline): allows raw_cohort, dataset, but NOT groups
    base_cohort: dict[str, Any] = {
        "name": name,
        "negated": False,
        "data_group_id": data_group_id,
    }
    if isinstance(cb.cohort, int):
        base_cohort["id"] = cb.cohort
        base_cohort["groups"] = []
    else:
        base_cohort["raw_cohort"] = _sanitize_raw_cohort(cb.cohort.to_dict())

    cohorts: list[dict[str, Any]] = [base_cohort]
    value_labels: list[str] = [name]

    if cb.include_negated:
        cohorts.append({**base_cohort, "negated": True})
        value_labels.append(f"Not In {name}")

    return {
        "value": value_labels,
        "resourceType": "events",
        "profileType": None,
        "search": "",
        "dataGroupId": data_group_id,
        "propertyType": None,
        "typeCast": None,
        "cohorts": cohorts,
        "isHidden": False,
    }


def build_filter_entry(f: AbstractFilter) -> dict[str, Any]:
    """Convert a Filter object to a bookmark filter dict.

    The rendering lives on the model — see ``AbstractFilter._dump_bookmark``
    and the overrides on ``ContainmentFilter``, ``RelativeDateFilter`` and
    ``CompoundFilter`` in ``mixpanel_headless.types``.

    Args:
        f: The filter to render.

    Returns:
        The bookmark filter entry.

    Example:
        ```python
        build_filter_entry(FilterFactory.equals("country", "US"))
        # {"resourceType": "events", "filterType": "string", ...}
        ```
    """
    return f.mixpanel_model_dump("bookmark")


def build_flow_where_entries(
    filters: Sequence[AbstractFilter],
) -> list[dict[str, Any]]:
    """Build the flat ``where`` entry list for flow bookmark params.

    The arb_funnels endpoint accepts global property filters as a flat
    ``where`` list of ``{property, operator, value}`` dicts (a simpler
    schema than the ``sections.filter`` entries used by insights /
    funnels / retention). Filter kinds the flat format cannot express
    are rejected at build time rather than silently corrupted:

    - non-string properties (custom property refs) are not addressable
      by name in the flat format
    - ``list_contains`` carries nested sub-filters the flat format has
      no key for
    - relative-date operators carry a date unit the flat format has no
      key for; an absolute date filter expresses the same intent

    Args:
        filters: List of property ``Filter`` objects. Must not be
            empty — caller should check before calling. Error paths are
            indexed relative to this list (``where[i]``).

    Returns:
        List of ``{property, operator[, value]}`` dicts suitable for
        the ``where`` bookmark key. ``value`` is omitted for no-value
        operators such as ``is set``.

    Raises:
        BookmarkValidationError: If a filter uses ``list_contains``, a
            relative-date operator, or a non-string property (custom
            property refs) — kinds the flat format cannot express. The
            error carries an ``FL_WHERE_*`` code and a ``where[i]`` path.
        RuntimeError: If ``filters`` is empty (caller misuse — the flow
            path guards with ``if property_filters:``).

    Example:
        ```python
        entries = build_flow_where_entries([FilterFactory.equals("country", "US")])
        # [{"property": "country", "operator": "equals", "value": ["US"]}]
        ```
    """
    if not filters:
        raise RuntimeError(
            "build_flow_where_entries requires at least one filter; "
            "caller should check before calling"
        )
    entries: list[dict[str, Any]] = []
    for i, f in enumerate(filters):
        # A property check, not a filter one: it applies to every member, and
        # the model cannot see whether its own property is a plain name.
        if not isinstance(f.property, str):
            _reject(
                path=f"where[{i}]",
                message=(
                    f"flow where filters only support string "
                    f"property names; got {type(f.property).__name__} — "
                    f"custom property refs are not supported in "
                    f"flow filters"
                ),
                code="FL_WHERE_CUSTOM_PROPERTY_UNSUPPORTED",
            )
        # Members the flat format cannot express refuse themselves. Only the
        # position is added here, since only this loop knows the index.
        try:
            entries.append(f.mixpanel_model_dump("flow_where"))
        except PayloadFormatError as exc:
            _reject(path=f"where[{i}]", message=exc.message, code=exc.code)
    return entries


def build_flow_segment_entries(
    segments: Sequence[str | GroupBy | CohortBreakdown | FrequencyBreakdown],
) -> list[dict[str, Any]]:
    """Build the flat ``segment_by`` entry list for flow bookmark params.

    The arb_funnels endpoint accepts breakdowns as a flat ``segment_by``
    list of ``{property}`` dicts. Breakdown kinds the flat format cannot
    express are rejected at build time — forwarding them produces an
    HTTP 200 with silently empty results:

    - ``CohortBreakdown`` / ``FrequencyBreakdown`` have no property
      name; their group-section entries carry display labels instead
    - ``GroupBy`` on a custom property ref has no name to send
    - ``GroupBy`` numeric bucketing has no key in the flat format
    - ``GroupBy.list_item`` sub-property breakdowns have no key in the
      flat format (the group-section ``listItemGroup`` shape is
      insights-only); sending just the list property would run a
      different query

    Args:
        segments: List of segment specifications. Must not be empty —
            caller should check before calling. Only plain property
            name strings and ``GroupBy`` objects with string properties
            and no bucketing are expressible. Error paths are indexed
            relative to this list (``segments[i]``).

    Returns:
        List of ``{property}`` dicts suitable for the ``segment_by``
        bookmark key.

    Raises:
        BookmarkValidationError: If a segment is a ``CohortBreakdown``
            / ``FrequencyBreakdown``, a ``GroupBy`` on a custom
            property ref, or a ``GroupBy`` with numeric bucketing —
            kinds the flat format cannot express. The error carries an
            ``FL_SEGMENT_*`` code and a ``segments[i]`` path.
        RuntimeError: If ``segments`` is empty (caller misuse — the
            flow path guards with ``if segments:``).

    Example:
        ```python
        entries = build_flow_segment_entries(["country", GroupBy("city")])
        # [{"property": "country"}, {"property": "city"}]
        ```
    """
    if not segments:
        raise RuntimeError(
            "build_flow_segment_entries requires at least one segment; "
            "caller should check before calling"
        )
    entries: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        if isinstance(seg, str):
            entries.append({"property": seg})
            continue
        if isinstance(seg, GroupBy):
            prop = seg.property
            if not isinstance(prop, str):
                _reject(
                    path=f"segments[{i}]",
                    message=(
                        f"flow segments only support plain property "
                        f"names; got a GroupBy on "
                        f"{type(prop).__name__} — custom properties "
                        f"are not supported in flow segment_by"
                    ),
                    code="FL_SEGMENT_CUSTOM_PROPERTY_UNSUPPORTED",
                )
            if (
                seg.bucket_size is not None
                or seg.bucket_min is not None
                or seg.bucket_max is not None
            ):
                _reject(
                    path=f"segments[{i}]",
                    message=(
                        "flow segments cannot express numeric "
                        "bucketing — the flat segment_by format has "
                        "no key for bucket parameters. Use a plain "
                        "GroupBy without buckets"
                    ),
                    code="FL_SEGMENT_BUCKETING_UNSUPPORTED",
                )
            if seg._list_item_mode is not None:
                _reject(
                    path=f"segments[{i}]",
                    message=(
                        "flow segments cannot express "
                        "GroupBy.list_item sub-property breakdowns "
                        "— the flat segment_by format has no key "
                        "for the sub-property, and sending just "
                        "the list property would run a different "
                        "query. Use a plain property name instead"
                    ),
                    code="FL_SEGMENT_LIST_ITEM_UNSUPPORTED",
                )
            entries.append({"property": prop})
            continue
        _reject(
            path=f"segments[{i}]",
            message=(
                f"flow segments do not support "
                f"{type(seg).__name__} — the flat segment_by format "
                f"only carries property names. Use a property name "
                f"string or GroupBy instead"
            ),
            code="FL_SEGMENT_TYPE_UNSUPPORTED",
        )
    return entries


def build_flow_cohort_filter(
    where: AbstractFilter | Sequence[AbstractFilter],
) -> dict[str, Any] | None:
    """Build the ``filter_by_cohort`` dict for flow bookmark params.

    Flows use a legacy ``filter_by_cohort`` top-level key rather than
    the ``sections.filter`` array used by insights/funnels/retention.
    Only cohort filters (``FilterFactory.in_cohort`` / ``FilterFactory.not_in_cohort``)
    are accepted; non-cohort filters raise ``ValueError``.

    Args:
        where: A single cohort ``Filter`` or list of cohort ``Filter``
            objects. Only the first cohort filter is used (flows
            support a single cohort filter).

    Returns:
        Dict with cohort filter structure for the ``filter_by_cohort``
        key, or ``None`` if ``where`` is empty.

    Raises:
        BookmarkValidationError: If more than one cohort filter is
            provided (flows support a single cohort filter) — the one
            user-reachable rejection, code ``FL_WHERE_MULTIPLE_COHORTS``.
        RuntimeError: If a non-cohort filter reaches this builder (the
            flow path splits cohort from property filters first), or a
            cohort filter's ``_value`` structure is malformed — both
            indicate library bugs, not bad user input.

    Example:
        ```python
        fbc = build_flow_cohort_filter(FilterFactory.in_cohort(123, "PU"))
        # {"id": 123, "name": "PU", "negated": False}
        ```
    """
    filters: Sequence[AbstractFilter] = (
        [where] if isinstance(where, AbstractFilter) else where
    )
    if not filters:
        return None

    for f in filters:
        if f.property != "$cohorts":
            raise RuntimeError(
                "build_flow_cohort_filter only accepts cohort filters "
                "(FilterFactory.in_cohort/not_in_cohort); property filters should "
                "use build_flow_where_entries instead"
            )

    if len(filters) > 1:
        _reject(
            path="where",
            message=(
                f"query_flow supports a single cohort filter, but "
                f"{len(filters)} were provided. Pass only one "
                f"FilterFactory.in_cohort/not_in_cohort."
            ),
            code="FL_WHERE_MULTIPLE_COHORTS",
        )

    f = filters[0]
    # `ContainmentFilter.value` is `str | list[CohortRef]` and the $cohorts
    # pairing is enforced at construction, so the structure is a type here
    # rather than something to re-derive and guard.
    if not isinstance(f, ContainmentFilter) or not isinstance(f.value, list):
        raise RuntimeError(
            "Internal error: a cohort filter must be a ContainmentFilter "
            f"carrying a list of CohortRef; got {type(f).__name__}."
        )
    cohort = f.value[0].cohort
    result: dict[str, Any] = {
        "name": cohort.name,
        "negated": f.operator == "does not contain",
    }
    if cohort.id is not None:
        result["id"] = cohort.id
    if cohort.raw_cohort is not None:
        result["raw_cohort"] = cohort.raw_cohort
    return result


def build_frequency_group_entry(
    fb: FrequencyBreakdown,
    *,
    data_group_id: int | None = None,
) -> dict[str, Any]:
    """Build a single frequency group entry for sections.group[].

    Produces the frequency-specific group dict matching the Mixpanel
    bookmark API format with ``behaviorType`` inside the ``behavior``
    sub-dict, ``event`` as a ``{label, value}`` object, and bucket
    configuration in a ``customBucket`` object with camelCase keys.

    Args:
        fb: FrequencyBreakdown specification.
        data_group_id: Optional data group ID for group-level analytics.

    Returns:
        Group entry dict matching the Mixpanel bookmark API schema:
        ``dataset``, ``behavior`` (with ``behaviorType``, ``event``
        object, ``aggregationOperator``, ``filters``,
        ``filtersOperator``, ``dateRange``), ``value`` (display
        label), ``resourceType``, ``propertyType``, ``dataGroupId``,
        and ``customBucket`` (with ``bucketSize``, ``min``, ``max``,
        ``disabled``).

    Example:
        ```python
        from mixpanel_headless._internal.bookmark_builders import (
            build_frequency_group_entry,
        )
        from mixpanel_headless.types import FrequencyBreakdown

        entry = build_frequency_group_entry(FrequencyBreakdown("Purchase"))
        # {"dataset": "$mixpanel", "resourceType": "people",
        #  "behavior": {"behaviorType": "$frequency",
        #               "event": {"label": "Purchase", "value": "Purchase"},
        #               ...},
        #  "customBucket": {"bucketSize": 1, "min": 0, "max": 10, ...}}
        ```
    """
    display_label = fb.label if fb.label is not None else f"{fb.event} Frequency"
    entry: dict[str, Any] = {
        "dataset": "$mixpanel",
        "behavior": {
            "aggregationOperator": "total",
            "event": {"label": fb.event, "value": fb.event},
            "behaviorType": "$frequency",
            "filters": [],
            "filtersOperator": "and",
            "dateRange": None,
        },
        "value": display_label,
        "resourceType": "people",
        "propertyType": "number",
        "dataGroupId": data_group_id,
        "customBucket": {
            "bucketSize": fb.bucket_size,
            "min": fb.bucket_min,
            "max": fb.bucket_max,
            "disabled": False,
        },
    }
    return entry


def build_frequency_filter_entry(ff: FrequencyFilter) -> dict[str, Any]:
    """Build a single frequency filter entry for sections.filter[].

    Produces the frequency-specific filter dict with ``behaviorType``
    set to ``"$frequency"`` and ``resourceType`` set to ``"people"``.

    Args:
        ff: FrequencyFilter specification.

    Returns:
        Filter entry dict with ``customProperty.behavior`` sub-dict
        containing the frequency event, operator, and threshold.
        Optionally includes ``dateRange`` and ``eventFilters``.

    Example:
        ```python
        from mixpanel_headless._internal.bookmark_builders import (
            build_frequency_filter_entry,
        )
        from mixpanel_headless.types import FrequencyFilter

        entry = build_frequency_filter_entry(
            FrequencyFilter("Login", value=5)
        )
        # {"resourceType": "people", "behaviorType": "$frequency",
        #  "customProperty": {"behavior": {"event": "Login", ...}}}
        ```
    """
    behavior: dict[str, Any] = {
        "event": ff.event,
        "aggregation": "total",
        "filterOperator": ff.operator,
        "filterValue": ff.value,
    }
    if ff.date_range_value is not None and ff.date_range_unit is not None:
        behavior["dateRange"] = {
            "value": ff.date_range_value,
            "unit": ff.date_range_unit,
        }
    if ff.event_filters is not None:
        behavior["eventFilters"] = [build_filter_entry(f) for f in ff.event_filters]
    entry: dict[str, Any] = {
        "resourceType": "people",
        "behaviorType": "$frequency",
        "customProperty": {
            "behavior": behavior,
        },
    }
    if ff.label is not None:
        entry["label"] = ff.label
    return entry


def build_time_comparison(tc: TimeComparison) -> dict[str, str]:
    """Build the ``timeComparison`` dict for ``displayOptions``.

    Converts a ``TimeComparison`` dataclass into the JSON dict format
    expected by the Mixpanel bookmark API inside
    ``displayOptions.timeComparison``.

    The output format is ``{"type": <type>, "value": <unit_or_date>}``:

    - For ``type="relative"``: value is the comparison unit
      (day, week, month, quarter, year).
    - For ``type="absolute-start"`` or ``"absolute-end"``: value is
      the ISO date string (YYYY-MM-DD).

    Args:
        tc: A validated ``TimeComparison`` dataclass instance.

    Returns:
        Dict with ``type`` and ``value`` keys, both strings.

    Example:
        ```python
        from mixpanel_headless._internal.bookmark_builders import (
            build_time_comparison,
        )
        from mixpanel_headless.types import TimeComparison

        result = build_time_comparison(TimeComparison.relative("month"))
        # {"type": "relative", "value": "month"}
        ```
    """
    value: str
    if tc.type == "relative":
        # tc.unit guaranteed non-None by __post_init__ TC1
        if tc.unit is None:  # pragma: no cover — guarded by TC1
            raise AssertionError(
                "unreachable: TC1 guarantees unit when type='relative'"
            )
        value = tc.unit
    else:
        # tc.date guaranteed non-None by __post_init__ TC2
        if tc.date is None:  # pragma: no cover — guarded by TC2
            raise AssertionError(
                "unreachable: TC2 guarantees date when type='absolute-*'"
            )
        value = tc.date
    return {"type": tc.type, "value": value}
