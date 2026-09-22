"""Shared Literal type aliases for parameter validation.

These types are exported from the public API and can be used by
library consumers for their own type hints. The module also holds
:data:`ALIAS_DOCS`, the one-line descriptions the built-in help shows for
every export that has no docstring of its own.

Example:
    from mixpanel_headless import TimeUnit, Workspace

    def my_query(ws: Workspace, unit: TimeUnit) -> None:
        result = ws.segmentation(
            "event", from_date="2024-01-01", to_date="2024-01-31", unit=unit
        )
"""

from __future__ import annotations

from typing import Literal

# =============================================================================
# Time Units
# =============================================================================

# Time units for segmentation, retention, event_counts, property_counts, frequency
TimeUnit = Literal["day", "week", "month"]

# Time units for numeric aggregations (segmentation_numeric, sum, average)
HourDayUnit = Literal["hour", "day"]

# Time units for bookmark query API (query, build_params, build_time_section)
QueryTimeUnit = Literal["hour", "day", "week", "month", "quarter"]

# =============================================================================
# Count / Aggregation Types
# =============================================================================

# Count/aggregation methods
CountType = Literal["general", "unique", "average"]

# Counting methods for flows analysis
FlowCountType = Literal["unique", "total", "session"]

# =============================================================================
# Insights Math Types
# =============================================================================

MathType = Literal[
    "total",
    "unique",
    "dau",
    "wau",
    "mau",
    "average",
    "median",
    "min",
    "max",
    "p25",
    "p75",
    "p90",
    "p99",
    "percentile",
    "histogram",
    "cumulative_unique",
    "sessions",
    "unique_values",
    "most_frequent",
    "first_value",
    "multi_attribution",
    "numeric_summary",
]
"""Aggregation function for query metrics.

+-------------------+------------------------------------------------------------------+--------------------+
| Value             | Meaning                                                          | Requires property? |
+===================+==================================================================+====================+
| total             | Count events, or sum a numeric property if ``property`` is set   | Optional           |
+-------------------+------------------------------------------------------------------+--------------------+
| unique            | Count distinct users                                             | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| dau               | Daily Active Users (unique users per day)                        | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| wau               | Weekly Active Users (unique users per 7-day window)              | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| mau               | Monthly Active Users (unique users per 28-day window)            | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| average           | Mean of a numeric property's values                              | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| median            | Median (50th percentile) of a numeric property                   | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| min               | Minimum value of a numeric property                              | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| max               | Maximum value of a numeric property                              | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| p25               | 25th percentile of a numeric property                            | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| p75               | 75th percentile of a numeric property                            | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| p90               | 90th percentile of a numeric property                            | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| p99               | 99th percentile of a numeric property                            | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| percentile        | Custom percentile (requires ``percentile_value``)                | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| histogram         | Distribution of a numeric property's values                      | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| cumulative_unique | Running count of distinct users over time                        | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| sessions          | Count sessions (not events or users)                             | No                 |
+-------------------+------------------------------------------------------------------+--------------------+
| unique_values     | Count of distinct values of a property                           | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| most_frequent     | Most commonly occurring value of a property                      | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| first_value       | First observed value of a property per user                      | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| multi_attribution | Multi-touch attribution across a property                        | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+
| numeric_summary   | Summary stats (count, mean, variance) of a property              | Yes                |
+-------------------+------------------------------------------------------------------+--------------------+

Note: Mixpanel has no ``"sum"`` math type. Use ``math="total"`` with
a ``property`` to sum a numeric property's values.

``dau``, ``wau``, ``mau``, and ``unique`` are incompatible with ``per_user``.

``percentile`` maps to ``custom_percentile`` in bookmark JSON and requires
``percentile_value`` on Metric (or as a top-level param on ``query()``/``build_params()``).
``histogram`` maps directly to ``histogram`` in bookmark JSON.
"""

PerUserAggregation = Literal["unique_values", "total", "average", "min", "max"]
"""Per-user pre-aggregation type.

Requires ``math_property`` to be set. The query first computes the
per-user aggregate, then applies the top-level ``math`` across users.

+-----------------+---------------------------------------------------------------+
| Value           | Meaning                                                       |
+=================+===============================================================+
| total           | Sum of the property value per user (then aggregate)           |
+-----------------+---------------------------------------------------------------+
| average         | Mean of the property value per user (then aggregate)          |
+-----------------+---------------------------------------------------------------+
| min             | Minimum property value per user (then aggregate)              |
+-----------------+---------------------------------------------------------------+
| max             | Maximum property value per user (then aggregate)              |
+-----------------+---------------------------------------------------------------+
| unique_values   | Count of distinct property values per user (then aggregate)   |
+-----------------+---------------------------------------------------------------+

Maps to ``perUserAggregation`` in the bookmark measurement block.
"""

# =============================================================================
# Funnel Types
# =============================================================================

FunnelMathType = Literal[
    "conversion_rate_unique",
    "conversion_rate_total",
    "conversion_rate_session",
    "unique",
    "total",
    "average",
    "median",
    "min",
    "max",
    "p25",
    "p75",
    "p90",
    "p99",
    "histogram",
]
"""Aggregation function for funnel query metrics.

+---------------------------+------------------------------------------------------+--------------------+
| Value                     | Meaning                                              | Requires property? |
+===========================+======================================================+====================+
| conversion_rate_unique    | Unique-user conversion rate (default)                | No                 |
+---------------------------+------------------------------------------------------+--------------------+
| conversion_rate_total     | Total-event conversion rate                          | No                 |
+---------------------------+------------------------------------------------------+--------------------+
| conversion_rate_session   | Session-based conversion rate                        | No                 |
+---------------------------+------------------------------------------------------+--------------------+
| unique                    | Raw count of unique users per step                   | No                 |
+---------------------------+------------------------------------------------------+--------------------+
| total                     | Raw total event count per step                       | No                 |
+---------------------------+------------------------------------------------------+--------------------+
| average                   | Mean of a numeric property per step                  | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| median                    | Median of a numeric property per step                | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| min                       | Minimum of a numeric property per step               | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| max                       | Maximum of a numeric property per step               | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| p25                       | 25th percentile of a numeric property per step       | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| p75                       | 75th percentile of a numeric property per step       | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| p90                       | 90th percentile of a numeric property per step       | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| p99                       | 99th percentile of a numeric property per step       | Yes                |
+---------------------------+------------------------------------------------------+--------------------+
| histogram                 | Distribution of a numeric property per step          | Yes                |
+---------------------------+------------------------------------------------------+--------------------+

These 14 values are the public-facing funnel math types. The Mixpanel API
also accepts internal aliases (``"general"``, ``"session"``,
``"conversion_rate"``) but those are not exposed in the public API.
"""

ConversionWindowUnit = Literal[
    "second", "minute", "hour", "day", "week", "month", "session"
]
"""Time unit for funnel conversion window.

+----------+----------------------------------------------+
| Value    | Meaning                                      |
+==========+==============================================+
| second   | Conversion window in seconds (max 31708800)  |
+----------+----------------------------------------------+
| minute   | Conversion window in minutes (max 528480)    |
+----------+----------------------------------------------+
| hour     | Conversion window in hours (max 8808)        |
+----------+----------------------------------------------+
| day      | Conversion window in days (max 367)          |
+----------+----------------------------------------------+
| week     | Conversion window in weeks (max 52)          |
+----------+----------------------------------------------+
| month    | Conversion window in months (max 12)         |
+----------+----------------------------------------------+
| session  | Conversion window in sessions (max 12)       |
+----------+----------------------------------------------+
"""

FunnelOrder = Literal["loose", "any"]
"""Funnel step ordering mode.

+--------+----------------------------------------------+
| Value  | Meaning                                      |
+========+==============================================+
| loose  | Steps must occur in order but other events   |
|        | may happen between them (default)            |
+--------+----------------------------------------------+
| any    | Steps may occur in any order                 |
+--------+----------------------------------------------+
"""

FunnelMode = Literal["steps", "trends", "table"]
"""Display mode for funnel query results.

+--------+----------------------------------------------+
| Value  | Meaning                                      |
+========+==============================================+
| steps  | Step-by-step conversion view (default)       |
+--------+----------------------------------------------+
| trends | Conversion trend over time                   |
+--------+----------------------------------------------+
| table  | Tabular conversion data                      |
+--------+----------------------------------------------+
"""

# =============================================================================
# Retention Types
# =============================================================================

RetentionAlignment = Literal["birth", "interval_start"]
"""Retention alignment mode.

+------------------+----------------------------------------------+
| Value            | Meaning                                      |
+==================+==============================================+
| birth            | Align to each cohort's born date (default)   |
+------------------+----------------------------------------------+
| interval_start   | Align all cohorts to the same start date     |
+------------------+----------------------------------------------+
"""

RetentionMode = Literal["curve", "trends", "table"]
"""Display mode for retention query results.

+--------+----------------------------------------------+
| Value  | Meaning                                      |
+========+==============================================+
| curve  | Retention curve (default)                    |
+--------+----------------------------------------------+
| trends | Trend lines over time                        |
+--------+----------------------------------------------+
| table  | Tabular cohort x bucket grid                 |
+--------+----------------------------------------------+
"""

RetentionMathType = Literal["retention_rate", "unique", "total", "average"]
"""Aggregation function for retention query metrics.

+----------------+----------------------------------------------+
| Value          | Meaning                                      |
+================+==============================================+
| retention_rate | Percentage of users retained (default)       |
+----------------+----------------------------------------------+
| unique         | Raw count of retained users                  |
+----------------+----------------------------------------------+
| total          | Total event count per retention bucket       |
+----------------+----------------------------------------------+
| average        | Average of a numeric property per bucket     |
+----------------+----------------------------------------------+

Maps directly to the ``measurement.math`` field in bookmark JSON.
"""

# =============================================================================
# Advanced Query Types
# =============================================================================

SegmentMethod = Literal["all", "first"]
"""Method for counting qualifying events in segmentation.

+--------+------------------------------------------------------+
| Value  | Meaning                                              |
+========+======================================================+
| all    | Count all qualifying events (default)                |
+--------+------------------------------------------------------+
| first  | Count only the first qualifying event per user       |
+--------+------------------------------------------------------+
"""

FunnelReentryMode = Literal["default", "basic", "aggressive", "optimized"]
"""Re-entry mode for funnel queries.

+------------+------------------------------------------------------+
| Value      | Meaning                                              |
+============+======================================================+
| default    | Server default behavior                              |
+------------+------------------------------------------------------+
| basic      | Users re-enter at steps after first                  |
+------------+------------------------------------------------------+
| aggressive | Each re-entry generates additional conversion        |
+------------+------------------------------------------------------+
| optimized  | Optimized re-entry counting                          |
+------------+------------------------------------------------------+
"""

RetentionUnboundedMode = Literal[
    "none", "carry_back", "carry_forward", "consecutive_forward"
]
"""Unbounded retention mode for retention queries.

+----------------------+------------------------------------------------------+
| Value                | Meaning                                              |
+======================+======================================================+
| none                 | No unbounded retention (default)                     |
+----------------------+------------------------------------------------------+
| carry_back           | Count users in all prior buckets                     |
+----------------------+------------------------------------------------------+
| carry_forward        | Count users in all subsequent buckets                |
+----------------------+------------------------------------------------------+
| consecutive_forward  | Count users in consecutive subsequent buckets        |
+----------------------+------------------------------------------------------+
"""

TimeComparisonType = Literal["relative", "absolute-start", "absolute-end"]
"""Type of time comparison for query results.

+----------------+------------------------------------------------------+
| Value          | Meaning                                              |
+================+======================================================+
| relative       | Compare against previous period of same length       |
+----------------+------------------------------------------------------+
| absolute-start | Compare against period starting from a specific date |
+----------------+------------------------------------------------------+
| absolute-end   | Compare against period ending at a specific date     |
+----------------+------------------------------------------------------+
"""

TimeComparisonUnit = Literal["day", "week", "month", "quarter", "year"]
"""Time unit for period-over-period comparisons.

+---------+----------------------------------------------+
| Value   | Meaning                                      |
+=========+==============================================+
| day     | Compare against previous day                 |
+---------+----------------------------------------------+
| week    | Compare against previous week                |
+---------+----------------------------------------------+
| month   | Compare against previous month               |
+---------+----------------------------------------------+
| quarter | Compare against previous quarter             |
+---------+----------------------------------------------+
| year    | Compare against previous year                |
+---------+----------------------------------------------+
"""

CohortAggregationType = Literal["total", "unique", "average", "min", "max", "median"]
"""Aggregation type for cohort behavior criteria.

+---------+----------------------------------------------+
| Value   | Meaning                                      |
+=========+==============================================+
| total   | Sum of property values                       |
+---------+----------------------------------------------+
| unique  | Count of distinct property values            |
+---------+----------------------------------------------+
| average | Mean of property values                      |
+---------+----------------------------------------------+
| min     | Minimum property value                       |
+---------+----------------------------------------------+
| max     | Maximum property value                       |
+---------+----------------------------------------------+
| median  | Median property value                        |
+---------+----------------------------------------------+
"""

FlowSessionEvent = Literal["start", "end"]
"""Session anchor event type for flow queries.

+--------+----------------------------------------------+
| Value  | Meaning                                      |
+========+==============================================+
| start  | Session start anchor ($session_start)        |
+--------+----------------------------------------------+
| end    | Session end anchor ($session_end)            |
+--------+----------------------------------------------+
"""

FrequencyFilterOperator = Literal[
    "is at least",
    "is at most",
    "is greater than",
    "is less than",
    "is equal to",
]
"""Comparison operator for frequency filters.

+------------------+----------------------------------------------+
| Value            | Meaning                                      |
+==================+==============================================+
| is at least      | Count >= threshold (default)                 |
+------------------+----------------------------------------------+
| is at most       | Count <= threshold                           |
+------------------+----------------------------------------------+
| is greater than  | Count > threshold                            |
+------------------+----------------------------------------------+
| is less than     | Count < threshold                            |
+------------------+----------------------------------------------+
| is equal to      | Count == threshold                           |
+------------------+----------------------------------------------+

Note: ``"is between"`` is excluded because ``FrequencyFilter.value``
is typed as ``int | float`` (single scalar) and cannot represent
the two-bound range that "between" requires.
"""

# =============================================================================
# Flow Types
# =============================================================================

# Chart types for flows visualization
FlowChartType = Literal["sankey", "paths", "tree"]

FlowConversionWindowUnit = Literal["day", "week", "month", "session"]
"""Time unit for flow conversion window.

Subset of ``ConversionWindowUnit`` — flows do not support
second, minute, or hour granularity.

+----------+----------------------------------------------+
| Value    | Meaning                                      |
+==========+==============================================+
| day      | Conversion window in days (default)          |
+----------+----------------------------------------------+
| week     | Conversion window in weeks                   |
+----------+----------------------------------------------+
| month    | Conversion window in months                  |
+----------+----------------------------------------------+
| session  | Conversion window in sessions                |
+----------+----------------------------------------------+
"""

# Node types in a flow tree response
FlowNodeType = Literal["ANCHOR", "NORMAL", "DROPOFF", "PRUNED", "FORWARD", "REVERSE"]

# Anchor types in a flow tree response
FlowAnchorType = Literal["NORMAL", "RELATIVE_REVERSE", "RELATIVE_FORWARD"]

# =============================================================================
# Insights Display Mode
# =============================================================================

InsightsMode = Literal["timeseries", "total", "table"]
"""Display mode for insights query results.

+------------+----------------------------------------------+
| Value      | Meaning                                      |
+============+==============================================+
| timeseries | Time-series data with date-indexed values     |
|            | (default)                                    |
+------------+----------------------------------------------+
| total      | Single aggregate value per metric             |
+------------+----------------------------------------------+
| table      | Tabular data view                            |
+------------+----------------------------------------------+
"""

# =============================================================================
# Filter Types
# =============================================================================

FilterPropertyType = Literal[
    "string", "number", "boolean", "datetime", "list", "object"
]
"""Property data type for filter conditions.

Includes ``"datetime"`` and ``"list"`` for API compatibility, and
``"object"`` for ``Filter.list_contains`` (filtering on subproperties of
objects nested inside a list-of-objects property). Datetime factory
methods (``Filter.on``, ``Filter.before``, etc.) produce filters with
``filterType="datetime"``.
"""

CustomPropertyType = Literal["string", "number", "boolean", "datetime"]
"""Output type for custom property definitions.

Unlike ``FilterPropertyType``, excludes ``"list"`` which is not valid
for custom property output types. Also reused by ``SubPropertyInfo``
and ``GroupBy.list_item`` since those operate on the same scalar
type space.
"""

FilterOperator = Literal[
    "contains",
    "does not contain",
    "does not equal",
    "ends with",
    "equals",
    "false",
    "is at least",
    "is at most",
    "is between",
    "is greater than",
    "is less than",
    "is not set",
    "is set",
    "list_contains",
    "not between",
    "starts with",
    "true",
    "was before",
    "was between",
    "was in the",
    "was in the next",
    "was not between",
    "was not in the",
    "was not on",
    "was on",
    "was since",
]
"""All recognized values of ``Filter._operator``.

Centralized so additions/removals stay in lockstep with the bookmark
wire format and so mypy catches typos at every Filter classmethod
factory call site.
"""

FilterOperatorInput = Literal[
    # --- FilterOperator members (the canonical wire spellings) ---
    "contains",
    "does not contain",
    "does not equal",
    "ends with",
    "equals",
    "false",
    "is at least",
    "is at most",
    "is between",
    "is greater than",
    "is less than",
    "is not set",
    "is set",
    "list_contains",
    "not between",
    "starts with",
    "true",
    "was before",
    "was between",
    "was in the",
    "was in the next",
    "was not between",
    "was not in the",
    "was not on",
    "was on",
    "was since",
    # --- Filter factory-method names accepted as aliases ---
    "at_least",
    "at_most",
    "before",
    "between",
    "date_between",
    "date_not_between",
    "ends_with",
    "greater_than",
    "in_cohort",
    "in_the_last",
    "in_the_next",
    "is_false",
    "is_not_set",
    "is_set",
    "is_true",
    "less_than",
    "not_between",
    "not_contains",
    "not_equals",
    "not_in_cohort",
    "not_in_the_last",
    "not_on",
    "on",
    "since",
    "starts_with",
    # --- Segmentation-``where`` spelling kept constructible ---
    "is equal to",
]
"""Every spelling ``Filter(...)`` accepts for ``_operator`` on direct construction.

The union of :data:`FilterOperator`, the public ``Filter`` factory-method
names (``"greater_than"``, ``"is_set"``, ...) and the segfilter-only
``"is equal to"``. ``Filter.__post_init__`` normalizes any alias to its
:data:`FilterOperator` member, so a constructed Filter always *stores* a
canonical operator; this wider type only describes what may be passed in.
Kept in lockstep with ``types._FILTER_OPERATOR_ALIASES`` by a unit test.
"""

FilterDateUnit = Literal["hour", "day", "week", "month"]
"""Time unit for relative date filters.

Used by ``Filter.in_the_last()`` and ``Filter.not_in_the_last()``
to specify the granularity of the relative time window.
Maps to ``filterDateUnit`` in bookmark JSON.
"""

FiltersCombinator = Literal["all", "any"]
"""How multiple filters combine.

+-------+----------------------------------------------+
| Value | Meaning                                      |
+=======+==============================================+
| all   | All filters must match (AND logic, default)  |
+-------+----------------------------------------------+
| any   | Any filter may match (OR logic)              |
+-------+----------------------------------------------+
"""

# =============================================================================
# One-line descriptions for the built-in help
# =============================================================================

ALIAS_DOCS: dict[str, str] = {
    # Time units
    "TimeUnit": (
        "Bucket size for the legacy live queries segmentation, retention, "
        "event_counts, property_counts, and frequency, and the retention_unit "
        "of Workspace.query_retention / build_retention_params."
    ),
    "HourDayUnit": (
        "Bucket size for the numeric live queries segmentation_numeric, "
        "segmentation_sum, and segmentation_average, and the addiction_unit "
        "of frequency."
    ),
    "QueryTimeUnit": (
        "Time bucket for the unit parameter of Workspace.query, query_funnel, "
        "query_retention, and their build_* helpers."
    ),
    # Count types
    "CountType": (
        "Counting method for the legacy live queries that take a type "
        "parameter: total events, unique users, or the average per user."
    ),
    "FlowCountType": (
        "Counting method for Workspace.query_flow / build_flow_params "
        "(count_type): unique users, total events, or sessions."
    ),
    # Insights math
    "MathType": (
        "Aggregation for a plain-string event in Workspace.query / "
        "build_params and for Metric.math."
    ),
    "PerUserAggregation": (
        "Per-user pre-aggregation applied before math in Workspace.query / "
        "build_params and Metric.per_user; requires math_property."
    ),
    # Funnel types
    "FunnelMathType": (
        "Aggregation for Workspace.query_funnel / build_funnel_params (math), "
        "including the conversion_rate_* variants."
    ),
    "ConversionWindowUnit": (
        "Unit of the funnel conversion window (conversion_window_unit) in "
        "Workspace.query_funnel / build_funnel_params."
    ),
    "FunnelOrder": (
        "Step ordering for FunnelStep.order: loose (in order, other events "
        "allowed between steps) or any."
    ),
    "FunnelMode": (
        "Display mode for Workspace.query_funnel / build_funnel_params (mode): "
        "steps, trends, or table."
    ),
    # Retention types
    "RetentionAlignment": (
        "Cohort alignment for Workspace.query_retention / "
        "build_retention_params (alignment): birth or interval_start."
    ),
    "RetentionMode": (
        "Display mode for Workspace.query_retention / build_retention_params "
        "(mode): curve, trends, or table."
    ),
    "RetentionMathType": (
        "Measurement math for Workspace.query_retention / "
        "build_retention_params (math); retention_rate is the default."
    ),
    # Advanced query types
    "SegmentMethod": (
        "How Metric.segment_method counts qualifying events per user: all "
        "events or the first one only."
    ),
    "FunnelReentryMode": (
        "Re-entry handling for Workspace.query_funnel / build_funnel_params "
        "(reentry_mode) when a user restarts the funnel."
    ),
    "RetentionUnboundedMode": (
        "Unbounded retention handling for Workspace.query_retention / "
        "build_retention_params (unbounded_mode)."
    ),
    "TimeComparisonType": (
        "Kind of period-over-period comparison in TimeComparison.type: "
        "relative, absolute-start, or absolute-end."
    ),
    "TimeComparisonUnit": (
        "Offset unit for TimeComparison.relative / TimeComparison.unit in "
        "period-over-period comparisons."
    ),
    "CohortAggregationType": (
        "Aggregation over a numeric property in CohortCriteria.did_event "
        "(aggregation) cohort behavior criteria."
    ),
    "FlowSessionEvent": (
        "Session anchor for FlowStep.session_event: the start or the end of a session."
    ),
    "FrequencyFilterOperator": (
        "Comparison operator for FrequencyFilter.operator; single-value "
        "operators only, no between."
    ),
    # Flow types
    "FlowChartType": (
        "Visualization mode of a flow query result, passed as the mode "
        "parameter of the flow engine methods and of flow report links."
    ),
    "FlowConversionWindowUnit": (
        "Unit of the flow conversion window (conversion_window_unit) in "
        "Workspace.query_flow / build_flow_params; no sub-day units."
    ),
    "FlowNodeType": (
        "Node kind in a flow tree result (FlowTreeNode.type / "
        "FlowStepNode.type), such as ANCHOR or DROPOFF."
    ),
    "FlowAnchorType": (
        "Anchor kind in a flow tree result (FlowTreeNode.anchor_type / "
        "FlowStepNode.anchorType)."
    ),
    # Insights mode
    "InsightsMode": (
        "Display mode for Workspace.query / build_params (mode): timeseries, "
        "total, or table."
    ),
    # Filter types
    "CustomPropertyType": (
        "Output type of a custom property (CreateCustomPropertyParams."
        "property_type, GroupBy.property_type, SubPropertyInfo.type)."
    ),
    "FilterOperator": (
        "Canonical wire spelling of a Filter operator as stored in bookmark JSON."
    ),
    "FilterPropertyType": (
        "Property data type of a Filter condition (property_type), including "
        "list and object for nested data."
    ),
    "FilterDateUnit": (
        "Unit of the relative window in Filter.in_the_last, in_the_next, and "
        "not_in_the_last (date_unit)."
    ),
    "FiltersCombinator": (
        "How the filters on a Metric, FunnelStep, RetentionEvent, or FlowStep "
        "combine: all (AND) or any (OR)."
    ),
    # Aliases exported from other modules
    "AccountType": (
        "Discriminator of the Account union and AccountSummary.type: "
        "service_account, oauth_browser, or oauth_token."
    ),
    "Region": (
        "Mixpanel data residency region (us, eu, in) used by accounts, "
        "sessions, and report links."
    ),
    "BookmarkType": (
        "Saved report type from the Bookmarks API (BookmarkInfo.type, "
        "list_bookmarks, list_bookmarks_v2, saved_report_link)."
    ),
    "SavedReportType": (
        "Report type detected from a saved report result "
        "(SavedReportResult.report_type); note funnel, not funnels."
    ),
    "EntityType": (
        "Lexicon entity kind (event or profile) for Workspace.lexicon_schemas "
        "/ lexicon_schema (entity_type)."
    ),
    "ReportLinkType": (
        "Report type of a shareable report link: Workspace.create_report_link "
        "(report_type), ReportLink.report_type, and the bookmark_type of "
        "query_saved_report; excludes launch-analysis."
    ),
    # Union / Annotated aliases and constants exported from other modules
    "Account": (
        "Discriminated union over the three account variants, dispatched on "
        "the type field; build one from a dict with pydantic.TypeAdapter(Account)."
    ),
    "PropertySpec": (
        "Any way of naming a property in a query parameter: a plain property "
        "name or a custom-property reference (Metric.property, "
        "GroupBy.property, and the Filter class-method property arguments)."
    ),
    "ReportLinkQueryResult": (
        "Typed result of Workspace.query_report_link; the concrete class "
        "follows the link's report type, so narrow with isinstance or "
        "ResolvedReport.report_type."
    ),
    "BUSINESS_CONTEXT_MAX_CHARS": (
        "Maximum length of a business-context document in characters; the "
        "server rejects longer content and set_business_context checks it "
        "before sending."
    ),
}
"""One-line description per export that has no docstring of its own.

Read by the built-in help (``mp.help("MathType")``) so a ``Literal`` alias
renders a sentence instead of a bogus ``Name(args, kwargs)`` signature, and
so a ``Union`` / ``Annotated`` alias or a module constant shows a summary
instead of the ``typing`` or ``int`` docstring. Most keys are the ``Literal``
aliases defined in this module; the rest describe exports that live
elsewhere (``Region`` and ``AccountType`` are exported from
``_internal/auth/account.py``, ``BookmarkType``, ``SavedReportType``,
``EntityType``, ``ReportLinkType``, ``PropertySpec``,
``ReportLinkQueryResult`` and ``BUSINESS_CONTEXT_MAX_CHARS`` from
``types.py``, ``Account`` from ``auth_types.py``) so one dict covers every
such export. ``tests/unit/help/test_registry_completeness.py`` asserts the
key set equals the set of exports without a docstring of their own.

Prefer sentences that explain the concept over ones that list member values
or every accepting method: the rendered entry already prints the live
``values`` and ``used_by`` blocks, and hard-coded lists drift.
"""

__all__ = [
    # Time units
    "TimeUnit",
    "HourDayUnit",
    "QueryTimeUnit",
    # Count types
    "CountType",
    "FlowCountType",
    # Insights math
    "MathType",
    "PerUserAggregation",
    # Funnel types
    "FunnelMathType",
    "ConversionWindowUnit",
    "FunnelOrder",
    "FunnelMode",
    # Retention types
    "RetentionAlignment",
    "RetentionMode",
    "RetentionMathType",
    # Advanced query types
    "SegmentMethod",
    "FunnelReentryMode",
    "RetentionUnboundedMode",
    "TimeComparisonType",
    "TimeComparisonUnit",
    "CohortAggregationType",
    "FlowSessionEvent",
    "FrequencyFilterOperator",
    # Flow types
    "FlowChartType",
    "FlowConversionWindowUnit",
    "FlowNodeType",
    "FlowAnchorType",
    # Insights mode
    "InsightsMode",
    # Filter types
    "CustomPropertyType",
    "FilterOperator",
    "FilterPropertyType",
    "FilterDateUnit",
    "FiltersCombinator",
    # Built-in help
    "ALIAS_DOCS",
]
