"""Tests for the saved metric and saved behavior write types.

Covers ``WarehouseMetric``, ``RawMetricDefinition``, ``RawBehaviorDefinition``,
the create and update params models, ``BulkUpdateMetricEntry``, and the write
side of ``MetricGoal``: defaults, construction-time refusals with registry
codes, instance-only definition fields, name stripping, and immutability.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from mixpanel_headless.exceptions import CODED_GUARD_REGISTRY, ParamValidationError
from mixpanel_headless.types import (
    BulkUpdateMetricEntry,
    CohortMetric,
    CreateBehaviorParams,
    CreateMetricParams,
    Formula,
    FunnelBehavior,
    FunnelMetric,
    Metric,
    MetricDisplay,
    MetricGoal,
    RawBehaviorDefinition,
    RawMetricDefinition,
    RetentionBehavior,
    RetentionMetric,
    SimpleBehavior,
    UpdateBehaviorParams,
    UpdateMetricParams,
    WarehouseMetric,
)

# =============================================================================
# WarehouseMetric
# =============================================================================


class TestWarehouseMetric:
    """WarehouseMetric holds a warehouse query and the server defaults."""

    def test_defaults(self) -> None:
        """Aggregation and sync interval default to the server fallbacks."""
        wm = WarehouseMetric(55, "SELECT 1", "numeric")
        assert wm.source_id == 55
        assert wm.sql == "SELECT 1"
        assert wm.metric_type == "numeric"
        assert wm.value_column is None
        assert wm.time_column is None
        assert wm.aggregation == "none"
        assert wm.sync_interval == "hourly"

    def test_frozen(self) -> None:
        """WarehouseMetric instances are immutable."""
        wm = WarehouseMetric(55, "SELECT 1", "numeric")
        with pytest.raises(AttributeError):
            wm.sql = "SELECT 2"  # type: ignore[misc]


# =============================================================================
# RawMetricDefinition and RawBehaviorDefinition
# =============================================================================


class TestRawMetricDefinition:
    """RawMetricDefinition carries a wire definition dict and its kind."""

    @pytest.mark.parametrize("kind", ["metric", "formula"])
    def test_behavior_and_formula_kinds(self, kind: str) -> None:
        """Metric and formula kinds take no warehouse source.

        Args:
            kind: The wire kind.
        """
        raw = RawMetricDefinition(kind, {"a": 1})  # type: ignore[arg-type]
        assert raw.type == kind
        assert raw.warehouse_source_id is None

    def test_warehouse_kind_with_source(self) -> None:
        """A warehouse kind keeps its source id."""
        raw = RawMetricDefinition("warehouse", {"query": "q"}, warehouse_source_id=5)
        assert raw.warehouse_source_id == 5

    def test_warehouse_kind_without_source_is_allowed(self) -> None:
        """A warehouse kind can omit the source id; an update keeps the stored one."""
        raw = RawMetricDefinition("warehouse", {"query": "q"})
        assert raw.warehouse_source_id is None

    def test_unknown_kind_refused(self) -> None:
        """A kind outside metric, formula, warehouse raises SM4_SCHEMA."""
        with pytest.raises(ParamValidationError) as exc_info:
            RawMetricDefinition("behavior", {})  # type: ignore[arg-type]
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "type"
        assert "SM4_SCHEMA" in CODED_GUARD_REGISTRY

    def test_source_on_non_warehouse_refused(self) -> None:
        """A warehouse source on a metric or formula kind raises SM4_SCHEMA."""
        with pytest.raises(ParamValidationError) as exc_info:
            RawMetricDefinition("metric", {}, warehouse_source_id=5)
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "warehouse_source_id"

    def test_non_mapping_definition_refused(self) -> None:
        """A definition that is not a mapping raises SM4_SCHEMA."""
        with pytest.raises(ParamValidationError) as exc_info:
            RawMetricDefinition("metric", [1, 2])  # type: ignore[arg-type]
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "definition"


class TestRawBehaviorDefinition:
    """RawBehaviorDefinition carries a wire behavior definition dict."""

    def test_behavior_type(self) -> None:
        """behavior_type reads definition.behavior.type."""
        raw = RawBehaviorDefinition({"behavior": {"type": "funnel", "behaviors": []}})
        assert raw.behavior_type == "funnel"

    def test_behavior_type_missing(self) -> None:
        """behavior_type is None when the definition has no type string."""
        assert RawBehaviorDefinition({"behavior": {}}).behavior_type is None
        assert RawBehaviorDefinition({}).behavior_type is None

    def test_non_mapping_definition_refused(self) -> None:
        """A definition that is not a mapping raises SM4_SCHEMA."""
        with pytest.raises(ParamValidationError) as exc_info:
            RawBehaviorDefinition("funnel")  # type: ignore[arg-type]
        assert exc_info.value.code == "SM4_SCHEMA"


# =============================================================================
# Params models
# =============================================================================


class TestCreateMetricParams:
    """CreateMetricParams takes a name, a typed definition, and optional metadata."""

    def test_minimal(self) -> None:
        """Name and definition are the only required fields."""
        params = CreateMetricParams(name="Logins", definition=Metric("Login"))
        assert params.description is None
        assert params.display is None
        assert params.goals is None
        assert params.owned_by is None
        assert params.verified is None

    def test_name_is_stripped(self) -> None:
        """Surrounding whitespace leaves the name."""
        params = CreateMetricParams(name="  Logins \n", definition=Metric("Login"))
        assert params.name == "Logins"

    @pytest.mark.parametrize(
        "definition",
        [
            Metric("Login", math="unique"),
            CohortMetric(123, "Power users"),
            FunnelMetric(FunnelBehavior(["Signup", "Purchase"])),
            RetentionMetric(RetentionBehavior("Signup", "Login")),
            Formula("A / B", metrics=[Metric("A"), Metric("B")]),
            WarehouseMetric(55, "SELECT 1", "numeric"),
            RawMetricDefinition("formula", {"formula": {}}),
        ],
    )
    def test_accepts_each_definition_type(self, definition: object) -> None:
        """Each supported definition value is kept as the same instance.

        Args:
            definition: A supported definition value.
        """
        params = CreateMetricParams(name="m", definition=definition)
        assert params.definition is definition

    def test_refuses_a_plain_dict(self) -> None:
        """A plain dict is not a definition; wrap it in RawMetricDefinition."""
        with pytest.raises(ValidationError):
            CreateMetricParams(name="m", definition={"behavior": {}})

    def test_all_fields(self) -> None:
        """Every optional field is kept."""
        params = CreateMetricParams(
            name="m",
            definition=Metric("Login"),
            description="d",
            display=MetricDisplay(suffix="%"),
            goals=[MetricGoal(label="Target")],
            owned_by=8,
            verified=True,
        )
        assert params.display == MetricDisplay(suffix="%")
        assert params.goals is not None
        assert params.goals[0].label == "Target"
        assert params.owned_by == 8
        assert params.verified is True

    def test_frozen(self) -> None:
        """CreateMetricParams instances are immutable."""
        params = CreateMetricParams(name="m", definition=Metric("Login"))
        with pytest.raises(ValidationError):
            params.name = "x"  # type: ignore[misc]


class TestUpdateMetricParams:
    """UpdateMetricParams has only optional fields."""

    def test_empty(self) -> None:
        """An empty update is valid."""
        params = UpdateMetricParams()
        assert params.model_dump() == {
            "name": None,
            "description": None,
            "definition": None,
            "display": None,
            "goals": None,
            "owned_by": None,
            "verified": None,
        }

    def test_name_is_stripped(self) -> None:
        """Surrounding whitespace leaves the name."""
        assert UpdateMetricParams(name=" x ").name == "x"

    def test_definition_instance(self) -> None:
        """A typed definition is kept as the same instance."""
        metric = Metric("Login")
        assert UpdateMetricParams(definition=metric).definition is metric


class TestBulkUpdateMetricEntry:
    """BulkUpdateMetricEntry holds an id plus the fields the server reads."""

    def test_fields(self) -> None:
        """Id and the optional fields are kept."""
        entry = BulkUpdateMetricEntry(id=7, verified=True, owned_by=8, name=" n ")
        assert entry.id == 7
        assert entry.verified is True
        assert entry.owned_by == 8
        assert entry.name == "n"
        assert entry.description is None
        assert entry.definition is None

    def test_id_must_be_positive(self) -> None:
        """A zero or negative id fails validation."""
        with pytest.raises(ValidationError):
            BulkUpdateMetricEntry(id=0)


class TestBehaviorParams:
    """CreateBehaviorParams and UpdateBehaviorParams."""

    def test_create(self) -> None:
        """Create takes a name, a raw behavior definition, and a description."""
        raw = RawBehaviorDefinition({"behavior": {"type": "simple"}})
        params = CreateBehaviorParams(name=" Any purchase ", behavior=raw)
        assert params.name == "Any purchase"
        assert params.behavior is raw
        assert params.description is None

    @pytest.mark.parametrize(
        "behavior",
        [
            SimpleBehavior(["Purchase", "Subscribe"]),
            FunnelBehavior(["View Cart", "Purchase"]),
            RetentionBehavior("Signup", "Login"),
        ],
    )
    def test_create_accepts_typed_behaviors(self, behavior: object) -> None:
        """Each typed behavior value is kept as the same instance.

        Args:
            behavior: A typed behavior value.
        """
        params = CreateBehaviorParams(name="b", behavior=behavior)
        assert params.behavior is behavior
        assert UpdateBehaviorParams(behavior=behavior).behavior is behavior

    def test_create_refuses_a_plain_dict(self) -> None:
        """A plain dict is not a behavior; wrap it in RawBehaviorDefinition."""
        with pytest.raises(ValidationError):
            CreateBehaviorParams(name="b", behavior={"behavior": {}})

    def test_update_defaults(self) -> None:
        """Every update field is optional."""
        params = UpdateBehaviorParams()
        assert params.name is None
        assert params.description is None
        assert params.behavior is None
        assert params.verified is None


# =============================================================================
# MetricGoal write side
# =============================================================================


class TestMetricGoalWriteSide:
    """MetricGoal as a write value."""

    def test_id_is_optional(self) -> None:
        """A goal without an id is valid; the write adds a UUID."""
        goal = MetricGoal(label="Target")
        assert goal.id is None

    def test_checkpoints_accept_dates(self) -> None:
        """Checkpoints take strings, dates, and datetimes."""
        goal = MetricGoal(
            label="Target",
            checkpoints=[
                ("2026-10-01T00:00:00", 1.0),
                (date(2026, 11, 1), 2.0),
                (datetime(2026, 12, 1, 6, 0), 3.0),
            ],
        )
        assert goal.checkpoints[1] == (date(2026, 11, 1), 2.0)
        assert goal.checkpoints[2] == (datetime(2026, 12, 1, 6, 0), 3.0)

    def test_string_checkpoint_stays_a_string(self) -> None:
        """A stored ISO string is not turned into a datetime on read."""
        goal = MetricGoal.model_validate(
            {"id": "g", "label": "L", "checkpoints": [["2025-11-01T00:00:00", 5000]]}
        )
        assert goal.checkpoints == [("2025-11-01T00:00:00", 5000.0)]
