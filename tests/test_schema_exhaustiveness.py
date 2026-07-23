"""Schema-exhaustiveness spec for the query-model JSON schema surface.

The four query models (``InsightsQuery``, ``FunnelQuery``, ``RetentionQuery``,
``FlowQuery``) and every building block reachable from them must produce a
JSON schema that fully self-describes every valid input — with NO opaque
holes. An LLM reads ``model_json_schema()`` and builds a schema against it,
so the output must contain:

- no ``additionalProperties: true`` (open/untyped objects),
- no underscore-prefixed property names (leaked private fields),
- no empty ``{}`` subschema (matches-anything holes),
- no ``"type": "object"`` without ``properties`` (untyped object holes).

The declarative cohort input models (``InlineCohort`` and its criterion
union) provide the clean, exhaustive shape that replaces the wire-format
builder types in the schema, while the builder API keeps working at runtime.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from mixpanel_headless.query_models import (
    FlowQuery,
    FunnelQuery,
    InsightsQuery,
    RetentionQuery,
)
from mixpanel_headless.types import (
    BehavioralCriterion,
    CohortBreakdown,
    CohortCriteria,
    CohortDefinition,
    CohortMetric,
    CohortReferenceCriterion,
    Filter,
    InlineCohort,
    Metric,
    PropertyCriterion,
)

ALL_MODELS = [InsightsQuery, FunnelQuery, RetentionQuery, FlowQuery]


# =============================================================================
# Schema-walking helpers
# =============================================================================


def _walk(node: Any, path: str = "$") -> list[tuple[str, Any]]:
    """Yield ``(path, subschema)`` for every dict node in a JSON schema.

    Args:
        node: The JSON schema fragment to walk.
        path: Dotted path to ``node`` (for diagnostics).

    Returns:
        List of ``(path, dict-node)`` pairs across the whole schema tree.
    """
    found: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        found.append((path, node))
        for key, value in node.items():
            found.extend(_walk(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(_walk(item, f"{path}[{i}]"))
    return found


def _property_names(schema: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect ``(def_name, property_name)`` for every declared property.

    Args:
        schema: A full ``model_json_schema()`` output.

    Returns:
        List of ``(container, property)`` pairs across top-level and ``$defs``.
    """
    names: list[tuple[str, str]] = []
    for prop in schema.get("properties", {}):
        names.append(("<root>", prop))
    for def_name, definition in schema.get("$defs", {}).items():
        for prop in definition.get("properties", {}):
            names.append((def_name, prop))
    return names


# =============================================================================
# Exhaustiveness: no opaque holes
# =============================================================================


class TestNoOpaqueHoles:
    """Query-model schemas contain no opaque/self-undescribing subschemas."""

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_no_additional_properties_true(self, model_cls: type[BaseModel]) -> None:
        """No subschema allows arbitrary keys via ``additionalProperties: true``."""
        schema = model_cls.model_json_schema()
        offenders = [
            path
            for path, node in _walk(schema)
            if node.get("additionalProperties") is True
        ]
        assert not offenders, f"{model_cls.__name__}: open objects at {offenders}"

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_every_object_with_properties_forbids_extras(
        self, model_cls: type[BaseModel]
    ) -> None:
        """Every ``type: object`` node with ``properties`` sets ``additionalProperties: false``.

        Regression guard for finding
        ``custom-property-dataclasses-missing-additionalProperties-false``:
        OMITTING ``additionalProperties`` means "arbitrary extra keys
        allowed" in JSON Schema — semantically identical to ``true`` —
        while the runtime rejects extras on every query building block.
        ``test_no_additional_properties_true`` only catches the literal
        ``true`` form, which pydantic never emits, so plain stdlib
        dataclasses (whose ``$defs`` omit the keyword entirely) slipped
        through as open-object holes. This asserts the explicit
        ``false`` on every properties-bearing object node across the
        four schemas, ``$defs`` included, keeping the advertised schema
        an exact contract with the ``extra="forbid"`` runtime.
        """
        offenders = [
            path
            for path, node in _walk(model_cls.model_json_schema())
            if node.get("type") == "object"
            and "properties" in node
            and node.get("additionalProperties") is not False
        ]
        assert not offenders, (
            f"{model_cls.__name__}: object nodes allowing extra keys "
            f"(additionalProperties omitted or not false) at {offenders}"
        )

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_no_underscore_properties(self, model_cls: type[BaseModel]) -> None:
        """No leaked private fields (property names starting with ``_``)."""
        schema = model_cls.model_json_schema()
        leaked = [
            f"{container}.{prop}"
            for container, prop in _property_names(schema)
            if prop.startswith("_")
        ]
        assert not leaked, f"{model_cls.__name__}: leaked private fields {leaked}"

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_no_untyped_object(self, model_cls: type[BaseModel]) -> None:
        """No ``type: object`` node lacks both ``properties`` and typed ``additionalProperties``.

        An object with neither is indistinguishable from ``dict[str, Any]``.
        """
        offenders: list[str] = []
        for path, node in _walk(model_cls.model_json_schema()):
            if node.get("type") != "object":
                continue
            if "properties" in node:
                continue
            addl = node.get("additionalProperties")
            # A typed additionalProperties (a schema dict) is fine; True/absent is not.
            if isinstance(addl, dict) and addl:
                continue
            offenders.append(path)
        assert not offenders, f"{model_cls.__name__}: untyped objects at {offenders}"

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_no_empty_subschema_in_defs(self, model_cls: type[BaseModel]) -> None:
        """No ``$defs`` entry is an empty ``{}`` (matches-anything hole).

        An ``is_instance`` core-schema arm renders as ``{}`` in JSON schema;
        the declarative bridge must keep such holes out of the output.
        """
        schema = model_cls.model_json_schema()
        # anyOf arms that are literally {} are the tell-tale is_instance holes.
        offenders = [
            path
            for path, node in _walk(schema)
            if "anyOf" in node and any(arm == {} for arm in node["anyOf"])
        ]
        assert not offenders, f"{model_cls.__name__}: empty anyOf arm at {offenders}"


# =============================================================================
# Numeric constraints render as JSON-Schema keywords
# =============================================================================


class TestNumericConstraintRendering:
    """Numeric bounds render as standard JSON-Schema keywords.

    Regression tests for finding ``percentile-bounds-dropped-from-json-schema``:
    attaching ``Field(ge=..., le=...)`` to a *union* emits literal
    ``ge``/``le`` keys that standard validators ignore, so a
    schema-conforming payload like ``percentile_value: 150`` passed
    external validation and failed at runtime. Bounds must be annotated
    per-arm so ``minimum``/``maximum``/``exclusiveMinimum`` appear.
    """

    def test_percentile_value_bounds_rendered(self) -> None:
        """InsightsQuery.percentile_value arms carry minimum/maximum 0..100."""
        prop = InsightsQuery.model_json_schema()["properties"]["percentile_value"]
        numeric_arms = [
            node for _, node in _walk(prop) if node.get("type") in ("integer", "number")
        ]
        assert numeric_arms, f"no numeric arms found in {prop}"
        for arm in numeric_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"
            assert arm.get("maximum") == 100, f"missing maximum in {arm}"

    def test_group_by_bucket_size_bound_rendered(self) -> None:
        """GroupBy.bucket_size arms carry exclusiveMinimum 0."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["GroupBy"]["properties"]["bucket_size"]
        numeric_arms = [
            node for _, node in _walk(prop) if node.get("type") in ("integer", "number")
        ]
        assert numeric_arms, f"no numeric arms found in {prop}"
        for arm in numeric_arms:
            assert arm.get("exclusiveMinimum") == 0, f"missing bound in {arm}"

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_no_raw_constraint_keys(self, model_cls: type[BaseModel]) -> None:
        """No subschema carries pydantic's literal ge/le/gt/lt keys."""
        offenders = [
            (path, sorted(set(node) & {"ge", "le", "gt", "lt"}))
            for path, node in _walk(model_cls.model_json_schema())
            if set(node) & {"ge", "le", "gt", "lt"}
        ]
        assert not offenders, (
            f"{model_cls.__name__}: raw constraint keys at {offenders}"
        )

    def test_metric_percentile_value_bounds_rendered(self) -> None:
        """Metric.percentile_value arms carry minimum/maximum 0..100.

        Regression for finding ``metric-percentile-value-unbounded-everywhere``:
        the top-level ``InsightsQuery.percentile_value`` was bounded but the
        per-metric field rendered as bare integer/number arms, so a
        schema-conforming ``percentile_value: 150`` built and shipped
        ``custom_percentile`` 150 to the server.
        """
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["Metric"]["properties"]["percentile_value"]
        numeric_arms = [
            node for _, node in _walk(prop) if node.get("type") in ("integer", "number")
        ]
        assert numeric_arms, f"no numeric arms found in {prop}"
        for arm in numeric_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"
            assert arm.get("maximum") == 100, f"missing maximum in {arm}"

    def test_frequency_filter_value_minimum_rendered(self) -> None:
        """FrequencyFilter.value arms carry minimum 0 (runtime rule FF3)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["FrequencyFilter"]["properties"]["value"]
        numeric_arms = [
            node for _, node in _walk(prop) if node.get("type") in ("integer", "number")
        ]
        assert numeric_arms, f"no numeric arms found in {prop}"
        for arm in numeric_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"

    def test_frequency_filter_date_range_value_bound_rendered(self) -> None:
        """FrequencyFilter.date_range_value carries exclusiveMinimum 0 (FF5)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["FrequencyFilter"]["properties"]["date_range_value"]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("exclusiveMinimum") == 0, f"missing bound in {arm}"

    def test_exclusion_from_step_minimum_rendered(self) -> None:
        """Exclusion.from_step carries minimum 0 (runtime >= 0 rule)."""
        defs = FunnelQuery.model_json_schema()["$defs"]
        prop = defs["Exclusion"]["properties"]["from_step"]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"

    @pytest.mark.parametrize("field_name", ["forward", "reverse"])
    def test_flow_step_direction_bounds_rendered(self, field_name: str) -> None:
        """FlowStep.forward/reverse carry minimum 0 / maximum 5 (runtime 0-5)."""
        defs = FlowQuery.model_json_schema()["$defs"]
        prop = defs["FlowStep"]["properties"][field_name]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"
            assert arm.get("maximum") == 5, f"missing maximum in {arm}"

    def test_retention_bucket_sizes_items_bound_rendered(self) -> None:
        """RetentionQuery.bucket_sizes items carry exclusiveMinimum 0 (R5)."""
        prop = RetentionQuery.model_json_schema()["properties"]["bucket_sizes"]
        item_schemas = [
            node["items"]
            for _, node in _walk(prop)
            if node.get("type") == "array" and isinstance(node.get("items"), dict)
        ]
        assert item_schemas, f"no array arms found in {prop}"
        for items in item_schemas:
            assert items.get("type") == "integer", f"non-integer items in {items}"
            assert items.get("exclusiveMinimum") == 0, f"missing bound in {items}"

    @pytest.mark.parametrize("def_name", ["CohortBreakdown", "CohortMetric"])
    def test_cohort_int_arm_bound_rendered(self, def_name: str) -> None:
        """Saved-cohort-ID arms carry exclusiveMinimum 0 (positive-ID rule)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs[def_name]["properties"]["cohort"]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("exclusiveMinimum") == 0, f"missing bound in {arm}"

    def test_cohort_reference_criterion_id_bound_rendered(self) -> None:
        """CohortReferenceCriterion.cohort_id carries exclusiveMinimum 0.

        Regression guard for finding
        ``declarative-cohort-criterion-models-lax-coerce-int-bool``:
        making ``cohort_id`` strict must keep the positive-ID bound
        rendered as a standard JSON-Schema keyword.
        """
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["CohortReferenceCriterion"]["properties"]["cohort_id"]
        assert prop.get("type") == "integer"
        assert prop.get("exclusiveMinimum") == 0, f"missing bound in {prop}"

    @pytest.mark.parametrize("field_name", ["at_least", "at_most", "exactly"])
    def test_behavioral_count_bounds_rendered(self, field_name: str) -> None:
        """BehavioralCriterion count arms carry minimum 0.

        Regression guard for finding
        ``declarative-cohort-criterion-models-lax-coerce-int-bool``:
        making the frequency-bound fields strict must keep the
        non-negative count bound rendered per integer arm.
        """
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["BehavioralCriterion"]["properties"][field_name]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("minimum") == 0, f"missing minimum in {arm}"

    @pytest.mark.parametrize(
        "field_name", ["within_days", "within_weeks", "within_months"]
    )
    def test_behavioral_window_bounds_rendered(self, field_name: str) -> None:
        """BehavioralCriterion window arms carry exclusiveMinimum 0.

        Regression guard for finding
        ``declarative-cohort-criterion-models-lax-coerce-int-bool``:
        making the rolling-window fields strict must keep the positive
        bound rendered per integer arm.
        """
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["BehavioralCriterion"]["properties"][field_name]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("exclusiveMinimum") == 0, f"missing bound in {arm}"

    def test_custom_property_ref_id_bound_rendered(self) -> None:
        """CustomPropertyRef.id carries exclusiveMinimum 0 (CP1 positive rule)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["CustomPropertyRef"]["properties"]["id"]
        assert prop.get("type") == "integer"
        assert prop.get("exclusiveMinimum") == 0, f"missing bound in {prop}"

    def test_inline_custom_property_formula_max_length_rendered(self) -> None:
        """InlineCustomProperty.formula carries maxLength 20000 (CP5)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["InlineCustomProperty"]["properties"]["formula"]
        assert prop.get("maxLength") == 20_000, f"missing maxLength in {prop}"

    def test_inline_custom_property_inputs_constraints_rendered(self) -> None:
        """InlineCustomProperty.inputs renders CP3/CP4 as object keywords.

        ``minProperties: 1`` mirrors CP3 (non-empty inputs) and
        ``propertyNames.pattern`` mirrors CP4 (single uppercase A-Z keys),
        while the typed ``additionalProperties`` value schema is preserved.
        """
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["InlineCustomProperty"]["properties"]["inputs"]
        assert prop.get("minProperties") == 1, f"missing minProperties in {prop}"
        assert prop.get("propertyNames") == {"pattern": "^[A-Z]$"}, (
            f"missing propertyNames in {prop}"
        )
        assert isinstance(prop.get("additionalProperties"), dict), (
            f"untyped inputs values in {prop}"
        )

    def test_time_comparison_date_pattern_rendered(self) -> None:
        """TimeComparison.date carries the YYYY-MM-DD pattern (runtime _DATE_RE)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["TimeComparison"]["properties"]["date"]
        string_arms = [node for _, node in _walk(prop) if node.get("type") == "string"]
        assert string_arms, f"no string arms found in {prop}"
        for arm in string_arms:
            assert arm.get("pattern") == r"^\d{4}-\d{2}-\d{2}$", (
                f"missing pattern in {arm}"
            )

    # -------------------------------------------------------------------
    # Runtime maxima render alongside the already-rendered minima.
    # Regression tests for finding
    # ``flow-and-time-maximum-bounds-missing-from-schema``: the minimum
    # side of these bounds rendered but the runtime-enforced maxima
    # (FL3/FL4/FL6, V20, V23, R5c, F1, F8) did not, so a schema-driven
    # consumer could synthesize guaranteed-to-fail payloads.
    # -------------------------------------------------------------------

    @pytest.mark.parametrize("field_name", ["forward", "reverse"])
    def test_flow_query_direction_maximum_rendered(self, field_name: str) -> None:
        """FlowQuery.forward/reverse carry maximum 5 (runtime FL3/FL4)."""
        prop = FlowQuery.model_json_schema()["properties"][field_name]
        assert prop.get("minimum") == 0, f"missing minimum in {prop}"
        assert prop.get("maximum") == 5, f"missing maximum in {prop}"

    def test_flow_query_cardinality_maximum_rendered(self) -> None:
        """FlowQuery.cardinality carries maximum 50 (runtime FL6)."""
        prop = FlowQuery.model_json_schema()["properties"]["cardinality"]
        assert prop.get("minimum") == 1, f"missing minimum in {prop}"
        assert prop.get("maximum") == 50, f"missing maximum in {prop}"

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_last_maximum_rendered(self, model_cls: type[BaseModel]) -> None:
        """Every model's ``last`` carries maximum 3650 (runtime V20)."""
        prop = model_cls.model_json_schema()["properties"]["last"]
        assert prop.get("minimum") == 1, f"missing minimum in {prop}"
        assert prop.get("maximum") == 3650, f"missing maximum in {prop}"

    def test_insights_rolling_maximum_rendered(self) -> None:
        """InsightsQuery.rolling carries maximum 365 (runtime V23)."""
        prop = InsightsQuery.model_json_schema()["properties"]["rolling"]
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"no integer arms found in {prop}"
        for arm in int_arms:
            assert arm.get("exclusiveMinimum") == 0, f"missing bound in {arm}"
            assert arm.get("maximum") == 365, f"missing maximum in {arm}"

    def test_retention_bucket_sizes_max_items_rendered(self) -> None:
        """RetentionQuery.bucket_sizes carries maxItems 730 (runtime R5c)."""
        prop = RetentionQuery.model_json_schema()["properties"]["bucket_sizes"]
        array_arms = [node for _, node in _walk(prop) if node.get("type") == "array"]
        assert array_arms, f"no array arms found in {prop}"
        for arm in array_arms:
            assert arm.get("maxItems") == 730, f"missing maxItems in {arm}"

    def test_funnel_steps_max_items_rendered(self) -> None:
        """FunnelQuery.steps carries maxItems 100 (runtime F1_MAX_STEPS)."""
        prop = FunnelQuery.model_json_schema()["properties"]["steps"]
        assert prop.get("minItems") == 2, f"missing minItems in {prop}"
        assert prop.get("maxItems") == 100, f"missing maxItems in {prop}"

    def test_funnel_holding_constant_max_items_rendered(self) -> None:
        """FunnelQuery.holding_constant carries maxItems 3 (runtime F8)."""
        prop = FunnelQuery.model_json_schema()["properties"]["holding_constant"]
        array_arms = [node for _, node in _walk(prop) if node.get("type") == "array"]
        assert array_arms, f"no array arms found in {prop}"
        for arm in array_arms:
            assert arm.get("maxItems") == 3, f"missing maxItems in {arm}"

    # -------------------------------------------------------------------
    # Non-empty-string and filter-value item bounds render too.
    # Regression tests for finding
    # ``non-empty-string-and-filter-value-item-bounds-missing-from-schema``.
    # -------------------------------------------------------------------

    def test_filter_value_array_arm_item_bounds_rendered(self) -> None:
        """Filter.value array arms carry minItems 1 / maxItems 1000 (B20/B21)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["Filter"]["properties"]["value"]
        array_arms = [node for _, node in _walk(prop) if node.get("type") == "array"]
        assert array_arms, f"no array arms found in {prop}"
        for arm in array_arms:
            assert arm.get("minItems") == 1, f"missing minItems in {arm}"
            assert arm.get("maxItems") == 1000, f"missing maxItems in {arm}"

    def test_group_by_property_str_arm_min_length_rendered(self) -> None:
        """GroupBy.property's string arm carries minLength 1 (post-init rule)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["GroupBy"]["properties"]["property"]
        string_arms = [node for _, node in _walk(prop) if node.get("type") == "string"]
        assert string_arms, f"no string arms found in {prop}"
        for arm in string_arms:
            assert arm.get("minLength") == 1, f"missing minLength in {arm}"

    def test_frequency_filter_event_min_length_rendered(self) -> None:
        """FrequencyFilter.event carries minLength 1 (runtime FF1)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["FrequencyFilter"]["properties"]["event"]
        assert prop.get("minLength") == 1, f"missing minLength in {prop}"

    def test_holding_constant_property_min_length_rendered(self) -> None:
        """HoldingConstant.property carries minLength 1 (post-init rule)."""
        defs = FunnelQuery.model_json_schema()["$defs"]
        prop = defs["HoldingConstant"]["properties"]["property"]
        assert prop.get("minLength") == 1, f"missing minLength in {prop}"

    def test_inline_custom_property_formula_min_length_rendered(self) -> None:
        """InlineCustomProperty.formula carries minLength 1 (CP2)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["InlineCustomProperty"]["properties"]["formula"]
        assert prop.get("minLength") == 1, f"missing minLength in {prop}"
        assert prop.get("maxLength") == 20_000, f"missing maxLength in {prop}"

    def test_property_input_name_min_length_rendered(self) -> None:
        """PropertyInput.name carries minLength 1 (CP6)."""
        defs = InsightsQuery.model_json_schema()["$defs"]
        prop = defs["PropertyInput"]["properties"]["name"]
        assert prop.get("minLength") == 1, f"missing minLength in {prop}"


class TestSchemaOnlyBoundDocstringsNameRealEnforcers:
    """Schema-only bound docstrings reference the real runtime enforcer.

    Regression test for finding
    ``cp-docstrings-name-nonexistent-validate-custom-property-spec``:
    three docstrings claimed runtime enforcement "stays in
    ``validate_custom_property_spec``", but no function of that name
    exists — the CP1-CP6 rules live in ``_validate_custom_property``
    (``_internal/validation.py``), reached via ``_scan_custom_properties``
    at build time. Auditors grepping for the named function must find it.
    """

    def test_no_reference_to_nonexistent_validator(self) -> None:
        """types.py never names the nonexistent validate_custom_property_spec."""
        import inspect

        from mixpanel_headless import types as types_module

        source = inspect.getsource(types_module)
        assert "validate_custom_property_spec" not in source

    def test_named_enforcer_exists(self) -> None:
        """The function the corrected docstrings name actually exists."""
        from mixpanel_headless._internal import validation

        assert callable(validation._validate_custom_property)


# =============================================================================
# Schema/runtime parity: CohortMetric advertises only what it accepts
# =============================================================================


class TestCohortMetricSchemaMatchesRuntime:
    """CohortMetric's schema advertises exactly the inputs its runtime accepts.

    Regression tests for finding
    ``cohort-metric-schema-advertises-unsupported-inline-cohort-arm``:
    ``model_json_schema()`` rendered an ``InlineCohort`` arm on
    ``CohortMetric.cohort`` although ``__post_init__`` unconditionally
    rejects inline definitions (server returns 500) — a schema-valid
    payload was guaranteed to fail at validation. The definition arm is
    now hidden from the JSON schema (``SkipJsonSchema``) while the
    runtime arm stays so Python builder callers keep the targeted
    500-warning message.
    """

    def test_cohort_metric_schema_is_integer_only(self) -> None:
        """The schema for CohortMetric.cohort has no InlineCohort arm."""
        prop = InsightsQuery.model_json_schema()["$defs"]["CohortMetric"]["properties"][
            "cohort"
        ]
        refs = [node["$ref"] for _, node in _walk(prop) if "$ref" in node]
        assert not refs, f"CohortMetric.cohort advertises non-integer arms: {refs}"
        int_arms = [node for _, node in _walk(prop) if node.get("type") == "integer"]
        assert int_arms, f"integer arm missing from {prop}"

    def test_cohort_breakdown_schema_keeps_inline_arm(self) -> None:
        """CohortBreakdown.cohort (which accepts inline) keeps its schema arm."""
        prop = InsightsQuery.model_json_schema()["$defs"]["CohortBreakdown"][
            "properties"
        ]["cohort"]
        refs = [node["$ref"] for _, node in _walk(prop) if "$ref" in node]
        assert any("InlineCohort" in ref for ref in refs), (
            f"CohortBreakdown.cohort lost its inline arm: {prop}"
        )

    def test_cohort_metric_runtime_still_rejects_inline_definition(self) -> None:
        """The dict path still rejects inline cohorts with the 500 warning."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError, match="server returns 500"):
            InsightsQuery.model_validate(
                {
                    "events": [
                        {
                            "cohort": {
                                "operator": "and",
                                "criteria": [
                                    {
                                        "kind": "property",
                                        "property": "plan",
                                        "value": "premium",
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

    def test_cohort_metric_builder_path_still_rejects_definition(self) -> None:
        """Python builder callers still get the targeted 500 rejection."""
        from pydantic import ValidationError

        cd = CohortDefinition.all_of(CohortCriteria.has_property("plan", "premium"))
        with pytest.raises(ValidationError, match="server returns 500"):
            CohortMetric(cd)


# =============================================================================
# Declarative cohort input models are public
# =============================================================================


class TestDeclarativeModelsExported:
    """The declarative cohort input models are importable and pydantic."""

    def test_models_are_basemodels(self) -> None:
        """All declarative cohort models subclass ``pydantic.BaseModel``."""
        for cls in (
            PropertyCriterion,
            BehavioralCriterion,
            CohortReferenceCriterion,
            InlineCohort,
        ):
            assert issubclass(cls, BaseModel)

    def test_public_exports(self) -> None:
        """Declarative models are exported from the package root."""
        import mixpanel_headless as mp

        for name in (
            "PropertyCriterion",
            "BehavioralCriterion",
            "CohortReferenceCriterion",
            "InlineCohort",
        ):
            assert hasattr(mp, name), f"missing export: {name}"


# =============================================================================
# Wire-format parity: declarative == builder
# =============================================================================


class TestInlineCohortWireParity:
    """``InlineCohort.to_dict()`` matches the equivalent builder output."""

    def test_property_criterion_parity(self) -> None:
        """A property criterion serializes identically to the builder."""
        inline = InlineCohort(
            criteria=[
                PropertyCriterion(property="plan", value="premium"),
            ]
        )
        builder = CohortDefinition.all_of(
            CohortCriteria.has_property("plan", "premium"),
        )
        assert inline.to_dict() == builder.to_dict()

    def test_behavioral_criterion_parity(self) -> None:
        """A behavioral criterion serializes identically to the builder."""
        inline = InlineCohort(
            criteria=[
                BehavioralCriterion(event="Purchase", at_least=3, within_days=30),
            ]
        )
        builder = CohortDefinition.all_of(
            CohortCriteria.did_event("Purchase", at_least=3, within_days=30),
        )
        assert inline.to_dict() == builder.to_dict()

    def test_cohort_reference_parity(self) -> None:
        """A cohort-reference criterion serializes identically to the builder."""
        inline = InlineCohort(
            criteria=[CohortReferenceCriterion(cohort_id=456)],
        )
        builder = CohortDefinition.all_of(CohortCriteria.in_cohort(456))
        assert inline.to_dict() == builder.to_dict()

    def test_negated_cohort_reference_parity(self) -> None:
        """A negated cohort reference matches ``not_in_cohort``."""
        inline = InlineCohort(
            criteria=[CohortReferenceCriterion(cohort_id=456, negated=True)],
        )
        builder = CohortDefinition.all_of(CohortCriteria.not_in_cohort(456))
        assert inline.to_dict() == builder.to_dict()

    def test_any_of_parity(self) -> None:
        """``operator='or'`` matches ``CohortDefinition.any_of``."""
        inline = InlineCohort(
            operator="or",
            criteria=[
                PropertyCriterion(property="plan", value="premium"),
                CohortReferenceCriterion(cohort_id=7),
            ],
        )
        builder = CohortDefinition.any_of(
            CohortCriteria.has_property("plan", "premium"),
            CohortCriteria.in_cohort(7),
        )
        assert inline.to_dict() == builder.to_dict()

    def test_nested_parity_and_behavior_reindex(self) -> None:
        """Nested groups and multi-behavior keys re-index identically."""
        inline = InlineCohort(
            criteria=[
                BehavioralCriterion(event="A", at_least=1, within_days=7),
                InlineCohort(
                    operator="or",
                    criteria=[
                        BehavioralCriterion(event="B", exactly=0, within_days=7),
                        PropertyCriterion(property="country", value="US"),
                    ],
                ),
            ]
        )
        builder = CohortDefinition.all_of(
            CohortCriteria.did_event("A", at_least=1, within_days=7),
            CohortDefinition.any_of(
                CohortCriteria.did_not_do_event("B", within_days=7),
                CohortCriteria.has_property("country", "US"),
            ),
        )
        assert inline.to_dict() == builder.to_dict()


# =============================================================================
# Backward compatibility: builder instances still accepted at runtime
# =============================================================================


class TestBuilderBackwardCompat:
    """Existing builder-based call sites keep working after the refactor."""

    def test_cohort_breakdown_accepts_definition(self) -> None:
        """``CohortBreakdown`` still accepts a builder ``CohortDefinition``."""
        cd = CohortDefinition.all_of(CohortCriteria.has_property("plan", "premium"))
        cb = CohortBreakdown(cd, name="Premium")
        assert isinstance(cb.cohort, CohortDefinition)
        assert cb.cohort.to_dict() == cd.to_dict()

    def test_cohort_breakdown_accepts_int(self) -> None:
        """``CohortBreakdown`` still accepts a saved cohort ID."""
        cb = CohortBreakdown(123, name="Saved")
        assert cb.cohort == 123

    def test_cohort_metric_accepts_int(self) -> None:
        """``CohortMetric`` still accepts a saved cohort ID."""
        cm = CohortMetric(123, name="Saved")
        assert cm.cohort == 123

    def test_filter_in_cohort_accepts_definition(self) -> None:
        """``Filter.in_cohort`` still accepts a builder ``CohortDefinition``."""
        cd = CohortDefinition.all_of(CohortCriteria.in_cohort(9))
        f = Filter.in_cohort(cd, name="Ref")
        assert isinstance(f, Filter)


# =============================================================================
# Query-field coercion: declarative JSON -> builder at validation time
# =============================================================================


class TestQueryFieldCoercion:
    """LLM-shaped declarative JSON validates and coerces to builder objects."""

    def test_group_by_inline_cohort_from_json(self) -> None:
        """Declarative inline cohort in ``group_by`` coerces to a definition."""
        payload = {
            "events": [{"event": "Purchase"}],
            "group_by": [
                {
                    "cohort": {
                        "operator": "and",
                        "criteria": [
                            {"kind": "property", "property": "plan", "value": "premium"}
                        ],
                    },
                    "name": "Premium",
                }
            ],
        }
        q = InsightsQuery.model_validate(payload)
        (breakdown,) = q.group_by  # type: ignore[misc]
        assert isinstance(breakdown, CohortBreakdown)
        assert isinstance(breakdown.cohort, CohortDefinition)
        expected = CohortDefinition.all_of(
            CohortCriteria.has_property("plan", "premium")
        )
        assert breakdown.cohort.to_dict() == expected.to_dict()

    def test_group_by_saved_cohort_id_from_json(self) -> None:
        """A bare integer cohort ID still validates in ``group_by``."""
        q = InsightsQuery.model_validate(
            {
                "events": [{"event": "Purchase"}],
                "group_by": [{"cohort": 321, "name": "Saved"}],
            }
        )
        (breakdown,) = q.group_by  # type: ignore[misc]
        assert isinstance(breakdown, CohortBreakdown)
        assert breakdown.cohort == 321

    def test_python_construction_still_works(self) -> None:
        """Python-level construction via the builder is unaffected."""
        q = InsightsQuery(
            events=[Metric("Purchase")],
            group_by=[
                CohortBreakdown(
                    CohortDefinition.all_of(CohortCriteria.in_cohort(5)),
                    name="Ref",
                )
            ],
        )
        (breakdown,) = q.group_by  # type: ignore[misc]
        assert isinstance(breakdown, CohortBreakdown)
        assert isinstance(breakdown.cohort, CohortDefinition)
        assert breakdown.cohort.to_dict() == (
            CohortDefinition.all_of(CohortCriteria.in_cohort(5)).to_dict()
        )
