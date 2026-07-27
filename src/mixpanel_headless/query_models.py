"""Pydantic input models for Workspace query methods.

Each model mirrors the signature of a ``Workspace.build_*_params()`` method,
providing a single validated object for schema generation and type-safe input.

These query models — and every building block they reference (``Filter``,
``Metric``, ``GroupBy``, cohort types, etc.) — MUST remain self-sufficient:
they are designed to be imported independently by *other* repositories (e.g.
an MCP "Run-Query" tool that generates its request schema from
``model_json_schema()`` instead of hand-maintaining AI types). That means:

- No opaque holes in the generated JSON schema (no ``Any``, no bare ``dict``,
  no ``additionalProperties: true``, no leaked private/underscore fields).
- No dependency on runtime state, config, or network — construction and
  schema generation work standalone from a fresh import.
- Every field carries a description and a closed type so the schema alone
  fully specifies every valid input.
- Integer and boolean fields validate in **strict mode**
  (``Field(strict=True)`` / ``StrictInt``) — on the query models AND on
  every nested building block (``Metric``, ``GroupBy``, ``Exclusion``,
  ``FrequencyFilter``, ``FrequencyBreakdown``, ``CohortMetric``,
  ``CohortBreakdown``, ``FlowStep``): pydantic's lax coercion would
  otherwise normalize ``True``/``1.0``/``"2"`` into integers *before*
  the Workspace validators run, silently building a different query
  than the caller wrote (e.g. ``cohort: "5"`` querying saved cohort 5
  after a typo). Strict fields reject those inputs with the same
  structured ``BookmarkValidationError`` the builders raise.
- Numeric bounds are annotated per union alternative (e.g.
  ``Annotated[int, Field(strict=True, ge=0, le=100)]``) so they render
  as standard JSON-Schema ``minimum``/``maximum`` keywords instead of
  pydantic's literal ``ge``/``le`` keys, which external validators
  would silently ignore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StrictInt,
    ValidationError,
    model_validator,
)

from mixpanel_headless._internal.bookmark_enums import (
    _MAX_FLOW_CARDINALITY,
    _MAX_FLOW_STEPS_DIRECTION,
    _MAX_FUNNEL_STEPS,
    _MAX_HOLDING_CONSTANT,
    _MAX_LAST_DAYS,
    _MAX_RETENTION_BUCKETS,
    _MAX_ROLLING,
)
from mixpanel_headless._internal.bookmark_schema import (
    translate_pydantic_exception,
)
from mixpanel_headless._internal.pydantic_utils import discriminated_union
from mixpanel_headless._internal.validation import (
    v9_to_requires_from,
    v26_percentile_requires_value,
)
from mixpanel_headless._literal_types import (
    ConversionWindowUnit,
    FlowChartType,
    FlowConversionWindowUnit,
    FlowCountType,
    FunnelMathType,
    FunnelMode,
    FunnelOrder,
    FunnelReentryMode,
    InsightsMode,
    MathType,
    PerUserAggregation,
    QueryTimeUnit,
    RetentionAlignment,
    RetentionMathType,
    RetentionMode,
    RetentionUnboundedMode,
    TimeUnit,
)
from mixpanel_headless.exceptions import (
    BookmarkValidationError,
)
from mixpanel_headless.exceptions import (
    ValidationError as InternalValidationError,
)
from mixpanel_headless.types import (
    CohortBreakdown,
    CohortMetric,
    Exclusion,
    Filter,
    FlowStep,
    Formula,
    FrequencyBreakdown,
    FrequencyFilter,
    FunnelStep,
    GroupBy,
    HoldingConstant,
    Metric,
    RetentionEvent,
    TimeComparison,
    _DateStrSchema,
    _PercentileValue,
    _PositiveStrictIntSchema,
    _str_or,
    _union_discriminator,
)

# =============================================================================
# Discriminated item types for the query models' union list fields
#
# Each ambiguous union is a callable-Discriminator union, so pydantic validates
# only the alternative a value structurally matches — one located error on a bad
# entry (or the custom_error_message on an unroutable one), never every
# alternative's shape noise. Routing lives in types._union_discriminator / _str_or.
# =============================================================================

# Runtime tagged union; plain union for mypy — see ``discriminated_union``.
if TYPE_CHECKING:
    _EventItem = str | Metric | CohortMetric | Formula
else:
    _EventItem = discriminated_union(
        [str, Metric, CohortMetric, Formula],
        _union_discriminator(
            (
                (Formula, "expression"),
                (CohortMetric, "cohort"),
                (Metric, "event"),
            )
        ),
        error_type="invalid_event_item",
        message=(
            "each event must be an event-name string or an object with "
            "'event' (a metric), 'cohort' (a cohort metric), or 'expression' "
            "(a formula)"
        ),
    )
"""One ``events`` entry: string · ``Metric`` · ``CohortMetric`` · ``Formula``."""

if TYPE_CHECKING:
    _InsightsBreakdownItem = str | GroupBy | CohortBreakdown | FrequencyBreakdown
else:
    _InsightsBreakdownItem = discriminated_union(
        [str, GroupBy, CohortBreakdown, FrequencyBreakdown],
        _union_discriminator(
            (
                (CohortBreakdown, "cohort"),
                (FrequencyBreakdown, "event"),
                (GroupBy, "property"),
            )
        ),
        error_type="invalid_group_by_item",
        message=(
            "each group_by must be a property-name string or an object with "
            "'property' (a property breakdown), 'cohort' (a cohort breakdown), "
            "or 'event' (a frequency breakdown)"
        ),
    )
"""One insights ``group_by`` entry (adds the frequency-breakdown alternative)."""

if TYPE_CHECKING:
    _BreakdownItem = str | GroupBy | CohortBreakdown
else:
    _BreakdownItem = discriminated_union(
        [str, GroupBy, CohortBreakdown],
        _union_discriminator(
            (
                (CohortBreakdown, "cohort"),
                (GroupBy, "property"),
            )
        ),
        error_type="invalid_group_by_item",
        message=(
            "each group_by must be a property-name string or an object with "
            "'property' (a property breakdown) or 'cohort' (a cohort breakdown)"
        ),
    )
"""One funnel / retention ``group_by`` entry (no frequency alternative)."""

if TYPE_CHECKING:
    _WhereItem = Filter | FrequencyFilter
else:
    _WhereItem = discriminated_union(
        [Filter, FrequencyFilter],
        _union_discriminator(
            (
                (FrequencyFilter, "event"),
                (Filter, "property"),
            ),
            allow_str=False,
        ),
        error_type="invalid_where_item",
        message=(
            "each where entry must be an object with 'property' (a property "
            "filter) or 'event' (a frequency filter)"
        ),
    )
"""One insights ``where`` entry: ``Filter`` · ``FrequencyFilter`` (no string alternative)."""

if TYPE_CHECKING:
    _StepItem = str | FunnelStep
else:
    _StepItem = discriminated_union(
        [str, FunnelStep],
        _str_or(FunnelStep),
        error_type="invalid_funnel_step",
        message="each step must be an event-name string or a FunnelStep object",
    )
"""One funnel ``steps`` entry: string · ``FunnelStep``."""

if TYPE_CHECKING:
    _ExclusionItem = str | Exclusion
else:
    _ExclusionItem = discriminated_union(
        [str, Exclusion],
        _str_or(Exclusion),
        error_type="invalid_exclusion",
        message="each exclusion must be an event-name string or an Exclusion object",
    )
"""One funnel ``exclusions`` entry: string · ``Exclusion``."""

if TYPE_CHECKING:
    _HoldingConstantItem = str | HoldingConstant
else:
    _HoldingConstantItem = discriminated_union(
        [str, HoldingConstant],
        _str_or(HoldingConstant),
        error_type="invalid_holding_constant",
        message=(
            "each holding_constant must be a property-name string or a "
            "HoldingConstant object"
        ),
    )
"""One funnel ``holding_constant`` entry: string · ``HoldingConstant``."""

if TYPE_CHECKING:
    _RetentionEventItem = str | RetentionEvent
else:
    _RetentionEventItem = discriminated_union(
        [str, RetentionEvent],
        _str_or(RetentionEvent),
        error_type="invalid_retention_event",
        message="must be an event-name string or a RetentionEvent object",
    )
"""A retention ``born_event`` / ``return_event``: string · ``RetentionEvent``."""

if TYPE_CHECKING:
    _SegmentItem = str | GroupBy
else:
    _SegmentItem = discriminated_union(
        [str, GroupBy],
        _str_or(GroupBy),
        error_type="invalid_segment",
        message="each segment must be a property-name string or a GroupBy object",
    )
"""One flow ``segments`` entry: string · ``GroupBy``."""


def _flow_event_discriminator(v: Any) -> str:
    """Route the flow ``event`` union: string → "str", list/tuple → the list, else → one FlowStep.

    Total (never None): a non-list, non-string value goes to the single
    ``FlowStep`` alternative so a bad dict shows that model's own field errors.

    Args:
        v: The ``event`` value (str, FlowStep, dict, or list).

    Returns:
        ``"str"``, ``"FlowStepList"``, or ``"FlowStep"`` — unmarked; the tag
        prefix is applied by ``discriminated_union``.
    """
    if isinstance(v, str):
        return "str"
    if isinstance(v, (list, tuple)):
        return "FlowStepList"
    return "FlowStep"


if TYPE_CHECKING:
    _FlowStepItem = str | FlowStep
else:
    _FlowStepItem = discriminated_union(
        [str, FlowStep],
        _str_or(FlowStep),
        error_type="invalid_flow_step",
        message="each flow step must be an event-name string or a FlowStep object",
    )
"""One item inside a flow ``event`` list: string · ``FlowStep``."""

if TYPE_CHECKING:
    _FlowEvent = str | FlowStep | list[_FlowStepItem]
else:
    _FlowEvent = discriminated_union(
        {"str": str, "FlowStep": FlowStep, "FlowStepList": list[_FlowStepItem]},
        _flow_event_discriminator,
        error_type="invalid_flow_event",
        message=(
            "event must be an event-name string, a FlowStep object, or a list "
            "of event-name strings / FlowStep objects"
        ),
    )
"""The flow ``event`` field: string · ``FlowStep`` · list of either."""


class _BaseQuery(BaseModel):
    """Shared base for query models.

    Provides frozen config with ``extra="forbid"``, and a wrap
    validator that converts ``pydantic.ValidationError`` (from
    ``Field`` constraints like ``ge``, ``min_length``) into
    ``BookmarkValidationError`` so callers get a single error type.
    Subclasses add cross-field checks in ``_get_cross_field_errors``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Schema-only date pattern (``_DateStrSchema``) — runtime date
    # validation is handled by ``validate_time_args`` (V8 checks) at
    # build time, which produces domain-specific error messages
    # (``"from_date must be YYYY-MM-DD format"``) a bare pydantic
    # ``pattern`` error would replace.
    from_date: _DateStrSchema | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
        examples=["2025-01-01"],
    )
    to_date: _DateStrSchema | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
        examples=["2025-01-31"],
    )
    # ``maximum`` is a schema-only mirror of the build-time V20 cap;
    # runtime enforcement stays in ``validate_time_args`` so callers
    # keep its curated message.
    last: int = Field(
        30,
        ge=1,
        strict=True,
        json_schema_extra={"maximum": _MAX_LAST_DAYS},
        description=(
            f"Relative time range in days. Default: 30. "
            f"Maximum: {_MAX_LAST_DAYS} (~10 years)."
        ),
        examples=[7, 30, 90],
    )
    data_group_id: StrictInt | None = Field(
        None,
        description="Data group ID for group-level analytics.",
    )

    def _get_cross_field_errors(self) -> list[InternalValidationError]:
        """Return cross-field errors shared by all query models.

        Rejects ``to_date`` without ``from_date`` via the shared V9
        predicate (``v9_to_requires_from``) — every builder ignores a
        lone ``to_date``, silently falling back to ``last``. A lone
        ``from_date`` is allowed because every builder fills today's
        date for the missing ``to_date``.

        Subclasses extend via ``super()._get_cross_field_errors()``.

        Returns:
            List of validation errors (empty when the model is valid).
        """
        return v9_to_requires_from(self.from_date, self.to_date)

    @model_validator(mode="wrap")
    @classmethod
    def _wrap_validation(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler[_BaseQuery],
    ) -> _BaseQuery:
        """Convert pydantic validation failures to ``BookmarkValidationError``.

        Routes pydantic errors through the shared translator
        (``translate_pydantic_exception``) so model-construction errors
        carry the same path grammar (``where[0].bogus``) and stable
        ``B*``/``S*`` codes as every other producer of
        ``BookmarkValidationError`` — union member class names and raw
        pydantic type strings never reach callers. Cross-field rules
        from ``_get_cross_field_errors()`` are applied after field
        validation succeeds.

        Args:
            data: The raw input being validated (dict, keyword dict, or
                an existing instance, per pydantic wrap-validator rules).
            handler: Pydantic's inner validation callable; invoking it
                runs normal field validation for the model.

        Returns:
            The validated model instance.

        Raises:
            BookmarkValidationError: If field validation fails (with the
                translated pydantic errors) or any cross-field rule
                fails (with that rule's structured error).
        """
        try:
            instance = handler(data)
        except ValidationError as exc:
            raise BookmarkValidationError(translate_pydantic_exception(exc)) from exc
        cross = instance._get_cross_field_errors()
        if cross:
            raise BookmarkValidationError(cross)
        return instance


class _TimeComparableQuery(_BaseQuery):
    """Base for query models that support period-over-period comparison.

    ``FlowQuery`` extends ``_BaseQuery`` directly — the flows endpoint
    rejects time comparison (``FL_TIME_COMPARISON_NOT_SUPPORTED``), so
    its schema must not advertise the field.
    """

    time_comparison: TimeComparison | None = Field(
        None,
        description="Period-over-period comparison.",
    )


class InsightsQuery(_TimeComparableQuery):
    """Input model for an insights query.

    Bundles all parameters accepted by ``Workspace.build_params()`` and
    ``Workspace.query()`` into a single validated object.  Useful as a
    JSON-schema source for MCP tools and other schema-driven consumers.

    Note:
        Frozen but not hashable — list fields prevent hashing despite
        ``frozen=True``. Use ``model_dump()`` for dict keys if needed.

    Example (typed):
        ```python
        from mixpanel_headless import InsightsQuery, Metric, Filter

        q = InsightsQuery(
            events=[Metric("Login", math="unique")],
            where=[Filter.equals("country", "US")],
            last=7,
        )
        params = ws.build_params(q)
        result = ws.query(q)
        ```

    Example (dicts):
        ```python
        from mixpanel_headless import InsightsQuery

        q = InsightsQuery.model_validate({
            "events": [{"event": "Login", "math": "unique"}],
            "where": [{"property": "country", "operator": "equals", "value": "US"}],
            "last": 7,
        })
        ```
    """

    events: list[_EventItem] = Field(
        ...,
        min_length=1,
        description="Events to query. Each is an event name string, Metric, CohortMetric, or Formula.",
    )
    unit: QueryTimeUnit = Field(
        "day",
        description="Time granularity: hour, day, week, month, quarter.",
    )
    math: MathType = Field(
        "total",
        description="Aggregation function applied to bare-string events.",
    )
    math_property: str | None = Field(
        None,
        description="Property name for property-based math (applies to bare-string events).",
    )
    per_user: PerUserAggregation | None = Field(
        None,
        description="Per-user pre-aggregation (applies to bare-string events).",
    )
    percentile_value: _PercentileValue | None = Field(
        None,
        description="Custom percentile value (e.g. 95). Used when math='percentile'.",
    )
    group_by: list[_InsightsBreakdownItem] | None = Field(
        None,
        description="Break down results by property values, cohort, or event frequency.",
    )
    where: list[_WhereItem] | None = Field(
        None,
        description="Filter results by property conditions.",
    )
    formula: str | None = Field(
        None,
        description="Formula expression referencing events by position letter (A, B, C...).",
    )
    formula_label: str | None = Field(
        None,
        description="Display label for the formula result.",
    )
    # ``maximum`` is a schema-only mirror of the build-time V23 cap;
    # runtime enforcement stays in ``validate_query_args`` so callers
    # keep its curated message.
    rolling: (
        Annotated[StrictInt, Field(gt=0, json_schema_extra={"maximum": _MAX_ROLLING})]
        | None
    ) = Field(
        None,
        description=f"Rolling window size in periods. Maximum: {_MAX_ROLLING}.",
    )
    cumulative: bool = Field(
        False,
        strict=True,
        description="Enable cumulative analysis mode.",
    )
    mode: InsightsMode = Field(
        "timeseries",
        description="Result shape: timeseries (per-period), total (single aggregate), table.",
    )

    def _get_cross_field_errors(self) -> list[InternalValidationError]:
        """Validate cross-field constraints for insights queries.

        Extends the base checks with the shared V26 predicate
        (``v26_percentile_requires_value``): ``percentile_value`` is
        required when ``math="percentile"`` and at least one event is a
        bare string (Metric objects carry their own math).

        Returns:
            List of validation errors (empty when the model is valid).
        """
        errors = super()._get_cross_field_errors()
        errors.extend(
            v26_percentile_requires_value(self.events, self.math, self.percentile_value)
        )
        return errors


class FunnelQuery(_TimeComparableQuery):
    """Input model for a funnel query.

    Bundles all parameters accepted by ``Workspace.build_funnel_params()``
    and ``Workspace.query_funnel()`` into a single validated object.

    Example (typed):
        ```python
        from mixpanel_headless import FunnelQuery, FunnelStep, Filter

        q = FunnelQuery(
            steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
            conversion_window=7,
            where=[Filter.equals("country", "US")],
        )
        params = ws.build_funnel_params(q)
        result = ws.query_funnel(q)
        ```

    Example (dicts):
        ```python
        from mixpanel_headless import FunnelQuery

        q = FunnelQuery.model_validate({
            "steps": ["Signup", "Purchase"],
            "conversion_window": 7,
        })
        ```
    """

    # ``maxItems`` is a schema-only mirror of the build-time F1
    # step-count cap; runtime enforcement stays in
    # ``validate_funnel_args`` so callers keep the ``F1_MAX_STEPS``
    # message.
    steps: list[_StepItem] = Field(
        ...,
        min_length=2,
        json_schema_extra={"maxItems": _MAX_FUNNEL_STEPS},
        description=(
            f"Funnel step specifications. At least 2 required, "
            f"at most {_MAX_FUNNEL_STEPS}."
        ),
    )
    conversion_window: int = Field(
        14,
        ge=1,
        strict=True,
        description="Conversion window size. Default: 14.",
    )
    conversion_window_unit: ConversionWindowUnit = Field(
        "day",
        description="Conversion window time unit.",
    )
    order: FunnelOrder = Field(
        "loose",
        description="Step ordering mode: loose or any.",
    )
    unit: QueryTimeUnit = Field(
        "day",
        description="Time aggregation unit.",
    )
    math: FunnelMathType = Field(
        "conversion_rate_unique",
        description="Funnel aggregation function.",
    )
    math_property: str | None = Field(
        None,
        description="Numeric property for property-aggregation math types.",
    )
    group_by: list[_BreakdownItem] | None = Field(
        None,
        description="Break down results by property or cohort membership.",
    )
    where: list[Filter] | None = Field(
        None,
        description="Filter results by property conditions.",
    )
    exclusions: list[_ExclusionItem] | None = Field(
        None,
        description="Events to exclude between steps.",
    )
    # ``maxItems`` is a schema-only mirror of the build-time F8 cap;
    # runtime enforcement stays in ``validate_funnel_args`` so callers
    # keep the ``F8_MAX_HOLDING_CONSTANT`` message.
    holding_constant: (
        Annotated[
            list[_HoldingConstantItem],
            Field(json_schema_extra={"maxItems": _MAX_HOLDING_CONSTANT}),
        ]
        | None
    ) = Field(
        None,
        description=(
            f"Properties to hold constant across funnel steps "
            f"(at most {_MAX_HOLDING_CONSTANT})."
        ),
    )
    mode: FunnelMode = Field(
        "steps",
        description="Display mode: steps, trends, or table.",
    )
    reentry_mode: FunnelReentryMode | None = Field(
        None,
        description="Funnel reentry mode: default, basic, aggressive, or optimized.",
    )


class RetentionQuery(_TimeComparableQuery):
    """Input model for a retention query.

    Bundles all parameters accepted by ``Workspace.build_retention_params()``
    and ``Workspace.query_retention()`` into a single validated object.

    Example (typed):
        ```python
        from mixpanel_headless import RetentionQuery

        q = RetentionQuery(
            born_event="Signup",
            return_event="Login",
            retention_unit="week",
        )
        params = ws.build_retention_params(q)
        result = ws.query_retention(q)
        ```

    Example (dicts):
        ```python
        from mixpanel_headless import RetentionQuery

        q = RetentionQuery.model_validate({
            "born_event": "Signup",
            "return_event": "Login",
            "retention_unit": "week",
        })
        ```
    """

    born_event: _RetentionEventItem = Field(
        ...,
        description="Event that defines cohort membership.",
    )
    return_event: _RetentionEventItem = Field(
        ...,
        description="Event that defines return.",
    )
    retention_unit: TimeUnit = Field(
        "week",
        description="Retention period unit: day, week, or month.",
    )
    alignment: RetentionAlignment = Field(
        "birth",
        description="Retention alignment mode: birth or interval_start.",
    )
    # ``maxItems`` is a schema-only mirror of the build-time R5c cap;
    # runtime enforcement stays in ``validate_retention_args`` so
    # callers keep its curated message.
    bucket_sizes: (
        Annotated[
            list[_PositiveStrictIntSchema],
            Field(json_schema_extra={"maxItems": _MAX_RETENTION_BUCKETS}),
        ]
        | None
    ) = Field(
        None,
        description=(
            f"Custom bucket sizes for retention periods (strictly ascending "
            f"positive integers, at most {_MAX_RETENTION_BUCKETS}). Items are "
            f"strict integers — bool/float/str values are rejected."
        ),
    )
    unit: QueryTimeUnit = Field(
        "day",
        description="Time aggregation unit.",
    )
    math: RetentionMathType = Field(
        "retention_rate",
        description="Retention aggregation function.",
    )
    group_by: list[_BreakdownItem] | None = Field(
        None,
        description="Break down results by property or cohort membership.",
    )
    where: list[Filter] | None = Field(
        None,
        description="Filter results by property conditions.",
    )
    mode: RetentionMode = Field(
        "curve",
        description="Display mode: curve, trends, or table.",
    )
    unbounded_mode: RetentionUnboundedMode | None = Field(
        None,
        description="Unbounded retention mode: none, carry_back, carry_forward, or consecutive_forward.",
    )
    retention_cumulative: bool = Field(
        False,
        strict=True,
        description="Whether to use cumulative retention counting.",
    )


class FlowQuery(_BaseQuery):
    """Input model for a flow query.

    Bundles all parameters accepted by ``Workspace.build_flow_params()``
    and ``Workspace.query_flow()`` into a single validated object.

    Example (typed):
        ```python
        from mixpanel_headless import FlowQuery, FlowStep, GroupBy

        q = FlowQuery(
            event="Login",
            forward=5,
            segments=[GroupBy("country")],
        )
        params = ws.build_flow_params(q)
        result = ws.query_flow(q)
        ```

    Example (dicts):
        ```python
        from mixpanel_headless import FlowQuery

        q = FlowQuery.model_validate({
            "event": "Login",
            "forward": 5,
        })
        ```
    """

    event: _FlowEvent = Field(
        ...,
        description="Event specification: a name, FlowStep, or list of names/FlowSteps.",
    )
    # The ``maximum`` keywords on forward/reverse and cardinality are
    # schema-only mirrors of the build-time FL3/FL4/FL6 rules; runtime
    # enforcement stays in ``validate_flow_args`` so callers keep its
    # curated range messages. ``FlowStep.forward``/``reverse`` carry
    # the same 0-5 bound.
    forward: int = Field(
        3,
        ge=0,
        strict=True,
        json_schema_extra={"maximum": _MAX_FLOW_STEPS_DIRECTION},
        description=(
            f"Default forward step count. Default: 3. "
            f"Maximum: {_MAX_FLOW_STEPS_DIRECTION}."
        ),
    )
    reverse: int = Field(
        0,
        ge=0,
        strict=True,
        json_schema_extra={"maximum": _MAX_FLOW_STEPS_DIRECTION},
        description=(
            f"Default reverse step count. Default: 0. "
            f"Maximum: {_MAX_FLOW_STEPS_DIRECTION}."
        ),
    )
    conversion_window: int = Field(
        7,
        ge=1,
        strict=True,
        description="Conversion window size. Default: 7.",
    )
    conversion_window_unit: FlowConversionWindowUnit = Field(
        "day",
        description="Conversion window time unit.",
    )
    count_type: FlowCountType = Field(
        "unique",
        description="Counting method: unique, total, or session.",
    )
    cardinality: int = Field(
        3,
        ge=1,
        strict=True,
        json_schema_extra={"maximum": _MAX_FLOW_CARDINALITY},
        description=(
            f"Number of top paths to return. Default: 3. "
            f"Maximum: {_MAX_FLOW_CARDINALITY}."
        ),
    )
    collapse_repeated: bool = Field(
        False,
        strict=True,
        description="Merge consecutive repeated events.",
    )
    hidden_events: list[str] | None = Field(
        None,
        description="Events to hide from flow results.",
    )
    mode: FlowChartType = Field(
        "sankey",
        description="Display mode: sankey, paths, or tree.",
    )
    where: list[Filter] | None = Field(
        None,
        description="Filter results by property conditions.",
    )
    segments: list[_SegmentItem] | None = Field(
        None,
        description=(
            "Segment (breakdown) specification for flow results. "
            "Flow segments only carry plain property names — cohort and "
            "frequency breakdowns are not supported."
        ),
    )
    exclusions: list[str] | None = Field(
        None,
        description="Event names to exclude from flow paths.",
    )

    def _get_cross_field_errors(self) -> list[InternalValidationError]:
        """Validate cross-field constraints for flow queries.

        Extends the base checks (lone ``to_date`` rejection) with an
        empty-event-list rule: ``event=[]`` is schema-representable (the
        list union alternative has no minItems) but meaningless, so it is
        rejected with a distinct code. A lone ``from_date`` is accepted
        like the other models — ``build_date_range`` fills today's date
        for the missing ``to_date``.

        Returns:
            List of validation errors (empty when the model is valid).
        """
        errors = super()._get_cross_field_errors()
        if isinstance(self.event, list) and len(self.event) == 0:
            errors.append(
                InternalValidationError(
                    path="event",
                    message="event list must not be empty",
                    code="EMPTY_EVENT_LIST",
                )
            )
        return errors
