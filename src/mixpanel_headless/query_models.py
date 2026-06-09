"""Pydantic input models for Workspace query methods.

Each model mirrors the signature of a ``Workspace.build_*_params()`` method,
providing a single validated object for schema generation and type-safe input.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class InsightsQuery(BaseModel):
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
            "where": [{"_property": "country", "_operator": "equals", "_value": ["US"]}],
            "last": 7,
        })
        ```
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: list[str | Metric | CohortMetric | Formula] = Field(
        ...,
        description="Events to query. Each is an event name string, Metric, CohortMetric, or Formula.",
    )
    from_date: str | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
    )
    to_date: str | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
    )
    last: int = Field(
        30,
        description="Relative time range in days. Default: 30. Overridden when from_date is set.",
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

    @model_validator(mode="after")
    def _validate_constraints(self) -> "InsightsQuery":
        """Validate min-events and cross-field constraints."""
        errors: list[InternalValidationError] = []
        if len(self.events) < 1:
            errors.append(
                InternalValidationError(
                    path="events",
                    message="At least 1 event is required (got 0)",
                    code="MIN_EVENTS",
                )
            )
        if self.last < 1:
            errors.append(
                InternalValidationError(
                    path="last",
                    message=f"last must be >= 1 (got {self.last})",
                    code="INVALID_LAST",
                )
            )
        if self.to_date is not None and self.from_date is None:
            errors.append(
                InternalValidationError(
                    path="to_date",
                    message="to_date requires from_date to be set",
                    code="TO_DATE_WITHOUT_FROM",
                )
            )
        if self.math == "percentile" and self.percentile_value is None:
            errors.append(
                InternalValidationError(
                    path="percentile_value",
                    message="percentile_value is required when math='percentile'",
                    code="MISSING_PERCENTILE_VALUE",
                )
            )
        if errors:
            raise BookmarkValidationError(errors)
        return self


class FunnelQuery(BaseModel):
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

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: list[str | FunnelStep] = Field(
        ...,
        description="Funnel step specifications. At least 2 required.",
    )
    conversion_window: int = Field(
        14,
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
    from_date: str | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
    )
    to_date: str | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
    )
    last: int = Field(
        30,
        description="Relative time range in days. Default: 30.",
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
    group_by: list[GroupBy | CohortBreakdown] | None = Field(
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

    @model_validator(mode="after")
    def _validate_constraints(self) -> "FunnelQuery":
        """Validate min-steps and cross-field constraints."""
        errors: list[InternalValidationError] = []
        if len(self.steps) < 2:
            errors.append(
                InternalValidationError(
                    path="steps",
                    message=f"At least 2 steps are required (got {len(self.steps)})",
                    code="F1_MIN_STEPS",
                )
            )
        if self.last < 1:
            errors.append(
                InternalValidationError(
                    path="last",
                    message=f"last must be >= 1 (got {self.last})",
                    code="INVALID_LAST",
                )
            )
        if self.to_date is not None and self.from_date is None:
            errors.append(
                InternalValidationError(
                    path="to_date",
                    message="to_date requires from_date to be set",
                    code="TO_DATE_WITHOUT_FROM",
                )
            )
        if errors:
            raise BookmarkValidationError(errors)
        return self


class RetentionQuery(BaseModel):
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

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    from_date: str | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
    )
    to_date: str | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
    )
    last: int = Field(
        30,
        description="Relative time range in days. Default: 30.",
    )
    unit: QueryTimeUnit = Field(
        "day",
        description="Time aggregation unit.",
    )
    math: RetentionMathType = Field(
        "retention_rate",
        description="Retention aggregation function.",
    )
    group_by: list[GroupBy | CohortBreakdown] | None = Field(
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

    @model_validator(mode="after")
    def _validate_constraints(self) -> "RetentionQuery":
        """Validate cross-field constraints."""
        errors: list[InternalValidationError] = []
        if self.last < 1:
            errors.append(
                InternalValidationError(
                    path="last",
                    message=f"last must be >= 1 (got {self.last})",
                    code="INVALID_LAST",
                )
            )
        if self.to_date is not None and self.from_date is None:
            errors.append(
                InternalValidationError(
                    path="to_date",
                    message="to_date requires from_date to be set",
                    code="TO_DATE_WITHOUT_FROM",
                )
            )
        if errors:
            raise BookmarkValidationError(errors)
        return self


class FlowQuery(BaseModel):
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

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str | FlowStep | list[str | FlowStep] = Field(
        ...,
        description="Event specification: a name, FlowStep, or list of names/FlowSteps.",
    )
    forward: int = Field(
        3,
        description="Default forward step count. Default: 3.",
    )
    reverse: int = Field(
        0,
        description="Default reverse step count. Default: 0.",
    )
    from_date: str | None = Field(
        None,
        description="Start date (YYYY-MM-DD). Overrides 'last' when set.",
    )
    to_date: str | None = Field(
        None,
        description="End date (YYYY-MM-DD). Requires from_date.",
    )
    last: int = Field(
        30,
        description="Relative time range in days. Default: 30.",
    )
    conversion_window: int = Field(
        7,
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
    segments: list[GroupBy | CohortBreakdown | FrequencyBreakdown] | None = Field(
        None,
        description="Segment (breakdown) specification for flow results.",
    )
    exclusions: list[str] | None = Field(
        None,
        description="Event names to exclude from flow paths.",
    )

    @model_validator(mode="after")
    def _validate_constraints(self) -> "FlowQuery":
        """Validate cross-field constraints."""
        errors: list[InternalValidationError] = []
        if isinstance(self.event, list) and len(self.event) == 0:
            errors.append(
                InternalValidationError(
                    path="event",
                    message="event list must not be empty",
                    code="EMPTY_EVENT_LIST",
                )
            )
        if self.last < 1:
            errors.append(
                InternalValidationError(
                    path="last",
                    message=f"last must be >= 1 (got {self.last})",
                    code="INVALID_LAST",
                )
            )
        if self.to_date is not None and self.from_date is None:
            errors.append(
                InternalValidationError(
                    path="to_date",
                    message="to_date requires from_date to be set",
                    code="TO_DATE_WITHOUT_FROM",
                )
            )
        if errors:
            raise BookmarkValidationError(errors)
        return self
