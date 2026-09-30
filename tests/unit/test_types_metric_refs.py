"""Unit tests for the saved-entity reference types MetricRef and BehaviorRef.

Covers construction defaults, keyword-only fields, immutability, the
construction-time guards and their codes, and the registration of the
new codes in ``CODED_GUARD_REGISTRY``.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.query.metric_builders import (
    build_metric_ref_overrides,
)
from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    CODED_GUARD_TWIN_CODES,
    ParamValidationError,
)
from mixpanel_headless.types import (
    BehaviorRef,
    CustomPropertyRef,
    MetricRef,
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
        percentile_value = 95 if math == "percentile" else None
        ref = MetricRef(1, math=math, percentile_value=percentile_value)
        assert ref.math == math

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
# SavedMetric.to_ref / SavedBehavior.to_ref
# =============================================================================


class TestSavedMetricToRef:
    """Tests for SavedMetric.to_ref() — a saved metric as a MetricRef."""

    @pytest.mark.parametrize(
        ("row", "kind"),
        [
            (behavior_metric_json(), "metric"),
            (formula_metric_json(), "formula"),
            (warehouse_metric_json(), "warehouse"),
        ],
    )
    def test_kind_comes_from_the_saved_metric(
        self, row: dict[str, Any], kind: str
    ) -> None:
        """The reference carries the id and the kind of the saved metric."""
        metric = SavedMetric.model_validate(row)
        assert metric.to_ref() == MetricRef(metric.id, type=kind)  # type: ignore[arg-type]

    def test_typed_overrides_pass_through(self) -> None:
        """Every keyword reaches the reference field of the same name."""
        metric = SavedMetric.model_validate(behavior_metric_json(metric_id=42))
        ref = metric.to_ref(
            label="First buyers",
            math="average",
            property="amount",
            per_user="total",
            percentile_value=90,
            segment_method="first",
            funnel_order="any",
            step_index=1,
            bucket_index=2,
            hidden=False,
            overrides={"measurement": {"actionMode": "include"}},
        )
        assert ref == MetricRef(
            42,
            label="First buyers",
            math="average",
            property="amount",
            per_user="total",
            percentile_value=90,
            segment_method="first",
            funnel_order="any",
            step_index=1,
            bucket_index=2,
            hidden=False,
            overrides={"measurement": {"actionMode": "include"}},
        )

    def test_reference_guards_still_apply(self) -> None:
        """A filters override is refused on the way through."""
        metric = SavedMetric.model_validate(behavior_metric_json())
        with pytest.raises(ParamValidationError) as exc_info:
            metric.to_ref(overrides={"behavior": {"filters": []}})
        assert exc_info.value.code == "MR1_FILTER_OVERRIDE"

    def test_formula_refuses_behavior_overrides(self) -> None:
        """A saved formula takes no measurement override."""
        metric = SavedMetric.model_validate(formula_metric_json())
        with pytest.raises(ParamValidationError) as exc_info:
            metric.to_ref(math="unique")
        assert exc_info.value.code == "MR6_OVERRIDE_NOT_APPLICABLE"

    def test_legacy_kind_is_refused(self) -> None:
        """MR5_INVALID_TYPE: the server runs no legacy behavior row by reference."""
        metric = SavedMetric.model_validate(
            {**behavior_metric_json(), "type": "behavior"}
        )
        with pytest.raises(ParamValidationError) as exc_info:
            metric.to_ref()
        assert exc_info.value.code == "MR5_INVALID_TYPE"
        assert "behavior" in str(exc_info.value)


class TestSavedBehaviorToRef:
    """Tests for SavedBehavior.to_ref() — a saved behavior as a BehaviorRef."""

    @pytest.mark.parametrize("kind", ["simple", "funnel", "retention"])
    def test_type_and_id(self, kind: str) -> None:
        """The reference carries the id and the type of the saved behavior."""
        behavior = SavedBehavior.model_validate(
            saved_behavior_json(behavior_id=31, behavior_type=kind)
        )
        assert behavior.to_ref() == BehaviorRef(31, kind)  # type: ignore[arg-type]

    def test_unknown_type_is_refused(self) -> None:
        """BR2_INVALID_TYPE: an unknown stored type cannot be referenced."""
        behavior = SavedBehavior.model_validate(
            saved_behavior_json(behavior_type="cohort")
        )
        with pytest.raises(ParamValidationError) as exc_info:
            behavior.to_ref()
        assert exc_info.value.code == "BR2_INVALID_TYPE"


# =============================================================================
# Code registration
# =============================================================================


class TestMetricRefOverridesAreFrozen:
    """The raw overrides are copied into a read-only form at construction."""

    def test_later_mutation_of_the_callers_dict_has_no_effect(self) -> None:
        """A filter list added to the caller's dict afterwards never reaches the ref."""
        raw: dict[str, Any] = {"behavior": {"funnelOrder": "any"}}
        ref = MetricRef(1, overrides=raw)
        raw["behavior"]["filters"] = [{"value": "US"}]
        raw["measurement"] = {"math": "unique"}
        assert ref.overrides == {"behavior": {"funnelOrder": "any"}}
        assert build_metric_ref_overrides(ref) == {"behavior": {"funnelOrder": "any"}}

    def test_nested_values_are_read_only(self) -> None:
        """The stored mapping and its nested mappings cannot be changed."""
        ref = MetricRef(1, overrides={"behavior": {"funnelOrder": "any"}, "x": [1]})
        assert ref.overrides is not None
        with pytest.raises(TypeError):
            ref.overrides["behavior"]["filters"] = []
        with pytest.raises(TypeError):
            ref.overrides["y"] = 1  # type: ignore[index]
        assert ref.overrides["x"] == (1,)

    def test_builder_output_is_plain_json(self) -> None:
        """The builder writes plain dicts and lists, not the frozen forms."""
        ref = MetricRef(1, overrides={"measurement": {"x": [1, {"y": [2]}]}})
        written = build_metric_ref_overrides(ref)
        assert written == {"measurement": {"x": [1, {"y": [2]}]}}
        assert type(written["measurement"]) is dict
        assert type(written["measurement"]["x"]) is list
        assert type(written["measurement"]["x"][1]) is dict
        assert json.loads(json.dumps(written)) == written

    def test_equal_refs_compare_equal(self) -> None:
        """Two references with the same overrides are equal."""
        assert MetricRef(1, overrides={"a": {"b": 1}}) == MetricRef(
            1, overrides={"a": {"b": 1}}
        )


class TestMetricRefMeasurementRules:
    """The inline Metric combination rules run on the typed override fields."""

    @pytest.mark.parametrize("math", ["unique", "dau", "wau", "mau"])
    def test_per_user_with_user_count_math_raises_v3(self, math: str) -> None:
        """per_user with a user-count math raises V3_PER_USER_INCOMPATIBLE."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, math=math, per_user="average", property="amount")  # type: ignore[arg-type]
        assert exc_info.value.code == "V3_PER_USER_INCOMPATIBLE"

    @pytest.mark.parametrize("math", ["unique", "dau", "conversion_rate_unique"])
    def test_property_with_non_property_math_raises_v14(self, math: str) -> None:
        """A property with a math that takes none raises V14_METRIC_REJECTS_PROPERTY."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, math=math, property="amount")  # type: ignore[arg-type]
        assert exc_info.value.code == "V14_METRIC_REJECTS_PROPERTY"

    def test_percentile_without_value_raises_v26(self) -> None:
        """math="percentile" without a value raises V26_PERCENTILE_REQUIRES_VALUE."""
        with pytest.raises(ParamValidationError) as exc_info:
            MetricRef(1, math="percentile", property="ms")
        assert exc_info.value.code == "V26_PERCENTILE_REQUIRES_VALUE"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"math": "average"},
            {"math": "histogram"},
            {"per_user": "total"},
            {"math": "total", "property": "amount"},
            {"math": "percentile", "percentile_value": 95},
            {"per_user": "average", "math": "average"},
        ],
    )
    def test_partial_overrides_that_the_saved_metric_completes_pass(
        self, kwargs: dict[str, Any]
    ) -> None:
        """A field the saved definition can supply (property, per_user) is not required."""
        assert MetricRef(1, **kwargs).id == 1

    @pytest.mark.parametrize(
        "code", ["V3_PER_USER_INCOMPATIBLE", "V14_METRIC_REJECTS_PROPERTY"]
    )
    def test_codes_are_registered_twins(self, code: str) -> None:
        """The reused validator codes are registered as guard twins."""
        assert code in CODED_GUARD_TWIN_CODES


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
