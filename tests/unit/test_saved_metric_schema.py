"""Unit tests for the saved metric and saved behavior definition mirrors.

The mirrors in ``src/mixpanel_headless/_internal/bookmark_schema.py`` copy
the server models that generate the POST JSON Schema of the ``/metrics`` and
``/behaviors`` App API endpoints, at analytics commit ``a7a57abaae7``:

- ``lib/common/mxpnl/report/metric/models.py``: ``ReferencedMetricClause``,
  ``FormulaInnerDefinition``, ``FormulaMetricDefinition``,
  ``BehaviorMetricDefinition``
- ``lib/common/mxpnl/report/bookmarks/insights/show.py``:
  ``WarehouseShowClauseDefinition``, ``MetricDisplay``, ``SubBehavior``,
  ``Behavior``, ``BehaviorMeasurement``, ``FormulaMeasurement``
- ``lib/common/mxpnl/report/bookmarks/common/definitions.py``: ``Goal``
- ``webapp/app_api/projects/behaviors/__types__/behaviors_req.py``: the
  ``definition`` object of a saved behavior (``{"behavior": Behavior}``)

The field-set tests pin each mirror to the server field list, so a change on
either side fails here and names the class to compare. The other tests check
that live-shaped definitions pass and that unknown keys and bad values fail
with a field path.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from mixpanel_headless._internal.bookmark_schema import (
    Behavior,
    BehaviorMeasurement,
    BehaviorMetricDefinition,
    FormulaInnerDefinition,
    FormulaMeasurement,
    FormulaMetricDefinition,
    Goal,
    MetricDisplay,
    ReferencedMetricClause,
    SavedBehaviorDefinition,
    SubBehavior,
    WarehouseShowClauseDefinition,
    validate_with_pydantic,
)
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    formula_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
)


def _wire_fields(model: type[BaseModel]) -> set[str]:
    """Return the wire key of every field of a mirror model.

    Args:
        model: A mirror model class.

    Returns:
        The alias of each field when it has one, otherwise the field name.
    """
    return {info.alias or name for name, info in model.model_fields.items()}


# =============================================================================
# Pinned field lists (server models at a7a57abaae7)
# =============================================================================


_BEHAVIOR_SHOW_CLAUSE_FIELDS = {
    "_idx",
    "type",
    "id",
    "userNamed",
    "name",
    "behavior",
    "measurement",
    "statsig",
    "srm",
    "comparisons",
    "display",
    "isHidden",
    "isExpanded",
    "labelPrefix",
    "formulaLabel",
    "showClauseIndex",
    "hasUnsavedChanges",
    "goals",
    "overrides",
}
"""Fields of show.py ``BehaviorShowClause`` that the mirror declares."""


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            WarehouseShowClauseDefinition,
            {
                "query",
                "metricType",
                "aggregation",
                "syncInterval",
                "timeColumn",
                "valueColumn",
                "measurement",
                "goals",
                "display",
            },
        ),
        (FormulaInnerDefinition, {"definition", "referencedMetrics"}),
        (FormulaMetricDefinition, {"display", "measurement", "formula", "goals"}),
        (BehaviorMetricDefinition, {"display", "measurement", "behavior", "goals"}),
        (SavedBehaviorDefinition, {"behavior"}),
        (ReferencedMetricClause, _BEHAVIOR_SHOW_CLAUSE_FIELDS | {"metric_id"}),
        (
            MetricDisplay,
            {
                "abbrev",
                "axis",
                "direction",
                "hideTrendline",
                "minimumDetectableEffect",
                "oneSided",
                "power",
                "precision",
                "prefix",
                "suffix",
                "trendline",
            },
        ),
        (
            Goal,
            {
                "id",
                "label",
                "checkpoints",
                "target_type",
                "target_input",
                "unit",
                "direction",
            },
        ),
        (FormulaMeasurement, {"cumulative", "rolling", "multiAttribution"}),
        (
            BehaviorMeasurement,
            {
                "dataGroupId",
                "math",
                "property",
                "cumulative",
                "perUserAggregation",
                "rolling",
                "segmentMethod",
                "multiAttribution",
                "stepIndex",
                "actionMode",
                "actionStep",
                "retentionBucketIndex",
                "retentionCumulative",
                "retentionSegmentationEvent",
                "percentile",
                "id",
                "type",
            },
        ),
        (
            SubBehavior,
            {
                "_idx",
                "type",
                "id",
                "name",
                "renamed",
                "filters",
                "filtersDeterminer",
                "funnelOrder",
                "behaviors",
                "display",
                "customEventSet",
            },
        ),
        (
            Behavior,
            {
                "type",
                "id",
                "name",
                "renamed",
                "dataGroupId",
                "filter",
                "filters",
                "filtersDeterminer",
                "resourceType",
                "behaviors",
                "raw_cohort",
                "customBucket",
                "conversionWindowDuration",
                "conversionWindowUnit",
                "funnelReentryMode",
                "funnelOrder",
                "exclusions",
                "aggregateBy",
                "retentionType",
                "retentionAlignmentType",
                "retentionUnit",
                "retentionUnbounded",
                "retentionUnboundedMode",
                "retentionCustomBucketSizes",
                "segmentationEvent",
                "unsavedId",
                "search",
                "profileType",
                "dataset",
                "datasetId",
                "projectId",
                "display",
                "disableCohortize",
                "customEventSet",
                "hasUnsavedChanges",
            },
        ),
    ],
)
def test_field_lists_match_server_models(
    model: type[BaseModel], expected: set[str]
) -> None:
    """Each mirror declares exactly the fields of its server model.

    Args:
        model: The mirror model class.
        expected: The wire keys of the server model at a7a57abaae7.
    """
    assert _wire_fields(model) == expected


@pytest.mark.parametrize(
    ("model", "required"),
    [
        (WarehouseShowClauseDefinition, {"query", "metricType"}),
        (FormulaInnerDefinition, {"definition", "referencedMetrics"}),
        (FormulaMetricDefinition, {"formula"}),
        (BehaviorMetricDefinition, {"measurement", "behavior"}),
        (SavedBehaviorDefinition, {"behavior"}),
        (Goal, {"id", "label", "checkpoints"}),
    ],
)
def test_required_fields_match_server_models(
    model: type[BaseModel], required: set[str]
) -> None:
    """Each mirror requires exactly the fields its server model requires.

    Args:
        model: The mirror model class.
        required: The required wire keys of the server model.
    """
    actual = {
        info.alias or name
        for name, info in model.model_fields.items()
        if info.is_required()
    }
    assert actual == required


def test_all_mirrors_forbid_unknown_keys() -> None:
    """Every definition mirror rejects keys it does not declare, as the server does."""
    for model in (
        WarehouseShowClauseDefinition,
        FormulaInnerDefinition,
        FormulaMetricDefinition,
        BehaviorMetricDefinition,
        SavedBehaviorDefinition,
        ReferencedMetricClause,
        MetricDisplay,
    ):
        assert model.model_config.get("extra") == "forbid", model.__name__


# =============================================================================
# Live-shaped definitions pass
# =============================================================================


class TestAcceptedDefinitions:
    """Definitions in the stored shapes pass their mirror."""

    def test_behavior_metric(self) -> None:
        """A simple behavior metric with display and goals passes."""
        definition = behavior_metric_json()["definition"]
        assert validate_with_pydantic(BehaviorMetricDefinition, definition) == []

    def test_formula_with_reference_and_inline_operands(self) -> None:
        """A formula with id operands (plus metric_id) and an inline operand passes."""
        definition = formula_metric_json()["definition"]
        assert validate_with_pydantic(FormulaMetricDefinition, definition) == []

    def test_warehouse_metric(self) -> None:
        """A synced timeseries warehouse definition passes."""
        definition = warehouse_metric_json()["definition"]
        assert validate_with_pydantic(WarehouseShowClauseDefinition, definition) == []

    def test_saved_behavior(self) -> None:
        """A funnel behavior definition passes."""
        definition = saved_behavior_json()["definition"]
        assert validate_with_pydantic(SavedBehaviorDefinition, definition) == []

    def test_behavior_reference_in_metric(self) -> None:
        """A behavior metric whose behavior is a saved-behavior reference passes."""
        definition = {
            "behavior": {"type": "funnel", "id": 58856},
            "measurement": {"math": "conversion_rate_unique"},
        }
        assert validate_with_pydantic(BehaviorMetricDefinition, definition) == []

    def test_display_sizing_keys(self) -> None:
        """The experiment sizing keys of MetricDisplay pass."""
        display = {"minimumDetectableEffect": 0.05, "oneSided": True, "power": 0.8}
        assert validate_with_pydantic(MetricDisplay, display) == []

    def test_sub_behavior_ui_index(self) -> None:
        """A sub-behavior with the UI key ``_idx`` passes."""
        definition = saved_behavior_json()["definition"]
        definition["behavior"]["behaviors"][0]["_idx"] = "a1"
        assert validate_with_pydantic(SavedBehaviorDefinition, definition) == []


# =============================================================================
# Refused definitions carry a field path
# =============================================================================


class TestRefusedDefinitions:
    """Bad definitions fail with the path of the bad field."""

    def test_unknown_key_in_behavior(self) -> None:
        """An unknown key under behavior names its path."""
        definition = behavior_metric_json()["definition"]
        definition["behavior"]["bogus"] = 1
        errors = validate_with_pydantic(
            BehaviorMetricDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.behavior.bogus"]

    def test_bad_math(self) -> None:
        """A math outside the server enum fails at measurement.math."""
        definition = behavior_metric_json()["definition"]
        definition["measurement"]["math"] = "not_a_math"
        errors = validate_with_pydantic(
            BehaviorMetricDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.measurement.math"]

    def test_chart_type_in_display_is_refused(self) -> None:
        """``display.chartType`` is outside the server model and fails."""
        definition = behavior_metric_json()["definition"]
        definition["display"]["chartType"] = "bar"
        errors = validate_with_pydantic(
            BehaviorMetricDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.display.chartType"]

    def test_formula_measurement_rejects_math(self) -> None:
        """A formula's own measurement has no math key."""
        definition: dict[str, Any] = formula_metric_json()["definition"]
        definition["measurement"] = {"math": "total"}
        errors = validate_with_pydantic(
            FormulaMetricDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.measurement.math"]

    def test_missing_measurement(self) -> None:
        """A behavior metric without a measurement fails."""
        definition = behavior_metric_json()["definition"]
        del definition["measurement"]
        errors = validate_with_pydantic(
            BehaviorMetricDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.measurement"]

    def test_warehouse_bad_sync_interval(self) -> None:
        """A sync interval outside the server enum fails."""
        definition = warehouse_metric_json()["definition"]
        definition["syncInterval"] = "yearly"
        errors = validate_with_pydantic(
            WarehouseShowClauseDefinition, definition, path_prefix="definition"
        )
        assert [e.path for e in errors] == ["definition.syncInterval"]

    def test_saved_behavior_extra_top_level_key(self) -> None:
        """A saved behavior definition holds only ``behavior``."""
        errors = validate_with_pydantic(
            SavedBehaviorDefinition,
            {"behavior": {"type": "simple"}, "measurement": {}},
            path_prefix="definition",
        )
        assert [e.path for e in errors] == ["definition.measurement"]
