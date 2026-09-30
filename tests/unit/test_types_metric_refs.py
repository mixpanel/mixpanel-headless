"""Unit tests for the saved-entity reference types MetricRef and BehaviorRef.

Covers construction defaults, keyword-only fields, immutability, the
construction-time guards and their codes, and the registration of the
new codes in ``CODED_GUARD_REGISTRY``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import CODED_GUARD_REGISTRY, ParamValidationError
from mixpanel_headless.types import (
    BehaviorRef,
    CustomPropertyRef,
    MetricRef,
)

# =============================================================================
# MetricRef — construction
# =============================================================================


class TestMetricRefConstruction:
    """Tests for MetricRef defaults and field handling."""

    def test_id_only_defaults(self) -> None:
        """An id alone gives a behavior-metric reference with no overrides."""
        ref = MetricRef(42)
        assert ref.id == 42
        assert ref.type == "metric"
        assert ref.label is None
        assert ref.math is None
        assert ref.property is None
        assert ref.per_user is None
        assert ref.percentile_value is None
        assert ref.segment_method is None
        assert ref.funnel_order is None
        assert ref.step_index is None
        assert ref.bucket_index is None
        assert ref.hidden is None
        assert ref.overrides is None

    def test_fields_after_id_are_keyword_only(self) -> None:
        """Every field after id must be passed by keyword."""
        with pytest.raises(TypeError):
            MetricRef(42, "formula")  # type: ignore[misc]

    def test_every_typed_field(self) -> None:
        """Every typed field is stored as given."""
        ref = MetricRef(
            7,
            label="Buyers",
            math="percentile",
            property=CustomPropertyRef(3),
            per_user="average",
            percentile_value=95,
            segment_method="first",
            funnel_order="any",
            step_index=2,
            bucket_index=1,
            hidden=True,
            overrides={"measurement": {"actionMode": "include"}},
        )
        assert ref.label == "Buyers"
        assert ref.math == "percentile"
        assert ref.property == CustomPropertyRef(3)
        assert ref.per_user == "average"
        assert ref.percentile_value == 95
        assert ref.segment_method == "first"
        assert ref.funnel_order == "any"
        assert ref.step_index == 2
        assert ref.bucket_index == 1
        assert ref.hidden is True
        assert ref.overrides == {"measurement": {"actionMode": "include"}}

    @pytest.mark.parametrize("kind", ["metric", "formula", "warehouse"])
    def test_each_kind(self, kind: Any) -> None:
        """Each saved metric kind is a valid reference type."""
        assert MetricRef(1, type=kind).type == kind

    def test_frozen(self) -> None:
        """A MetricRef cannot be changed after construction."""
        ref = MetricRef(1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = 2  # type: ignore[misc]

    def test_equality_and_hash(self) -> None:
        """Two references with the same fields are equal and hash the same."""
        assert MetricRef(5, math="unique") == MetricRef(5, math="unique")
        assert hash(MetricRef(5)) == hash(MetricRef(5))

    def test_exported_from_package_root(self) -> None:
        """MetricRef and BehaviorRef are public exports."""
        assert mp.MetricRef is MetricRef
        assert mp.BehaviorRef is BehaviorRef
        assert "MetricRef" in mp.__all__
        assert "BehaviorRef" in mp.__all__


# =============================================================================
# MetricRef — guards
# =============================================================================


class TestMetricRefIdGuard:
    """MR4_INVALID_ID: the id is a positive integer."""

    @pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, "12", None])
    def test_rejects_bad_id(self, bad: Any) -> None:
        """Zero, negatives, booleans, floats, strings, and None are refused."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(bad)
        assert exc_info.value.code == "MR4_INVALID_ID"

    def test_error_is_a_value_error(self) -> None:
        """The guard stays catchable as ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            MetricRef(0)


class TestMetricRefTypeGuard:
    """MR5_INVALID_TYPE: the type is metric, formula, or warehouse."""

    @pytest.mark.parametrize("bad", ["behavior", "Metric", "", "simple"])
    def test_rejects_unknown_type(self, bad: Any) -> None:
        """Legacy and unknown kinds are refused."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, type=bad)
        assert exc_info.value.code == "MR5_INVALID_TYPE"


class TestMetricRefFilterOverrideGuard:
    """MR1_FILTER_OVERRIDE: raw overrides hold no filters at any depth."""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"behavior": {"filters": []}},
            {"behavior": {"filters": [{"value": "US"}]}},
            {"filters": []},
            {"behavior": {"filter": []}},
            {"behavior": {"behaviors": [{"filters": []}]}},
        ],
    )
    def test_rejects_filters(self, overrides: dict[str, Any]) -> None:
        """A filters or filter key anywhere in overrides is refused."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, overrides=overrides)
        assert exc_info.value.code == "MR1_FILTER_OVERRIDE"

    def test_message_names_both_alternatives(self) -> None:
        """The message names report-level where= and a detached inline copy."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, overrides={"behavior": {"filters": []}})
        message = str(exc_info.value)
        assert "where=" in message
        assert "inline" in message
        assert "index" in message

    def test_filters_determiner_is_allowed(self) -> None:
        """A scalar key that only starts with filters is not a filter list."""
        ref = MetricRef(1, overrides={"behavior": {"filtersDeterminer": "any"}})
        assert ref.overrides == {"behavior": {"filtersDeterminer": "any"}}


class TestMetricRefOverrideValueGuard:
    """MR7_INVALID_OVERRIDE: typed overrides and the raw mapping are well formed."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"math": "conversion"},
            {"math": "custom_percentile"},
            {"per_user": "median"},
            {"funnel_order": "strict"},
            {"step_index": -1},
            {"step_index": True},
            {"step_index": 1.0},
            {"bucket_index": -2},
            {"bucket_index": False},
            {"percentile_value": float("nan")},
            {"percentile_value": float("inf")},
            {"percentile_value": True},
            {"percentile_value": "95"},
            {"label": ""},
            {"label": "   "},
            {"hidden": 1},
            {"overrides": [("measurement", {})]},
            {"overrides": {1: "x"}},
        ],
    )
    def test_rejects_bad_value(self, kwargs: dict[str, Any]) -> None:
        """Each malformed typed override or raw mapping is refused."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, **kwargs)
        assert exc_info.value.code == "MR7_INVALID_OVERRIDE"

    @pytest.mark.parametrize(
        "math", ["unique", "percentile", "conversion_rate_unique", "retention_rate"]
    )
    def test_accepts_math_of_every_engine(self, math: Any) -> None:
        """Insights, funnel, and retention maths are all valid overrides."""
        assert MetricRef(1, math=math).math == math

    def test_accepts_zero_indexes(self) -> None:
        """Step and bucket index zero are valid."""
        ref = MetricRef(1, step_index=0, bucket_index=0)
        assert (ref.step_index, ref.bucket_index) == (0, 0)

    def test_empty_overrides_mapping_is_allowed(self) -> None:
        """An empty raw mapping is valid and adds nothing."""
        assert MetricRef(1, overrides={}).overrides == {}


class TestMetricRefSegmentMethodGuard:
    """MT2_INVALID_SEGMENT_METHOD: the same rule and code as Metric."""

    def test_rejects_unknown_segment_method(self) -> None:
        """A segment method other than all or first is refused."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, segment_method="last")  # type: ignore[arg-type]
        assert exc_info.value.code == "MT2_INVALID_SEGMENT_METHOD"


class TestMetricRefKindGuard:
    """MR6_OVERRIDE_NOT_APPLICABLE: behavior-metric overrides need a metric kind."""

    @pytest.mark.parametrize("kind", ["formula", "warehouse"])
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"math": "unique"},
            {"property": "amount"},
            {"per_user": "total"},
            {"percentile_value": 90},
            {"segment_method": "first"},
            {"funnel_order": "loose"},
            {"step_index": 0},
            {"bucket_index": 0},
        ],
    )
    def test_rejects_behavior_overrides(
        self, kind: Any, kwargs: dict[str, Any]
    ) -> None:
        """A formula or warehouse reference refuses measurement and behavior fields."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, type=kind, **kwargs)
        assert exc_info.value.code == "MR6_OVERRIDE_NOT_APPLICABLE"

    @pytest.mark.parametrize("kind", ["formula", "warehouse"])
    def test_allows_label_hidden_and_raw(self, kind: Any) -> None:
        """Label, hidden, and raw overrides apply to every kind."""
        ref = MetricRef(
            1,
            type=kind,
            label="Revenue",
            hidden=False,
            overrides={"measurement": {"cumulative": True}},
        )
        assert ref.label == "Revenue"


# =============================================================================
# BehaviorRef
# =============================================================================


class TestBehaviorRef:
    """Tests for BehaviorRef construction and guards."""

    @pytest.mark.parametrize("kind", ["simple", "funnel", "retention"])
    def test_each_kind(self, kind: Any) -> None:
        """Each saved behavior type is valid."""
        ref = BehaviorRef(9, kind)
        assert (ref.id, ref.type) == (9, kind)

    def test_type_is_required(self) -> None:
        """A BehaviorRef needs its type, because the engines check it."""
        with pytest.raises(TypeError):
            BehaviorRef(9)  # type: ignore[call-arg]

    @pytest.mark.parametrize("bad", [0, -3, True, 2.0, "9"])
    def test_rejects_bad_id(self, bad: Any) -> None:
        """BR1_INVALID_ID: the id is a positive integer."""
        with pytest.raises(ParamValidationError) as exc_info:
            BehaviorRef(bad, "funnel")
        assert exc_info.value.code == "BR1_INVALID_ID"

    @pytest.mark.parametrize("bad", ["event", "cohort", "Funnel", ""])
    def test_rejects_unknown_type(self, bad: Any) -> None:
        """BR2_INVALID_TYPE: the type is simple, funnel, or retention."""
        with pytest.raises(ParamValidationError) as exc_info:
            BehaviorRef(1, bad)
        assert exc_info.value.code == "BR2_INVALID_TYPE"

    def test_frozen(self) -> None:
        """A BehaviorRef cannot be changed after construction."""
        ref = BehaviorRef(1, "funnel")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.type = "retention"  # type: ignore[misc]


# =============================================================================
# Code registration
# =============================================================================


class TestReferenceCodesRegistered:
    """The new guard codes are in CODED_GUARD_REGISTRY."""

    @pytest.mark.parametrize(
        "code",
        [
            "MR1_FILTER_OVERRIDE",
            "MR2_OPERAND_OVERRIDE",
            "MR4_INVALID_ID",
            "MR5_INVALID_TYPE",
            "MR6_OVERRIDE_NOT_APPLICABLE",
            "MR7_INVALID_OVERRIDE",
            "BR1_INVALID_ID",
            "BR2_INVALID_TYPE",
        ],
    )
    def test_registered(self, code: str) -> None:
        """Each reference guard code is registered."""
        assert code in CODED_GUARD_REGISTRY
