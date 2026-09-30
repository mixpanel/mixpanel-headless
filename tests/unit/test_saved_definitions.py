"""Unit tests for ``mixpanel_headless._internal.saved_definitions``.

The module turns saved metric and saved behavior write values into wire
definitions and runs the coded checks that the Workspace write methods apply
before any request:

- ``metric_wire_parts`` / ``behavior_wire_definition``: kind, definition
  dict, and warehouse source of each definition value
- ``display_to_wire`` / ``goal_to_wire`` / ``apply_presentation``
- ``check_name`` / ``check_description`` (``SM1_EMPTY_NAME``,
  ``SM2_NAME_TOO_LONG``)
- ``check_metric_definition`` / ``check_behavior_definition``
  (``SM4_SCHEMA``)
- ``check_formula_operands`` (``FM6_OPERAND_ATTRIBUTION``)
- ``check_same_kind`` (``SM3_KIND_CHANGE``)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from mixpanel_headless._internal.query.metric_builders import (
    build_behavior_definition,
    build_formula_definition,
    build_metric_definition,
)
from mixpanel_headless._internal.saved_definitions import (
    apply_presentation,
    behavior_wire_definition,
    check_behavior_definition,
    check_description,
    check_formula_operands,
    check_metric_definition,
    check_name,
    check_same_kind,
    display_to_wire,
    finish_metric_change,
    goal_to_wire,
    metric_wire_parts,
    prepare_metric_change,
    prepare_new_metric,
)
from mixpanel_headless.exceptions import CODED_GUARD_REGISTRY, ParamValidationError
from mixpanel_headless.types import (
    BehaviorRef,
    CohortMetric,
    Filter,
    Formula,
    FunnelBehavior,
    FunnelMetric,
    Metric,
    MetricDisplay,
    MetricGoal,
    MetricRef,
    RawBehaviorDefinition,
    RawMetricDefinition,
    RetentionBehavior,
    RetentionMetric,
    SavedMetric,
    SimpleBehavior,
    WarehouseMetric,
)
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    formula_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
)

# =============================================================================
# Wire parts
# =============================================================================


class TestMetricWireParts:
    """metric_wire_parts gives the kind, definition, and source of each value."""

    def test_metric(self) -> None:
        """A Metric gives the behavior and measurement of its show clause."""
        parts = metric_wire_parts(
            Metric("Login", math="unique", filters=[Filter.equals("plan", "pro")])
        )
        assert parts.kind == "metric"
        assert parts.warehouse_source_id is None
        assert parts.definition == {
            "behavior": {
                "type": "event",
                "name": "Login",
                "resourceType": "events",
                "filtersDeterminer": "all",
                "filters": parts.definition["behavior"]["filters"],
            },
            "measurement": {"math": "unique"},
        }
        assert len(parts.definition["behavior"]["filters"]) == 1

    def test_metric_property_math(self) -> None:
        """A property math writes the property into the measurement."""
        parts = metric_wire_parts(Metric("Purchase", math="average", property="amount"))
        assert parts.definition["measurement"] == {
            "math": "average",
            "property": {"name": "amount", "resourceType": "events"},
        }

    def test_cohort_metric(self) -> None:
        """A CohortMetric gives the cohort behavior and the unique measurement."""
        parts = metric_wire_parts(CohortMetric(123, "Power users"))
        assert parts.kind == "metric"
        assert parts.definition == {
            "behavior": {
                "type": "cohort",
                "name": "Power users",
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
        }

    def test_warehouse_metric_writes_server_defaults(self) -> None:
        """A WarehouseMetric writes aggregation and syncInterval explicitly."""
        parts = metric_wire_parts(WarehouseMetric(55, "SELECT 1", "numeric"))
        assert parts.kind == "warehouse"
        assert parts.warehouse_source_id == 55
        assert parts.definition == {
            "query": "SELECT 1",
            "metricType": "numeric",
            "aggregation": "none",
            "syncInterval": "hourly",
        }

    def test_warehouse_metric_columns(self) -> None:
        """Value and time columns use their camelCase wire keys."""
        parts = metric_wire_parts(
            WarehouseMetric(
                55,
                "SELECT day, v FROM t",
                "timeseries",
                value_column="v",
                time_column="day",
                aggregation="last_value",
                sync_interval="daily",
            )
        )
        assert parts.definition == {
            "query": "SELECT day, v FROM t",
            "metricType": "timeseries",
            "aggregation": "last_value",
            "syncInterval": "daily",
            "timeColumn": "day",
            "valueColumn": "v",
        }

    def test_raw_definition_is_copied(self) -> None:
        """A raw definition is deep-copied, so later edits do not leak back."""
        source = formula_metric_json()["definition"]
        parts = metric_wire_parts(RawMetricDefinition("formula", source))
        assert parts.kind == "formula"
        assert parts.definition == source
        parts.definition["formula"]["definition"] = "A"
        assert source["formula"]["definition"] == "A / B * 100"

    def test_raw_warehouse_source(self) -> None:
        """A raw warehouse definition keeps its source id."""
        parts = metric_wire_parts(
            RawMetricDefinition("warehouse", {"query": "q"}, warehouse_source_id=9)
        )
        assert parts.warehouse_source_id == 9


class TestBehaviorWireDefinition:
    """behavior_wire_definition copies a raw behavior definition."""

    def test_copy(self) -> None:
        """The wire definition equals the input and does not share it."""
        source = saved_behavior_json()["definition"]
        wire = behavior_wire_definition(RawBehaviorDefinition(source))
        assert wire == source
        wire["behavior"]["type"] = "simple"
        assert source["behavior"]["type"] == "funnel"


# =============================================================================
# Presentation values
# =============================================================================


class TestPresentation:
    """display_to_wire, goal_to_wire, and apply_presentation."""

    def test_display_uses_wire_keys(self) -> None:
        """Snake-case fields go out as camelCase keys; None values stay out."""
        display = MetricDisplay(suffix="%", hide_trendline=True, one_sided=False)
        assert display_to_wire(display) == {
            "suffix": "%",
            "hideTrendline": True,
            "oneSided": False,
        }

    def test_display_keeps_unknown_keys(self) -> None:
        """An unknown key goes out as given, so the schema check can refuse it."""
        display = MetricDisplay.model_validate({"chartType": "bar", "precision": 1})
        assert display_to_wire(display) == {"precision": 1, "chartType": "bar"}

    def test_goal_new_id_and_iso_checkpoints(self) -> None:
        """A new goal gets a UUID; dates and datetimes become naive ISO strings."""
        aware = datetime(2026, 12, 31, 18, 0, tzinfo=timezone(timedelta(hours=-5)))
        goal = MetricGoal(
            label="Q4",
            checkpoints=[
                (date(2026, 10, 1), 1000),
                (datetime(2026, 11, 1, 6, 30), 2000),
                (aware, 3000),
                ("2026-12-31T00:00:00", 5000),
            ],
        )
        wire = goal_to_wire(goal)
        uuid.UUID(wire["id"])
        assert wire == {
            "id": wire["id"],
            "label": "Q4",
            "checkpoints": [
                ["2026-10-01T00:00:00", 1000.0],
                ["2026-11-01T06:30:00", 2000.0],
                ["2026-12-31T23:00:00", 3000.0],
                ["2026-12-31T00:00:00", 5000.0],
            ],
            "target_type": "absolute",
        }

    def test_goal_keeps_id_and_drops_deprecated_keys(self) -> None:
        """A stored goal keeps its id; ``unit`` and ``direction`` never go out."""
        goal = MetricGoal.model_validate(
            {
                "id": "g-1",
                "label": "L",
                "checkpoints": [["2026-01-01T00:00:00", 1]],
                "target_type": "relative",
                "target_input": 0.2,
                "unit": "users",
                "direction": "greater_than",
            }
        )
        assert goal_to_wire(goal) == {
            "id": "g-1",
            "label": "L",
            "checkpoints": [["2026-01-01T00:00:00", 1.0]],
            "target_type": "relative",
            "target_input": 0.2,
        }

    def test_apply_presentation_replaces_keys(self) -> None:
        """Display and goals from the params replace the keys of the definition."""
        definition: dict[str, Any] = {"behavior": {}, "display": {"prefix": "$"}}
        apply_presentation(
            definition,
            display=MetricDisplay(suffix="%"),
            goals=[MetricGoal(id="g", label="L")],
        )
        assert definition["display"] == {"suffix": "%"}
        assert definition["goals"] == [
            {"id": "g", "label": "L", "checkpoints": [], "target_type": "absolute"}
        ]

    def test_apply_presentation_none_leaves_keys(self) -> None:
        """None leaves the definition keys as they are; an empty list clears goals."""
        definition: dict[str, Any] = {
            "display": {"prefix": "$"},
            "goals": [{"id": "g"}],
        }
        apply_presentation(definition, display=None, goals=None)
        assert definition == {"display": {"prefix": "$"}, "goals": [{"id": "g"}]}
        apply_presentation(definition, display=None, goals=[])
        assert definition["goals"] == []


# =============================================================================
# SM1 and SM2
# =============================================================================


class TestNameChecks:
    """check_name and check_description."""

    def test_empty_name(self) -> None:
        """An empty name raises SM1_EMPTY_NAME."""
        with pytest.raises(ParamValidationError) as exc_info:
            check_name("", entity="saved metric")
        assert exc_info.value.code == "SM1_EMPTY_NAME"
        assert "SM1_EMPTY_NAME" in CODED_GUARD_REGISTRY

    def test_none_name_is_skipped(self) -> None:
        """None (no change on an update) passes."""
        check_name(None, entity="saved metric")

    def test_long_name(self) -> None:
        """A name over 255 characters raises SM2_NAME_TOO_LONG."""
        check_name("x" * 255, entity="saved metric")
        with pytest.raises(ParamValidationError) as exc_info:
            check_name("x" * 256, entity="saved metric")
        assert exc_info.value.code == "SM2_NAME_TOO_LONG"
        assert exc_info.value.details == {"field": "name", "length": 256, "max": 255}

    def test_long_description(self) -> None:
        """A description over 255 characters raises SM2_NAME_TOO_LONG."""
        check_description(None, entity="saved behavior")
        check_description("d" * 255, entity="saved behavior")
        with pytest.raises(ParamValidationError) as exc_info:
            check_description("d" * 300, entity="saved behavior")
        assert exc_info.value.code == "SM2_NAME_TOO_LONG"
        assert exc_info.value.details["field"] == "description"
        assert "SM2_NAME_TOO_LONG" in CODED_GUARD_REGISTRY


# =============================================================================
# SM4
# =============================================================================


class TestSchemaChecks:
    """check_metric_definition and check_behavior_definition."""

    @pytest.mark.parametrize(
        ("kind", "row"),
        [
            ("metric", behavior_metric_json()),
            ("formula", formula_metric_json()),
            ("warehouse", warehouse_metric_json()),
        ],
    )
    def test_valid_definitions_pass(self, kind: str, row: dict[str, Any]) -> None:
        """Each stored definition shape passes its kind's mirror.

        Args:
            kind: The metric kind.
            row: A fixture row of that kind.
        """
        check_metric_definition(kind, row["definition"])

    def test_error_names_the_field_path(self) -> None:
        """A bad key raises SM4_SCHEMA with the path in the message and details."""
        definition = behavior_metric_json()["definition"]
        definition["behavior"]["bogus"] = True
        with pytest.raises(ParamValidationError) as exc_info:
            check_metric_definition("metric", definition)
        exc = exc_info.value
        assert exc.code == "SM4_SCHEMA"
        assert "definition.behavior.bogus" in str(exc)
        assert exc.details["path"] == "definition.behavior.bogus"
        assert exc.details["errors"][0]["path"] == "definition.behavior.bogus"
        assert "SM4_SCHEMA" in CODED_GUARD_REGISTRY

    def test_kind_mismatch_is_caught(self) -> None:
        """A behavior metric definition sent as a formula fails the formula mirror."""
        with pytest.raises(ParamValidationError) as exc_info:
            check_metric_definition("formula", behavior_metric_json()["definition"])
        paths = [e["path"] for e in exc_info.value.details["errors"]]
        assert "definition.formula" in paths

    def test_several_errors_are_counted(self) -> None:
        """The message counts the other errors after the first."""
        definition = behavior_metric_json()["definition"]
        definition["behavior"]["bogus"] = True
        definition["measurement"]["math"] = "nope"
        with pytest.raises(ParamValidationError) as exc_info:
            check_metric_definition("metric", definition)
        assert "and 1 more" in str(exc_info.value)
        assert len(exc_info.value.details["errors"]) == 2

    def test_behavior_definition(self) -> None:
        """A saved behavior definition passes; an extra key fails with its path."""
        check_behavior_definition(saved_behavior_json()["definition"])
        with pytest.raises(ParamValidationError) as exc_info:
            check_behavior_definition({"behavior": {"type": "simple"}, "name": "x"})
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "definition.name"


# =============================================================================
# FM6
# =============================================================================


def _formula(*operands: dict[str, Any]) -> dict[str, Any]:
    """Build a saved formula definition with the given operands.

    Args:
        *operands: Operand clauses for ``referencedMetrics``.

    Returns:
        A formula definition dict.
    """
    return {"formula": {"definition": "A / B", "referencedMetrics": list(operands)}}


class TestFormulaOperandChecks:
    """check_formula_operands mirrors the web-app rule for saved formulas."""

    def test_plain_operands_pass(self) -> None:
        """Inline and reference operands without attribution pass."""
        check_formula_operands(formula_metric_json()["definition"])

    def test_null_segment_method_passes(self) -> None:
        """A null segmentMethod (common in stored formulas) passes."""
        check_formula_operands(
            _formula({"measurement": {"math": "unique", "segmentMethod": None}})
        )

    @pytest.mark.parametrize(
        ("operand", "key"),
        [
            (
                {"measurement": {"math": "unique", "segmentMethod": "first"}},
                "segmentMethod",
            ),
            ({"measurement": {"segmentMethod": "all"}}, "segmentMethod"),
            (
                {"measurement": {"multiAttribution": {"type": "linear"}}},
                "multiAttribution",
            ),
            (
                {
                    "id": 5,
                    "type": "metric",
                    "overrides": {"measurement": {"segmentMethod": "last"}},
                },
                "segmentMethod",
            ),
        ],
    )
    def test_attribution_and_segment_method_refused(
        self, operand: dict[str, Any], key: str
    ) -> None:
        """An operand with segment method or attribution raises FM6.

        Args:
            operand: The offending operand.
            key: The measurement key that the error names.
        """
        with pytest.raises(ParamValidationError) as exc_info:
            check_formula_operands(_formula({"id": 1, "type": "metric"}, operand))
        exc = exc_info.value
        assert exc.code == "FM6_OPERAND_ATTRIBUTION"
        assert exc.details == {"operand": 1, "key": key}
        assert "FM6_OPERAND_ATTRIBUTION" in CODED_GUARD_REGISTRY

    def test_unknown_shapes_are_left_to_the_schema_check(self) -> None:
        """Non-dict operands and a missing formula block raise nothing here."""
        check_formula_operands({})
        check_formula_operands({"formula": {"referencedMetrics": "x"}})
        check_formula_operands(_formula("junk", {"measurement": "x"}))  # type: ignore[arg-type]


# =============================================================================
# SM3
# =============================================================================


class TestSameKind:
    """check_same_kind refuses a change of kind or warehouse source."""

    def test_same_kind_passes(self) -> None:
        """The same kind passes; legacy ``behavior`` counts as ``metric``."""
        check_same_kind(
            entity="saved metric", entity_id=1, stored_kind="metric", new_kind="metric"
        )
        check_same_kind(
            entity="saved metric",
            entity_id=1,
            stored_kind="behavior",
            new_kind="metric",
        )

    def test_kind_change_refused(self) -> None:
        """A new kind raises SM3_KIND_CHANGE."""
        with pytest.raises(ParamValidationError) as exc_info:
            check_same_kind(
                entity="saved metric",
                entity_id=7,
                stored_kind="metric",
                new_kind="formula",
            )
        exc = exc_info.value
        assert exc.code == "SM3_KIND_CHANGE"
        assert exc.details == {"id": 7, "stored": "metric", "new": "formula"}
        assert "create a new" in str(exc)
        assert "SM3_KIND_CHANGE" in CODED_GUARD_REGISTRY

    def test_warehouse_source_change_refused(self) -> None:
        """A different warehouse source raises SM3_KIND_CHANGE."""
        with pytest.raises(ParamValidationError) as exc_info:
            check_same_kind(
                entity="saved metric",
                entity_id=7,
                stored_kind="warehouse",
                new_kind="warehouse",
                stored_source_id=55,
                new_source_id=56,
            )
        assert exc_info.value.details == {
            "id": 7,
            "stored_warehouse_source_id": 55,
            "new_warehouse_source_id": 56,
        }

    def test_same_or_absent_source_passes(self) -> None:
        """The same source, or no new source, passes."""
        check_same_kind(
            entity="saved metric",
            entity_id=7,
            stored_kind="warehouse",
            new_kind="warehouse",
            stored_source_id=55,
            new_source_id=55,
        )
        check_same_kind(
            entity="saved metric",
            entity_id=7,
            stored_kind="warehouse",
            new_kind="warehouse",
            stored_source_id=55,
            new_source_id=None,
        )


# =============================================================================
# Definition changes (create and update)
# =============================================================================


class TestPrepareMetricChange:
    """prepare_metric_change runs every local check of a definition change."""

    def test_nothing_to_change(self) -> None:
        """No definition, display, or goals gives None."""
        assert prepare_metric_change(None, None, None, validate=True) is None

    def test_definition_with_presentation(self) -> None:
        """A new definition gets the params display and goals written in."""
        change = prepare_metric_change(
            Metric("Login"),
            MetricDisplay(suffix=" users"),
            [MetricGoal(id="g", label="L")],
            validate=True,
        )
        assert change is not None
        assert change.parts is not None
        assert change.parts.kind == "metric"
        assert change.parts.definition["display"] == {"suffix": " users"}
        assert change.parts.definition["goals"][0]["id"] == "g"

    def test_schema_failure_raises_before_any_read(self) -> None:
        """A bad raw definition raises SM4_SCHEMA with validate=True."""
        with pytest.raises(ParamValidationError) as exc_info:
            prepare_metric_change(
                RawMetricDefinition("metric", {"behavior": {"bogus": 1}}),
                None,
                None,
                validate=True,
            )
        assert exc_info.value.code == "SM4_SCHEMA"

    def test_validate_false_skips_the_schema_check(self) -> None:
        """validate=False sends a definition the mirror would refuse."""
        change = prepare_metric_change(
            RawMetricDefinition("metric", {"behavior": {"bogus": 1}}),
            None,
            None,
            validate=False,
        )
        assert change is not None
        assert change.parts is not None
        assert change.parts.definition == {"behavior": {"bogus": 1}}

    def test_formula_operand_rule_runs_without_validate(self) -> None:
        """FM6 is not part of the schema check, so validate=False keeps it."""
        definition = _formula({"measurement": {"segmentMethod": "first"}})
        with pytest.raises(ParamValidationError) as exc_info:
            prepare_metric_change(
                RawMetricDefinition("formula", definition), None, None, validate=False
            )
        assert exc_info.value.code == "FM6_OPERAND_ATTRIBUTION"

    def test_presentation_only_checks_the_new_pieces(self) -> None:
        """Without a definition, the display and goals themselves are checked."""
        with pytest.raises(ParamValidationError) as exc_info:
            prepare_metric_change(
                None,
                MetricDisplay.model_validate({"chartType": "bar"}),
                None,
                validate=True,
            )
        assert exc_info.value.details["path"] == "definition.display.chartType"
        with pytest.raises(ParamValidationError) as goal_info:
            prepare_metric_change(
                None,
                None,
                [MetricGoal(label="L", target_type="weird")],
                validate=True,
            )
        assert goal_info.value.details["path"] == "definition.goals[0].target_type"

    def test_presentation_only_passes(self) -> None:
        """Valid display and goals give a change with no new definition."""
        change = prepare_metric_change(
            None, MetricDisplay(precision=2), [], validate=True
        )
        assert change is not None
        assert change.parts is None


class TestFinishMetricChange:
    """finish_metric_change merges a prepared change with the stored metric."""

    def test_new_definition_keeps_stored_presentation(self) -> None:
        """A typed definition keeps the stored display and goals."""
        stored = SavedMetric.model_validate(behavior_metric_json())
        change = prepare_metric_change(
            Metric("Login", math="unique"), None, None, validate=True
        )
        assert change is not None
        definition = finish_metric_change(change, stored)
        assert definition["measurement"] == {"math": "unique"}
        assert definition["display"] == stored.definition["display"]
        assert definition["goals"] == stored.definition["goals"]

    def test_params_presentation_wins(self) -> None:
        """Display and goals from the params replace the stored ones."""
        stored = SavedMetric.model_validate(behavior_metric_json())
        change = prepare_metric_change(
            Metric("Login"), MetricDisplay(precision=3), [], validate=True
        )
        assert change is not None
        definition = finish_metric_change(change, stored)
        assert definition["display"] == {"precision": 3}
        assert definition["goals"] == []

    def test_presentation_only_uses_the_stored_definition(self) -> None:
        """Without a new definition, the stored one goes back with the new display."""
        stored = SavedMetric.model_validate(behavior_metric_json())
        change = prepare_metric_change(
            None, MetricDisplay(prefix="#"), None, validate=True
        )
        assert change is not None
        definition = finish_metric_change(change, stored)
        assert definition["behavior"] == stored.definition["behavior"]
        assert definition["measurement"] == stored.definition["measurement"]
        assert definition["display"] == {"prefix": "#"}
        assert definition["goals"] == stored.definition["goals"]
        assert stored.definition["display"] != {"prefix": "#"}

    def test_kind_change_refused(self) -> None:
        """A formula definition for a behavior metric raises SM3_KIND_CHANGE."""
        stored = SavedMetric.model_validate(behavior_metric_json())
        change = prepare_metric_change(
            RawMetricDefinition("formula", formula_metric_json()["definition"]),
            None,
            None,
            validate=True,
        )
        assert change is not None
        with pytest.raises(ParamValidationError) as exc_info:
            finish_metric_change(change, stored)
        assert exc_info.value.code == "SM3_KIND_CHANGE"

    def test_warehouse_source_change_refused(self) -> None:
        """A warehouse definition on another source raises SM3_KIND_CHANGE."""
        stored = SavedMetric.model_validate(warehouse_metric_json())
        change = prepare_metric_change(
            WarehouseMetric(56, "SELECT 1", "numeric"), None, None, validate=True
        )
        assert change is not None
        with pytest.raises(ParamValidationError) as exc_info:
            finish_metric_change(change, stored)
        assert exc_info.value.code == "SM3_KIND_CHANGE"


# =============================================================================
# Typed metric and behavior values through the definition compiler
# =============================================================================


class TestTypedDefinitions:
    """metric_wire_parts and behavior_wire_definition over the typed values."""

    def test_funnel_metric(self) -> None:
        """A FunnelMetric gives a behavior metric with the funnel behavior."""
        metric = FunnelMetric(FunnelBehavior(["Signup", "Purchase"]))
        parts = metric_wire_parts(metric)
        assert parts.kind == "metric"
        assert parts.definition == build_metric_definition(metric)
        assert parts.definition["behavior"]["type"] == "funnel"
        assert "name" not in parts.definition

    def test_retention_metric_over_a_saved_behavior(self) -> None:
        """A RetentionMetric over a BehaviorRef keeps the reference."""
        metric = RetentionMetric(BehaviorRef(4410, "retention"))
        parts = metric_wire_parts(metric)
        assert parts.kind == "metric"
        assert parts.definition["behavior"]["id"] == 4410
        assert parts.definition["behavior"]["type"] == "retention"

    def test_metric_over_several_events(self) -> None:
        """A Metric over two events gives a simple behavior metric."""
        parts = metric_wire_parts(Metric(["Purchase", "Subscribe"], math="unique"))
        assert parts.definition["behavior"]["type"] == "simple"
        assert parts.definition["measurement"] == {"math": "unique"}

    def test_formula_with_operands(self) -> None:
        """A Formula with operands gives a saved formula; references keep their id."""
        formula = Formula(
            "A / B",
            label="Ratio",
            metrics=[Metric("Purchase", math="unique"), MetricRef(104700)],
        )
        parts = metric_wire_parts(formula)
        assert parts.kind == "formula"
        assert parts.warehouse_source_id is None
        assert parts.definition == build_formula_definition(formula)
        operands = parts.definition["formula"]["referencedMetrics"]
        assert operands[1] == {"type": "metric", "id": 104700}
        assert parts.definition["formula"]["definition"] == "A / B"

    def test_formula_without_operands_refused(self) -> None:
        """A Formula whose letters name the query's metrics cannot be saved (SM7)."""
        with pytest.raises(ParamValidationError) as exc_info:
            metric_wire_parts(Formula("B / A"))
        exc = exc_info.value
        assert exc.code == "SM7_FORMULA_WITHOUT_OPERANDS"
        assert exc.code in CODED_GUARD_REGISTRY
        assert "metrics=" in str(exc)

    def test_formula_operand_segment_method_refused(self) -> None:
        """An inline operand with a segment method fails the operand rule (FM6)."""
        formula = Formula(
            "A", metrics=[Metric("Login", math="unique", segment_method="first")]
        )
        with pytest.raises(ParamValidationError) as exc_info:
            prepare_new_metric(formula, None, None, validate=True)
        assert exc_info.value.code == "FM6_OPERAND_ATTRIBUTION"

    def test_typed_formula_passes_the_schema_check(self) -> None:
        """The compiled formula passes the mirror of the server schema."""
        formula = Formula(
            "A + B",
            metrics=[
                Metric("Login"),
                FunnelMetric(FunnelBehavior(["Signup", "Purchase"])),
            ],
        )
        parts = prepare_new_metric(formula, None, None, validate=True)
        assert parts.kind == "formula"

    @pytest.mark.parametrize(
        ("behavior", "wire_type"),
        [
            (SimpleBehavior(["Purchase", "Subscribe"], name="Buyers"), "simple"),
            (FunnelBehavior(["View Cart", "Purchase"]), "funnel"),
            (RetentionBehavior("Signup", "Login"), "retention"),
        ],
    )
    def test_behavior_values(
        self,
        behavior: SimpleBehavior | FunnelBehavior | RetentionBehavior,
        wire_type: str,
    ) -> None:
        """Each behavior value compiles to {"behavior"} with no name and passes the mirror.

        Args:
            behavior: A typed behavior value.
            wire_type: Its wire type.
        """
        definition = behavior_wire_definition(behavior)
        assert definition == build_behavior_definition(behavior)
        assert definition["behavior"]["type"] == wire_type
        assert "name" not in definition["behavior"]
        check_behavior_definition(definition)
