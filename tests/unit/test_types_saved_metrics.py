"""Tests for the saved metric and saved behavior result types.

Covers ``SavedMetric``, ``SavedBehavior``, ``MetricDisplay``, and
``MetricGoal``: parsing of the App API row shapes of all three metric kinds
and the three behavior types, frozen immutability, unknown-key preservation,
and the typed accessors, which return ``None`` or an empty list for a shape
they do not know and never raise.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from mixpanel_headless.types import (
    CohortCreator,
    MetricDisplay,
    MetricGoal,
    SavedBehavior,
    SavedMetric,
)
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    formula_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
)

# =============================================================================
# SavedMetric — parsing
# =============================================================================


class TestSavedMetricParsing:
    """SavedMetric parses each metric kind as the App API returns it."""

    def test_behavior_metric_fields(self) -> None:
        """A behavior metric row parses into typed metadata fields."""
        metric = SavedMetric.model_validate(behavior_metric_json())
        assert metric.id == 104700
        assert metric.name == "Weekly signups"
        assert metric.type == "metric"
        assert metric.description == "Unique users who signed up."
        assert metric.definition["measurement"] == {"math": "unique"}
        assert metric.created == datetime(2026, 3, 1, 12, 0, 0)
        assert metric.modified == datetime(2026, 9, 1, 8, 30, 0)
        assert isinstance(metric.created_by, CohortCreator)
        assert metric.created_by.email == "ana@example.com"
        assert metric.is_visible is True
        assert metric.is_locked is False
        assert metric.can_view is True
        assert metric.can_update_basic is True
        assert metric.can_share is True

    def test_unverified_defaults(self) -> None:
        """A row without the conditional keys gets the documented defaults."""
        metric = SavedMetric.model_validate(behavior_metric_json())
        assert metric.verified is False
        assert metric.last_verified is None
        assert metric.last_verified_by is None
        assert metric.owned_by is None
        assert metric.contacts == []
        assert metric.warehouse_source_id is None

    def test_verified_metric_with_owner(self) -> None:
        """The verified and owner keys parse when the server sends them."""
        metric = SavedMetric.model_validate(behavior_metric_json(verified=True))
        assert metric.verified is True
        assert metric.last_verified == datetime(2026, 9, 2, 10, 0, 0)
        assert metric.last_verified_by is not None
        assert metric.last_verified_by.id == 8
        assert metric.owned_by is not None
        assert metric.owned_by.name == "Olu Owner"
        assert metric.contacts == ["olu@example.com"]

    def test_formula_metric(self) -> None:
        """A saved formula row parses with its kind."""
        metric = SavedMetric.model_validate(formula_metric_json())
        assert metric.type == "formula"
        assert metric.description == ""

    def test_warehouse_metric(self) -> None:
        """A warehouse row parses with its source id and a false can_view."""
        metric = SavedMetric.model_validate(warehouse_metric_json())
        assert metric.type == "warehouse"
        assert metric.warehouse_source_id == 55
        assert metric.can_view is False

    def test_legacy_and_unknown_kinds_parse(self) -> None:
        """Any ``type`` string parses: legacy ``behavior`` rows and new kinds."""
        for kind in ("behavior", "metric.simple", "something-new"):
            metric = SavedMetric.model_validate(
                {**behavior_metric_json(), "type": kind}
            )
            assert metric.type == kind

    def test_minimal_row(self) -> None:
        """Only id, name, type, and definition are required."""
        metric = SavedMetric.model_validate(
            {"id": 1, "name": "m", "type": "metric", "definition": {}}
        )
        assert metric.description == ""
        assert metric.created is None
        assert metric.created_by is None
        assert metric.can_view is None

    @pytest.mark.parametrize("missing", ["id", "name", "type", "definition"])
    def test_required_keys(self, missing: str) -> None:
        """A row without a required key fails validation.

        Args:
            missing: The required key to drop.
        """
        row = behavior_metric_json()
        del row[missing]
        with pytest.raises(ValidationError):
            SavedMetric.model_validate(row)

    def test_unknown_keys_are_kept(self) -> None:
        """Keys the model does not name survive in ``model_extra`` and dumps."""
        metric = SavedMetric.model_validate(
            {**behavior_metric_json(), "can_update_restricted": True, "new_key": [1]}
        )
        assert metric.model_extra is not None
        assert metric.model_extra["allow_staff_override"] is False
        assert metric.model_extra["can_update_restricted"] is True
        dumped = metric.model_dump()
        assert dumped["new_key"] == [1]
        assert dumped["is_superadmin"] is False

    def test_frozen(self) -> None:
        """SavedMetric instances are immutable."""
        metric = SavedMetric.model_validate(behavior_metric_json())
        with pytest.raises(ValidationError):
            metric.name = "renamed"  # type: ignore[misc]


# =============================================================================
# SavedMetric — typed accessors
# =============================================================================


class TestSavedMetricAccessors:
    """Typed accessors read the definition by kind and never raise."""

    def test_behavior_metric_accessors(self) -> None:
        """A behavior metric exposes behavior type, math, display, and goals."""
        metric = SavedMetric.model_validate(behavior_metric_json())
        assert metric.behavior_type == "simple"
        assert metric.math == "unique"
        assert metric.formula_expression is None
        assert metric.referenced_metric_ids == []
        assert metric.display == MetricDisplay(suffix=" users", prefix="", precision=0)
        (goal,) = metric.goals
        assert goal.label == "Q4 target"
        assert goal.checkpoints == [("2026-12-31T00:00:00", 5000.0)]

    def test_any_math_and_behavior_type_string(self) -> None:
        """Math and behavior type are returned as sent, known or not."""
        row = behavior_metric_json()
        row["definition"]["behavior"]["type"] = "people"
        row["definition"]["measurement"]["math"] = "sessions"
        metric = SavedMetric.model_validate(row)
        assert metric.behavior_type == "people"
        assert metric.math == "sessions"

    def test_formula_accessors(self) -> None:
        """A saved formula exposes its expression and referenced metric ids."""
        metric = SavedMetric.model_validate(formula_metric_json())
        assert metric.formula_expression == "A / B * 100"
        assert metric.referenced_metric_ids == [104700, 104701]
        assert metric.behavior_type is None
        assert metric.math is None
        assert metric.display is not None
        assert metric.display.suffix == "%"
        assert metric.goals == []

    def test_referenced_ids_from_metric_id_string_and_deduplicated(self) -> None:
        """Ids come from ``id`` or the response-only ``metric_id``, once each."""
        row = formula_metric_json()
        row["definition"]["formula"]["referencedMetrics"] = [
            {"type": "metric", "metric_id": "9"},
            {"type": "metric", "id": 9},
            {"type": "metric", "id": None},
            {"type": "metric", "id": True},
            {"type": "metric", "metric_id": "abc"},
            {"type": "metric", "id": 3},
            "not-a-dict",
        ]
        metric = SavedMetric.model_validate(row)
        assert metric.referenced_metric_ids == [9, 3]

    def test_warehouse_accessors_are_empty(self) -> None:
        """A warehouse metric has no behavior, math, formula, display, or goals."""
        metric = SavedMetric.model_validate(warehouse_metric_json())
        assert metric.behavior_type is None
        assert metric.math is None
        assert metric.formula_expression is None
        assert metric.referenced_metric_ids == []
        assert metric.display is None
        assert metric.goals == []

    @pytest.mark.parametrize(
        "definition",
        [
            {},
            {"behavior": "event"},
            {"behavior": {"type": 5}},
            {"measurement": ["unique"]},
            {"measurement": {"math": None}},
            {"formula": "A+B"},
            {"formula": {"definition": 12, "referencedMetrics": "x"}},
            {"display": "wide"},
            {"display": {"precision": "many"}},
            {"goals": "none"},
            {"goals": [{"label": "no id"}, 5]},
        ],
    )
    def test_unknown_shapes_give_none_or_empty(
        self, definition: dict[str, Any]
    ) -> None:
        """Every accessor returns None or [] for a definition shape it does not know.

        Args:
            definition: A definition dict with an unexpected shape.
        """
        metric = SavedMetric.model_validate(
            {"id": 1, "name": "odd", "type": "metric", "definition": definition}
        )
        assert metric.behavior_type is None
        assert metric.math is None
        assert metric.formula_expression is None
        assert metric.referenced_metric_ids == []
        assert metric.display is None
        assert metric.goals == []

    def test_goals_skip_entries_that_do_not_parse(self) -> None:
        """Goals that parse are returned; entries that do not are left out."""
        row = behavior_metric_json()
        good = row["definition"]["goals"][0]
        row["definition"]["goals"] = [good, {"label": "missing id"}, "junk"]
        metric = SavedMetric.model_validate(row)
        assert [g.id for g in metric.goals] == [good["id"]]

    def test_accessors_are_not_dumped(self) -> None:
        """model_dump holds the server fields, not the computed accessors."""
        dumped = SavedMetric.model_validate(behavior_metric_json()).model_dump()
        for name in ("behavior_type", "math", "formula_expression", "goals"):
            assert name not in dumped


# =============================================================================
# SavedBehavior
# =============================================================================


class TestSavedBehavior:
    """SavedBehavior parses the three behavior types and keeps unknown keys."""

    @pytest.mark.parametrize("behavior_type", ["simple", "funnel", "retention"])
    def test_behavior_types(self, behavior_type: str) -> None:
        """Each behavior type parses with its wire ``type``.

        Args:
            behavior_type: The wire ``type`` of the fixture row.
        """
        behavior = SavedBehavior.model_validate(
            saved_behavior_json(behavior_type=behavior_type)
        )
        assert behavior.type == behavior_type
        assert behavior.behavior_type == behavior_type

    def test_fields(self) -> None:
        """A behavior row parses into typed metadata fields."""
        behavior = SavedBehavior.model_validate(saved_behavior_json())
        assert behavior.id == 3001
        assert behavior.name == "Checkout"
        assert behavior.description is None
        assert behavior.definition["behavior"]["conversionWindowDuration"] == 7
        assert behavior.created == datetime(2026, 6, 1)
        assert behavior.created_by is not None
        assert behavior.created_by.id == 7
        assert behavior.verified is False
        assert behavior.last_verified_by is None
        assert behavior.can_view is True

    def test_verified_behavior(self) -> None:
        """The verified keys parse when the server sends them."""
        behavior = SavedBehavior.model_validate(saved_behavior_json(verified=True))
        assert behavior.verified is True
        assert behavior.last_verified == datetime(2026, 6, 3)
        assert behavior.last_verified_by is not None
        assert behavior.last_verified_by.email == "olu@example.com"

    def test_description_string(self) -> None:
        """A string description is kept as sent."""
        behavior = SavedBehavior.model_validate(saved_behavior_json(description="d"))
        assert behavior.description == "d"

    def test_unknown_type_and_keys(self) -> None:
        """Any ``type`` string parses and unknown keys are kept."""
        behavior = SavedBehavior.model_validate(
            {**saved_behavior_json(), "type": "behavior.new", "extra_flag": 1}
        )
        assert behavior.type == "behavior.new"
        assert behavior.model_dump()["extra_flag"] == 1

    def test_behavior_type_unknown_shape(self) -> None:
        """behavior_type is None when the definition has no behavior type string."""
        definitions: list[dict[str, Any]] = [
            {},
            {"behavior": []},
            {"behavior": {"type": 1}},
        ]
        for definition in definitions:
            behavior = SavedBehavior.model_validate(
                {"id": 1, "name": "b", "type": "funnel", "definition": definition}
            )
            assert behavior.behavior_type is None

    def test_has_no_metric_only_fields(self) -> None:
        """SavedBehavior does not model owner, contacts, or a warehouse source."""
        for name in ("owned_by", "contacts", "warehouse_source_id"):
            assert name not in SavedBehavior.model_fields

    def test_frozen(self) -> None:
        """SavedBehavior instances are immutable."""
        behavior = SavedBehavior.model_validate(saved_behavior_json())
        with pytest.raises(ValidationError):
            behavior.name = "renamed"  # type: ignore[misc]


# =============================================================================
# MetricDisplay and MetricGoal (read side)
# =============================================================================


class TestMetricDisplay:
    """MetricDisplay reads the camelCase wire keys and keeps unknown keys."""

    def test_wire_aliases(self) -> None:
        """The camelCase wire keys map to snake_case fields."""
        display = MetricDisplay.model_validate(
            {
                "prefix": "$",
                "suffix": "",
                "precision": 2,
                "abbrev": True,
                "direction": "down",
                "axis": "secondary",
                "trendline": True,
                "hideTrendline": False,
                "minimumDetectableEffect": 0.05,
                "oneSided": True,
                "power": 0.8,
            }
        )
        assert display.prefix == "$"
        assert display.precision == 2
        assert display.abbrev is True
        assert display.direction == "down"
        assert display.axis == "secondary"
        assert display.trendline is True
        assert display.hide_trendline is False
        assert display.minimum_detectable_effect == 0.05
        assert display.one_sided is True
        assert display.power == 0.8

    def test_field_names_also_accepted(self) -> None:
        """Construction by Python field name works (populate_by_name)."""
        display = MetricDisplay(hide_trendline=True, one_sided=False)
        assert display.hide_trendline is True
        assert display.one_sided is False

    def test_unknown_keys_kept(self) -> None:
        """A key outside the server model, such as ``chartType``, is kept."""
        display = MetricDisplay.model_validate({"chartType": "bar"})
        assert display.model_dump()["chartType"] == "bar"

    def test_frozen(self) -> None:
        """MetricDisplay instances are immutable."""
        display = MetricDisplay(prefix="$")
        with pytest.raises(ValidationError):
            display.prefix = "EUR"  # type: ignore[misc]


class TestMetricGoal:
    """MetricGoal reads a stored goal, including the deprecated keys."""

    def test_fields(self) -> None:
        """A goal parses its id, label, checkpoints, and target fields."""
        goal = MetricGoal.model_validate(
            {
                "id": "g1",
                "label": "Target",
                "checkpoints": [["2026-01-01", 10], ["2026-02-01", 20.5]],
                "target_type": "relative",
                "target_input": 0.1,
            }
        )
        assert goal.id == "g1"
        assert goal.label == "Target"
        assert goal.checkpoints == [("2026-01-01", 10.0), ("2026-02-01", 20.5)]
        assert goal.target_type == "relative"
        assert goal.target_input == 0.1

    def test_defaults(self) -> None:
        """Only id and label are required."""
        goal = MetricGoal(id="g", label="L")
        assert goal.checkpoints == []
        assert goal.target_type == "absolute"
        assert goal.target_input is None

    def test_deprecated_keys_kept(self) -> None:
        """The deprecated ``unit`` and ``direction`` keys stay as unknown keys."""
        goal = MetricGoal.model_validate(
            {"id": "g", "label": "L", "unit": "users", "direction": "greater_than"}
        )
        assert goal.model_extra == {"unit": "users", "direction": "greater_than"}
