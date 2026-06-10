"""Pydantic input models for Workspace query methods.

Each model mirrors the signature of a ``Workspace.build_*_params()`` method,
providing a single validated object for schema generation and type-safe input.
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

The pattern appears in the generated schema so LLM callers know the
expected format.  Runtime validation stays in ``build_time_section``
(V8 checks) to preserve existing error messages.
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

    def _get_cross_field_errors(self) -> list[InternalValidationError]:
        """Return cross-field errors shared by all query models.

        Rejects ``to_date`` without ``from_date`` — every builder
        ignores a lone ``to_date``, silently falling back to ``last``.
        A lone ``from_date`` is allowed here because the insights /
        funnel / retention builders fill today's date for the missing
        ``to_date``; ``FlowQuery`` overrides to reject it since the
        flow builder cannot express a from-only range.

        Subclasses extend via ``super()._get_cross_field_errors()``.

        Returns:
            List of validation errors (empty when the model is valid).
        """
        errors: list[InternalValidationError] = []
        if self.to_date is not None and self.from_date is None:
            errors.append(
                InternalValidationError(
                    path="to_date",
                    message="to_date requires from_date to be set",
                    code="TO_DATE_WITHOUT_FROM",
                )
            )
        return errors

    @model_validator(mode="wrap")
    @classmethod
    def _wrap_validation(
        cls,
        data: Any,
        handler: ModelWrapValidatorHandler[_BaseQuery],
    ) -> _BaseQuery:
        """Catch pydantic ValidationError and convert to BookmarkValidationError."""
        try:
            instance = handler(data)
        except ValidationError as exc:
            errors = [
                InternalValidationError(
                    path=".".join(str(loc) for loc in e["loc"]),
                    message=e["msg"],
                    code=e["type"],
                )
                for e in exc.errors()
            ]
            raise BookmarkValidationError(errors) from exc
        cross = instance._get_cross_field_errors()
        if cross:
            raise BookmarkValidationError(cross)
        return instance


class InsightsQuery(_BaseQuery):
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
    time_comparison: TimeComparison | None = Field(
        None,
        description="Period-over-period comparison.",
    )
    data_group_id: int | None = Field(
        None,
        description="Data group ID for group-level analytics.",
    )

    def _get_cross_field_errors(self) -> list[InternalValidationError]:
        """Validate cross-field constraints for insights queries."""
        errors = super()._get_cross_field_errors()
        has_bare_strings = any(isinstance(e, str) for e in self.events)
        if (
            self.math == "percentile"
            and self.percentile_value is None
            and has_bare_strings
        ):
            errors.append(
                InternalValidationError(
                    path="percentile_value",
                    message="percentile_value is required when math='percentile'",
                    code="MISSING_PERCENTILE_VALUE",
                )
            )
        return errors


class FunnelQuery(_BaseQuery):
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
    time_comparison: TimeComparison | None = Field(
        None,
        description="Period-over-period comparison.",
    )
    data_group_id: int | None = Field(
        None,
        description="Data group ID for group-level analytics.",
    )


class RetentionQuery(_BaseQuery):
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
    time_comparison: TimeComparison | None = Field(
        None,
        description="Period-over-period comparison.",
    )
    data_group_id: int | None = Field(
        None,
        description="Data group ID for group-level analytics.",
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
    data_group_id: int | None = Field(
        None,
        description="Data group ID for group-level analytics.",
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

        Unlike the other query models, flow rejects a lone
        ``from_date``: the flow builder's ``build_date_range`` cannot
        express a from-only range and would silently fall back to the
        relative ``last`` window.
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
        if self.from_date is not None and self.to_date is None:
            errors.append(
                InternalValidationError(
                    path="from_date",
                    message="from_date requires to_date to be set",
                    code="FROM_DATE_WITHOUT_TO",
                )
            )
        return errors
