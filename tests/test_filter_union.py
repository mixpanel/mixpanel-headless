"""Schema/runtime parity spec for the native ``Filter`` discriminated union.

``Filter`` used to be one flat dataclass carrying an eight-field superset
of every operator's needs, with each operator's value rules encoded in
``__post_init__`` — so none of those rules reached
``model_json_schema()``. Payloads the runtime rejected were advertised as
valid, which breaks the consuming repositories that drive an LLM/MCP
request schema off the generated schema.

``Filter`` replaced that with one discriminated union whose members
each declare only the fields their operator accepts, so stock Pydantic
types do the validating and the schema is *generated* rather than
hand-written. Routing goes through ``MarkedDiscriminator`` so the chosen
member's tag stays strippable from caller-facing error paths; the
``oneOf`` is unambiguous without JSON Schema's ``discriminator`` keyword
because every member pins ``operator`` to its own literals.

Tests below name the parity gap they close as ``G1``-``G8``. Those
numbers are defined by :attr:`TestParityMatrix._GAPS` at the foot of this
module, which holds the payload for each. The property-based counterpart
lives in ``tests/test_filter_union_pbt.py``: this module pins the gaps by
example, that one hunts for new ones.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, get_args

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from mixpanel_headless._internal.bookmark_enums import _MAX_FILTER_VALUES
from mixpanel_headless.types import (
    AbstractFilter,
    ContainmentFilter,
    EqualityFilter,
    Filter,
    FilterFactory,
    FilterOperator,
    PresenceFilter,
)

_ADAPTER: TypeAdapter[Any] = TypeAdapter(Filter)
"""Shared adapter — building one per test is pure overhead."""

_SCHEMA: dict[str, Any] = _ADAPTER.json_schema()
"""The generated schema, built once.

``TypeAdapter.json_schema()`` is not memoized — it rebuilds the whole
ten-member ``$defs`` block on every call, at ~4 ms a time. Regenerating
it per assertion cost about a quarter-second across this module and its
property-based sibling. Nothing here mutates it: the two tests that strip
a key copy first.
"""

_VALIDATOR = Draft202012Validator(_SCHEMA)
"""Schema-side validator, compiled once from :data:`_SCHEMA`.

Matches the convention in ``tests/test_filter_union_pbt.py``, so both
modules ask the schema the same way.
"""

_DATE_SCHEMA = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
"""The schema every ``_DateStr`` field is expected to render."""


def _defs() -> dict[str, Any]:
    """Return the ``$defs`` block of the generated ``Filter`` schema.

    Returns:
        Mapping of member class name to its JSON Schema object. Shared,
        not a copy — treat it as read-only.
    """
    defs: dict[str, Any] = _SCHEMA["$defs"]
    return defs


def _error_types(exc_info: pytest.ExceptionInfo[ValidationError]) -> set[str]:
    """Collect the distinct Pydantic error codes from a raised ``ValidationError``.

    Args:
        exc_info: The ``pytest.raises`` capture holding the error.

    Returns:
        The set of ``error["type"]`` values, deduplicated. Union members
        each contribute an error, so assertions read more clearly against
        a set than against ``errors()[0]``.
    """
    return {error["type"] for error in exc_info.value.errors()}


_MINIMAL_VALUE: dict[str, Any] = {
    "is set": None,
    "is not set": None,
    "true": None,
    "false": None,
    "equals": "x",
    "does not equal": "x",
    "contains": "x",
    "does not contain": "x",
    "starts with": "x",
    "ends with": "x",
    "is greater than": 1,
    "is less than": 1,
    "is at least": 1,
    "is at most": 1,
    "is between": [1, 2],
    "not between": [1, 2],
    "was on": "2025-01-01",
    "was not on": "2025-01-01",
    "was before": "2025-01-01",
    "was since": "2025-01-01",
    "was between": ["2025-01-01", "2025-01-02"],
    "was not between": ["2025-01-01", "2025-01-02"],
    "was in the": 7,
    "was not in the": 7,
    "was in the next": 7,
}
"""The smallest value each operator accepts — ``None`` for the value-less ones."""


def _payload_for(operator: str) -> dict[str, Any]:
    """Build the smallest payload that validates for *operator*.

    Args:
        operator: Any operator the union accepts.

    Returns:
        A dict using the public wire names, ready for ``validate_python``.
    """
    if operator == "list_contains":
        return {
            "property": "cart",
            "operator": operator,
            "list_item_filters": [
                {"property": "Brand", "operator": "equals", "value": "nike"}
            ],
        }
    payload: dict[str, Any] = {"property": "p", "operator": operator}
    value = _MINIMAL_VALUE[operator]
    if value is not None:
        payload["value"] = value
    return payload


def _routes_to(operator: str) -> str:
    """Return the name of the member *operator* routes to.

    Replaces an assertion on the schema's ``discriminator.mapping``, which
    pydantic cannot generate for a callable discriminator. Exercising the
    routing itself is the stronger check anyway: it proves the operator
    both selects a member *and* validates against it.

    Args:
        operator: Any operator the union accepts.

    Returns:
        The validated instance's class name.
    """
    return type(_ADAPTER.validate_python(_payload_for(operator))).__name__


def _member_refs(one_of: list[dict[str, Any]]) -> set[str]:
    """Collect the member names a ``oneOf`` block points at.

    Args:
        one_of: A schema's ``oneOf`` list of ``$ref`` objects.

    Returns:
        The referenced ``$defs`` keys.
    """
    return {choice["$ref"].rsplit("/", 1)[-1] for choice in one_of}


class TestFilterUnionSchema:
    """The generated schema is a valid, self-describing contract."""

    def test_schema_is_metaschema_valid(self) -> None:
        """``Filter``'s schema passes Draft 2020-12 metaschema validation."""
        Draft202012Validator.check_schema(_SCHEMA)

    def test_members_pin_operator_to_disjoint_literals(self) -> None:
        """No two members accept the same ``operator``, so ``oneOf`` is unambiguous.

        Routing is a callable discriminator (so its tag stays strippable
        from error paths), and JSON Schema cannot express that as a
        ``discriminator`` keyword. What keeps the generated ``oneOf``
        decidable instead is this: each member's ``operator`` is a closed
        enum, and the enums do not overlap. A consumer can pick the
        branch from ``operator`` alone.
        """
        seen: dict[str, str] = {}
        for name, schema in _defs().items():
            operator = schema.get("properties", {}).get("operator")
            if operator is None:
                continue
            values = operator.get("enum") or [operator["const"]]
            for value in values:
                assert value not in seen, (
                    f"operator {value!r} is claimed by both {seen[value]} and {name}"
                )
                seen[value] = name

    def test_presence_operators_route_to_presence_filter(self) -> None:
        """Both presence operators select ``PresenceFilter``."""
        assert _routes_to("is set") == "PresenceFilter"
        assert _routes_to("is not set") == "PresenceFilter"

    def test_presence_value_is_null_typed(self) -> None:
        """``PresenceFilter.value`` renders as ``type: "null"`` — G5, in the schema.

        The flat ``Filter`` advertises ``value`` as a broad union for
        every operator, so a presence filter carrying a value looks legal
        to a schema reader. A ``None`` annotation makes the prohibition
        machine-readable.
        """
        schema = _SCHEMA
        value = schema["$defs"]["PresenceFilter"]["properties"]["value"]
        assert value["type"] == "null"


class TestPresenceFilterValidation:
    """Runtime behaviour of the presence member matches its schema."""

    @pytest.mark.parametrize("operator", ["is set", "is not set"])
    def test_accepts_bare_presence_payload(self, operator: str) -> None:
        """A presence filter with no ``value`` validates and keeps its operator."""
        parsed = _ADAPTER.validate_python({"property": "plan", "operator": operator})
        assert parsed.operator == operator
        assert parsed.value is None

    def test_rejects_value_on_presence_operator(self) -> None:
        """G5: ``{"operator": "is set", "value": "y"}`` is rejected.

        Schema-valid and runtime-invalid under the flat ``Filter``; the
        ``None`` annotation is what closes the gap — in the schema as
        well as at runtime. A ``BeforeValidator`` runs first only to keep
        the flat ``Filter``'s actionable wording, which names the
        operator and points at ``equals``.
        """
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "plan", "operator": "is set", "value": "y"}
            )
        error = exc_info.value.errors()[0]
        assert error["type"] == "value_error"
        assert "does not take a value" in error["msg"]
        assert "did you mean operator 'equals'?" in error["msg"]

    def test_rejects_unknown_operator(self) -> None:
        """An operator outside the union fails with ``union_tag_invalid``.

        The operator is deliberately nonsense rather than a
        real-but-unmigrated one: an operator that later becomes legal
        would turn this into a silent no-op. Routing it nowhere fires the
        union's own ``custom_error_type``, which names every operator
        that *is* accepted, instead of ten members' worth of shape noise.
        """
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python({"property": "plan", "operator": "is bananas"})
        assert exc_info.value.errors()[0]["type"] == "invalid_filter_operator"

    def test_rejects_extra_keys(self) -> None:
        """``extra="forbid"`` keeps the runtime as closed as the schema claims."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "plan", "operator": "is set", "bogus": 1}
            )

    def test_validated_instance_is_filter_base(self) -> None:
        """Validation returns a ``Filter``, preserving ``isinstance`` identity.

        Nine production call sites branch on ``isinstance(x, AbstractFilter)``.
        Members subclass the plain ``Filter`` base precisely so those
        sites — and the ~700 factory calls across the suite — need no
        edits now that the flat dataclass is retired.
        """
        parsed = _ADAPTER.validate_python({"property": "plan", "operator": "is set"})
        assert isinstance(parsed, AbstractFilter)
        assert isinstance(parsed, PresenceFilter)


class TestScalarMemberSchema:
    """Each scalar member advertises only the value shapes it accepts."""

    @pytest.mark.parametrize(
        ("operator", "member"),
        [
            ("equals", "EqualityFilter"),
            ("does not equal", "EqualityFilter"),
            ("contains", "ContainmentFilter"),
            ("does not contain", "ContainmentFilter"),
            ("starts with", "SubstringFilter"),
            ("ends with", "SubstringFilter"),
            ("is greater than", "NumericComparisonFilter"),
            ("is less than", "NumericComparisonFilter"),
            ("is at least", "NumericComparisonFilter"),
            ("is at most", "NumericComparisonFilter"),
            ("true", "BooleanStateFilter"),
            ("false", "BooleanStateFilter"),
        ],
    )
    def test_every_scalar_operator_routes_to_its_member(
        self, operator: str, member: str
    ) -> None:
        """Every scalar operator selects — and validates against — one member."""
        assert _routes_to(operator) == member

    def test_equality_list_value_bounds_rendered(self) -> None:
        """``EqualityFilter``'s list alternatives carry the shared size bounds.

        The flat ``Filter`` states these bounds in a hand-written
        ``WithJsonSchema`` blob; here they are generated from the
        annotation, so schema and runtime cannot drift.
        """
        alternatives = _defs()["EqualityFilter"]["properties"]["value"]["anyOf"]
        arrays = [alt for alt in alternatives if alt.get("type") == "array"]
        assert arrays, "expected at least one array alternative"
        for array in arrays:
            assert array["minItems"] == 1
            assert array["maxItems"] == _MAX_FILTER_VALUES

    def test_numeric_compare_value_admits_only_numbers(self) -> None:
        """G2, in the schema: a numeric comparand renders as integer/number only."""
        value = _defs()["NumericComparisonFilter"]["properties"]["value"]
        assert {alt["type"] for alt in value["anyOf"]} == {"integer", "number"}

    def test_boolean_value_is_null_typed(self) -> None:
        """``true``/``false`` take no operand, and the schema says so."""
        assert _defs()["BooleanStateFilter"]["properties"]["value"]["type"] == "null"

    def test_equality_property_type_excludes_boolean(self) -> None:
        """A boolean property has no ``equals`` operand, so the enum omits it.

        The flat ``Filter`` raises for this combination at runtime while
        advertising ``boolean`` as a legal ``property_type``; narrowing the
        ``Literal`` moves the rule into the schema.
        """
        enum = _defs()["EqualityFilter"]["properties"]["property_type"]["enum"]
        assert "boolean" not in enum
        assert "string" in enum

    def test_numeric_compare_property_type_is_pinned(self) -> None:
        """``NumericComparisonFilter`` pins ``property_type`` to ``number``.

        The flat ``Filter`` silently rewrote a caller-supplied ``string``
        to ``number`` in ``__post_init__``; pinning the ``Literal`` states
        the constraint up front instead of mutating the input.
        """
        prop_type = _defs()["NumericComparisonFilter"]["properties"]["property_type"]
        assert prop_type["const"] == "number"

    def test_substring_value_is_string_only(self) -> None:
        """``SubstringFilter.value`` advertises ``str`` and hides the cohort shape.

        ``FilterFactory.in_cohort()`` emits ``contains`` against ``$cohorts`` with a
        ``list[dict]`` value. That is a builder artifact, not a declarative
        input, so ``SkipJsonSchema`` keeps it runtime-legal and
        schema-invisible — schema ⊂ runtime, the safe direction.
        """
        assert _defs()["SubstringFilter"]["properties"]["value"]["type"] == "string"


class TestEqualityFilterValidation:
    """``equals``/``does not equal`` — the most common payload in the API."""

    def test_accepts_bare_scalar_payload(self) -> None:
        """``{"operator": "equals", "value": "x"}`` validates with no ``property_type``.

        The scalar is wrapped into a single-element list, matching the
        flat ``Filter`` and the wire format the segmentation API expects.
        """
        parsed = _ADAPTER.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        assert parsed.value == ["US"]
        assert parsed.property_type == "string"

    def test_accepts_list_value(self) -> None:
        """A list of strings passes through untouched."""
        parsed = _ADAPTER.validate_python(
            {"property": "country", "operator": "does not equal", "value": ["US", "CA"]}
        )
        assert parsed.value == ["US", "CA"]

    def test_accepts_numeric_value_under_numeric_property_type(self) -> None:
        """A numeric-typed equality filter keeps its scalar operand unwrapped."""
        parsed = _ADAPTER.validate_python(
            {
                "property": "amount",
                "operator": "equals",
                "property_type": "number",
                "value": 10,
            }
        )
        assert parsed.value == 10

    def test_rejects_string_value_under_numeric_property_type(self) -> None:
        """G1: a numeric-typed filter rejects a string operand.

        Cross-field, so JSON Schema cannot express it; a
        ``model_validator`` keeps the runtime stricter than the schema.
        """
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "amount",
                    "operator": "equals",
                    "property_type": "number",
                    "value": "oops",
                }
            )

    def test_rejects_numeric_list_under_string_property_type(self) -> None:
        """A string-typed filter rejects numeric list items."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "country", "operator": "equals", "value": [1, 2]}
            )

    def test_rejects_bare_number_under_string_property_type(self) -> None:
        """A string-typed filter rejects a scalar numeric operand.

        The scalar-to-list wrap only fires for ``str``, so a bare number
        reaches the string branch unwrapped. It must raise the flat
        ``Filter``'s "needs str or list" message rather than blowing up on
        an un-iterable operand.
        """
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "country", "operator": "equals", "value": 10}
            )
        assert "list of strings" in str(exc_info.value)

    def test_rejects_boolean_property_type(self) -> None:
        """``property_type: "boolean"`` is outside the narrowed enum."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {
                    "property": "opted_in",
                    "operator": "equals",
                    "property_type": "boolean",
                    "value": "true",
                }
            )
        assert "literal_error" in _error_types(exc_info)

    def test_rejects_bool_value(self) -> None:
        """``True`` is not silently coerced to ``1``.

        Lax ``int`` coercion would turn a boolean operand into an integer
        before any operator rule ran; the strict numeric alternatives
        refuse it natively, replacing a hand-written before-validator.
        """
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "opted_in", "operator": "equals", "value": True}
            )

    def test_rejects_empty_list(self) -> None:
        """An empty value list violates the rendered ``minItems`` bound."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "country", "operator": "equals", "value": []}
            )
        assert "too_short" in _error_types(exc_info)

    def test_rejects_missing_value(self) -> None:
        """``equals`` requires an operand — the field has no default."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python({"property": "country", "operator": "equals"})
        assert "missing" in _error_types(exc_info)


class TestNumericCompareFilterValidation:
    """``is greater than`` and friends accept numbers and nothing else."""

    @pytest.mark.parametrize(
        "operator", ["is greater than", "is less than", "is at least", "is at most"]
    )
    def test_accepts_numeric_comparand(self, operator: str) -> None:
        """A numeric comparand validates and defaults ``property_type``."""
        parsed = _ADAPTER.validate_python(
            {"property": "amount", "operator": operator, "value": 10}
        )
        assert parsed.value == 10
        assert parsed.property_type == "number"

    def test_rejects_string_comparand(self) -> None:
        """G2: ``{"operator": "is greater than", "value": "abc"}`` is rejected.

        Schema-valid and runtime-invalid under the flat ``Filter``. Strict
        numeric alternatives close it, so the failure is ``*_type`` rather
        than ``*_parsing`` — a numeric-looking string is refused too,
        which is exactly what ``{"type": "number"}`` promises.
        """
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is greater than", "value": "abc"}
            )
        assert _error_types(exc_info) == {"int_type", "float_type"}

    def test_rejects_bool_comparand(self) -> None:
        """``True`` is not a number, and strict mode says so."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is at least", "value": True}
            )

    def test_rejects_missing_value(self) -> None:
        """A comparison without a comparand is meaningless."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is greater than"}
            )
        assert "missing" in _error_types(exc_info)


class TestSubstringFilterValidation:
    """Substring operators take exactly one string."""

    @pytest.mark.parametrize(
        "operator", ["contains", "does not contain", "starts with", "ends with"]
    )
    def test_accepts_string_needle(self, operator: str) -> None:
        """A string needle validates."""
        parsed = _ADAPTER.validate_python(
            {"property": "email", "operator": operator, "value": "@mixpanel.com"}
        )
        assert parsed.value == "@mixpanel.com"

    def test_accepts_cohort_wire_shape(self) -> None:
        """The ``$cohorts`` builder artifact parses into ``CohortRef``.

        ``FilterFactory.in_cohort()`` emits this shape. It routes to
        :class:`ContainmentFilter` — the reason containment is its own
        model — and the entries come back typed rather than as the raw
        mappings the old ``SkipJsonSchema`` residual left them.
        """
        parsed = _ADAPTER.validate_python(
            {
                "property": "$cohorts",
                "operator": "contains",
                "value": [{"cohort": {"id": 123}}],
            }
        )
        assert isinstance(parsed, ContainmentFilter)
        assert not isinstance(parsed.value, str)
        assert [entry.cohort.id for entry in parsed.value] == [123]

    def test_rejects_list_of_strings(self) -> None:
        """A substring match takes one needle, not a list."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "email", "operator": "contains", "value": ["a", "b"]}
            )


class TestBooleanFilterValidation:
    """``true``/``false`` test a boolean property and take no operand."""

    @pytest.mark.parametrize("operator", ["true", "false"])
    def test_accepts_bare_boolean_payload(self, operator: str) -> None:
        """A boolean filter validates and pins ``property_type``."""
        parsed = _ADAPTER.validate_python(
            {"property": "opted_in", "operator": operator}
        )
        assert parsed.value is None
        assert parsed.property_type == "boolean"

    def test_rejects_value(self) -> None:
        """A boolean operator carrying a value is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "opted_in", "operator": "true", "value": True}
            )
        assert "value_error" in _error_types(exc_info)


class TestRangeAndDateMemberSchema:
    """Schema shape of the four range/date members."""

    @pytest.mark.parametrize(
        ("operator", "member"),
        [
            ("is between", "NumericRangeFilter"),
            ("not between", "NumericRangeFilter"),
            ("was on", "AbsoluteDateFilter"),
            ("was not on", "AbsoluteDateFilter"),
            ("was before", "AbsoluteDateFilter"),
            ("was since", "AbsoluteDateFilter"),
            ("was between", "DateRangeFilter"),
            ("was not between", "DateRangeFilter"),
            ("was in the", "RelativeDateFilter"),
            ("was not in the", "RelativeDateFilter"),
            ("was in the next", "RelativeDateFilter"),
        ],
    )
    def test_every_range_and_date_operator_routes_to_its_member(
        self, operator: str, member: str
    ) -> None:
        """Each range/date operator selects — and validates against — one member."""
        assert _routes_to(operator) == member

    def test_relative_window_bound_is_generated(self) -> None:
        """``exclusiveMinimum`` is generated, not hand-written.

        ``Annotated[StrictInt, Field(gt=0)]`` both emits the keyword and
        enforces it, unlike the schema-only ``_PositiveStrictIntSchema``
        alias used elsewhere in this module.
        """
        value = _defs()["RelativeDateFilter"]["properties"]["value"]
        assert value["exclusiveMinimum"] == 0
        assert value["type"] == "integer"

    def test_absolute_date_value_is_a_date_formatted_string(self) -> None:
        """``was on`` advertises a date-formatted, pattern-bounded string.

        ``format`` is annotation-only in Draft 2020-12, so the pattern
        carries the machine-checkable half: a schema-only consumer
        rejects ``"01-05-2025"`` without needing format assertions on.
        """
        value = dict(_defs()["AbsoluteDateFilter"]["properties"]["value"])
        value.pop("title", None)
        assert value == _DATE_SCHEMA

    def test_numeric_range_renders_a_fixed_length_pair(self) -> None:
        """A numeric range is a two-element array of numbers.

        It stays a JSON array (not a positional tuple) because the engage
        selector builder gates on ``isinstance(value, list)``; the length
        is pinned by ``minItems``/``maxItems`` instead of ``prefixItems``.
        """
        value = _defs()["NumericRangeFilter"]["properties"]["value"]
        assert value["minItems"] == value["maxItems"] == 2
        assert {alt["type"] for alt in value["items"]["anyOf"]} == {
            "integer",
            "number",
        }

    def test_date_range_renders_a_pair_of_dates(self) -> None:
        """Both endpoints of a date range carry ``format: "date"``."""
        value = _defs()["DateRangeFilter"]["properties"]["value"]
        assert value["minItems"] == value["maxItems"] == 2
        items = dict(value["items"])
        items.pop("title", None)
        assert items == _DATE_SCHEMA

    def test_date_unit_appears_only_on_the_relative_member(self) -> None:
        """``date_unit`` is scoped to the one member that uses it.

        On the flat ``Filter`` it sat on every operator's schema, telling
        consumers a ``date_unit`` was meaningful alongside ``equals``.
        """
        carriers = {
            name
            for name, schema in _defs().items()
            if "date_unit" in schema.get("properties", {})
        }
        assert carriers == {"RelativeDateFilter"}


class TestNumericRangeFilterValidation:
    """``is between`` / ``not between`` take exactly two numbers."""

    @pytest.mark.parametrize("operator", ["is between", "not between"])
    def test_accepts_numeric_pair(self, operator: str) -> None:
        """A two-number range validates and pins ``property_type``."""
        parsed = _ADAPTER.validate_python(
            {"property": "age", "operator": operator, "value": [18, 65]}
        )
        assert parsed.value == [18, 65]
        assert parsed.property_type == "number"

    def test_rejects_single_element(self) -> None:
        """G8: a one-element range is rejected as ``too_short``."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "age", "operator": "is between", "value": [1]}
            )
        assert "too_short" in _error_types(exc_info)

    def test_rejects_three_elements(self) -> None:
        """A range with a third endpoint is rejected, not truncated."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "age", "operator": "is between", "value": [1, 2, 3]}
            )
        assert "too_long" in _error_types(exc_info)

    def test_rejects_string_endpoint(self) -> None:
        """A range endpoint must be numeric, and is not coerced from text."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "age", "operator": "is between", "value": ["low", 10]}
            )
        assert _error_types(exc_info) == {"int_type", "float_type"}

    def test_rejects_bool_endpoint(self) -> None:
        """Strict numerics stop ``True`` from silently becoming ``1``."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "age", "operator": "is between", "value": [True, 10]}
            )


class TestAbsoluteDateFilterValidation:
    """The four single-date operators take one ``YYYY-MM-DD`` string."""

    @pytest.mark.parametrize(
        "operator", ["was on", "was not on", "was before", "was since"]
    )
    def test_accepts_iso_date(self, operator: str) -> None:
        """A well-formed date validates and pins ``property_type``."""
        parsed = _ADAPTER.validate_python(
            {"property": "$time", "operator": operator, "value": "2025-01-05"}
        )
        assert parsed.value == "2025-01-05"
        assert parsed.property_type == "datetime"

    def test_value_stays_a_string(self) -> None:
        """Wire-format guard — the single most important test in M3.

        ``bookmark_builders`` copies ``_value`` straight onto the outgoing
        payload, so promoting ``_DateStr`` to ``datetime.date`` would
        silently change ``"2025-01-05"`` into a Python object. Assert the
        type, not just equality: ``date`` compares unequal to the string,
        but a future ``str`` subclass would not.
        """
        parsed = _ADAPTER.validate_python(
            {"property": "$time", "operator": "was on", "value": "2025-01-05"}
        )
        assert type(parsed.value) is str

    @pytest.mark.parametrize(
        "value",
        [
            "2025-13-45",
            "2025-02-30",
            "01-05-2025",
            "2025-1-5",
            "not a date",
            "",
        ],
    )
    def test_rejects_malformed_or_impossible_dates(self, value: str) -> None:
        """G6: format *and* calendar validity are both enforced."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was on", "value": value}
            )
        assert "value_error" in _error_types(exc_info)

    def test_rejects_non_string_value(self) -> None:
        """A date operator will not accept a bare integer."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was on", "value": 20250105}
            )
        assert "string_type" in _error_types(exc_info)


class TestDateRangeFilterValidation:
    """``was between`` / ``was not between`` take two ordered dates."""

    @pytest.mark.parametrize("operator", ["was between", "was not between"])
    def test_accepts_ordered_pair(self, operator: str) -> None:
        """A well-ordered date pair validates as strings."""
        parsed = _ADAPTER.validate_python(
            {
                "property": "$time",
                "operator": operator,
                "value": ["2025-01-01", "2025-02-01"],
            }
        )
        assert parsed.value == ["2025-01-01", "2025-02-01"]
        assert all(type(endpoint) is str for endpoint in parsed.value)

    def test_accepts_equal_endpoints(self) -> None:
        """A single-day window is legal — the bound is ``<=``, not ``<``."""
        parsed = _ADAPTER.validate_python(
            {
                "property": "$time",
                "operator": "was between",
                "value": ["2025-01-01", "2025-01-01"],
            }
        )
        assert parsed.value == ["2025-01-01", "2025-01-01"]

    def test_rejects_reversed_endpoints(self) -> None:
        """Ordering is cross-field, so it is a documented runtime residual."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {
                    "property": "$time",
                    "operator": "was between",
                    "value": ["2025-02-01", "2025-01-01"],
                }
            )
        assert "from_date must be before to_date" in str(exc_info.value)

    def test_rejects_malformed_endpoint(self) -> None:
        """Each endpoint is date-validated independently."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "$time",
                    "operator": "was between",
                    "value": ["2025-01-01", "2025-13-45"],
                }
            )


class TestRelativeDateFilterValidation:
    """The three relative-window operators take a positive integer."""

    @pytest.mark.parametrize(
        "operator", ["was in the", "was not in the", "was in the next"]
    )
    def test_accepts_positive_window(self, operator: str) -> None:
        """A positive window validates and defaults ``date_unit``."""
        parsed = _ADAPTER.validate_python(
            {"property": "$time", "operator": operator, "value": 7}
        )
        assert parsed.value == 7
        assert parsed.date_unit == "day"
        assert parsed.property_type == "datetime"

    def test_accepts_explicit_date_unit(self) -> None:
        """``date_unit`` is settable on the member that declares it."""
        parsed = _ADAPTER.validate_python(
            {
                "property": "$time",
                "operator": "was in the",
                "value": 3,
                "date_unit": "week",
            }
        )
        assert parsed.date_unit == "week"

    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive_window(self, value: int) -> None:
        """G7: the window bound is enforced, not merely advertised."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was in the", "value": value}
            )
        assert "greater_than" in _error_types(exc_info)

    @pytest.mark.parametrize("value", [True, "5", 2.5])
    def test_rejects_non_integer_window(self, value: object) -> None:
        """Strict integers keep bools, numeric strings, and floats out."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was in the", "value": value}
            )
        assert "int_type" in _error_types(exc_info)

    def test_rejects_date_unit_on_another_member(self) -> None:
        """``extra="forbid"`` keeps ``date_unit`` off non-relative members."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "country",
                    "operator": "equals",
                    "value": "US",
                    "date_unit": "day",
                }
            )


class TestListContainsFilterValidation:
    """``list_contains`` carries sub-filters instead of a value."""

    def _payload(self, **overrides: Any) -> dict[str, Any]:
        """Build a minimal valid ``list_contains`` payload.

        Args:
            **overrides: Keys to add to or replace in the base payload.

        Returns:
            A payload dict ready for ``_ADAPTER.validate_python``.
        """
        payload: dict[str, Any] = {
            "property": "cart",
            "operator": "list_contains",
            "list_item_filters": [
                {"property": "Brand", "operator": "equals", "value": "nike"}
            ],
            "list_item_quantifier": "any",
        }
        payload.update(overrides)
        return payload

    def test_accepts_valid_nesting(self) -> None:
        """A sub-filter round-trips as its own validated member."""
        parsed = _ADAPTER.validate_python(self._payload())
        (sub,) = parsed.list_item_filters
        assert isinstance(sub, EqualityFilter)
        assert sub.property == "Brand"
        assert parsed.list_item_quantifier == "any"

    def test_quantifier_defaults_to_any(self) -> None:
        """Omitting the quantifier matches the factory's ``"any"`` default."""
        payload = self._payload()
        del payload["list_item_quantifier"]
        assert _ADAPTER.validate_python(payload).list_item_quantifier == "any"

    def test_rejects_value(self) -> None:
        """G3: the conditions belong in the sub-filters, not in ``value``."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(self._payload(value="nike"))
        assert "value_error" in _error_types(exc_info)

    def test_rejects_missing_sub_filters(self) -> None:
        """G4: ``list_item_filters`` is required, not defaulted to ``None``."""
        payload = self._payload()
        del payload["list_item_filters"]
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(payload)
        assert "missing" in _error_types(exc_info)

    def test_rejects_empty_sub_filters(self) -> None:
        """A ``list_contains`` with nothing to match is meaningless."""
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(self._payload(list_item_filters=[]))
        assert "too_short" in _error_types(exc_info)

    def test_rejects_nested_list_contains(self) -> None:
        """Nesting is structurally impossible, not a runtime check.

        ``_list_item_filters`` points at a union that omits
        ``CompoundFilter``, so the tag is simply unknown there — and
        the prohibition is visible in the schema rather than buried in
        ``__post_init__``.
        """
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(self._payload(list_item_filters=[self._payload()]))
        assert "invalid_nested_filter_operator" in _error_types(exc_info)

    def test_rejects_bad_quantifier(self) -> None:
        """The quantifier is a closed set of two values."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(self._payload(list_item_quantifier="some"))


class TestCohortPropertyGuard:
    """``$cohorts`` stays reserved for the cohort constructors.

    The flat ``Filter.__post_init__`` refused any hand-rolled ``$cohorts``
    filter that did not carry the ``[{"cohort": {...}}]`` wire structure,
    exempting only the value-less presence operators. These tests pin that
    behaviour so the union reproduces it exactly rather than approximately.
    """

    @pytest.mark.parametrize("operator", ["is set", "is not set"])
    def test_presence_operators_may_target_cohorts(self, operator: str) -> None:
        """The two value-less operators stay allowed on ``$cohorts``.

        They emit an ordinary filter entry that never touches the cohort
        wire structure, and were constructible before the guard existed.
        """
        parsed = _ADAPTER.validate_python(
            {"property": "$cohorts", "operator": operator}
        )
        assert isinstance(parsed, PresenceFilter)

    @pytest.mark.parametrize(
        "payload",
        [
            {"property": "$cohorts", "operator": "equals", "value": "123"},
            {"property": "$cohorts", "operator": "contains", "value": "123"},
            {"property": "$cohorts", "operator": "starts with", "value": "1"},
            {"property": "$cohorts", "operator": "true", "property_type": "boolean"},
            {"property": "$cohorts", "operator": "is greater than", "value": 1},
            {"property": "$cohorts", "operator": "was on", "value": "2025-01-05"},
        ],
        ids=["equals", "contains", "starts-with", "true", "greater-than", "was-on"],
    )
    def test_rejects_hand_rolled_cohort_filters(self, payload: dict[str, Any]) -> None:
        """Everything but the presence operators is refused on ``$cohorts``.

        A hand-rolled ``$cohorts`` filter either crashed the flow builder
        with an internal error or silently emitted an ordinary string
        filter, so it is rejected at construction instead.
        """
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(payload)

    @pytest.mark.parametrize("operator", ["contains", "does not contain"])
    def test_accepts_the_constructor_wire_shape(self, operator: str) -> None:
        """The shape ``FilterFactory.in_cohort()`` emits validates unchanged."""
        parsed = _ADAPTER.validate_python(
            {
                "property": "$cohorts",
                "operator": operator,
                "value": [{"cohort": {"id": 123, "name": "Power Users"}}],
                "property_type": "list",
            }
        )
        assert not isinstance(parsed.value, str)
        assert [(e.cohort.id, e.cohort.name) for e in parsed.value] == [
            (123, "Power Users")
        ]

    @pytest.mark.parametrize(
        "value",
        [[], [{"id": 123}], [{"cohort": 123}], [{"cohort": {"id": 1}}, {"x": 1}]],
        ids=["empty", "no-cohort-key", "cohort-not-a-dict", "one-bad-item"],
    )
    def test_rejects_malformed_cohort_wire_shape(self, value: list[Any]) -> None:
        """A near-miss of the wire structure is refused, not coerced."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "$cohorts",
                    "operator": "contains",
                    "value": value,
                    "property_type": "list",
                }
            )

    def test_rejects_cohort_wire_shape_on_another_property(self) -> None:
        """The ``list[dict]`` value is legal only on ``$cohorts``.

        The flat filter raised ``_MSG_NEEDS_STRING`` here; the union has
        to keep refusing it, otherwise a dict payload could smuggle the
        cohort structure onto an ordinary property.
        """
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "plan",
                    "operator": "contains",
                    "value": [{"cohort": {"id": 123}}],
                    "property_type": "list",
                }
            )


class TestUnionCompleteness:
    """The union covers the operator vocabulary exactly, with no gaps."""

    def test_every_member_is_reachable(self) -> None:
        """All ten members appear in the union's ``oneOf``."""
        assert len(_SCHEMA["oneOf"]) == 11

    def test_routing_covers_every_known_operator(self) -> None:
        """Every operator ``FilterOperator`` declares routes somewhere.

        Iterating :data:`FilterOperator` rather than a literal list means
        adding an operator to the package without adding it to a member
        fails loudly here, instead of silently producing
        ``union_tag_invalid`` for real callers.

        ``Filter``'s operator-family frozensets are deliberately not the
        source: none of them covers ``equals`` or ``list_contains``, so
        that route needs a hand-written patch set, and an operator missed
        from a frozenset would drop out of the loop unnoticed.
        """
        for operator in get_args(FilterOperator):
            assert _routes_to(operator), operator

    def test_nested_union_omits_only_list_contains(self) -> None:
        """The nested union is the outer one minus ``list_contains``."""
        outer = _member_refs(_SCHEMA["oneOf"])
        nested = _member_refs(
            _defs()["CompoundFilter"]["properties"]["list_item_filters"]["items"][
                "oneOf"
            ]
        )
        assert outer - nested == {"CompoundFilter"}

    def test_no_member_leaks_underscore_properties(self) -> None:
        """No member exposes a private field name to schema consumers."""
        leaked = {
            f"{name}.{prop}"
            for name, schema in _defs().items()
            for prop in schema.get("properties", {})
            if prop.startswith("_")
        }
        assert not leaked

    def test_scoped_fields_appear_only_where_they_apply(self) -> None:
        """List-only fields stay off the other nine members.

        On the flat ``Filter`` these sat on every operator's schema.
        """
        for field in ("list_item_filters", "list_item_quantifier"):
            carriers = {
                name
                for name, schema in _defs().items()
                if field in schema.get("properties", {})
            }
            assert carriers == {"CompoundFilter"}, field


class TestParityMatrix:
    """Every gap payload is now rejected by schema *and* by runtime.

    The eight rows are the schema/runtime divergences catalogued on the
    flat ``Filter``: each was advertised as valid by
    ``model_json_schema()`` while ``__post_init__`` rejected it. A
    consuming repository driving an LLM request schema off the generated
    schema would emit them and get a runtime error back.
    """

    _GAPS: dict[str, dict[str, Any]] = {
        "G1": {
            "property": "age",
            "operator": "equals",
            "property_type": "number",
            "value": "oops",
        },
        "G2": {"property": "age", "operator": "is greater than", "value": "abc"},
        "G3": {
            "property": "cart",
            "operator": "list_contains",
            "value": "nike",
            "list_item_filters": [
                {"property": "Brand", "operator": "equals", "value": "nike"}
            ],
        },
        "G4": {"property": "cart", "operator": "list_contains"},
        "G5": {"property": "plan", "operator": "is set", "value": "y"},
        "G6": {"property": "$time", "operator": "was on", "value": "2025-13-45"},
        "G7": {"property": "$time", "operator": "was in the", "value": 0},
        "G8": {"property": "age", "operator": "is between", "value": [1]},
    }

    @pytest.mark.parametrize("gap", sorted(_GAPS))
    def test_runtime_rejects_every_gap_payload(self, gap: str) -> None:
        """All eight payloads raise, including the two cross-field ones."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(self._GAPS[gap])

    @pytest.mark.parametrize("gap", sorted(set(_GAPS) - {"G6"}))
    def test_schema_rejects_every_structural_gap_payload(self, gap: str) -> None:
        """Seven of the eight are rejected by the generated schema alone.

        A plain Draft 2020-12 validator — no Pydantic, no Python — turns
        each one down, which is the property consuming repositories
        depend on.
        """
        assert not _VALIDATOR.is_valid(self._GAPS[gap])

    @pytest.mark.parametrize("gap", ["G6"])
    def test_documented_residuals_are_runtime_only(self, gap: str) -> None:
        """G6 is accepted by the schema and caught at runtime.

        Calendar validity: ``"2025-13-45"`` satisfies the ``pattern``
        but is not a real date, and no JSON Schema keyword expresses the
        difference. Runtime stricter than schema is the safe direction;
        the reverse is what this PR exists to eliminate.

        G1 used to sit here too — the cross-field ``value`` /
        ``property_type`` pairing. ``EqualityFilter`` now carries that
        rule as an ``if``/``then`` in its schema, so the schema rejects
        it and the row moved to the test above.
        """
        assert _VALIDATOR.is_valid(self._GAPS[gap])

    def test_integral_float_is_a_documented_residual(self) -> None:
        """``1.0`` is schema-valid on a strict-int field and runtime-invalid.

        JSON has one number type, so JSON Schema's ``"type": "integer"``
        matches any number with a zero fractional part. ``StrictInt``
        refuses ``1.0``, per the strict-mode policy that stops ``True``
        and ``"5"`` becoming ``1`` and ``5``. No keyword expresses the
        difference, so this joins the documented residuals — and it is
        unreachable from JSON text, which parses ``1`` to an ``int``.

        Found by ``tests/test_filter_union_pbt.py``, which is why that
        module exists.
        """
        payload = {"property": "created", "operator": "was in the", "value": 1.0}
        assert _VALIDATOR.is_valid(payload)
        with pytest.raises(ValidationError) as exc_info:
            _ADAPTER.validate_python(payload)
        assert _error_types(exc_info) == {"int_type"}

        # The same field parsed from JSON text is an int, and validates.
        from_json = json.loads(
            '{"property": "created", "operator": "was in the", "value": 1}'
        )
        assert _ADAPTER.validate_python(from_json).value == 1


# =============================================================================
# Filter validation, moved here from tests/test_query_models.py
#
# These classes predate the union and were retuned in place when it landed —
# five `match=` strings had to change. Keeping them next to the members they
# exercise means one home for filter validation, so the next message change
# costs one edit rather than two. They are wordier than the schema-shape tests
# above because several assert classmethod/dict parity, which the schema
# cannot express.
# =============================================================================


class TestFilterDictConstruction:
    """Filter supports dict construction via validation aliases."""

    def test_equals_dict(self) -> None:
        """Dict with 'equals' produces a Filter with wrapped value."""
        f = _ADAPTER.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        assert isinstance(f, AbstractFilter)
        assert f.value == ["US"]
        assert f.property_type == "string"

    def test_numeric_operator_dict(self) -> None:
        """Dict with numeric operator infers property_type='number'."""
        f = _ADAPTER.validate_python(
            {"property": "amount", "operator": "is greater than", "value": 50}
        )
        assert isinstance(f, AbstractFilter)
        assert f.property_type == "number"

    def test_is_set_no_value(self) -> None:
        """Dict with 'is set' needs no value field."""
        f = _ADAPTER.validate_python({"property": "email", "operator": "is set"})
        assert isinstance(f, AbstractFilter)
        assert f.value is None

    def test_between_operator_dict(self) -> None:
        """Dict with 'is between' accepts a two-element list."""
        f = _ADAPTER.validate_python(
            {"property": "amount", "operator": "is between", "value": [10, 50]}
        )
        assert isinstance(f, AbstractFilter)
        assert f.property_type == "number"
        assert f.value == [10, 50]

    def test_equals_non_string_scalar_rejected(self) -> None:
        """equals with a bare non-string scalar is rejected.

        The classmethod contract is ``str | list[str]``; passing the
        scalar through emitted a bare ``filterValue: 5`` on the wire
        where every classmethod-built equals emits a list.
        """
        with pytest.raises(ValidationError, match="string or a list"):
            _ADAPTER.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": 5}
            )

    def test_not_equals_bool_scalar_rejected(self) -> None:
        """does not equal with a bare bool is rejected like other scalars.

        Strict scalars and strict list items reject ``True`` structurally
        now, so the message is pydantic's per-alternative one rather than
        the flat filter's single hand-written line.
        """
        with pytest.raises(ValidationError, match="valid string"):
            _ADAPTER.validate_python(
                {"property": "active", "operator": "does not equal", "value": True}
            )

    def test_equals_list_elements_must_be_strings(self) -> None:
        """String-typed equals rejects a homogeneous non-string list."""
        with pytest.raises(ValidationError, match="list of strings"):
            _ADAPTER.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": [5, 6]}
            )

    def test_equals_mixed_list_rejected_by_field_typing(self) -> None:
        """Mixed-type lists match no _value union alternative and are rejected."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": [5, "a"]}
            )

    def test_is_between_requires_numeric_elements(self) -> None:
        """is between requires numeric endpoints (FilterFactory.between parity).

        String endpoints built a self-contradictory wire entry
        (filterType "number" with string operands).
        """
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is between", "value": ["a", "b"]}
            )

    def test_is_between_mixed_float_int_accepted(self) -> None:
        """is between accepts mixed int/float endpoints like FilterFactory.between."""
        f = _ADAPTER.validate_python(
            {"property": "amount", "operator": "is between", "value": [1, 2.5]}
        )
        assert f.value == [1, 2.5]
        assert f.property_type == "number"

    def test_equivalence_with_classmethod(self) -> None:
        """Dict-constructed Filter matches classmethod-constructed Filter."""
        f_dict = _ADAPTER.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        f_cls = FilterFactory.equals("country", "US")
        assert f_dict.property == f_cls.property
        assert f_dict.operator == f_cls.operator
        assert f_dict.value == f_cls.value
        assert f_dict.property_type == f_cls.property_type

    def test_invalid_operator_rejected(self) -> None:
        """Unknown operator string is rejected by FilterOperator literal."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {"property": "x", "operator": "bogus", "value": "y"}
            )

    def test_relative_date_default_unit(self) -> None:
        """Relative-date operators default date_unit to 'day'."""
        f = _ADAPTER.validate_python(
            {"property": "created", "operator": "was in the", "value": 7}
        )
        assert f.date_unit == "day"
        assert f.property_type == "datetime"

    def test_relative_date_explicit_unit(self) -> None:
        """Explicit date_unit overrides the default."""
        f = _ADAPTER.validate_python(
            {
                "property": "created",
                "operator": "was in the",
                "value": 2,
                "date_unit": "week",
            }
        )
        assert f.date_unit == "week"

    def test_boolean_type_inference(self) -> None:
        """Boolean operators infer property_type='boolean'."""
        f = _ADAPTER.validate_python({"property": "active", "operator": "true"})
        assert f.property_type == "boolean"


class TestFilterEqualityPropertyTypeCompatibility:
    """Equality operands must match an explicitly declared property_type.

    A scalar string was wrapped into a list before ``_property_type`` was
    consulted, so a filter declared ``number`` kept a string operand and
    reached the wire as ``filterType: "number"`` with
    ``filterValue: ["oops"]`` — a self-contradictory query the API cannot
    answer meaningfully.
    """

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_number_type_rejects_scalar_string(self, operator: str) -> None:
        """A number-typed equality rejects a scalar string operand.

        Args:
            operator: The equality operator under test.
        """
        with pytest.raises(ValidationError, match="numeric"):
            _ADAPTER.validate_python(
                {
                    "property": "amount",
                    "operator": operator,
                    "value": "oops",
                    "property_type": "number",
                }
            )

    def test_number_type_rejects_string_list(self) -> None:
        """A number-typed equality rejects a list of string operands."""
        with pytest.raises(ValidationError, match="numeric"):
            _ADAPTER.validate_python(
                {
                    "property": "amount",
                    "operator": "equals",
                    "value": ["10", "20"],
                    "property_type": "number",
                }
            )

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_number_type_keeps_scalar_numeric_value(self, operator: str) -> None:
        """A number-typed equality keeps a numeric scalar unwrapped.

        Pinned by ``filter_to_selector``: the scalar numeric form is the
        schema-driven equality path through ``query_user``.

        Args:
            operator: The equality operator under test.
        """
        f = _ADAPTER.validate_python(
            {
                "property": "count",
                "operator": operator,
                "value": 42,
                "property_type": "number",
            }
        )
        assert f.value == 42
        assert f.property_type == "number"

    def test_number_type_accepts_numeric_list(self) -> None:
        """A number-typed equality accepts a list of numeric operands."""
        f = _ADAPTER.validate_python(
            {
                "property": "count",
                "operator": "equals",
                "value": [1, 2.5],
                "property_type": "number",
            }
        )
        assert f.value == [1, 2.5]

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_boolean_type_rejects_equality(self, operator: str) -> None:
        """A boolean-typed property cannot be tested with equality.

        Boolean properties are tested with the value-less ``true`` /
        ``false`` operators, so no operand is compatible here. The rule
        now lives in ``EqualityFilter.property_type``'s ``Literal``,
        which omits ``"boolean"`` — so it reaches the schema instead of
        being a Python-only check.

        Args:
            operator: The equality operator under test.
        """
        with pytest.raises(ValidationError, match="literal_error"):
            _ADAPTER.validate_python(
                {
                    "property": "active",
                    "operator": operator,
                    "value": "oops",
                    "property_type": "boolean",
                }
            )

    def test_string_type_still_wraps_scalar(self) -> None:
        """The default string-typed equality keeps wrapping a scalar."""
        f = _ADAPTER.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        assert f.value == ["US"]

    def test_explicit_string_type_still_wraps_scalar(self) -> None:
        """An explicitly string-typed equality keeps wrapping a scalar."""
        f = _ADAPTER.validate_python(
            {
                "property": "country",
                "operator": "equals",
                "value": "US",
                "property_type": "string",
            }
        )
        assert f.value == ["US"]

    def test_datetime_type_still_wraps_scalar(self) -> None:
        """A datetime-typed equality is unaffected by the number rule."""
        f = _ADAPTER.validate_python(
            {
                "property": "$time",
                "operator": "equals",
                "value": "2024-01-01",
                "property_type": "datetime",
            }
        )
        assert f.value == ["2024-01-01"]

    def test_classmethod_number_equality_still_builds(self) -> None:
        """Direct construction with a numeric operand is unaffected."""
        f = EqualityFilter(
            property="count",
            operator="equals",
            value=42,
            property_type="number",
            resource_type="events",
        )
        assert f.value == 42


class TestFilterDictDateValidation:
    """Dict-constructed Filters validate dates exactly like the classmethods.

    ``__post_init__`` must replicate the classmethods' date validation
    (``_validate_date``, from<=to ordering, quantity > 0) so the
    dict/LLM construction path cannot produce wire payloads the
    classmethod path would reject.
    """

    def test_was_on_rejects_malformed_date(self) -> None:
        """'was on' with a non-date string is rejected (classmethod parity)."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was on", "value": "not-a-date"}
            )

    def test_was_on_rejects_invalid_calendar_date(self) -> None:
        """'was on' with an impossible calendar date is rejected."""
        with pytest.raises(ValueError, match="not a valid calendar date"):
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was on", "value": "2024-02-30"}
            )

    def test_was_on_rejects_non_string_value(self) -> None:
        """'was on' with a numeric value is rejected.

        ``_DateStr`` is a ``str`` alias, so a non-string never reaches
        the date parser — it fails the annotation first.
        """
        with pytest.raises(ValueError, match="valid string"):
            _ADAPTER.validate_python(
                {"property": "$time", "operator": "was on", "value": 20240101}
            )

    @pytest.mark.parametrize("operator", ["was not on", "was before", "was since"])
    def test_single_date_operators_reject_malformed_date(self, operator: str) -> None:
        """All single-date operators validate their date value."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _ADAPTER.validate_python(
                {"property": "created", "operator": operator, "value": "01/01/2024"}
            )

    def test_was_on_valid_date_matches_classmethod(self) -> None:
        """'was on' with a valid date matches FilterFactory.on()."""
        f_dict = _ADAPTER.validate_python(
            {"property": "created", "operator": "was on", "value": "2024-06-01"}
        )
        f_cls = FilterFactory.on("created", "2024-06-01")
        assert f_dict.value == f_cls.value
        assert f_dict.property_type == f_cls.property_type

    def test_was_between_rejects_reversed_range(self) -> None:
        """'was between' with from > to is rejected (classmethod parity)."""
        with pytest.raises(ValueError, match="from_date must be before to_date"):
            _ADAPTER.validate_python(
                {
                    "property": "created",
                    "operator": "was between",
                    "value": ["2024-06-30", "2024-01-01"],
                }
            )

    def test_was_not_between_rejects_reversed_range(self) -> None:
        """'was not between' with from > to is rejected."""
        with pytest.raises(ValueError, match="from_date must be before to_date"):
            _ADAPTER.validate_python(
                {
                    "property": "created",
                    "operator": "was not between",
                    "value": ["2024-06-30", "2024-01-01"],
                }
            )

    def test_was_between_rejects_malformed_dates(self) -> None:
        """'was between' validates both elements as dates."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _ADAPTER.validate_python(
                {
                    "property": "created",
                    "operator": "was between",
                    "value": ["2024-01-01", "garbage"],
                }
            )

    def test_was_between_valid_range_matches_classmethod(self) -> None:
        """'was between' with a valid range matches FilterFactory.date_between()."""
        f_dict = _ADAPTER.validate_python(
            {
                "property": "created",
                "operator": "was between",
                "value": ["2024-01-01", "2024-06-30"],
            }
        )
        f_cls = FilterFactory.date_between("created", "2024-01-01", "2024-06-30")
        assert f_dict.value == f_cls.value
        assert f_dict.property_type == f_cls.property_type

    def test_numeric_between_unaffected_by_date_checks(self) -> None:
        """Numeric 'is between' still accepts descending numbers (not dates)."""
        f = _ADAPTER.validate_python(
            {"property": "amount", "operator": "is between", "value": [10, 50]}
        )
        assert f.value == [10, 50]

    @pytest.mark.parametrize(
        "operator", ["was in the", "was not in the", "was in the next"]
    )
    def test_relative_date_rejects_zero_quantity(self, operator: str) -> None:
        """Relative-date operators reject quantity == 0 (classmethod parity)."""
        with pytest.raises(ValueError, match="greater than 0"):
            _ADAPTER.validate_python(
                {"property": "created", "operator": operator, "value": 0}
            )

    def test_relative_date_rejects_negative_quantity(self) -> None:
        """Relative-date operators reject negative quantities."""
        with pytest.raises(ValueError, match="greater than 0"):
            _ADAPTER.validate_python(
                {"property": "created", "operator": "was in the", "value": -3}
            )

    def test_relative_date_rejects_non_int_quantity(self) -> None:
        """Relative-date operators reject non-integer quantities.

        ``StrictInt`` refuses the coercion, so the failure is a type
        error rather than a bounds error.
        """
        with pytest.raises(ValueError, match="valid integer"):
            _ADAPTER.validate_python(
                {"property": "created", "operator": "was in the", "value": "soon"}
            )

    def test_relative_date_valid_matches_classmethod(self) -> None:
        """'was in the' with valid quantity matches FilterFactory.in_the_last()."""
        f_dict = _ADAPTER.validate_python(
            {
                "property": "created",
                "operator": "was in the",
                "value": 7,
                "date_unit": "week",
            }
        )
        f_cls = FilterFactory.in_the_last("created", 7, "week")
        assert f_dict.value == f_cls.value
        assert f_dict.date_unit == f_cls.date_unit


# =============================================================================
# Wrap-validator error grammar: package paths and stable codes
# =============================================================================


class TestFilterOperatorValueShape:
    """Filter enforces value shape per operator family at construction.

    Regression tests for finding
    ``filter-operator-value-shape-not-enforced``: numeric operators
    must carry numeric scalars, string operators must carry strings,
    and required values may not be omitted — otherwise the dict/LLM
    path emits self-contradictory wire entries (``filterType="number"``
    with ``filterValue="oops"``).
    """

    def test_greater_than_string_value_rejected(self) -> None:
        """'is greater than' with value 'oops' is rejected.

        ``StrictInt | StrictFloat`` refuses the coercion, so the
        rejection is structural and visible in the schema as
        ``{"type": "integer"} | {"type": "number"}``.
        """
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is greater than", "value": "oops"}
            )

    @pytest.mark.parametrize(
        "operator", ["is greater than", "is less than", "is at least", "is at most"]
    )
    def test_numeric_operators_reject_string_values(self, operator: str) -> None:
        """Every scalar numeric operator rejects a non-numeric value."""
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": operator, "value": "oops"}
            )

    def test_numeric_operator_rejects_bool_value(self) -> None:
        """'is less than' with a bool value is rejected (bool is not numeric)."""
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is less than", "value": True}
            )

    @pytest.mark.parametrize(
        "operator", ["is greater than", "is less than", "is at least", "is at most"]
    )
    def test_numeric_operators_reject_omitted_value(self, operator: str) -> None:
        """Scalar numeric operators require a value.

        ``NumericComparisonFilter.value`` has no default, so an omission is
        a stock ``missing`` and the schema lists ``value`` as required.
        """
        with pytest.raises(ValidationError, match="Field required"):
            _ADAPTER.validate_python({"property": "amount", "operator": operator})

    @pytest.mark.parametrize(
        "operator", ["contains", "does not contain", "starts with", "ends with"]
    )
    def test_string_operators_reject_numeric_values(self, operator: str) -> None:
        """String operators reject int/float values."""
        with pytest.raises(ValidationError, match="string"):
            _ADAPTER.validate_python(
                {"property": "name", "operator": operator, "value": 123}
            )

    def test_starts_with_float_value_rejected(self) -> None:
        """'starts with' with a float value is rejected."""
        with pytest.raises(ValidationError, match="string"):
            _ADAPTER.validate_python(
                {"property": "url", "operator": "starts with", "value": 1.5}
            )

    @pytest.mark.parametrize(
        "operator", ["contains", "does not contain", "starts with", "ends with"]
    )
    def test_string_operators_reject_omitted_value(self, operator: str) -> None:
        """String operators require a value."""
        with pytest.raises(ValidationError, match="string"):
            _ADAPTER.validate_python({"property": "name", "operator": operator})

    def test_contains_list_value_rejected(self) -> None:
        """'contains' with a list value is rejected (contract is str)."""
        with pytest.raises(ValidationError, match="string"):
            _ADAPTER.validate_python(
                {"property": "name", "operator": "contains", "value": ["a", "b"]}
            )

    def test_is_between_list_position_bools_rejected(self) -> None:
        """'is between' with [True, False] must not coerce to [1, 0].

        Regression for finding ``filter-list-position-bools-still-coerce``:
        booleans INSIDE list values hit pydantic's lax ``list[int | float]``
        alternative and coerced to 0/1 before ``__post_init__`` ran. The
        strict list items now refuse them outright.
        """
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "is between", "value": [True, False]}
            )

    def test_not_between_list_position_bool_rejected(self) -> None:
        """'not between' with a boolean endpoint is rejected."""
        with pytest.raises(ValidationError, match="valid number"):
            _ADAPTER.validate_python(
                {"property": "amount", "operator": "not between", "value": [1, True]}
            )

    def test_between_classmethod_bool_endpoint_rejected(self) -> None:
        """FilterFactory.between('amount', True, 100) must not become [1, 100]."""
        with pytest.raises(ValidationError, match="valid number"):
            FilterFactory.between("amount", True, 100)

    def test_equals_number_ptype_bool_list_rejected(self) -> None:
        """equals with property_type='number' and value [True] is rejected."""
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "property": "amount",
                    "operator": "equals",
                    "value": [True],
                    "property_type": "number",
                }
            )

    def test_equals_bool_list_error_reports_original_input(self) -> None:
        """The equals bool-list error reports [True], not the coerced [1]."""
        with pytest.raises(ValidationError, match=r"\[True\]") as exc_info:
            _ADAPTER.validate_python(
                {"property": "plan", "operator": "equals", "value": [True]}
            )
        assert "[1]" not in str(exc_info.value)

    def test_string_operator_valid_value_matches_classmethod(self) -> None:
        """'contains' with a string still matches FilterFactory.contains()."""
        f_dict = _ADAPTER.validate_python(
            {"property": "name", "operator": "contains", "value": "john"}
        )
        f_cls = FilterFactory.contains("name", "john")
        assert f_dict.value == f_cls.value
        assert f_dict.property_type == f_cls.property_type

    def test_numeric_operator_valid_value_matches_classmethod(self) -> None:
        """'is greater than' with a number still matches FilterFactory.greater_than()."""
        f_dict = _ADAPTER.validate_python(
            {"property": "amount", "operator": "is greater than", "value": 50}
        )
        f_cls = FilterFactory.greater_than("amount", 50)
        assert f_dict.value == f_cls.value
        assert f_dict.property_type == f_cls.property_type


class TestFilterCohortPropertyGuard:
    """Hand-rolled '$cohorts' filters are rejected at construction.

    Regression tests for finding
    ``filter-operator-value-shape-not-enforced``: the dict repro
    ``{"property": "$cohorts", "operator": "contains", "value": "123"}``
    previously constructed fine, then the Flow build path crashed with
    a raw internal ``RuntimeError`` while the Insights path silently
    emitted an ordinary string filter. Cohort membership must go
    through ``FilterFactory.in_cohort()`` / ``FilterFactory.not_in_cohort()``, which
    build the internal wire structure the builders require.
    """

    _COHORT_REPRO: ClassVar[dict[str, object]] = {
        "property": "$cohorts",
        "operator": "contains",
        "value": "123",
    }

    def test_hand_rolled_cohorts_contains_rejected(self) -> None:
        """The exact dict repro is rejected at Filter validation."""
        with pytest.raises(ValidationError, match="in_cohort"):
            _ADAPTER.validate_python(self._COHORT_REPRO)

    def test_hand_rolled_cohorts_equals_rejected(self) -> None:
        """'$cohorts' with a non-cohort operator is rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            _ADAPTER.validate_python(
                {"property": "$cohorts", "operator": "equals", "value": "123"}
            )

    def test_hand_rolled_cohorts_malformed_wire_shape_rejected(self) -> None:
        """A list-of-dicts value missing the 'cohort' key is rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            _ADAPTER.validate_python(
                {
                    "property": "$cohorts",
                    "operator": "contains",
                    "value": [{"not_cohort": 1}],
                }
            )

    def test_in_cohort_constructor_still_works(self) -> None:
        """FilterFactory.in_cohort() output passes the new guard."""
        f = FilterFactory.in_cohort(123, "Power Users")
        assert f.property == "$cohorts"
        assert f.operator == "contains"

    def test_not_in_cohort_constructor_still_works(self) -> None:
        """FilterFactory.not_in_cohort() output passes the new guard."""
        f = FilterFactory.not_in_cohort(789, "Bots")
        assert f.operator == "does not contain"

    def test_is_set_on_cohorts_allowed(self) -> None:
        """FilterFactory.is_set('$cohorts') constructs a normal is-set filter.

        Regression for finding
        ``cohorts-guard-rejects-previously-valid-is-set``: the guard
        must not reject the value-less presence operators, which built
        an ordinary filter entry before the guard existed.
        """
        f = FilterFactory.is_set("$cohorts")
        assert f.property == "$cohorts"
        assert f.operator == "is set"
        assert f.value is None

    def test_is_not_set_on_cohorts_allowed(self) -> None:
        """FilterFactory.is_not_set('$cohorts') constructs a normal filter."""
        f = FilterFactory.is_not_set("$cohorts")
        assert f.operator == "is not set"
        assert f.value is None

    def test_dict_path_is_set_on_cohorts_allowed(self) -> None:
        """The dict/LLM path accepts a value-less is-set on '$cohorts'."""
        f = _ADAPTER.validate_python({"property": "$cohorts", "operator": "is set"})
        assert f.operator == "is set"
        assert f.value is None

    def test_true_operator_on_cohorts_still_rejected(self) -> None:
        """Value-less boolean operators on '$cohorts' remain rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            _ADAPTER.validate_python({"property": "$cohorts", "operator": "true"})


class TestFilterNoValueOperatorValueRejected:
    """No-value operators reject a supplied value instead of discarding it.

    Regression tests for finding
    ``filter-no-value-operators-silently-discard-value``: ``is set`` /
    ``is not set`` / ``true`` / ``false`` silently nulled a
    caller-supplied value, running a bare existence check instead of the
    comparison the caller almost certainly meant (``operator "equals"``)
    — a semantically different query. The other operator families all
    reject mismatched values with a targeted ``ValueError``; the
    no-value family must do the same.
    """

    @pytest.mark.parametrize("operator", ["is set", "is not set", "true", "false"])
    def test_no_value_operator_with_value_rejected(self, operator: str) -> None:
        """Each no-value operator rejects a caller-supplied value."""
        with pytest.raises(ValidationError, match="does not take a value"):
            _ADAPTER.validate_python(
                {"property": "country", "operator": operator, "value": "US"}
            )

    def test_is_set_error_suggests_equals(self) -> None:
        """The is-set rejection points the caller at operator 'equals'."""
        with pytest.raises(ValidationError, match="did you mean operator 'equals'"):
            _ADAPTER.validate_python(
                {"property": "country", "operator": "is set", "value": "US"}
            )

    def test_error_reports_original_value(self) -> None:
        """The rejection message echoes the discarded value."""
        with pytest.raises(ValidationError, match="'US'"):
            _ADAPTER.validate_python(
                {"property": "country", "operator": "is set", "value": "US"}
            )

    @pytest.mark.parametrize("operator", ["is set", "is not set", "true", "false"])
    def test_no_value_operator_without_value_still_accepted(
        self, operator: str
    ) -> None:
        """Omitting the value keeps every no-value operator constructible."""
        f = _ADAPTER.validate_python({"property": "country", "operator": operator})
        assert f.value is None

    def test_classmethods_unaffected(self) -> None:
        """The value-less classmethod constructors keep working."""
        assert FilterFactory.is_set("email").value is None
        assert FilterFactory.is_not_set("email").value is None
        assert FilterFactory.is_true("active").value is None
        assert FilterFactory.is_false("active").value is None
