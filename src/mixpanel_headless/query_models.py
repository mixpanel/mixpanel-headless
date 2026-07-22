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
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    WithJsonSchema,
    model_validator,
)

from mixpanel_headless._internal.bookmark_schema import (
    translate_pydantic_exception,
)
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
)

_DateStr = Annotated[
    str,
    WithJsonSchema({"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}),
]
"""String annotated with a YYYY-MM-DD pattern for JSON schema consumers.

Schema-only — no runtime enforcement here.  Runtime date validation
is handled by ``validate_time_args`` (V8 checks) at build time, which
produces domain-specific error messages (``"from_date must be
YYYY-MM-DD format"``).  Adding a Pydantic ``pattern`` or
``AfterValidator`` would catch bad dates earlier but replace those
messages with generic Pydantic errors.
"""


class _BaseQuery(BaseModel):
    """Shared base for query models.

    Provides frozen config with ``extra="forbid"``, and a wrap
    validator that converts ``pydantic.ValidationError`` (from
    ``Field`` constraints like ``ge``, ``min_length``) into
    ``BookmarkValidationError`` so callers get a single error type.
    Subclasses add cross-field checks in ``_get_cross_field_errors``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_date: _DateStr | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
        examples=["2025-01-01"],
    )
    to_date: _DateStr | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
        examples=["2025-01-31"],
    )
    last: int = Field(
        30,
        ge=1,
        description="Relative time range in days. Default: 30.",
        examples=[7, 30, 90],
    )
    data_group_id: int | None = Field(
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

    events: list[str | Metric | CohortMetric | Formula] = Field(
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
    percentile_value: int | float | None = Field(
        None,
        ge=0,
        le=100,
        description="Custom percentile value (e.g. 95). Used when math='percentile'.",
    )
    group_by: list[str | GroupBy | CohortBreakdown | FrequencyBreakdown] | None = Field(
        None,
        description="Break down results by property values, cohort, or event frequency.",
    )
    where: list[Filter | FrequencyFilter] | None = Field(
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
    rolling: int | None = Field(
        None,
        gt=0,
        description="Rolling window size in periods.",
    )
    cumulative: bool = Field(
        False,
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

    steps: list[str | FunnelStep] = Field(
        ...,
        min_length=2,
        description="Funnel step specifications. At least 2 required.",
    )
    conversion_window: int = Field(
        14,
        ge=1,
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
    group_by: list[str | GroupBy | CohortBreakdown] | None = Field(
        None,
        description="Break down results by property or cohort membership.",
    )
    where: list[Filter] | None = Field(
        None,
        description="Filter results by property conditions.",
    )
    exclusions: list[str | Exclusion] | None = Field(
        None,
        description="Events to exclude between steps.",
    )
    holding_constant: list[str | HoldingConstant] | None = Field(
        None,
        description="Properties to hold constant across funnel steps.",
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

    born_event: str | RetentionEvent = Field(
        ...,
        description="Event that defines cohort membership.",
    )
    return_event: str | RetentionEvent = Field(
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
    bucket_sizes: list[int] | None = Field(
        None,
        description="Custom bucket sizes for retention periods.",
    )
    unit: QueryTimeUnit = Field(
        "day",
        description="Time aggregation unit.",
    )
    math: RetentionMathType = Field(
        "retention_rate",
        description="Retention aggregation function.",
    )
    group_by: list[str | GroupBy | CohortBreakdown] | None = Field(
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

    event: str | FlowStep | list[str | FlowStep] = Field(
        ...,
        description="Event specification: a name, FlowStep, or list of names/FlowSteps.",
    )
    forward: int = Field(
        3,
        ge=0,
        description="Default forward step count. Default: 3.",
    )
    reverse: int = Field(
        0,
        ge=0,
        description="Default reverse step count. Default: 0.",
    )
    conversion_window: int = Field(
        7,
        ge=1,
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
        description="Number of top paths to return. Default: 3.",
    )
    collapse_repeated: bool = Field(
        False,
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
    segments: list[str | GroupBy] | None = Field(
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
        list union arm has no minItems) but meaningless, so it is
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
