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
