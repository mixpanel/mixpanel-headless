"""Tests for the inline-metric builders and the definition compiler.

Covers metrics over a custom event or more than one event, funnel and
retention metrics, formulas that hold their own operands, and the saved
definition that the create layer sends. The tests assert exact dicts and
key order, as in ``test_metric_builders.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mixpanel_headless._internal.bookmark_builders import build_filter_entry
from mixpanel_headless._internal.query.metric_builders import (
    build_custom_event_behavior,
    build_formula_clause,
    build_formula_definition,
    build_funnel_measurement,
    build_funnel_metric_clause,
    build_inline_metric_clause,
    build_metric_clause,
    build_metric_definition,
    build_retention_measurement,
    build_retention_metric_clause,
    build_show_section,
    build_simple_behavior,
    build_simple_event_entry,
    custom_event_name,
    simple_behavior_name,
)
from mixpanel_headless.types import (
    CohortMetric,
    CustomEventRef,
    CustomPropertyRef,
    Exclusion,
    Filter,
    Formula,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    HoldingConstant,
    Metric,
    RetentionBehavior,
    RetentionEvent,
    RetentionMetric,
    SimpleBehavior,
)

PRO = Filter.equals("plan", "pro")
"""A filter used across the tests."""


def _entry(
    name: str,
    *,
    filters: list[dict[str, Any]] | None = None,
    determiner: str = "all",
) -> dict[str, Any]:
    """Return the expected entry of an event inside a simple behavior."""
    return {
        "type": "event",
        "id": None,
        "name": name,
        "filters": filters or [],
        "filtersDeterminer": determiner,
    }


def _ce_entry(
    custom_event_id: int,
    *,
    filters: list[dict[str, Any]] | None = None,
    determiner: str = "all",
) -> dict[str, Any]:
    """Return the expected entry of a custom event inside a simple behavior."""
    return {
        "type": "custom-event",
        "id": custom_event_id,
        "name": f"$custom_event:{custom_event_id}",
        "filters": filters or [],
        "filtersDeterminer": determiner,
    }


def _simple(name: str, behaviors: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the expected simple behavior block."""
    return {
        "type": "simple",
        "name": name,
        "resourceType": "events",
        "filtersDeterminer": "all",
        "filters": [],
        "behaviors": behaviors,
    }


def _funnel_behavior(**overrides: Any) -> dict[str, Any]:
    """Return the expected behavior block of a two-step funnel metric."""
    behavior: dict[str, Any] = {
        "type": "funnel",
        "resourceType": "events",
        "behaviors": [
            {
                "type": "event",
                "id": None,
                "name": "Signup",
                "filters": [],
                "filtersDeterminer": "all",
                "funnelOrder": "loose",
            },
            {
                "type": "event",
                "id": None,
                "name": "Purchase",
                "filters": [],
                "filtersDeterminer": "all",
                "funnelOrder": "loose",
            },
        ],
        "conversionWindowDuration": 14,
        "conversionWindowUnit": "day",
        "funnelOrder": "loose",
        "exclusions": [],
        "aggregateBy": [],
        "filter": [],
    }
    behavior.update(overrides)
    return behavior


def _retention_behavior(**overrides: Any) -> dict[str, Any]:
    """Return the expected behavior block of a retention metric."""
    behavior: dict[str, Any] = {
        "type": "retention",
        "resourceType": "events",
        "behaviors": [
            {
                "type": "event",
                "id": None,
                "name": "Signup",
                "filters": [],
                "filtersDeterminer": "all",
            },
            {
                "type": "event",
                "id": None,
                "name": "Login",
                "filters": [],
                "filtersDeterminer": "all",
            },
        ],
        "retentionUnit": "week",
        "retentionAlignmentType": "birth",
        "retentionCustomBucketSizes": [],
        "filter": [],
    }
    behavior.update(overrides)
    return behavior


FUNNEL = FunnelBehavior(["Signup", "Purchase"])
"""A two-step funnel behavior with the engine defaults."""

RETENTION = RetentionBehavior("Signup", "Login")
"""A retention behavior with the engine defaults."""


# =============================================================================
# Custom events
# =============================================================================


class TestCustomEvent:
    """A custom event is written by id, with its ``$custom_event:`` name."""

    def test_name(self) -> None:
        """The wire name of a custom event is ``$custom_event:<id>``."""
        assert custom_event_name(CustomEventRef(42)) == "$custom_event:42"

    def test_behavior_without_filters(self) -> None:
        """The behavior has the id, the wire name, and the events resource."""
        assert build_custom_event_behavior(CustomEventRef(42)) == {
            "type": "custom-event",
            "id": 42,
            "name": "$custom_event:42",
            "resourceType": "events",
            "filtersDeterminer": "all",
            "filters": [],
        }

    def test_behavior_with_filters(self) -> None:
        """Filters and the combinator are written as on an event behavior."""
        behavior = build_custom_event_behavior(
            CustomEventRef(42), filters=[PRO], filters_combinator="any"
        )
        assert behavior["filters"] == [build_filter_entry(PRO)]
        assert behavior["filtersDeterminer"] == "any"

    def test_metric_clause(self) -> None:
        """A metric over a custom event uses the custom-event behavior."""
        clause = build_metric_clause(Metric(CustomEventRef(42), math="unique"))
        assert clause == {
            "type": "metric",
            "behavior": build_custom_event_behavior(CustomEventRef(42)),
            "measurement": {"math": "unique"},
        }


# =============================================================================
# Simple behaviors
# =============================================================================


class TestSimpleEventEntry:
    """Each event of a simple behavior is one entry of ``behaviors``."""

    def test_name(self) -> None:
        """An event name gives an event entry with a null id."""
        assert build_simple_event_entry("Login") == _entry("Login")

    def test_name_with_filters(self) -> None:
        """Filters passed in are written on the entry."""
        entry = build_simple_event_entry(
            "Login", filters=[PRO], filters_combinator="any"
        )
        assert entry == _entry(
            "Login", filters=[build_filter_entry(PRO)], determiner="any"
        )

    def test_custom_event(self) -> None:
        """A custom event gives a custom-event entry with its id."""
        assert build_simple_event_entry(CustomEventRef(7)) == _ce_entry(7)

    def test_custom_event_with_filters(self) -> None:
        """Filters passed in are written on a custom-event entry too."""
        entry = build_simple_event_entry(CustomEventRef(7), filters=[PRO])
        assert entry == _ce_entry(7, filters=[build_filter_entry(PRO)])

    def test_step_uses_its_own_filters_and_label(self) -> None:
        """A FunnelStep keeps its own filters, combinator, and label."""
        step = FunnelStep(
            "Buy", label="Big buy", filters=[PRO], filters_combinator="any"
        )
        assert build_simple_event_entry(step) == {
            **_entry("Buy", filters=[build_filter_entry(PRO)], determiner="any"),
            "renamed": "Big buy",
        }


class TestSimpleBehaviorName:
    """The series name of a simple behavior."""

    def test_joins_event_labels(self) -> None:
        """Names, custom events, and step labels join with ``" or "``."""
        events: list[str | CustomEventRef | FunnelStep] = [
            "Login",
            CustomEventRef(7),
            FunnelStep("Buy", label="Big buy"),
            FunnelStep("Share"),
        ]
        assert simple_behavior_name(events) == (
            "Login or $custom_event:7 or Big buy or Share"
        )


class TestBuildSimpleBehavior:
    """The simple behavior block counts its events as one series."""

    def test_named(self) -> None:
        """A name is written as the behavior name."""
        assert build_simple_behavior(["Login", "Signup"], name="Signed in") == _simple(
            "Signed in", [_entry("Login"), _entry("Signup")]
        )

    @pytest.mark.parametrize("name", [None, "", "  "])
    def test_missing_or_blank_name_is_derived(self, name: str | None) -> None:
        """No name, or a blank one, joins the event names."""
        behavior = build_simple_behavior(["Login", CustomEventRef(3)], name=name)
        assert behavior == _simple(
            "Login or $custom_event:3", [_entry("Login"), _ce_entry(3)]
        )

    def test_filters_go_on_every_event(self) -> None:
        """Metric filters are written on each event; the block keeps none."""
        behavior = build_simple_behavior(
            ["Login", CustomEventRef(3)], filters=[PRO], filters_combinator="any"
        )
        pro = [build_filter_entry(PRO)]
        assert behavior == _simple(
            "Login or $custom_event:3",
            [
                _entry("Login", filters=pro, determiner="any"),
                _ce_entry(3, filters=pro, determiner="any"),
            ],
        )


class TestMetricOverSeveralEvents:
    """A metric over more than one event uses a simple behavior."""

    def test_list_of_events(self) -> None:
        """A list writes a simple behavior named after its events."""
        clause = build_metric_clause(
            Metric(["Login", "Signup"], math="unique", filters=[PRO])
        )
        pro = [build_filter_entry(PRO)]
        assert clause == {
            "type": "metric",
            "behavior": _simple(
                "Login or Signup",
                [_entry("Login", filters=pro), _entry("Signup", filters=pro)],
            ),
            "measurement": {"math": "unique"},
        }

    def test_list_combinator_goes_on_every_event(self) -> None:
        """The metric's filter combinator is written on each event entry."""
        clause = build_metric_clause(
            Metric(["Login", "Signup"], filters=[PRO], filters_combinator="any")
        )
        entries = clause["behavior"]["behaviors"]
        assert [e["filtersDeterminer"] for e in entries] == ["any", "any"]

    def test_custom_event_metric_keeps_its_filters(self) -> None:
        """Filters and the combinator of a custom-event metric are written."""
        clause = build_metric_clause(
            Metric(CustomEventRef(9), filters=[PRO], filters_combinator="any")
        )
        assert clause["behavior"]["filters"] == [build_filter_entry(PRO)]
        assert clause["behavior"]["filtersDeterminer"] == "any"

    def test_list_of_one_name_is_the_single_event(self) -> None:
        """A one-element list writes the same clause as the element alone."""
        assert build_metric_clause(Metric(["Login"], filters=[PRO])) == (
            build_metric_clause(Metric("Login", filters=[PRO]))
        )

    def test_list_of_one_custom_event_is_the_custom_event(self) -> None:
        """A one-element list of a custom event writes the custom event."""
        assert build_metric_clause(Metric([CustomEventRef(9)])) == (
            build_metric_clause(Metric(CustomEventRef(9)))
        )

    def test_simple_behavior(self) -> None:
        """A simple behavior writes its own name and events."""
        step = FunnelStep("Buy", filters=[PRO])
        clause = build_metric_clause(
            Metric(SimpleBehavior(["Login", step], name="Active"), math="total"),
            hidden=True,
        )
        assert clause == {
            "type": "metric",
            "behavior": _simple(
                "Active",
                [_entry("Login"), _entry("Buy", filters=[build_filter_entry(PRO)])],
            ),
            "measurement": {"math": "total"},
            "isHidden": True,
        }

    def test_single_event_bytes_are_unchanged(self) -> None:
        """A single event name keeps the event behavior of every release."""
        assert build_metric_clause(Metric("Login")) == {
            "type": "metric",
            "behavior": {
                "type": "event",
                "name": "Login",
                "resourceType": "events",
                "filtersDeterminer": "all",
                "filters": [],
            },
            "measurement": {"math": "total"},
        }


# =============================================================================
# Funnel and retention measurements
# =============================================================================


class TestMeasurementKeywords:
    """New measurement keywords leave the current bytes alone by default."""

    def test_funnel_step_index(self) -> None:
        """``step_index`` is written as ``stepIndex``."""
        measurement = build_funnel_measurement(
            math="conversion_rate_unique", math_property=None, step_index=2
        )
        assert measurement == {
            "math": "conversion_rate_unique",
            "property": None,
            "stepIndex": 2,
        }

    def test_retention_default_is_unchanged(self) -> None:
        """Without the new keywords the measurement is the math only."""
        assert build_retention_measurement(math="retention_rate") == {
            "math": "retention_rate"
        }

    def test_retention_all_keywords_in_order(self) -> None:
        """Property, bucket index, and cumulative follow the math, in order."""
        measurement = build_retention_measurement(
            math="average", cumulative=True, bucket_index=3, property="amount"
        )
        assert list(measurement) == [
            "math",
            "property",
            "retentionBucketIndex",
            "retentionCumulative",
        ]
        assert measurement["property"] == {"name": "amount", "resourceType": "events"}
        assert measurement["retentionBucketIndex"] == 3


# =============================================================================
# Funnel metrics
# =============================================================================


class TestFunnelMetricClause:
    """A funnel metric reuses the funnel behavior and measurement builders."""

    def test_defaults(self) -> None:
        """The defaults give the ``query_funnel`` behavior and measurement."""
        assert build_funnel_metric_clause(FunnelMetric(FUNNEL)) == {
            "type": "metric",
            "behavior": _funnel_behavior(),
            "measurement": {
                "math": "conversion_rate_unique",
                "property": None,
                "stepIndex": None,
            },
        }

    def test_every_behavior_field(self) -> None:
        """Steps, window, order, exclusions, constants, and reentry are written."""
        behavior = FunnelBehavior(
            ["Signup", FunnelStep("Purchase", label="Buy")],
            conversion_window=2,
            conversion_window_unit="week",
            order="any",
            exclusions=["Logout"],
            holding_constant="platform",
            reentry_mode="basic",
        )
        clause = build_funnel_metric_clause(FunnelMetric(behavior))
        written = clause["behavior"]
        assert written["conversionWindowDuration"] == 2
        assert written["conversionWindowUnit"] == "week"
        assert written["funnelOrder"] == "any"
        assert written["behaviors"][1]["renamed"] == "Buy"
        assert written["exclusions"] == [
            {"event": "Logout", "steps": {"from": 1, "to": 2}}
        ]
        assert written["aggregateBy"] == [
            {"value": "platform", "resourceType": "events"}
        ]
        assert written["funnelReentryMode"] == "basic"

    def test_exclusion_and_constant_objects(self) -> None:
        """Exclusion and HoldingConstant objects are used as given."""
        behavior = FunnelBehavior(
            ["A", "B", "C"],
            exclusions=[Exclusion("X", from_step=1, to_step=2)],
            holding_constant=[HoldingConstant("plan", "people"), "country"],
        )
        written = build_funnel_metric_clause(FunnelMetric(behavior))["behavior"]
        assert written["exclusions"] == [{"event": "X", "steps": {"from": 2, "to": 3}}]
        assert written["aggregateBy"] == [
            {"value": "plan", "resourceType": "people"},
            {"value": "country", "resourceType": "events"},
        ]

    def test_property_name_matches_query_funnel(self) -> None:
        """A property name is written as ``query_funnel`` writes ``math_property``."""
        clause = build_funnel_metric_clause(
            FunnelMetric(FUNNEL, math="average", property="amount", step_index=1)
        )
        assert clause["measurement"] == build_funnel_measurement(
            math="average", math_property="amount", step_index=1
        )

    def test_custom_property_uses_the_insights_property(self) -> None:
        """A custom property is written as on an insights metric."""
        clause = build_funnel_metric_clause(
            FunnelMetric(FUNNEL, math="total", property=CustomPropertyRef(5))
        )
        assert clause["measurement"] == {
            "math": "total",
            "property": {
                "customPropertyId": 5,
                "name": "",
                "resourceType": "events",
            },
            "stepIndex": None,
        }

    def test_hidden(self) -> None:
        """``hidden`` adds ``isHidden: True``."""
        clause = build_funnel_metric_clause(FunnelMetric(FUNNEL), hidden=True)
        assert clause["isHidden"] is True

    def test_label_is_the_clause_name(self) -> None:
        """A label is written as the clause ``name``, the series label."""
        clause = build_funnel_metric_clause(FunnelMetric(FUNNEL, label="Checkout"))
        assert clause["name"] == "Checkout"
        assert "name" not in clause["behavior"]
        assert "name" not in build_funnel_metric_clause(FunnelMetric(FUNNEL))

    def test_label_is_not_part_of_the_definition(self) -> None:
        """The saved definition holds no label; it is the saved metric's name."""
        definition = build_metric_definition(FunnelMetric(FUNNEL, label="Checkout"))
        assert definition == build_metric_definition(FunnelMetric(FUNNEL))


# =============================================================================
# Retention metrics
# =============================================================================


class TestRetentionMetricClause:
    """A retention metric reuses the retention behavior and measurement builders."""

    def test_defaults(self) -> None:
        """The defaults give the ``query_retention`` behavior and measurement."""
        assert build_retention_metric_clause(RetentionMetric(RETENTION)) == {
            "type": "metric",
            "behavior": _retention_behavior(),
            "measurement": {"math": "retention_rate"},
        }

    def test_every_field(self) -> None:
        """Behavior and measurement fields are all written."""
        behavior = RetentionBehavior(
            RetentionEvent("Signup", filters=[PRO]),
            "Login",
            retention_unit="day",
            alignment="interval_start",
            bucket_sizes=[1, 7],
            unbounded_mode="carry_back",
        )
        clause = build_retention_metric_clause(
            RetentionMetric(
                behavior,
                math="average",
                property="amount",
                bucket_index=7,
                retention_cumulative=True,
            ),
            hidden=True,
        )
        written = clause["behavior"]
        assert written["behaviors"][0]["filters"] == [build_filter_entry(PRO)]
        assert written["retentionUnit"] == "day"
        assert written["retentionAlignmentType"] == "interval_start"
        assert written["retentionCustomBucketSizes"] == [1, 7]
        assert written["retentionUnboundedMode"] == "carry_back"
        assert clause["measurement"] == {
            "math": "average",
            "property": {"name": "amount", "resourceType": "events"},
            "retentionBucketIndex": 7,
            "retentionCumulative": True,
        }
        assert clause["isHidden"] is True

    def test_label_is_the_clause_name(self) -> None:
        """A label is written as the clause ``name``, the series label."""
        metric = RetentionMetric(RETENTION, label="Week 1")
        assert build_retention_metric_clause(metric)["name"] == "Week 1"
        assert "name" not in build_retention_metric_clause(RetentionMetric(RETENTION))


# =============================================================================
# Dispatch and the definition compiler
# =============================================================================


INLINE_METRICS: list[Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
    Metric("Login", math="unique"),
    Metric(["Login", CustomEventRef(4)], math="total"),
    CohortMetric(12, "Power users"),
    FunnelMetric(FUNNEL),
    RetentionMetric(RETENTION, bucket_index=1),
]
"""One inline metric of each kind."""


class TestDispatchAndDefinition:
    """One builder per kind; the definition is the clause's two blocks."""

    @pytest.mark.parametrize("metric", INLINE_METRICS)
    def test_definition_is_behavior_and_measurement_of_the_clause(
        self, metric: Metric | CohortMetric | FunnelMetric | RetentionMetric
    ) -> None:
        """The saved definition equals the behavior and measurement of the clause."""
        clause = build_inline_metric_clause(metric)
        assert build_metric_definition(metric) == {
            "behavior": clause["behavior"],
            "measurement": clause["measurement"],
        }
        assert list(build_metric_definition(metric)) == ["behavior", "measurement"]

    def test_dispatch_matches_each_builder(self) -> None:
        """The dispatcher calls the builder of each kind."""
        metric, several, cohort, funnel, retention = INLINE_METRICS
        assert build_inline_metric_clause(metric) == build_metric_clause(metric)  # type: ignore[arg-type]
        assert build_inline_metric_clause(several) == build_metric_clause(several)  # type: ignore[arg-type]
        assert build_inline_metric_clause(funnel) == build_funnel_metric_clause(funnel)  # type: ignore[arg-type]
        assert build_inline_metric_clause(retention) == (
            build_retention_metric_clause(retention)  # type: ignore[arg-type]
        )
        assert build_inline_metric_clause(cohort)["behavior"]["type"] == "cohort"

    @pytest.mark.parametrize("metric", INLINE_METRICS)
    def test_hidden_reaches_every_kind(
        self, metric: Metric | CohortMetric | FunnelMetric | RetentionMetric
    ) -> None:
        """``hidden=True`` marks the clause of every kind as hidden."""
        assert build_inline_metric_clause(metric, hidden=True)["isHidden"] is True

    def test_cohort_clause_keeps_is_hidden(self) -> None:
        """A cohort clause always writes ``isHidden``, as it does today."""
        assert build_inline_metric_clause(CohortMetric(12))["isHidden"] is False
        assert build_inline_metric_clause(CohortMetric(12), hidden=True)["isHidden"]


# =============================================================================
# Formulas with operands
# =============================================================================


class TestFormulaWithOperands:
    """A formula with operands writes them into ``referencedMetrics``."""

    def test_clause(self) -> None:
        """Each operand is ``{type, behavior, measurement}``, in order."""
        operands: list[Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
            Metric("Purchase", math="total"),
            FunnelMetric(FUNNEL),
        ]
        clause = build_formula_clause(Formula("A / B", label="Per", metrics=operands))
        assert clause == {
            "type": "formula",
            "definition": "A / B",
            "measurement": {},
            "referencedMetrics": [
                {"type": "metric", **build_metric_definition(operands[0])},
                {"type": "metric", **build_metric_definition(operands[1])},
            ],
            "name": "Per",
        }

    def test_clause_without_operands_is_unchanged(self) -> None:
        """Without operands ``referencedMetrics`` stays empty."""
        assert build_formula_clause(Formula("B / A"))["referencedMetrics"] == []

    def test_definition(self) -> None:
        """The saved definition holds the expression and the operands."""
        operands: list[Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
            Metric("Purchase", math="total"),
            RetentionMetric(RETENTION),
        ]
        formula = Formula("A * B", label="ignored", metrics=operands)
        assert build_formula_definition(formula) == {
            "formula": {
                "definition": "A * B",
                "referencedMetrics": build_formula_clause(formula)["referencedMetrics"],
            }
        }

    def test_definition_needs_operands(self) -> None:
        """A formula without operands has no saved definition."""
        with pytest.raises(ValueError, match="own operands"):
            build_formula_definition(Formula("A / B"))


# =============================================================================
# Show section
# =============================================================================


class TestShowSectionWithNewKinds:
    """The show section takes every inline metric kind."""

    def _show(
        self,
        events: list[str | Metric | CohortMetric | FunnelMetric | RetentionMetric],
        formulas: list[Formula],
    ) -> list[dict[str, Any]]:
        """Build a show section with query defaults."""
        return build_show_section(
            events,
            math="total",
            math_property=None,
            per_user=None,
            percentile_value=None,
            formulas=formulas,
        )

    def test_funnel_and_retention_metrics(self) -> None:
        """Funnel and retention metrics are written in order."""
        show = self._show(
            ["Login", FunnelMetric(FUNNEL), RetentionMetric(RETENTION)], []
        )
        assert [c["behavior"]["type"] for c in show] == ["event", "funnel", "retention"]
        assert all("isHidden" not in c for c in show)

    def test_operand_formula_does_not_hide_metrics(self) -> None:
        """A formula with operands leaves the other metrics visible."""
        operand_formula = Formula("A", metrics=[Metric("Signup")])
        show = self._show(["Login", FunnelMetric(FUNNEL)], [operand_formula])
        assert "isHidden" not in show[0]
        assert "isHidden" not in show[1]
        assert show[2]["referencedMetrics"][0]["behavior"]["name"] == "Signup"

    def test_letter_formula_still_hides_metrics(self) -> None:
        """A formula without operands hides the metrics it names."""
        operand_formula = Formula("A", metrics=[Metric("Signup")])
        show = self._show(
            ["Login", FunnelMetric(FUNNEL)], [Formula("B / A"), operand_formula]
        )
        assert show[0]["isHidden"] is True
        assert show[1]["isHidden"] is True

    def test_operand_formula_alone(self) -> None:
        """A formula with operands can be the only clause."""
        show = self._show([], [Formula("A", metrics=[Metric("Signup")])])
        assert [c["type"] for c in show] == ["formula"]

    def test_plain_events_keep_query_level_settings(self) -> None:
        """A bare event name still takes the query-level math settings."""
        show = build_show_section(
            ["Login"],
            math="percentile",
            math_property="ms",
            per_user="total",
            percentile_value=95,
            formulas=[],
        )
        assert show[0]["measurement"] == {
            "math": "custom_percentile",
            "property": {"name": "ms", "resourceType": "events"},
            "perUserAggregation": "total",
            "percentile": 95,
        }

    def test_definition_needs_operands_message(self) -> None:
        """The error for a formula without operands says how to fix it."""
        with pytest.raises(ValueError) as excinfo:
            build_formula_definition(Formula("A / B"))
        assert str(excinfo.value) == (
            "A saved formula needs its own operands: pass Formula(..., metrics=[...])"
        )
