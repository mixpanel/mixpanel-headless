"""Property-based tests for saved-metric reference overrides.

Invariants: typed overrides never write a list (the server merges lists
item by item), raw overrides merge last and win, the reference clause
always holds its type and id, the overrides are plain JSON, and a
``property`` that is not a property name, a ``CustomPropertyRef``, or an
``InlineCustomProperty`` raises ``MR7_INVALID_OVERRIDE``, as does an
``overrides`` that is not a mapping on ``SavedMetric.to_ref``. Hypothesis
profiles come from ``tests/conftest.py`` (``default``, ``dev``, ``ci``).
"""

from __future__ import annotations

import json
from typing import Any, get_args

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.bookmark_enums import (
    MATH_NO_PER_USER,
    MATH_PROPERTY_OPTIONAL,
    MATH_REQUIRING_PROPERTY,
)
from mixpanel_headless._internal.query.metric_builders import (
    build_metric_ref_clause,
    build_metric_ref_overrides,
    build_operand_ref_clause,
)
from mixpanel_headless._literal_types import (
    FunnelMathType,
    FunnelOrder,
    MathType,
    PerUserAggregation,
    RetentionMathType,
    SegmentMethod,
)
from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import (
    CustomPropertyRef,
    InlineCustomProperty,
    MetricRef,
    SavedMetric,
)
from tests.unit._saved_metric_fixtures import behavior_metric_json

_MATHS = sorted(
    set(get_args(MathType))
    | set(get_args(FunnelMathType))
    | set(get_args(RetentionMathType))
)

_labels = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")
_properties = st.one_of(
    st.text(max_size=20),
    st.integers(min_value=1, max_value=10**6).map(CustomPropertyRef),
    st.sampled_from(["price", "quantity"]).map(
        lambda name: InlineCustomProperty.numeric("A * 2", A=name)
    ),
)
"""Every accepted property type: a name, a saved custom property, an inline one."""

_not_properties = st.one_of(
    st.booleans(),
    st.integers(),
    st.floats(),
    st.lists(st.text(max_size=5), max_size=3),
    st.dictionaries(st.text(max_size=5), st.text(max_size=5), max_size=3),
)
"""Values that are not a property name, a CustomPropertyRef, or an InlineCustomProperty."""


_measurement_fields = st.tuples(
    st.none() | st.sampled_from(_MATHS),
    st.none() | _properties,
    st.none() | st.sampled_from(get_args(PerUserAggregation)),
    st.none()
    | st.integers(min_value=1, max_value=99)
    | st.floats(min_value=0.5, max_value=99.5, allow_nan=False),
)
"""Any mix of math, property, per_user, and percentile_value."""

_TAKES_PROPERTY = MATH_REQUIRING_PROPERTY | MATH_PROPERTY_OPTIONAL
"""Maths that take a property."""


def _consistent(
    math: Any, prop: Any, per_user: Any, percentile_value: Any
) -> tuple[Any, Any, Any, Any]:
    """Drop measurement fields so that they do not contradict.

    Args:
        math: The drawn math, or ``None``.
        prop: The drawn property, or ``None``.
        per_user: The drawn per-user aggregation, or ``None``.
        percentile_value: The drawn percentile value, or ``None``.

    Returns:
        The four fields, with ``per_user`` dropped for a user-count math and
        ``property`` dropped for a math that takes none.
    """
    if math in MATH_NO_PER_USER:
        per_user = None
    if math is not None and math not in _TAKES_PROPERTY:
        prop = None
    return math, prop, per_user, percentile_value


@st.composite
def typed_refs(draw: st.DrawFn) -> MetricRef:
    """Draw a behavior-metric MetricRef with any mix of typed overrides.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        A MetricRef with no raw overrides. The measurement fields never
        contradict each other (see ``_measurement_fields``).
    """
    math, prop, per_user, percentile_value = _consistent(*draw(_measurement_fields))
    return MetricRef(
        draw(st.integers(min_value=1, max_value=10**9)),
        label=draw(st.none() | _labels),
        math=math,
        property=prop,
        per_user=per_user,
        percentile_value=percentile_value,
        segment_method=draw(st.none() | st.sampled_from(get_args(SegmentMethod))),
        funnel_order=draw(st.none() | st.sampled_from(get_args(FunnelOrder))),
        step_index=draw(st.none() | st.integers(min_value=0, max_value=20)),
        bucket_index=draw(st.none() | st.integers(min_value=0, max_value=20)),
        hidden=draw(st.none() | st.booleans()),
    )


def _contains_list(value: Any) -> bool:
    """Return whether a nested value holds a list anywhere.

    Args:
        value: A dict, a list, or a scalar.

    Returns:
        ``True`` when a list appears at any depth.
    """
    if isinstance(value, list):
        return True
    if isinstance(value, dict):
        return any(_contains_list(child) for child in value.values())
    return False


_json_scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=10)
_raw_keys = st.sampled_from(["name", "measurement", "display", "isHidden", "goals"])
_raw_leaf_keys = st.sampled_from(["math", "actionMode", "prefix", "cumulative"])
_raw_overrides = st.dictionaries(
    _raw_keys,
    _json_scalars | st.dictionaries(_raw_leaf_keys, _json_scalars, max_size=3),
    max_size=4,
)


@given(ref=typed_refs())
def test_typed_overrides_never_emit_a_list(ref: MetricRef) -> None:
    """No typed field writes a list, at any depth."""
    assert not _contains_list(build_metric_ref_overrides(ref))


@given(ref=typed_refs())
def test_overrides_are_plain_json(ref: MetricRef) -> None:
    """The overrides serialize to JSON and back without change."""
    overrides = build_metric_ref_overrides(ref)
    assert json.loads(json.dumps(overrides)) == overrides


@given(ref=typed_refs(), hidden=st.booleans())
def test_clause_starts_with_type_and_id(ref: MetricRef, hidden: bool) -> None:
    """Every reference clause starts with its type and id."""
    clause = build_metric_ref_clause(ref, hidden=hidden)
    assert list(clause)[:2] == ["type", "id"]
    assert (clause["type"], clause["id"]) == (ref.type, ref.id)
    assert ("overrides" in clause) == bool(build_metric_ref_overrides(ref))
    assert clause.get("isHidden", False) is hidden


@given(ref=typed_refs(), raw=_raw_overrides)
def test_raw_overrides_merge_last(ref: MetricRef, raw: dict[str, Any]) -> None:
    """Every raw leaf value reaches the result unchanged."""
    merged = MetricRef(
        ref.id,
        label=ref.label,
        math=ref.math,
        property=ref.property,
        per_user=ref.per_user,
        percentile_value=ref.percentile_value,
        segment_method=ref.segment_method,
        funnel_order=ref.funnel_order,
        step_index=ref.step_index,
        bucket_index=ref.bucket_index,
        hidden=ref.hidden,
        overrides=raw,
    )
    result = build_metric_ref_overrides(merged)
    typed = build_metric_ref_overrides(ref)
    for key, value in raw.items():
        if isinstance(value, dict):
            assert isinstance(result[key], dict)
            for leaf_key, leaf_value in value.items():
                assert result[key][leaf_key] == leaf_value
            if isinstance(typed.get(key), dict):
                for typed_key, typed_value in typed[key].items():
                    if typed_key not in value:
                        assert result[key][typed_key] == typed_value
        else:
            assert result[key] == value


@given(ref_id=st.integers(min_value=1, max_value=10**9))
def test_bare_operand_is_type_and_id(ref_id: int) -> None:
    """A reference with no overrides is always a valid operand."""
    assert build_operand_ref_clause(MetricRef(ref_id)) == {
        "type": "metric",
        "id": ref_id,
    }


@given(_measurement_fields)
def test_measurement_rules_match_the_inline_rules(fields: tuple[Any, ...]) -> None:
    """MetricRef refuses exactly the contradictory measurement combinations."""
    math, prop, per_user, percentile_value = fields
    expected: str | None = None
    if math is not None and per_user is not None and math in MATH_NO_PER_USER:
        expected = "V3_PER_USER_INCOMPATIBLE"
    elif math is not None and prop is not None and math not in _TAKES_PROPERTY:
        expected = "V14_METRIC_REJECTS_PROPERTY"
    try:
        MetricRef(
            1,
            math=math,
            property=prop,
            per_user=per_user,
            percentile_value=percentile_value,
        )
    except ParamValidationError as exc:
        assert exc.code == expected
    else:
        assert expected is None


@given(prop=_not_properties)
def test_property_outside_the_accepted_types_raises_mr7(prop: Any) -> None:
    """A property that is not a name or a custom property raises MR7_INVALID_OVERRIDE."""
    try:
        MetricRef(1, property=prop)
    except ParamValidationError as exc:
        assert exc.code == "MR7_INVALID_OVERRIDE"
    else:
        raise AssertionError(f"MetricRef accepted property={prop!r}")


_not_mappings = st.one_of(
    st.text(max_size=5),
    st.integers(),
    st.booleans(),
    st.lists(_json_scalars, max_size=3),
)
"""Raw overrides values that are not a mapping."""


@given(
    overrides=_not_mappings,
    stored=st.sampled_from(
        [{"math": "unique"}, {"math": "custom_percentile", "percentile": 95}]
    ),
)
def test_to_ref_reports_mr7_for_non_mapping_overrides(
    overrides: Any, stored: dict[str, Any]
) -> None:
    """SavedMetric.to_ref reports a non-mapping overrides as MR7_INVALID_OVERRIDE."""
    row = behavior_metric_json()
    row["definition"]["measurement"] = stored
    saved = SavedMetric.model_validate(row)
    try:
        saved.to_ref(math="percentile", overrides=overrides)
    except ParamValidationError as exc:
        assert exc.code == "MR7_INVALID_OVERRIDE"
    else:
        raise AssertionError(f"to_ref accepted overrides={overrides!r}")
