"""Show-clause builders for insights, funnel, and retention metrics.

Pure functions that turn typed inline query values (``Metric``,
``CohortMetric``, ``Formula``, ``FunnelStep``, ``RetentionEvent``, and the
engine arguments around them) into the ``sections.show`` fragments of
Mixpanel bookmark params. They do no I/O and no validation: the Workspace
query builders validate the arguments before they call these functions and
validate the assembled bookmark after.

A metric show clause is ``{"type": "metric", "behavior": ..., "measurement":
...}``. The behavior says what users did and the measurement says how to
count it. Each part has its own builder, so one inline value always gives the
same behavior and measurement wherever the library writes them.

Key order in every returned dict is part of the contract. The library sends
these dicts as JSON in insertion order, so a change of order changes the
request bytes.

These are internal helpers. Import them from
``mixpanel_headless._internal.query.metric_builders``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from mixpanel_headless._internal.bookmark_builders import (
    _build_composed_properties,
    build_filter_entry,
)
from mixpanel_headless._literal_types import (
    ConversionWindowUnit,
    FiltersCombinator,
    FunnelMathType,
    FunnelOrder,
    FunnelReentryMode,
    MathType,
    PerUserAggregation,
    RetentionAlignment,
    RetentionMathType,
    RetentionUnboundedMode,
    SegmentMethod,
    TimeUnit,
)
from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import (
    BehaviorRef,
    CohortMetric,
    CustomEventRef,
    CustomPropertyRef,
    Exclusion,
    Filter,
    Formula,
    FormulaOperand,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    HoldingConstant,
    InlineCustomProperty,
    Metric,
    MetricRef,
    PropertySpec,
    RetentionBehavior,
    RetentionEvent,
    RetentionMetric,
    SimpleBehavior,
    _sanitize_raw_cohort,
)

# =============================================================================
# Shared pieces
# =============================================================================


def assemble_metric_clause(
    behavior: dict[str, Any],
    measurement: dict[str, Any],
) -> dict[str, Any]:
    """Wrap a behavior block and a measurement block in a metric show clause.

    Args:
        behavior: The ``behavior`` block (what users did).
        measurement: The ``measurement`` block (how to count it).

    Returns:
        A dict with the keys ``type``, ``behavior``, and ``measurement``,
        in that order. The two blocks are used as given, not copied.
    """
    return {
        "type": "metric",
        "behavior": behavior,
        "measurement": measurement,
    }


def build_measurement_property(prop: PropertySpec) -> dict[str, Any]:
    """Build the ``measurement.property`` dict of an insights metric.

    Args:
        prop: A property name, a saved custom property reference, or an
            inline custom property.

    Returns:
        The property dict. A saved custom property gives its id with an
        empty name. An inline custom property gives its formula and inputs
        under ``customProperty``. A property name gives the name with the
        ``events`` resource type.

    Example:
        ```python
        build_measurement_property("amount")
        # {"name": "amount", "resourceType": "events"}

        build_measurement_property(CustomPropertyRef(42))
        # {"customPropertyId": 42, "name": "", "resourceType": "events"}
        ```
    """
    if isinstance(prop, CustomPropertyRef):
        return {
            "customPropertyId": prop.id,
            "name": "",
            "resourceType": "events",
        }
    if isinstance(prop, InlineCustomProperty):
        cp_dict: dict[str, Any] = {
            "displayFormula": prop.formula,
            "composedProperties": _build_composed_properties(prop.inputs),
            "name": "",
            "description": "",
            "resourceType": prop.resource_type,
        }
        if prop.property_type is not None:
            cp_dict["propertyType"] = prop.property_type
        return {
            "customProperty": cp_dict,
            "name": "",
            "resourceType": prop.resource_type,
            "dataset": "$mixpanel",
            "dataGroupId": None,
        }
    return {
        "name": prop,
        "resourceType": "events",
    }


# =============================================================================
# Insights metrics
# =============================================================================


def build_metric_measurement(
    *,
    math: MathType,
    property: PropertySpec | None = None,
    per_user: PerUserAggregation | None = None,
    percentile_value: int | float | None = None,
    segment_method: SegmentMethod | None = None,
) -> dict[str, Any]:
    """Build the ``measurement`` block of an insights event metric.

    The user-facing ``"percentile"`` math is written as
    ``"custom_percentile"``, the name the bookmark format uses. Each optional
    argument that is ``None`` leaves its key out.

    Args:
        math: Aggregation function.
        property: Property for property-based math.
        per_user: Per-user pre-aggregation.
        percentile_value: Percentile to compute. Written for any math.
        segment_method: How qualifying events count per user.

    Returns:
        The measurement dict. Keys, in order: ``math``, then ``property``,
        ``perUserAggregation``, ``percentile``, and ``segmentMethod`` when
        set.

    Example:
        ```python
        build_metric_measurement(math="percentile", property="ms", percentile_value=95)
        # {"math": "custom_percentile",
        #  "property": {"name": "ms", "resourceType": "events"},
        #  "percentile": 95}
        ```
    """
    bookmark_math = "custom_percentile" if math == "percentile" else math
    measurement: dict[str, Any] = {"math": bookmark_math}
    if property is not None:
        measurement["property"] = build_measurement_property(property)
    if per_user is not None:
        measurement["perUserAggregation"] = per_user
    if percentile_value is not None:
        measurement["percentile"] = percentile_value
    if segment_method is not None:
        measurement["segmentMethod"] = segment_method
    return measurement


def build_event_behavior(
    event: str,
    *,
    filters: Sequence[Filter] | None = None,
    filters_combinator: FiltersCombinator = "all",
) -> dict[str, Any]:
    """Build the ``behavior`` block of an insights metric over one event.

    Args:
        event: Mixpanel event name.
        filters: Per-metric filters. ``None`` or an empty list gives an
            empty filter list.
        filters_combinator: How the filters combine (``"all"`` or
            ``"any"``). Written as ``filtersDeterminer``.

    Returns:
        The behavior dict with ``type: "event"``.
    """
    behavior_filters: list[dict[str, Any]] = []
    if filters:
        behavior_filters = [build_filter_entry(f) for f in filters]
    return {
        "type": "event",
        "name": event,
        "resourceType": "events",
        "filtersDeterminer": filters_combinator,
        "filters": behavior_filters,
    }


def custom_event_name(ref: CustomEventRef) -> str:
    """Return the wire name of a saved custom event.

    Args:
        ref: The custom event reference.

    Returns:
        ``"$custom_event:<id>"``. The query API also accepts this name as a
        plain event name; the display name of a custom event matches no
        events.
    """
    return f"$custom_event:{ref.id}"


def build_custom_event_behavior(
    ref: CustomEventRef,
    *,
    filters: Sequence[Filter] | None = None,
    filters_combinator: FiltersCombinator = "all",
) -> dict[str, Any]:
    """Build the ``behavior`` block of an insights metric over a custom event.

    The block has the shape the web app writes: the id, the
    ``$custom_event:<id>`` name, and the events resource type. With the id
    alone the server adds the unique users of each alternative event
    instead of counting each user once.

    Args:
        ref: The custom event reference.
        filters: Per-metric filters. ``None`` or an empty list gives an
            empty filter list.
        filters_combinator: How the filters combine. Written as
            ``filtersDeterminer``.

    Returns:
        The behavior dict with ``type: "custom-event"``.
    """
    return {
        "type": "custom-event",
        "id": ref.id,
        "name": custom_event_name(ref),
        "resourceType": "events",
        "filtersDeterminer": filters_combinator,
        "filters": [build_filter_entry(f) for f in filters or []],
    }


def build_simple_event_entry(
    event: str | CustomEventRef | FunnelStep,
    *,
    filters: Sequence[Filter] | None = None,
    filters_combinator: FiltersCombinator = "all",
) -> dict[str, Any]:
    """Build one entry of the ``behaviors`` list of a simple behavior.

    Args:
        event: An event name, a custom event reference, or a
            ``FunnelStep``. A step writes its own filters, combinator, and
            label (as ``renamed``); the ``filters`` arguments do not apply
            to it.
        filters: Filters for a name or a custom event.
        filters_combinator: How those filters combine.

    Returns:
        The entry dict: ``type``, ``id``, ``name``, ``filters``, and
        ``filtersDeterminer``, then ``renamed`` for a labeled step.
    """
    if isinstance(event, FunnelStep):
        entry: dict[str, Any] = {
            "type": "event",
            "id": None,
            "name": event.event,
            "filters": [build_filter_entry(f) for f in event.filters or []],
            "filtersDeterminer": event.filters_combinator,
        }
        if event.label is not None:
            entry["renamed"] = event.label
        return entry
    if isinstance(event, CustomEventRef):
        kind, event_id, name = "custom-event", event.id, custom_event_name(event)
    else:
        kind, event_id, name = "event", None, event
    return {
        "type": kind,
        "id": event_id,
        "name": name,
        "filters": [build_filter_entry(f) for f in filters or []],
        "filtersDeterminer": filters_combinator,
    }


def simple_behavior_name(events: Sequence[str | CustomEventRef | FunnelStep]) -> str:
    """Derive the series name of a simple behavior from its events.

    Args:
        events: The events of the behavior.

    Returns:
        The event labels joined with ``" or "``: an event name, the
        ``$custom_event:<id>`` name, or a step label (else the step event).
    """
    labels: list[str] = []
    for event in events:
        if isinstance(event, FunnelStep):
            labels.append(event.label if event.label is not None else event.event)
        elif isinstance(event, CustomEventRef):
            labels.append(custom_event_name(event))
        else:
            labels.append(event)
    return " or ".join(labels)


def build_simple_behavior(
    events: Sequence[str | CustomEventRef | FunnelStep],
    *,
    name: str | None = None,
    filters: Sequence[Filter] | None = None,
    filters_combinator: FiltersCombinator = "all",
) -> dict[str, Any]:
    """Build the ``behavior`` block of a metric over more than one event.

    The query server counts the events as one series (unique users once,
    totals added) only when the behavior has a non-empty name; without one
    it returns one series per event. It ignores filters on the block, so
    filters go on each event entry.

    Args:
        events: The events, in order.
        name: The series name. ``None`` or a blank name derives one with
            :func:`simple_behavior_name`.
        filters: Filters written on every name and custom event entry.
        filters_combinator: How those filters combine.

    Returns:
        The behavior dict with ``type: "simple"``.

    Example:
        ```python
        build_simple_behavior(["Login", "Signup"])["name"]
        # "Login or Signup"
        ```
    """
    return {
        "type": "simple",
        "name": name if name and name.strip() else simple_behavior_name(events),
        "resourceType": "events",
        "filtersDeterminer": "all",
        "filters": [],
        "behaviors": [
            build_simple_event_entry(
                event, filters=filters, filters_combinator=filters_combinator
            )
            for event in events
        ],
    }


def build_metric_behavior(metric: Metric) -> dict[str, Any]:
    """Build the ``behavior`` block of a typed ``Metric``.

    Args:
        metric: The inline metric.

    Returns:
        An event behavior for one event name (the bytes of every release),
        a custom-event behavior for a custom event, and a simple behavior
        for a ``SimpleBehavior`` or a list of more than one event. A list
        of one event gives the behavior of that event alone.
    """
    event = metric.event
    filters = metric.filters
    combinator = metric.filters_combinator
    if isinstance(event, SimpleBehavior):
        return build_simple_behavior(event.events, name=event.name)
    if not isinstance(event, str | CustomEventRef):
        if len(event) > 1:
            return build_simple_behavior(
                event, filters=filters, filters_combinator=combinator
            )
        event = event[0]
    if isinstance(event, CustomEventRef):
        return build_custom_event_behavior(
            event, filters=filters, filters_combinator=combinator
        )
    return build_event_behavior(event, filters=filters, filters_combinator=combinator)


def _event_metric_clause(
    behavior: dict[str, Any],
    measurement: dict[str, Any],
    *,
    hidden: bool,
) -> dict[str, Any]:
    """Assemble an event metric clause and mark it hidden when asked.

    Args:
        behavior: The event behavior block.
        measurement: The insights measurement block.
        hidden: Whether to add ``isHidden: True``. A visible event metric
            has no ``isHidden`` key.

    Returns:
        The metric show clause.
    """
    clause = assemble_metric_clause(behavior, measurement)
    if hidden:
        clause["isHidden"] = True
    return clause


def build_metric_clause(metric: Metric, *, hidden: bool = False) -> dict[str, Any]:
    """Build the show clause of a typed ``Metric``.

    Args:
        metric: The inline metric. Its own math, property, per-user,
            percentile, filters, and segment method apply; query-level
            defaults do not.
        hidden: Whether the query shows the metric only through a formula.
            ``True`` adds ``isHidden: True``; ``False`` writes no
            ``isHidden`` key.

    Returns:
        The metric show clause.

    Example:
        ```python
        build_metric_clause(Metric("Login", math="unique"))
        # {"type": "metric",
        #  "behavior": {"type": "event", "name": "Login", "resourceType": "events",
        #               "filtersDeterminer": "all", "filters": []},
        #  "measurement": {"math": "unique"}}
        ```
    """
    behavior = build_metric_behavior(metric)
    measurement = build_metric_measurement(
        math=metric.math,
        property=metric.property,
        per_user=metric.per_user,
        percentile_value=metric.percentile_value,
        segment_method=metric.segment_method,
    )
    return _event_metric_clause(behavior, measurement, hidden=hidden)


def build_plain_event_clause(
    event: str,
    *,
    math: MathType,
    math_property: str | None,
    per_user: PerUserAggregation | None,
    percentile_value: int | float | None,
    hidden: bool = False,
) -> dict[str, Any]:
    """Build the show clause of a bare event name.

    A bare event name takes the query-level math, property, per-user, and
    percentile settings. It has no filters and no segment method.

    Args:
        event: Mixpanel event name.
        math: Query-level aggregation function.
        math_property: Query-level property for property-based math.
        per_user: Query-level per-user pre-aggregation.
        percentile_value: Query-level percentile value.
        hidden: Whether the query shows the metric only through a formula.
            ``True`` adds ``isHidden: True``.

    Returns:
        The metric show clause.
    """
    behavior = build_event_behavior(event)
    measurement = build_metric_measurement(
        math=math,
        property=math_property,
        per_user=per_user,
        percentile_value=percentile_value,
    )
    return _event_metric_clause(behavior, measurement, hidden=hidden)


def build_cohort_metric_clause(
    metric: CohortMetric,
    *,
    hidden: bool = False,
) -> dict[str, Any]:
    """Build the show clause of a ``CohortMetric`` (cohort size over time).

    The measurement is always ``unique``; query-level math does not apply.
    Unlike an event metric, a cohort metric clause always has an
    ``isHidden`` key.

    Args:
        metric: The cohort metric. A saved cohort id is written as
            ``behavior.id``. An inline definition is written as
            ``behavior.raw_cohort``, with the series name added, because
            the server reads the name from there to build labels.
        hidden: The value of ``isHidden``.

    Returns:
        The metric show clause.
    """
    behavior: dict[str, Any] = {
        "type": "cohort",
        "name": metric.name or "",
        "resourceType": "cohorts",
        "dataGroupId": None,
        "dataset": "$mixpanel",
        "filtersDeterminer": "all",
        "filters": [],
    }
    if isinstance(metric.cohort, int):
        behavior["id"] = metric.cohort
    else:
        raw = _sanitize_raw_cohort(metric.cohort.to_dict())
        # Server-side cohort processing expects `name` in the raw_cohort
        # dict (matching the stored cohort format). Without it, label
        # generation crashes.
        raw["name"] = metric.name or ""
        behavior["raw_cohort"] = raw

    clause = assemble_metric_clause(
        behavior,
        {
            "math": "unique",
            "property": None,
            "perUserAggregation": None,
        },
    )
    clause["isHidden"] = hidden
    return clause


def build_formula_clause(formula: Formula) -> dict[str, Any]:
    """Build the show clause of a ``Formula``.

    Without operands, the letters of the expression name the other show
    clauses of the query by position, so the clause has an empty
    ``referencedMetrics`` list. With operands, ``referencedMetrics`` holds
    one ``{type, behavior, measurement}`` entry per operand, in order, and
    the letters name those entries.

    Args:
        formula: The formula. A non-empty label is written as ``name``.

    Returns:
        The formula show clause.

    Example:
        ```python
        build_formula_clause(Formula("(B / A) * 100", label="Conversion %"))
        # {"type": "formula", "definition": "(B / A) * 100", "measurement": {},
        #  "referencedMetrics": [], "name": "Conversion %"}
        ```
    """
    clause: dict[str, Any] = {
        "type": "formula",
        "definition": formula.expression,
        "measurement": {},
        "referencedMetrics": build_formula_operands(formula),
    }
    if formula.label:
        clause["name"] = formula.label
    return clause


def build_show_section(
    events: Sequence[
        str | Metric | CohortMetric | FunnelMetric | RetentionMetric | MetricRef
    ],
    *,
    math: MathType,
    math_property: str | None,
    per_user: PerUserAggregation | None,
    percentile_value: int | float | None,
    formulas: Sequence[Formula],
) -> list[dict[str, Any]]:
    """Build the ``sections.show`` list of an insights query.

    Metrics come first, in the given order, and formulas follow. When the
    query has a formula without operands, every metric is hidden, so the
    chart shows the formula results only. A formula with its own operands
    names no other metric, so it hides nothing.

    Args:
        events: Bare event names, inline metrics (``Metric``,
            ``CohortMetric``, ``FunnelMetric``, ``RetentionMetric``), and
            ``MetricRef`` references to saved metrics.
        math: Query-level aggregation function for bare event names.
        math_property: Query-level property for bare event names.
        per_user: Query-level per-user pre-aggregation for bare event names.
        percentile_value: Query-level percentile value for bare event names.
        formulas: Formulas to append after the metrics.

    Returns:
        One show clause per event, then one per formula.

    Example:
        ```python
        show = build_show_section(
            ["Signup", Metric("Purchase", math="unique")],
            math="unique",
            math_property=None,
            per_user=None,
            percentile_value=None,
            formulas=[Formula("B / A")],
        )
        # Three clauses: two hidden metrics, then the formula.
        ```
    """
    hidden = any(f.metrics is None for f in formulas)
    show: list[dict[str, Any]] = []
    for item in events:
        if isinstance(item, str):
            show.append(
                build_plain_event_clause(
                    item,
                    math=math,
                    math_property=math_property,
                    per_user=per_user,
                    percentile_value=percentile_value,
                    hidden=hidden,
                )
            )
        elif isinstance(item, MetricRef):
            show.append(build_metric_ref_clause(item, hidden=hidden))
        else:
            show.append(build_inline_metric_clause(item, hidden=hidden))
    show.extend(build_formula_clause(f) for f in formulas)
    return show


# =============================================================================
# Saved-entity references
# =============================================================================


def _thaw(value: object) -> object:
    """Turn a stored override value back into plain JSON-safe objects.

    ``MetricRef`` stores its raw overrides as a read-only tree of
    ``MappingProxyType`` and tuples. The wire form is a plain dict with
    lists.

    Args:
        value: A value from the stored overrides tree.

    Returns:
        A new plain dict for a mapping, a new list for a tuple or list,
        and a deep copy of any other value.
    """
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(child) for child in value]
    return copy.deepcopy(value)


def _merge_overrides(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Deep-merge raw overrides into the typed overrides dict, in place.

    A mapping merges into a dict at the same key. Any other value (a
    scalar, ``None``, or a sequence) replaces the target value. Values are
    copied into plain dicts and lists, so the result never shares objects
    with ``source`` and is JSON-safe.

    Args:
        target: The typed overrides dict. Changed in place.
        source: The raw overrides of a ``MetricRef``.
    """
    for key, value in source.items():
        current = target.get(key)
        if isinstance(value, Mapping) and isinstance(current, dict):
            _merge_overrides(current, value)
        elif isinstance(value, Mapping):
            merged: dict[str, Any] = {}
            _merge_overrides(merged, value)
            target[key] = merged
        else:
            target[key] = _thaw(value)


def build_metric_ref_overrides(ref: MetricRef) -> dict[str, Any]:
    """Build the ``overrides`` dict of a saved-metric reference.

    Each typed field of the reference goes to its wire path in the show
    clause: ``label`` to ``name``, ``funnel_order`` to
    ``behavior.funnelOrder``, ``hidden`` to ``isHidden``, and the others to
    ``measurement`` keys. The user-facing ``"percentile"`` math is written
    as ``"custom_percentile"``, and a property has the same shape as the
    property of an inline ``Metric``. The raw ``ref.overrides`` mapping
    merges last, so a raw value wins over a typed field. Typed fields never
    write a list.

    Args:
        ref: The saved-metric reference.

    Returns:
        The overrides dict. Empty when the reference changes nothing. Keys,
        in order: ``name``, ``behavior``, ``measurement``, ``isHidden``,
        then any other raw keys.

    Example:
        ```python
        build_metric_ref_overrides(MetricRef(42, math="unique", label="Buyers"))
        # {"name": "Buyers", "measurement": {"math": "unique"}}
        ```
    """
    overrides: dict[str, Any] = {}
    if ref.label is not None:
        overrides["name"] = ref.label
    if ref.funnel_order is not None:
        overrides["behavior"] = {"funnelOrder": ref.funnel_order}

    measurement: dict[str, Any] = {}
    if ref.math is not None:
        measurement["math"] = (
            "custom_percentile" if ref.math == "percentile" else ref.math
        )
    if ref.property is not None:
        measurement["property"] = build_measurement_property(ref.property)
    if ref.per_user is not None:
        measurement["perUserAggregation"] = ref.per_user
    if ref.percentile_value is not None:
        measurement["percentile"] = ref.percentile_value
    if ref.segment_method is not None:
        measurement["segmentMethod"] = ref.segment_method
    if ref.step_index is not None:
        measurement["stepIndex"] = ref.step_index
    if ref.bucket_index is not None:
        measurement["retentionBucketIndex"] = ref.bucket_index
    if measurement:
        overrides["measurement"] = measurement

    if ref.hidden is not None:
        overrides["isHidden"] = ref.hidden
    if ref.overrides:
        _merge_overrides(overrides, ref.overrides)
    return overrides


def build_metric_ref_clause(ref: MetricRef, *, hidden: bool = False) -> dict[str, Any]:
    """Build the show clause of a saved-metric reference.

    The server finds the saved metric by id, replaces the clause with the
    saved definition, and then deep-merges ``overrides`` into it.

    Args:
        ref: The saved-metric reference.
        hidden: Whether the query shows the metric only through a formula.
            ``True`` adds a top-level ``isHidden: True``. A ``hidden`` value
            set on the reference goes into ``overrides`` and wins.

    Returns:
        The show clause. Keys, in order: ``type``, ``id``, then
        ``isHidden`` and ``overrides`` when set.

    Example:
        ```python
        build_metric_ref_clause(MetricRef(42, segment_method="first"))
        # {"type": "metric", "id": 42,
        #  "overrides": {"measurement": {"segmentMethod": "first"}}}
        ```
    """
    clause: dict[str, Any] = {"type": ref.type, "id": ref.id}
    if hidden:
        clause["isHidden"] = True
    overrides = build_metric_ref_overrides(ref)
    if overrides:
        clause["overrides"] = overrides
    return clause


def build_operand_ref_clause(ref: MetricRef) -> dict[str, Any]:
    """Build a formula operand that refers to a saved metric.

    Use it for each ``MetricRef`` entry of a formula's
    ``referencedMetrics``. The clause always holds ``type``, because the
    server reads the type of an operand directly and fails when it is
    absent (it corrects the type of a top-level clause only).

    Args:
        ref: The saved-metric reference. It must change nothing: no typed
            field, no label, no hidden flag, and no raw overrides.

    Returns:
        ``{"type": ref.type, "id": ref.id}``.

    Raises:
        ParamValidationError: ``MR2_OPERAND_OVERRIDE`` when the reference
            sets any override. The server ignores overrides on a formula
            operand, so the query would run the saved definition without
            the change.

    Example:
        ```python
        build_operand_ref_clause(MetricRef(104700))
        # {"type": "metric", "id": 104700}
        ```
    """
    if build_metric_ref_overrides(ref):
        raise ParamValidationError(
            f"MetricRef({ref.id}) is a formula operand and cannot carry "
            "overrides: the server ignores overrides on formula operands, so "
            "the formula would use the saved definition unchanged. Remove "
            "the overrides, or use an inline Metric as the operand.",
            code="MR2_OPERAND_OVERRIDE",
        )
    return {"type": ref.type, "id": ref.id}


def build_behavior_ref(ref: BehaviorRef) -> dict[str, Any]:
    """Build a behavior block that refers to a saved behavior.

    The block has no ``behaviors`` key, so the server replaces it with the
    saved behavior at query time. A block with both an id and inline
    ``behaviors`` keeps the inline copy instead.

    Args:
        ref: The saved-behavior reference.

    Returns:
        ``{"type": ref.type, "id": ref.id}``.
    """
    return {"type": ref.type, "id": ref.id}


# =============================================================================
# Funnel metrics
# =============================================================================


def build_funnel_step_behavior(
    step: FunnelStep, *, order: FunnelOrder
) -> dict[str, Any]:
    """Build one entry of the ``behaviors`` list of a funnel behavior.

    Args:
        step: The funnel step.
        order: The funnel-level step order. A step order override
            replaces it.

    Returns:
        The step behavior dict. A step label adds ``renamed`` at the end.
    """
    behavior_entry: dict[str, Any] = {
        "type": "event",
        "id": None,
        "name": step.event,
        "filters": [],
        "filtersDeterminer": step.filters_combinator,
        "funnelOrder": order,
    }
    if step.filters:
        behavior_entry["filters"] = [build_filter_entry(f) for f in step.filters]
    if step.label is not None:
        behavior_entry["renamed"] = step.label
    if step.order is not None:
        behavior_entry["funnelOrder"] = step.order
    return behavior_entry


def build_funnel_behavior(
    *,
    steps: Sequence[FunnelStep],
    conversion_window: int,
    conversion_window_unit: ConversionWindowUnit,
    order: FunnelOrder,
    exclusions: Sequence[Exclusion],
    holding_constant: Sequence[HoldingConstant],
    reentry_mode: FunnelReentryMode | None = None,
) -> dict[str, Any]:
    """Build the ``behavior`` block of a funnel metric.

    Args:
        steps: The funnel steps, in order.
        conversion_window: Conversion window size.
        conversion_window_unit: Conversion window time unit.
        order: Funnel step order (``"loose"`` or ``"any"``).
        exclusions: Events to exclude between steps. ``Exclusion`` step
            numbers are 0-based; the bookmark format is 1-based, and an
            open end runs to the last step.
        holding_constant: Properties to hold constant across steps.
            Written as ``aggregateBy``.
        reentry_mode: How users enter the funnel again after they convert.
            ``None`` leaves ``funnelReentryMode`` out.

    Returns:
        The funnel behavior dict with ``type: "funnel"``.

    Example:
        ```python
        behavior = build_funnel_behavior(
            steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
            conversion_window=14,
            conversion_window_unit="day",
            order="loose",
            exclusions=[Exclusion("Logout")],
            holding_constant=[],
        )
        # behavior["exclusions"] == [{"event": "Logout", "steps": {"from": 1, "to": 2}}]
        ```
    """
    behaviors = [build_funnel_step_behavior(step, order=order) for step in steps]

    exclusions_list: list[dict[str, Any]] = []
    for ex in exclusions:
        api_from = ex.from_step + 1
        api_to = (ex.to_step + 1) if ex.to_step is not None else len(steps)
        exclusions_list.append(
            {
                "event": ex.event,
                "steps": {
                    "from": api_from,
                    "to": api_to,
                },
            }
        )

    aggregate_by: list[dict[str, Any]] = [
        {"value": hc.property, "resourceType": hc.resource_type}
        for hc in holding_constant
    ]

    behavior: dict[str, Any] = {
        "type": "funnel",
        "resourceType": "events",
        "behaviors": behaviors,
        "conversionWindowDuration": conversion_window,
        "conversionWindowUnit": conversion_window_unit,
        "funnelOrder": order,
        "exclusions": exclusions_list,
        "aggregateBy": aggregate_by,
        "filter": [],
    }
    if reentry_mode is not None:
        behavior["funnelReentryMode"] = reentry_mode
    return behavior


def build_funnel_measurement(
    *,
    math: FunnelMathType,
    math_property: str | None,
    step_index: int | None = None,
) -> dict[str, Any]:
    """Build the ``measurement`` block of a funnel metric.

    Args:
        math: Funnel aggregation function.
        math_property: Numeric event property for property math. ``None``
            or an empty string writes a null property.
        step_index: The zero-based step to measure. ``None`` (the whole
            funnel) writes a null ``stepIndex``.

    Returns:
        The measurement dict with ``math``, ``property``, and ``stepIndex``.
    """
    return {
        "math": math,
        "property": (
            {
                "name": math_property,
                "type": "number",
                "resourceType": "events",
            }
            if math_property
            else None
        ),
        "stepIndex": step_index,
    }


# =============================================================================
# Retention metrics
# =============================================================================


def build_retention_event_behavior(event: RetentionEvent) -> dict[str, Any]:
    """Build one entry of the ``behaviors`` list of a retention behavior.

    Args:
        event: The born event or the return event.

    Returns:
        The event behavior dict.
    """
    behavior_entry: dict[str, Any] = {
        "type": "event",
        "id": None,
        "name": event.event,
        "filters": [],
        "filtersDeterminer": event.filters_combinator,
    }
    if event.filters:
        behavior_entry["filters"] = [build_filter_entry(f) for f in event.filters]
    return behavior_entry


def build_retention_behavior(
    *,
    born_event: RetentionEvent,
    return_event: RetentionEvent,
    retention_unit: TimeUnit,
    alignment: RetentionAlignment,
    bucket_sizes: Sequence[int] | None,
    unbounded_mode: RetentionUnboundedMode | None = None,
) -> dict[str, Any]:
    """Build the ``behavior`` block of a retention metric.

    Args:
        born_event: The event that puts a user in a cohort.
        return_event: The event that counts as a return.
        retention_unit: Retention period unit.
        alignment: Retention alignment mode.
        bucket_sizes: Custom bucket sizes. ``None`` or an empty list gives
            an empty list.
        unbounded_mode: How retention counts in unbounded periods. ``None``
            leaves ``retentionUnboundedMode`` out.

    Returns:
        The retention behavior dict with ``type: "retention"`` and exactly
        two event behaviors.
    """
    behavior: dict[str, Any] = {
        "type": "retention",
        "resourceType": "events",
        "behaviors": [
            build_retention_event_behavior(born_event),
            build_retention_event_behavior(return_event),
        ],
        "retentionUnit": retention_unit,
        "retentionAlignmentType": alignment,
        "retentionCustomBucketSizes": list(bucket_sizes) if bucket_sizes else [],
        "filter": [],
    }
    if unbounded_mode is not None:
        behavior["retentionUnboundedMode"] = unbounded_mode
    return behavior


def build_retention_measurement(
    *,
    math: RetentionMathType,
    cumulative: bool = False,
    bucket_index: int | None = None,
    property: PropertySpec | None = None,
) -> dict[str, Any]:
    """Build the ``measurement`` block of a retention metric.

    Args:
        math: Retention aggregation function.
        cumulative: Whether to count retention cumulatively. ``True`` adds
            ``retentionCumulative: True``; ``False`` leaves the key out.
        bucket_index: The bucket that a line or bar chart trends. ``None``
            leaves ``retentionBucketIndex`` out.
        property: The property to aggregate. ``None`` leaves ``property``
            out.

    Returns:
        The measurement dict. Keys, in order: ``math``, then ``property``,
        ``retentionBucketIndex``, and ``retentionCumulative`` when set.
    """
    measurement: dict[str, Any] = {"math": math}
    if property is not None:
        measurement["property"] = build_measurement_property(property)
    if bucket_index is not None:
        measurement["retentionBucketIndex"] = bucket_index
    if cumulative:
        measurement["retentionCumulative"] = True
    return measurement


# =============================================================================
# Funnel and retention metrics in any query, and saved definitions
# =============================================================================


def build_funnel_metric_behavior(behavior: FunnelBehavior) -> dict[str, Any]:
    """Build the ``behavior`` block of a ``FunnelBehavior``.

    Plain names become ``FunnelStep``, ``Exclusion``, and
    ``HoldingConstant`` objects first, as in ``query_funnel``, so the
    block is the one ``query_funnel`` writes for the same arguments.

    Args:
        behavior: The funnel behavior.

    Returns:
        The funnel behavior dict.
    """
    steps = [FunnelStep(s) if isinstance(s, str) else s for s in behavior.steps]
    exclusions = [
        Exclusion(e) if isinstance(e, str) else e for e in behavior.exclusions or []
    ]
    held = behavior.holding_constant
    held_values = [held] if isinstance(held, str | HoldingConstant) else held or []
    holding_constant = [
        HoldingConstant(h) if isinstance(h, str) else h for h in held_values
    ]
    return build_funnel_behavior(
        steps=steps,
        conversion_window=behavior.conversion_window,
        conversion_window_unit=behavior.conversion_window_unit,
        order=behavior.order,
        exclusions=exclusions,
        holding_constant=holding_constant,
        reentry_mode=behavior.reentry_mode,
    )


def build_funnel_metric_measurement(metric: FunnelMetric) -> dict[str, Any]:
    """Build the ``measurement`` block of a ``FunnelMetric``.

    Args:
        metric: The funnel metric.

    Returns:
        The measurement dict. A property name is written as
        ``query_funnel`` writes ``math_property``; a custom property is
        written as on an insights metric.
    """
    prop = metric.property
    if prop is None or isinstance(prop, str):
        return build_funnel_measurement(
            math=metric.math, math_property=prop, step_index=metric.step_index
        )
    return {
        "math": metric.math,
        "property": build_measurement_property(prop),
        "stepIndex": metric.step_index,
    }


def build_funnel_metric_clause(
    metric: FunnelMetric, *, hidden: bool = False
) -> dict[str, Any]:
    """Build the show clause of a ``FunnelMetric``.

    Args:
        metric: The funnel metric.
        hidden: Whether the query shows the metric only through a formula.
            ``True`` adds ``isHidden: True``.

    Returns:
        The metric show clause. A label is written as the clause ``name``,
        which the query server uses as the series label.
    """
    clause = _event_metric_clause(
        build_funnel_metric_behavior(metric.behavior),
        build_funnel_metric_measurement(metric),
        hidden=hidden,
    )
    if metric.label:
        clause["name"] = metric.label
    return clause


def build_retention_metric_behavior(behavior: RetentionBehavior) -> dict[str, Any]:
    """Build the ``behavior`` block of a ``RetentionBehavior``.

    Args:
        behavior: The retention behavior. Plain names become
            ``RetentionEvent`` objects first, as in ``query_retention``.

    Returns:
        The retention behavior dict.
    """
    born = behavior.born_event
    back = behavior.return_event
    return build_retention_behavior(
        born_event=RetentionEvent(born) if isinstance(born, str) else born,
        return_event=RetentionEvent(back) if isinstance(back, str) else back,
        retention_unit=behavior.retention_unit,
        alignment=behavior.alignment,
        bucket_sizes=behavior.bucket_sizes,
        unbounded_mode=behavior.unbounded_mode,
    )


def build_retention_metric_clause(
    metric: RetentionMetric, *, hidden: bool = False
) -> dict[str, Any]:
    """Build the show clause of a ``RetentionMetric``.

    Args:
        metric: The retention metric.
        hidden: Whether the query shows the metric only through a formula.
            ``True`` adds ``isHidden: True``.

    Returns:
        The metric show clause. A label is written as the clause ``name``,
        which the query server uses as the series label.
    """
    measurement = build_retention_measurement(
        math=metric.math,
        cumulative=metric.retention_cumulative,
        bucket_index=metric.bucket_index,
        property=metric.property,
    )
    clause = _event_metric_clause(
        build_retention_metric_behavior(metric.behavior), measurement, hidden=hidden
    )
    if metric.label:
        clause["name"] = metric.label
    return clause


def build_inline_metric_clause(
    metric: FormulaOperand, *, hidden: bool = False
) -> dict[str, Any]:
    """Build the show clause of any inline metric except a formula.

    Args:
        metric: A ``Metric``, ``CohortMetric``, ``FunnelMetric``, or
            ``RetentionMetric``.
        hidden: Whether the query shows the metric only through a formula.

    Returns:
        The metric show clause from the builder of the metric's kind.
    """
    if isinstance(metric, CohortMetric):
        return build_cohort_metric_clause(metric, hidden=hidden)
    if isinstance(metric, FunnelMetric):
        return build_funnel_metric_clause(metric, hidden=hidden)
    if isinstance(metric, RetentionMetric):
        return build_retention_metric_clause(metric, hidden=hidden)
    return build_metric_clause(metric, hidden=hidden)


def build_metric_definition(metric: FormulaOperand) -> dict[str, Any]:
    """Build the saved definition of an inline metric.

    A saved behavior metric stores ``{behavior, measurement}``. Both blocks
    come from the show-clause builder, so a saved metric queries the same
    way as the inline metric it came from.

    Args:
        metric: A ``Metric``, ``CohortMetric``, ``FunnelMetric``, or
            ``RetentionMetric``.

    Returns:
        ``{"behavior": ..., "measurement": ...}``.

    Example:
        ```python
        build_metric_definition(Metric("Login", math="unique"))
        # {"behavior": {"type": "event", "name": "Login", ...},
        #  "measurement": {"math": "unique"}}
        ```
    """
    clause = build_inline_metric_clause(metric)
    return {"behavior": clause["behavior"], "measurement": clause["measurement"]}


def build_behavior_definition(
    behavior: SimpleBehavior | FunnelBehavior | RetentionBehavior,
) -> dict[str, Any]:
    """Build the saved definition of a behavior value.

    A saved behavior stores ``{behavior}``. The block comes from the same
    builders as the behavior of a metric clause, without ``name``: the
    server refuses a name inside a saved behavior definition, and the
    saved behavior's own name labels it.

    Args:
        behavior: A ``SimpleBehavior``, ``FunnelBehavior``, or
            ``RetentionBehavior``. The name of a ``SimpleBehavior`` is a
            query-time series label and is not written.

    Returns:
        ``{"behavior": ...}``.

    Example:
        ```python
        build_behavior_definition(FunnelBehavior(["Signup", "Purchase"]))
        # {"behavior": {"type": "funnel", "resourceType": "events", ...}}
        ```
    """
    if isinstance(behavior, FunnelBehavior):
        block = build_funnel_metric_behavior(behavior)
    elif isinstance(behavior, RetentionBehavior):
        block = build_retention_metric_behavior(behavior)
    else:
        block = build_simple_behavior(behavior.events)
        del block["name"]
    return {"behavior": block}


def build_formula_operands(formula: Formula) -> list[dict[str, Any]]:
    """Build the ``referencedMetrics`` list of a formula.

    Args:
        formula: The formula.

    Returns:
        One ``{"type": "metric", "behavior": ..., "measurement": ...}``
        entry per operand, in order. A formula without operands gives an
        empty list.
    """
    return [
        {"type": "metric", **build_metric_definition(operand)}
        for operand in formula.metrics or []
    ]


def build_formula_definition(formula: Formula) -> dict[str, Any]:
    """Build the saved definition of a formula with its own operands.

    Args:
        formula: A formula with ``metrics``. The label is not part of the
            definition; it is the saved metric's name.

    Returns:
        ``{"formula": {"definition": ..., "referencedMetrics": [...]}}``,
        with the operands of :func:`build_formula_operands`.

    Raises:
        ValueError: If the formula has no operands. A saved formula must
            hold its own operands; the create layer refuses the other form
            first.
    """
    if formula.metrics is None:
        raise ValueError(
            "A saved formula needs its own operands: pass Formula(..., metrics=[...])"
        )
    return {
        "formula": {
            "definition": formula.expression,
            "referencedMetrics": build_formula_operands(formula),
        }
    }
