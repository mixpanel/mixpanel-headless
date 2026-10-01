"""Tests for the show-clause builder functions in metric_builders.py.

Each builder is a pure function from typed inline query values to a
fragment of the bookmark ``sections.show`` JSON. The tests assert exact
dicts, and key order where the order reaches the serialized request.
"""

from __future__ import annotations

from typing import Any, get_type_hints

from mixpanel_headless._internal.bookmark_builders import build_filter_entry
from mixpanel_headless._internal.query.metric_builders import (
    assemble_metric_clause,
    build_cohort_metric_clause,
    build_event_behavior,
    build_formula_clause,
    build_funnel_behavior,
    build_funnel_measurement,
    build_funnel_step_behavior,
    build_measurement_property,
    build_metric_clause,
    build_metric_measurement,
    build_plain_event_clause,
    build_retention_behavior,
    build_retention_event_behavior,
    build_retention_measurement,
    build_show_section,
)
from mixpanel_headless._literal_types import (
    ConversionWindowUnit,
    FunnelMathType,
    FunnelOrder,
)
from mixpanel_headless.types import (
    CohortCriteria,
    CohortDefinition,
    CohortMetric,
    CustomPropertyRef,
    Exclusion,
    Filter,
    Formula,
    FunnelStep,
    HoldingConstant,
    InlineCustomProperty,
    Metric,
    PropertyInput,
    RetentionEvent,
)

# =============================================================================
# Helpers
# =============================================================================


def _event_behavior(
    name: str,
    *,
    filters: list[dict[str, Any]] | None = None,
    determiner: str = "all",
) -> dict[str, Any]:
    """Return the expected behavior block of an event metric."""
    return {
        "type": "event",
        "name": name,
        "resourceType": "events",
        "filtersDeterminer": determiner,
        "filters": filters if filters is not None else [],
    }


def _inline_cohort_metric(name: str | None) -> CohortMetric:
    """Return a CohortMetric that holds an inline definition.

    Construction refuses an inline definition, because the server
    returns 500 for it. The builder still has a branch for it, so this
    helper skips the constructor checks to reach that branch.
    """
    definition = CohortDefinition(
        CohortCriteria.did_event("Purchase", at_least=1, within_days=30)
    )
    metric = object.__new__(CohortMetric)
    object.__setattr__(metric, "cohort", definition)
    object.__setattr__(metric, "name", name)
    return metric


# =============================================================================
# build_measurement_property
# =============================================================================


class TestBuildMeasurementProperty:
    """Tests for build_measurement_property() — the measurement property dict."""

    def test_plain_property_name(self) -> None:
        """A property name gives a name and the events resource type."""
        assert build_measurement_property("amount") == {
            "name": "amount",
            "resourceType": "events",
        }

    def test_empty_property_name_is_kept(self) -> None:
        """An empty string is a property name, not an absent property."""
        assert build_measurement_property("") == {
            "name": "",
            "resourceType": "events",
        }

    def test_custom_property_ref(self) -> None:
        """A saved custom property gives its id with an empty name."""
        assert build_measurement_property(CustomPropertyRef(42)) == {
            "customPropertyId": 42,
            "name": "",
            "resourceType": "events",
        }

    def test_inline_custom_property_without_type(self) -> None:
        """An inline custom property has no propertyType key when the type is unset."""
        prop = InlineCustomProperty(
            formula="A * B",
            inputs={
                "A": PropertyInput("price", type="number"),
                "B": PropertyInput("quantity", type="number"),
            },
        )
        assert build_measurement_property(prop) == {
            "customProperty": {
                "displayFormula": "A * B",
                "composedProperties": {
                    "A": {"value": "price", "type": "number", "resourceType": "event"},
                    "B": {
                        "value": "quantity",
                        "type": "number",
                        "resourceType": "event",
                    },
                },
                "name": "",
                "description": "",
                "resourceType": "events",
            },
            "name": "",
            "resourceType": "events",
            "dataset": "$mixpanel",
            "dataGroupId": None,
        }

    def test_inline_custom_property_with_type_and_people_resource(self) -> None:
        """The property type and the resource type reach the custom property."""
        prop = InlineCustomProperty(
            formula="A",
            inputs={"A": PropertyInput("age", type="number", resource_type="user")},
            property_type="number",
            resource_type="people",
        )
        result = build_measurement_property(prop)
        assert result == {
            "customProperty": {
                "displayFormula": "A",
                "composedProperties": {
                    "A": {"value": "age", "type": "number", "resourceType": "user"},
                },
                "name": "",
                "description": "",
                "resourceType": "people",
                "propertyType": "number",
            },
            "name": "",
            "resourceType": "people",
            "dataset": "$mixpanel",
            "dataGroupId": None,
        }
        assert list(result["customProperty"]) == [
            "displayFormula",
            "composedProperties",
            "name",
            "description",
            "resourceType",
            "propertyType",
        ]


# =============================================================================
# build_metric_measurement
# =============================================================================


class TestBuildMetricMeasurement:
    """Tests for build_metric_measurement() — the insights measurement block."""

    def test_math_only(self) -> None:
        """Only math gives a one-key measurement."""
        assert build_metric_measurement(math="unique") == {"math": "unique"}

    def test_percentile_maps_to_custom_percentile(self) -> None:
        """The user-facing percentile math is custom_percentile on the wire."""
        assert build_metric_measurement(
            math="percentile", property="duration", percentile_value=95
        ) == {
            "math": "custom_percentile",
            "property": {"name": "duration", "resourceType": "events"},
            "percentile": 95,
        }

    def test_all_optional_keys_in_order(self) -> None:
        """Every optional key appears after math, in a fixed order."""
        result = build_metric_measurement(
            math="total",
            property="amount",
            per_user="average",
            percentile_value=50,
            segment_method="first",
        )
        assert result == {
            "math": "total",
            "property": {"name": "amount", "resourceType": "events"},
            "perUserAggregation": "average",
            "percentile": 50,
            "segmentMethod": "first",
        }
        assert list(result) == [
            "math",
            "property",
            "perUserAggregation",
            "percentile",
            "segmentMethod",
        ]

    def test_percentile_value_without_percentile_math_is_kept(self) -> None:
        """A percentile value is written for any math, as the builder always did."""
        assert build_metric_measurement(math="total", percentile_value=90) == {
            "math": "total",
            "percentile": 90,
        }


# =============================================================================
# build_event_behavior
# =============================================================================


class TestBuildEventBehavior:
    """Tests for build_event_behavior() — the behavior block of one event."""

    def test_no_filters(self) -> None:
        """No filters give an empty filter list and the all determiner."""
        result = build_event_behavior("Login")
        assert result == _event_behavior("Login")
        assert list(result) == [
            "type",
            "name",
            "resourceType",
            "filtersDeterminer",
            "filters",
        ]

    def test_empty_filter_list(self) -> None:
        """An empty filter list gives an empty filter list."""
        assert build_event_behavior("Login", filters=[]) == _event_behavior("Login")

    def test_filters_and_any_combinator(self) -> None:
        """Each filter becomes a filter entry, and the combinator is the determiner."""
        filters = [
            Filter.equals("country", "US"),
            Filter.greater_than("amount", 10),
        ]
        result = build_event_behavior(
            "Purchase", filters=filters, filters_combinator="any"
        )
        assert result == _event_behavior(
            "Purchase",
            filters=[build_filter_entry(f) for f in filters],
            determiner="any",
        )


# =============================================================================
# assemble_metric_clause
# =============================================================================


class TestAssembleMetricClause:
    """Tests for assemble_metric_clause() — the metric show-clause wrapper."""

    def test_wraps_behavior_and_measurement(self) -> None:
        """The clause holds the type, the behavior, and the measurement, in order."""
        behavior = {"type": "funnel"}
        measurement = {"math": "conversion_rate_unique"}
        result = assemble_metric_clause(behavior, measurement)
        assert result == {
            "type": "metric",
            "behavior": {"type": "funnel"},
            "measurement": {"math": "conversion_rate_unique"},
        }
        assert list(result) == ["type", "behavior", "measurement"]
        assert result["behavior"] is behavior
        assert result["measurement"] is measurement


# =============================================================================
# build_metric_clause
# =============================================================================


class TestBuildMetricClause:
    """Tests for build_metric_clause() — the show clause of a typed Metric."""

    def test_default_metric(self) -> None:
        """A Metric with defaults gives total math and no isHidden key."""
        result = build_metric_clause(Metric("Login"))
        assert result == {
            "type": "metric",
            "behavior": _event_behavior("Login"),
            "measurement": {"math": "total"},
        }
        assert list(result) == ["type", "behavior", "measurement"]

    def test_hidden_adds_is_hidden_true(self) -> None:
        """A hidden metric clause ends with isHidden set to True."""
        result = build_metric_clause(Metric("Login", math="unique"), hidden=True)
        assert result == {
            "type": "metric",
            "behavior": _event_behavior("Login"),
            "measurement": {"math": "unique"},
            "isHidden": True,
        }
        assert list(result) == ["type", "behavior", "measurement", "isHidden"]

    def test_not_hidden_omits_is_hidden(self) -> None:
        """A visible metric clause has no isHidden key at all."""
        assert "isHidden" not in build_metric_clause(Metric("Login"), hidden=False)

    def test_every_metric_field(self) -> None:
        """Each Metric field reaches its place in the behavior or the measurement."""
        filters = [Filter.equals("plan", "pro")]
        metric = Metric(
            "Purchase",
            math="percentile",
            property=CustomPropertyRef(7),
            per_user="total",
            percentile_value=99,
            filters=filters,
            filters_combinator="any",
            segment_method="first",
        )
        assert build_metric_clause(metric) == {
            "type": "metric",
            "behavior": _event_behavior(
                "Purchase",
                filters=[build_filter_entry(f) for f in filters],
                determiner="any",
            ),
            "measurement": {
                "math": "custom_percentile",
                "property": {
                    "customPropertyId": 7,
                    "name": "",
                    "resourceType": "events",
                },
                "perUserAggregation": "total",
                "percentile": 99,
                "segmentMethod": "first",
            },
        }


# =============================================================================
# build_plain_event_clause
# =============================================================================


class TestBuildPlainEventClause:
    """Tests for build_plain_event_clause() — a bare event name with query defaults."""

    def test_inherits_query_defaults(self) -> None:
        """The query-level math, property, per-user, and percentile reach the clause."""
        assert build_plain_event_clause(
            "Purchase",
            math="average",
            math_property="amount",
            per_user="max",
            percentile_value=None,
        ) == {
            "type": "metric",
            "behavior": _event_behavior("Purchase"),
            "measurement": {
                "math": "average",
                "property": {"name": "amount", "resourceType": "events"},
                "perUserAggregation": "max",
            },
        }

    def test_percentile_and_hidden(self) -> None:
        """Percentile math maps to custom_percentile, and hidden adds isHidden."""
        assert build_plain_event_clause(
            "Load",
            math="percentile",
            math_property="ms",
            per_user=None,
            percentile_value=75,
            hidden=True,
        ) == {
            "type": "metric",
            "behavior": _event_behavior("Load"),
            "measurement": {
                "math": "custom_percentile",
                "property": {"name": "ms", "resourceType": "events"},
                "percentile": 75,
            },
            "isHidden": True,
        }

    def test_matches_equivalent_metric(self) -> None:
        """A bare event name and the same fields on a Metric give one clause."""
        plain = build_plain_event_clause(
            "Signup",
            math="unique",
            math_property=None,
            per_user=None,
            percentile_value=None,
            hidden=True,
        )
        typed = build_metric_clause(Metric("Signup", math="unique"), hidden=True)
        assert plain == typed


# =============================================================================
# build_cohort_metric_clause
# =============================================================================


class TestBuildCohortMetricClause:
    """Tests for build_cohort_metric_clause() — the show clause of a CohortMetric."""

    def test_saved_cohort(self) -> None:
        """A saved cohort id gives a cohort behavior with the id at the end."""
        result = build_cohort_metric_clause(CohortMetric(123, "Power Users"))
        assert result == {
            "type": "metric",
            "behavior": {
                "type": "cohort",
                "name": "Power Users",
                "resourceType": "cohorts",
                "dataGroupId": None,
                "dataset": "$mixpanel",
                "filtersDeterminer": "all",
                "filters": [],
                "id": 123,
            },
            "measurement": {
                "math": "unique",
                "property": None,
                "perUserAggregation": None,
            },
            "isHidden": False,
        }
        assert list(result) == ["type", "behavior", "measurement", "isHidden"]
        assert list(result["behavior"]) == [
            "type",
            "name",
            "resourceType",
            "dataGroupId",
            "dataset",
            "filtersDeterminer",
            "filters",
            "id",
        ]

    def test_hidden(self) -> None:
        """A hidden cohort metric has isHidden set to True."""
        result = build_cohort_metric_clause(CohortMetric(5), hidden=True)
        assert result["isHidden"] is True

    def test_no_name_gives_empty_string(self) -> None:
        """A cohort metric with no name writes an empty behavior name."""
        result = build_cohort_metric_clause(CohortMetric(5))
        assert result["behavior"]["name"] == ""

    def test_inline_definition_writes_raw_cohort_with_name(self) -> None:
        """An inline definition becomes raw_cohort, with the series name in it."""
        metric = _inline_cohort_metric("Buyers")
        assert isinstance(metric.cohort, CohortDefinition)
        result = build_cohort_metric_clause(metric)
        behavior = result["behavior"]
        assert "id" not in behavior
        expected_raw = metric.cohort.to_dict()
        # The null selector of the event selector is removed, because the
        # server crashes when it walks a null selector.
        assert expected_raw["behaviors"]["bhvr_0"]["count"]["event_selector"] == {
            "event": "Purchase",
            "selector": None,
        }
        del expected_raw["behaviors"]["bhvr_0"]["count"]["event_selector"]["selector"]
        expected_raw["name"] = "Buyers"
        assert behavior["raw_cohort"] == expected_raw
        assert list(behavior)[-1] == "raw_cohort"

    def test_inline_definition_without_name(self) -> None:
        """An inline definition with no series name writes an empty raw_cohort name."""
        result = build_cohort_metric_clause(_inline_cohort_metric(None))
        assert result["behavior"]["raw_cohort"]["name"] == ""
        assert result["behavior"]["name"] == ""


# =============================================================================
# build_formula_clause
# =============================================================================


class TestBuildFormulaClause:
    """Tests for build_formula_clause() — the show clause of a Formula."""

    def test_without_label(self) -> None:
        """A formula with no label has no name key and no referenced metrics."""
        result = build_formula_clause(Formula("A / B"))
        assert result == {
            "type": "formula",
            "definition": "A / B",
            "measurement": {},
            "referencedMetrics": [],
        }
        assert list(result) == [
            "type",
            "definition",
            "measurement",
            "referencedMetrics",
        ]

    def test_with_label(self) -> None:
        """A formula label becomes the clause name, after the other keys."""
        result = build_formula_clause(Formula("(B / A) * 100", label="Conversion %"))
        assert result == {
            "type": "formula",
            "definition": "(B / A) * 100",
            "measurement": {},
            "referencedMetrics": [],
            "name": "Conversion %",
        }
        assert list(result)[-1] == "name"

    def test_empty_label_is_omitted(self) -> None:
        """An empty label writes no name key."""
        assert "name" not in build_formula_clause(Formula("A", label=""))


# =============================================================================
# build_show_section
# =============================================================================


class TestBuildShowSection:
    """Tests for build_show_section() — the full sections.show list."""

    def test_mixed_items_without_formulas(self) -> None:
        """Strings, Metrics, and CohortMetrics keep their order, and none is hidden."""
        show = build_show_section(
            ["Login", Metric("Purchase", math="unique"), CohortMetric(9, "VIP")],
            math="total",
            math_property=None,
            per_user=None,
            percentile_value=None,
            formulas=[],
        )
        assert show == [
            {
                "type": "metric",
                "behavior": _event_behavior("Login"),
                "measurement": {"math": "total"},
            },
            {
                "type": "metric",
                "behavior": _event_behavior("Purchase"),
                "measurement": {"math": "unique"},
            },
            build_cohort_metric_clause(CohortMetric(9, "VIP"), hidden=False),
        ]
        assert show[2]["isHidden"] is False

    def test_formulas_hide_metrics_and_append_last(self) -> None:
        """With formulas, every metric is hidden and each formula follows the metrics."""
        show = build_show_section(
            ["Signup", Metric("Purchase", math="unique"), CohortMetric(9)],
            math="unique",
            math_property=None,
            per_user=None,
            percentile_value=None,
            formulas=[Formula("B / A", label="Rate"), Formula("C")],
        )
        assert show == [
            {
                "type": "metric",
                "behavior": _event_behavior("Signup"),
                "measurement": {"math": "unique"},
                "isHidden": True,
            },
            {
                "type": "metric",
                "behavior": _event_behavior("Purchase"),
                "measurement": {"math": "unique"},
                "isHidden": True,
            },
            build_cohort_metric_clause(CohortMetric(9), hidden=True),
            {
                "type": "formula",
                "definition": "B / A",
                "measurement": {},
                "referencedMetrics": [],
                "name": "Rate",
            },
            {
                "type": "formula",
                "definition": "C",
                "measurement": {},
                "referencedMetrics": [],
            },
        ]

    def test_plain_strings_use_query_defaults_and_metrics_do_not(self) -> None:
        """Query defaults apply to bare event names only, never to a Metric."""
        show = build_show_section(
            ["Checkout", Metric("Refund")],
            math="average",
            math_property="amount",
            per_user="total",
            percentile_value=None,
            formulas=[],
        )
        assert show[0]["measurement"] == {
            "math": "average",
            "property": {"name": "amount", "resourceType": "events"},
            "perUserAggregation": "total",
        }
        assert show[1]["measurement"] == {"math": "total"}

    def test_no_events(self) -> None:
        """No events and no formulas give an empty list."""
        assert (
            build_show_section(
                [],
                math="total",
                math_property=None,
                per_user=None,
                percentile_value=None,
                formulas=[],
            )
            == []
        )


# =============================================================================
# Funnel builders
# =============================================================================


class TestBuildFunnelStepBehavior:
    """Tests for build_funnel_step_behavior() — one entry of behavior.behaviors."""

    def test_plain_step(self) -> None:
        """A step with defaults takes the funnel order and has no renamed key."""
        result = build_funnel_step_behavior(FunnelStep("Signup"), order="loose")
        assert result == {
            "type": "event",
            "id": None,
            "name": "Signup",
            "filters": [],
            "filtersDeterminer": "all",
            "funnelOrder": "loose",
        }
        assert list(result) == [
            "type",
            "id",
            "name",
            "filters",
            "filtersDeterminer",
            "funnelOrder",
        ]

    def test_filters_label_and_order_override(self) -> None:
        """Step filters, label, and order override keep the base key order."""
        filters = [Filter.equals("source", "ads")]
        step = FunnelStep(
            "Purchase",
            label="Bought",
            filters=filters,
            filters_combinator="any",
            order="any",
        )
        result = build_funnel_step_behavior(step, order="loose")
        assert result == {
            "type": "event",
            "id": None,
            "name": "Purchase",
            "filters": [build_filter_entry(f) for f in filters],
            "filtersDeterminer": "any",
            "funnelOrder": "any",
            "renamed": "Bought",
        }
        assert list(result) == [
            "type",
            "id",
            "name",
            "filters",
            "filtersDeterminer",
            "funnelOrder",
            "renamed",
        ]


class TestBuildFunnelBehavior:
    """Tests for build_funnel_behavior() — the funnel behavior block."""

    def test_minimal_funnel(self) -> None:
        """Two steps with no exclusions and no holding constant."""
        result = build_funnel_behavior(
            steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
            conversion_window=14,
            conversion_window_unit="day",
            order="loose",
            exclusions=[],
            holding_constant=[],
        )
        assert result == {
            "type": "funnel",
            "resourceType": "events",
            "behaviors": [
                build_funnel_step_behavior(FunnelStep("Signup"), order="loose"),
                build_funnel_step_behavior(FunnelStep("Purchase"), order="loose"),
            ],
            "conversionWindowDuration": 14,
            "conversionWindowUnit": "day",
            "funnelOrder": "loose",
            "exclusions": [],
            "aggregateBy": [],
            "filter": [],
        }
        assert list(result) == [
            "type",
            "resourceType",
            "behaviors",
            "conversionWindowDuration",
            "conversionWindowUnit",
            "funnelOrder",
            "exclusions",
            "aggregateBy",
            "filter",
        ]

    def test_exclusions_use_one_based_step_range(self) -> None:
        """Exclusion steps are 1-based, and an open end runs to the last step."""
        result = build_funnel_behavior(
            steps=[FunnelStep("A"), FunnelStep("B"), FunnelStep("C")],
            conversion_window=1,
            conversion_window_unit="week",
            order="any",
            exclusions=[
                Exclusion("Logout"),
                Exclusion("Error", from_step=0, to_step=1),
            ],
            holding_constant=[],
        )
        assert result["exclusions"] == [
            {"event": "Logout", "steps": {"from": 1, "to": 3}},
            {"event": "Error", "steps": {"from": 1, "to": 2}},
        ]
        assert result["funnelOrder"] == "any"
        assert [b["funnelOrder"] for b in result["behaviors"]] == ["any"] * 3

    def test_holding_constant_and_reentry_mode(self) -> None:
        """Held properties become aggregateBy, and a reentry mode is the last key."""
        result = build_funnel_behavior(
            steps=[FunnelStep("A"), FunnelStep("B")],
            conversion_window=7,
            conversion_window_unit="day",
            order="loose",
            exclusions=[],
            holding_constant=[
                HoldingConstant("platform"),
                HoldingConstant("plan", resource_type="people"),
            ],
            reentry_mode="aggressive",
        )
        assert result["aggregateBy"] == [
            {"value": "platform", "resourceType": "events"},
            {"value": "plan", "resourceType": "people"},
        ]
        assert result["funnelReentryMode"] == "aggressive"
        assert list(result)[-1] == "funnelReentryMode"

    def test_no_reentry_mode_omits_key(self) -> None:
        """No reentry mode writes no funnelReentryMode key."""
        result = build_funnel_behavior(
            steps=[FunnelStep("A"), FunnelStep("B")],
            conversion_window=7,
            conversion_window_unit="day",
            order="loose",
            exclusions=[],
            holding_constant=[],
            reentry_mode=None,
        )
        assert "funnelReentryMode" not in result


class TestBuildFunnelMeasurement:
    """Tests for build_funnel_measurement() — the funnel measurement block."""

    def test_rate_math(self) -> None:
        """A rate math has a null property and a null step index."""
        result = build_funnel_measurement(
            math="conversion_rate_unique", math_property=None
        )
        assert result == {
            "math": "conversion_rate_unique",
            "property": None,
            "stepIndex": None,
        }
        assert list(result) == ["math", "property", "stepIndex"]

    def test_property_math(self) -> None:
        """A property math writes a numeric event property."""
        assert build_funnel_measurement(math="average", math_property="revenue") == {
            "math": "average",
            "property": {
                "name": "revenue",
                "type": "number",
                "resourceType": "events",
            },
            "stepIndex": None,
        }

    def test_empty_property_is_null(self) -> None:
        """An empty property name writes a null property."""
        result = build_funnel_measurement(math="average", math_property="")
        assert result["property"] is None


class TestFunnelBuilderTypes:
    """Tests that the funnel builders keep the funnel Literal types."""

    def test_order_window_unit_and_math_use_the_literal_aliases(self) -> None:
        """Order, window unit, and funnel math are typed with the aliases, not str."""
        step_hints = get_type_hints(build_funnel_step_behavior)
        behavior_hints = get_type_hints(build_funnel_behavior)
        measurement_hints = get_type_hints(build_funnel_measurement)
        assert step_hints["order"] == FunnelOrder
        assert behavior_hints["order"] == FunnelOrder
        assert behavior_hints["conversion_window_unit"] == ConversionWindowUnit
        assert measurement_hints["math"] == FunnelMathType


# =============================================================================
# Retention builders
# =============================================================================


class TestBuildRetentionEventBehavior:
    """Tests for build_retention_event_behavior() — one retention event entry."""

    def test_plain_event(self) -> None:
        """An event with no filters has an empty filter list."""
        result = build_retention_event_behavior(RetentionEvent("Signup"))
        assert result == {
            "type": "event",
            "id": None,
            "name": "Signup",
            "filters": [],
            "filtersDeterminer": "all",
        }
        assert list(result) == [
            "type",
            "id",
            "name",
            "filters",
            "filtersDeterminer",
        ]

    def test_filters(self) -> None:
        """Event filters become filter entries with the combinator as determiner."""
        filters = [Filter.equals("source", "organic")]
        result = build_retention_event_behavior(
            RetentionEvent("Signup", filters=filters, filters_combinator="any")
        )
        assert result["filters"] == [build_filter_entry(f) for f in filters]
        assert result["filtersDeterminer"] == "any"


class TestBuildRetentionBehavior:
    """Tests for build_retention_behavior() — the retention behavior block."""

    def test_default_buckets(self) -> None:
        """No bucket sizes give an empty list, and no unbounded mode key."""
        result = build_retention_behavior(
            born_event=RetentionEvent("Signup"),
            return_event=RetentionEvent("Login"),
            retention_unit="week",
            alignment="birth",
            bucket_sizes=None,
        )
        assert result == {
            "type": "retention",
            "resourceType": "events",
            "behaviors": [
                build_retention_event_behavior(RetentionEvent("Signup")),
                build_retention_event_behavior(RetentionEvent("Login")),
            ],
            "retentionUnit": "week",
            "retentionAlignmentType": "birth",
            "retentionCustomBucketSizes": [],
            "filter": [],
        }
        assert list(result) == [
            "type",
            "resourceType",
            "behaviors",
            "retentionUnit",
            "retentionAlignmentType",
            "retentionCustomBucketSizes",
            "filter",
        ]

    def test_bucket_sizes_are_copied(self) -> None:
        """Custom bucket sizes are written as a new list."""
        sizes = [1, 3, 7]
        result = build_retention_behavior(
            born_event=RetentionEvent("Signup"),
            return_event=RetentionEvent("Login"),
            retention_unit="day",
            alignment="interval_start",
            bucket_sizes=sizes,
        )
        assert result["retentionCustomBucketSizes"] == [1, 3, 7]
        assert result["retentionCustomBucketSizes"] is not sizes
        assert result["retentionAlignmentType"] == "interval_start"

    def test_empty_bucket_sizes(self) -> None:
        """An empty bucket list gives an empty list."""
        result = build_retention_behavior(
            born_event=RetentionEvent("Signup"),
            return_event=RetentionEvent("Login"),
            retention_unit="day",
            alignment="birth",
            bucket_sizes=[],
        )
        assert result["retentionCustomBucketSizes"] == []

    def test_unbounded_mode_is_last_key(self) -> None:
        """An unbounded mode is written after the base keys."""
        result = build_retention_behavior(
            born_event=RetentionEvent("Signup"),
            return_event=RetentionEvent("Login"),
            retention_unit="day",
            alignment="birth",
            bucket_sizes=None,
            unbounded_mode="carry_forward",
        )
        assert result["retentionUnboundedMode"] == "carry_forward"
        assert list(result)[-1] == "retentionUnboundedMode"


class TestBuildRetentionMeasurement:
    """Tests for build_retention_measurement() — the retention measurement block."""

    def test_not_cumulative(self) -> None:
        """A non-cumulative measurement holds only the math."""
        assert build_retention_measurement(math="retention_rate") == {
            "math": "retention_rate"
        }

    def test_cumulative(self) -> None:
        """A cumulative measurement adds retentionCumulative set to True."""
        assert build_retention_measurement(math="unique", cumulative=True) == {
            "math": "unique",
            "retentionCumulative": True,
        }
