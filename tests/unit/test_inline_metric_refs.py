"""Tests for saved-entity references inside inline metrics and formulas.

Covers a ``BehaviorRef`` as the behavior of a ``Metric`` (simple), a
``FunnelMetric`` (funnel), and a ``RetentionMetric`` (retention), and a
``MetricRef`` as a formula operand: construction guards, exact show-clause
and definition dicts, and the query validators.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from mixpanel_headless import Workspace
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.query.metric_builders import (
    build_formula_clause,
    build_formula_definition,
    build_funnel_metric_clause,
    build_inline_metric_clause,
    build_metric_clause,
    build_metric_definition,
    build_metric_ref_clause,
    build_retention_metric_clause,
)
from mixpanel_headless._internal.validation import (
    validate_bookmark,
    validate_query_args,
)
from mixpanel_headless.exceptions import CODED_GUARD_REGISTRY, ParamValidationError
from mixpanel_headless.types import (
    BehaviorRef,
    Filter,
    Formula,
    FormulaOperand,
    FunnelMetric,
    Metric,
    MetricRef,
    RetentionMetric,
    SavedMetric,
)
from tests.unit._saved_metric_fixtures import warehouse_metric_json

_TEST_SESSION = Session(
    account=ServiceAccount(
        name="test_account",
        region="us",
        username="test_user",
        secret=SecretStr("test_secret"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)
"""Fake session for ``Workspace(session=...)``."""

SIMPLE = BehaviorRef(31, "simple")
"""A saved simple behavior."""

FUNNEL = BehaviorRef(32, "funnel")
"""A saved funnel behavior."""

RETENTION = BehaviorRef(33, "retention")
"""A saved retention behavior."""


@pytest.fixture
def ws(mock_config_manager: MagicMock) -> Workspace:
    """Create Workspace with mocked dependencies for params testing."""
    return Workspace(session=_TEST_SESSION)


# =============================================================================
# Construction
# =============================================================================


class TestBehaviorRefConstruction:
    """A behavior reference must have the type that the metric needs."""

    def test_accepted_types(self) -> None:
        """Each metric takes a reference of its own behavior type."""
        assert Metric(SIMPLE, math="unique").event == SIMPLE
        assert FunnelMetric(FUNNEL).behavior == FUNNEL
        assert RetentionMetric(RETENTION).behavior == RETENTION

    @pytest.mark.parametrize(
        ("build", "wrong", "needed"),
        [
            (lambda ref: Metric(ref), FUNNEL, "simple"),
            (lambda ref: FunnelMetric(ref), RETENTION, "funnel"),
            (lambda ref: RetentionMetric(ref), SIMPLE, "retention"),
        ],
    )
    def test_wrong_type_raises_bh5(
        self, build: Any, wrong: BehaviorRef, needed: str
    ) -> None:
        """A reference of another type raises BH5_BEHAVIOR_REF_TYPE."""
        with pytest.raises(ParamValidationError) as excinfo:
            build(wrong)
        assert excinfo.value.code == "BH5_BEHAVIOR_REF_TYPE"
        assert f"needs a {needed} behavior" in excinfo.value.message

    def test_filters_with_behavior_ref_raise_mt3(self) -> None:
        """Metric filters cannot be combined with a saved behavior either."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(SIMPLE, filters=[Filter.equals("plan", "pro")])
        assert excinfo.value.code == "MT3_FILTERS_WITH_BEHAVIOR"

    def test_bh5_is_registered(self) -> None:
        """BH5_BEHAVIOR_REF_TYPE is a minted registry code."""
        assert "BH5_BEHAVIOR_REF_TYPE" in CODED_GUARD_REGISTRY


class TestMetricRefOperandConstruction:
    """A saved behavior metric can be a formula operand; a formula or warehouse cannot."""

    def test_behavior_metric_refs_are_operands(self) -> None:
        """Behavior-metric references are accepted operands."""
        operands: list[FormulaOperand] = [MetricRef(10), MetricRef(11), Metric("Login")]
        assert Formula("A + B + C", metrics=operands).metrics == operands

    def test_warehouse_ref_raises_fm7(self) -> None:
        """A warehouse reference raises FM7_WAREHOUSE_OPERAND."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A + B", metrics=[Metric("Login"), MetricRef(11, type="warehouse")])
        assert excinfo.value.code == "FM7_WAREHOUSE_OPERAND"
        assert "Formula.metrics[1]" in excinfo.value.message
        assert "behavior metrics" in excinfo.value.message

    def test_saved_warehouse_metric_ref_raises_fm7(self) -> None:
        """SavedMetric.to_ref() of a warehouse metric carries the kind and is refused."""
        saved = SavedMetric.model_validate(warehouse_metric_json())
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A", metrics=[saved.to_ref()])
        assert excinfo.value.code == "FM7_WAREHOUSE_OPERAND"

    def test_bare_ref_to_a_warehouse_metric_is_not_detected(self) -> None:
        """A bare MetricRef keeps the default kind, so the client cannot refuse it."""
        assert Formula("A", metrics=[MetricRef(11)]).metrics == [MetricRef(11)]

    def test_fm7_is_registered(self) -> None:
        """FM7_WAREHOUSE_OPERAND is a minted registry code."""
        assert "FM7_WAREHOUSE_OPERAND" in CODED_GUARD_REGISTRY

    def test_formula_ref_raises_fm3(self) -> None:
        """A reference to a saved formula cannot be an operand."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A", metrics=[MetricRef(12, type="formula")])
        assert excinfo.value.code == "FM3_NESTED_FORMULA"
        assert "Formula.metrics[0]" in excinfo.value.message

    def test_operand_ref_with_overrides_raises_mr2(self) -> None:
        """An operand reference with an override raises MR2_OPERAND_OVERRIDE."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A", metrics=[MetricRef(10, math="unique")])
        assert excinfo.value.code == "MR2_OPERAND_OVERRIDE"

    def test_operand_ref_with_label_raises_mr2(self) -> None:
        """A label is an override too; the server ignores it on an operand."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A", metrics=[MetricRef(10, label="x")])
        assert excinfo.value.code == "MR2_OPERAND_OVERRIDE"


# =============================================================================
# Show clauses and definitions
# =============================================================================


class TestBehaviorRefClauses:
    """A behavior reference is written as ``{type, id}`` with no ``behaviors``."""

    def test_metric_over_saved_simple_behavior(self) -> None:
        """A metric over a saved simple behavior writes the reference."""
        assert build_metric_clause(Metric(SIMPLE, math="unique")) == {
            "type": "metric",
            "behavior": {"type": "simple", "id": 31},
            "measurement": {"math": "unique"},
        }

    def test_funnel_metric_over_saved_funnel(self) -> None:
        """A funnel metric over a saved funnel writes the reference."""
        clause = build_funnel_metric_clause(
            FunnelMetric(FUNNEL, step_index=1, label="Checkout")
        )
        assert clause == {
            "type": "metric",
            "behavior": {"type": "funnel", "id": 32},
            "measurement": {
                "math": "conversion_rate_unique",
                "property": None,
                "stepIndex": 1,
            },
            "name": "Checkout",
        }

    def test_retention_metric_over_saved_retention(self) -> None:
        """A retention metric over a saved retention writes the reference."""
        clause = build_retention_metric_clause(
            RetentionMetric(RETENTION, bucket_index=7), hidden=True
        )
        assert clause == {
            "type": "metric",
            "behavior": {"type": "retention", "id": 33},
            "measurement": {"math": "retention_rate", "retentionBucketIndex": 7},
            "isHidden": True,
        }

    @pytest.mark.parametrize(
        ("metric", "behavior"),
        [
            (Metric(SIMPLE), {"type": "simple", "id": 31}),
            (FunnelMetric(FUNNEL), {"type": "funnel", "id": 32}),
            (RetentionMetric(RETENTION), {"type": "retention", "id": 33}),
        ],
    )
    def test_definition_keeps_the_reference(
        self,
        metric: Metric | FunnelMetric | RetentionMetric,
        behavior: dict[str, Any],
    ) -> None:
        """A saved metric over a saved behavior stores the reference."""
        assert build_metric_definition(metric)["behavior"] == behavior


class TestMetricRefOperands:
    """A saved metric operand is written as ``{type, id}``."""

    def test_formula_clause(self) -> None:
        """Reference operands keep their type; inline operands keep their blocks."""
        formula = Formula(
            "A / B + C",
            metrics=[MetricRef(10), MetricRef(11), Metric("Login")],
        )
        assert build_formula_clause(formula)["referencedMetrics"] == [
            {"type": "metric", "id": 10},
            {"type": "metric", "id": 11},
            {"type": "metric", **build_metric_definition(Metric("Login"))},
        ]

    def test_formula_definition(self) -> None:
        """A saved formula over saved metrics stores ``{type, id}`` operands."""
        formula = Formula("A / B", metrics=[MetricRef(10), MetricRef(20)])
        assert build_formula_definition(formula) == {
            "formula": {
                "definition": "A / B",
                "referencedMetrics": [
                    {"type": "metric", "id": 10},
                    {"type": "metric", "id": 20},
                ],
            }
        }

    def test_top_level_ref_uses_the_reference_clause(self) -> None:
        """The dispatcher writes a top-level reference as the reference clause."""
        ref = MetricRef(10, segment_method="first")
        assert build_inline_metric_clause(ref, hidden=True) == (
            build_metric_ref_clause(ref, hidden=True)
        )


# =============================================================================
# Validation
# =============================================================================


def _args(events: list[Any], formulas: list[Formula] | None = None) -> list[Any]:
    """Run ``validate_query_args`` with neutral query-level arguments."""
    resolved = formulas or []
    return validate_query_args(
        events=events,
        math="total",
        math_property=None,
        per_user=None,
        from_date=None,
        to_date=None,
        last=30,
        has_formula=any(f.metrics is None for f in resolved),
        rolling=None,
        cumulative=False,
        group_by=None,
        formulas=resolved,
    )


class TestValidationWithReferences:
    """The behavior rules do not run on a saved behavior; the server owns it."""

    def test_layer_one_accepts_references(self) -> None:
        """Metrics over saved behaviors and reference operands pass Layer 1."""
        formula = Formula("A / B", metrics=[MetricRef(10), Metric(SIMPLE)])
        events = [
            Metric(SIMPLE, math="unique"),
            FunnelMetric(FUNNEL, math="conversion_rate_session"),
            RetentionMetric(RETENTION),
        ]
        assert _args(events, [formula]) == []

    def test_layer_two_accepts_behavior_references(self) -> None:
        """A simple behavior reference needs no name in Layer 2."""
        show = [
            build_metric_clause(Metric(SIMPLE)),
            build_funnel_metric_clause(FunnelMetric(FUNNEL)),
            build_retention_metric_clause(RetentionMetric(RETENTION)),
            build_formula_clause(Formula("A", metrics=[MetricRef(10)])),
        ]
        bookmark = {"sections": {"show": show}, "displayOptions": {"chartType": "line"}}
        assert validate_bookmark(bookmark) == []

    def test_build_params(self, ws: Workspace) -> None:
        """``build_params`` writes a formula over saved metrics alone."""
        formula = Formula(
            "A / B", label="Ratio", metrics=[MetricRef(10), MetricRef(20)]
        )
        show = ws.build_params(formula)["sections"]["show"]
        assert show == [
            {
                "type": "formula",
                "definition": "A / B",
                "measurement": {},
                "referencedMetrics": [
                    {"type": "metric", "id": 10},
                    {"type": "metric", "id": 20},
                ],
                "name": "Ratio",
            }
        ]
