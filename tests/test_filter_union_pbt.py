"""Property-based schema/runtime parity for ``Filter``.

``tests/test_filter_union.py`` pins the parity gaps by example, one
payload each. This module states the invariant those examples are
instances of, and hunts for counterexamples across the cross product of
operator x property_type x value-kind:

    a filter payload validates against ``model_json_schema()``
    **if and only if** it validates at runtime

Three exemptions are allowed, all documented on :data:`Filter`.
They are named rather than numbered here, because :data:`Filter`
splits the same set four ways and citing across the two lists by number
has already gone wrong once.

Two of them leave the runtime *stricter* than the schema, so nothing
invalid gets through — but a consumer generating payloads from the
schema can still be told "no" about something the schema blessed, and
has to surface that rather than assume schema-valid is sufficient:

- **Cross-field rules JSON Schema cannot express.** ``EqualityFilter``'s
  value/property_type agreement, ``DateRangeFilter``'s from <= to,
  ``SubstringFilter``'s cohort pairing, and the base ``$cohorts`` guard
  are ``model_validator``s. Calendar validity (``2025-02-30`` matches
  the date ``pattern`` but is not a real date) is an ``AfterValidator``.
  All of them surface as ``value_error``, which is how this module
  recognises them.
- **Integral floats on ``RelativeDateFilter.value``.** JSON Schema's
  ``"type": "integer"`` matches ``1.0``; ``StrictInt`` does not. JSON
  has one number type, so no keyword can express the difference —
  recognised here by the ``int_type`` code landing on a ``float``.

The third runs the other way:

- **The ``$cohorts`` wire shape**, which ``SkipJsonSchema`` hides from
  the schema on purpose — the one place the runtime is *looser*. A
  schema-driven consumer never generates it, so it cannot surprise one.

Anything else is a real parity gap and fails the test.

Usage:
    # Run with default profile (100 examples)
    pytest tests/test_filter_union_pbt.py

    # Run with dev profile (10 examples)
    HYPOTHESIS_PROFILE=dev pytest tests/test_filter_union_pbt.py
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from mixpanel_headless.types import (
    AbsoluteDateFilter,
    BooleanStateFilter,
    ContainmentFilter,
    Filter,
    FilterFactory,
    FilterOperator,
    NumericComparisonFilter,
    PresenceFilter,
    RelativeDateFilter,
    SubstringFilter,
)


def _ops(*models: Any) -> tuple[str, ...]:
    """Every operator the given models claim, off their own literals.

    Read from the annotations rather than a hand-kept set: adding an
    operator to a model puts it in the grid with no second edit, and
    the two cannot drift.

    Args:
        *models: Filter model classes.

    Returns:
        The operator literals, in declaration order.
    """
    return tuple(
        op for m in models for op in get_args(m.model_fields["operator"].annotation)
    )


_ADAPTER: TypeAdapter[Any] = TypeAdapter(Filter)
"""Shared adapter — building one per example would dominate the runtime."""

_VALIDATOR = Draft202012Validator(_ADAPTER.json_schema())
"""Schema-side validator, built once from the generated schema."""

_ALL_OPERATORS: tuple[str, ...] = tuple(sorted(get_args(FilterOperator)))
"""Every operator the package declares, read off :data:`FilterOperator`.

Deliberately *not* assembled from ``Filter``'s operator-family
frozensets: no frozenset covers ``equals`` or ``list_contains``, so that
route needs a hand-written patch set, and an operator added to
:data:`FilterOperator` and to a member but missed from a frozenset would
silently drop out of the grid instead of failing. ``FilterOperator`` is
maintained independently of the members, which is what makes it an
oracle rather than a restatement.
"""

# =============================================================================
# Custom Strategies
# =============================================================================

property_names = st.sampled_from(
    ["plan", "amount", "$time", "created", "cart", "$cohorts"]
)
"""A small fixed set, including ``$cohorts`` so the guard is exercised."""

property_types = st.sampled_from(
    ["string", "number", "boolean", "datetime", "list", "object"]
)

date_like = st.sampled_from(
    [
        "2025-01-01",  # valid
        "2024-06-30",  # valid, earlier — exercises range ordering
        "2025-13-45",  # matches the pattern, not a real date (G6)
        "2025-02-30",  # matches the pattern, not a real date (G6)
        "01/01/2025",  # fails the pattern too
        "",
    ]
)

cohort_wire_values = st.sampled_from(
    [
        [{"cohort": {"id": 1, "name": "PU", "negated": False}}],
        [{"cohort": {}}],
        [{"not_cohort": {}}],
        [],
    ]
)
"""The builder-only shape ``SkipJsonSchema`` hides, plus near misses."""

filter_values = st.one_of(
    st.none(),
    st.text(max_size=8),
    st.integers(min_value=-5, max_value=5),
    st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
    st.booleans(),
    date_like,
    st.lists(st.text(max_size=4), max_size=3),
    st.lists(st.integers(min_value=-5, max_value=5), max_size=3),
    st.lists(
        st.one_of(st.integers(min_value=0, max_value=5), st.text(max_size=3)),
        max_size=3,
    ),
    st.lists(date_like, max_size=3),
    cohort_wire_values,
)
"""Every value shape any operator might plausibly receive, valid or not."""


numbers = st.one_of(
    st.integers(min_value=-5, max_value=5),
    st.floats(min_value=-5, max_value=5, allow_nan=False, allow_infinity=False),
)

nested_filters = st.sampled_from(
    [
        {"property": "Brand", "operator": "equals", "value": "nike"},
        {"property": "Qty", "operator": "is greater than", "value": 2},
        {"property": "x", "operator": "list_contains"},  # nesting is prohibited
    ]
)

_VALUE_BY_OPERATOR: dict[str, st.SearchStrategy[Any]] = {
    **dict.fromkeys(
        _ops(PresenceFilter, BooleanStateFilter),
        st.one_of(st.none(), st.text(max_size=4), numbers),
    ),
    **dict.fromkeys(
        ("equals", "does not equal"),
        st.one_of(
            st.text(max_size=6),
            numbers,
            st.booleans(),
            st.lists(st.text(max_size=4), max_size=3),
            st.lists(numbers, max_size=3),
        ),
    ),
    **dict.fromkeys(
        _ops(SubstringFilter, ContainmentFilter),
        st.one_of(st.text(max_size=6), numbers, cohort_wire_values),
    ),
    **dict.fromkeys(
        _ops(NumericComparisonFilter),
        st.one_of(numbers, st.text(max_size=4), st.booleans(), st.none()),
    ),
    **dict.fromkeys(
        ("is between", "not between"),
        st.lists(st.one_of(numbers, st.text(max_size=3)), max_size=3),
    ),
    **dict.fromkeys(_ops(AbsoluteDateFilter), st.one_of(date_like, numbers)),
    **dict.fromkeys(
        ("was between", "was not between"), st.lists(date_like, max_size=3)
    ),
    **dict.fromkeys(
        _ops(RelativeDateFilter),
        st.one_of(st.integers(min_value=-2, max_value=30), st.text(max_size=3)),
    ),
    "list_contains": st.one_of(st.none(), st.text(max_size=4)),
}
"""Per-operator value shapes: mostly what the operator takes, plus near misses.

Drawing the value independently of the operator — as
:func:`chaotic_payloads` does — almost never lands on a schema-valid
payload, which would make the parity properties pass vacuously.
"""


@st.composite
def coherent_payloads(draw: st.DrawFn, operator: str) -> dict[str, Any]:
    """Build a payload for *operator* whose value shape suits it.

    Still frequently invalid — the per-operator strategies deliberately
    include near misses — but valid often enough that both parity
    directions get real work to do.

    Args:
        draw: Hypothesis' draw callable.
        operator: The operator to build for.

    Returns:
        A dict of wire-named keys.
    """
    payload: dict[str, Any] = {
        "property": draw(
            st.sampled_from(["plan", "amount", "$time", "created", "cart"])
            if draw(st.integers(0, 3))
            else st.just("$cohorts")
        ),
        "operator": operator,
    }
    if draw(st.integers(0, 4)):
        payload["value"] = draw(_VALUE_BY_OPERATOR[operator])
    if operator == "list_contains" and draw(st.integers(0, 4)):
        payload["list_item_filters"] = draw(st.lists(nested_filters, max_size=2))
        if draw(st.booleans()):
            payload["list_item_quantifier"] = draw(st.sampled_from(["any", "all"]))
    if operator in _ops(RelativeDateFilter) and draw(st.booleans()):
        payload["date_unit"] = draw(st.sampled_from(["hour", "day", "week", "month"]))
    if draw(st.booleans()):
        payload["property_type"] = draw(property_types)
    if draw(st.booleans()):
        payload["resource_type"] = draw(st.sampled_from(["events", "people"]))
    return payload


@st.composite
def chaotic_payloads(draw: st.DrawFn, operator: str) -> dict[str, Any]:
    """Build a payload for *operator* with keys drawn independently of it.

    The union has to agree with its own schema about payloads nobody
    would write on purpose, not only about well-formed ones — a
    ``date_unit`` alongside ``equals``, a ``list_item_quantifier`` on a
    presence filter, and so on.

    Args:
        draw: Hypothesis' draw callable.
        operator: The operator to build for.

    Returns:
        A dict of wire-named keys, very often invalid.
    """
    payload: dict[str, Any] = {
        "property": draw(property_names),
        "operator": operator,
    }
    if draw(st.booleans()):
        payload["value"] = draw(filter_values)
    if draw(st.booleans()):
        payload["property_type"] = draw(property_types)
    if draw(st.booleans()):
        payload["date_unit"] = draw(st.sampled_from(["hour", "day", "week", "month"]))
    if draw(st.booleans()):
        payload["resource_type"] = draw(st.sampled_from(["events", "people"]))
    if draw(st.booleans()):
        payload["list_item_filters"] = draw(st.lists(nested_filters, max_size=2))
    if draw(st.booleans()):
        payload["list_item_quantifier"] = draw(st.sampled_from(["any", "all"]))
    return payload


def filter_payloads(operator: str) -> st.SearchStrategy[dict[str, Any]]:
    """Draw mostly-coherent payloads for *operator*, plus some chaotic ones.

    The operator is a test parameter rather than another thing to draw.
    Sampling it uniformly spread the example budget across 26 operators
    x 6 value kinds, thin enough that a real gap — a schema that
    over-advertises one member's value type, say — had only a ~1 in 4
    chance of being generated in a 100-example run. Fixing the operator
    per test gives every member its own budget, which makes the
    detection reliable rather than lucky.

    Args:
        operator: The operator every drawn payload will carry.

    Returns:
        A strategy over wire-named filter dicts.
    """
    return st.one_of(
        coherent_payloads(operator),
        coherent_payloads(operator),
        coherent_payloads(operator),
        chaotic_payloads(operator),
    )


_PAYLOADS: dict[str, st.SearchStrategy[dict[str, Any]]] = {
    operator: filter_payloads(operator) for operator in _ALL_OPERATORS
}
"""One strategy per operator, built once.

Calling :func:`filter_payloads` inside a ``@given`` body rebuilt five
strategy objects per example — ~9.6k constructions across a default run.
Hypothesis reuses a strategy instance across examples by design, so
building the table at import costs nothing and saves all of that.
"""


# =============================================================================
# Helpers
# =============================================================================


def _schema_accepts(payload: dict[str, Any]) -> bool:
    """Return whether the generated JSON Schema accepts *payload*.

    Args:
        payload: A wire-named filter dict.

    Returns:
        True when the payload satisfies the schema.
    """
    return _VALIDATOR.is_valid(payload)


def _runtime_error(payload: dict[str, Any]) -> ValidationError | None:
    """Validate *payload* at runtime and return the error, if any.

    Args:
        payload: A wire-named filter dict.

    Returns:
        The raised ``ValidationError``, or ``None`` when it validated.
    """
    try:
        _ADAPTER.validate_python(payload)
    except ValidationError as exc:
        return exc
    return None


def _is_documented_stricter_rejection(
    payload: dict[str, Any], error: ValidationError
) -> bool:
    """Return whether every error came from a documented runtime-only rule.

    Two codes qualify, and only these two:

    - ``value_error`` — the four ``model_validator``s and the date
      ``AfterValidator`` all raise ``ValueError``.
    - ``int_type`` on a ``float`` input — ``StrictInt`` refusing an
      integral float that JSON Schema's ``"type": "integer"`` matches.
      Narrowed to ``float`` inputs so a genuine type gap (``int_type``
      on a string, say) is still caught.

    Every other code corresponds to something the annotations — and
    therefore the schema — express, so seeing one on a schema-valid
    payload is a real parity gap.

    Args:
        payload: The wire-named filter dict that was validated.
        error: The runtime ``ValidationError``.

    Returns:
        True when every error is one of the documented residuals.
    """
    return all(
        entry["type"] == "value_error"
        or (entry["type"] == "int_type" and isinstance(payload.get("value"), float))
        for entry in error.errors()
    )


def _is_hidden_raw_cohort_shape(payload: dict[str, Any]) -> bool:
    """Return whether *payload* carries an inline ``raw_cohort`` definition.

    The ``$cohorts`` wire shape itself is now typed and public —
    ``ContainmentFilter.value`` is ``str | list[CohortRef]``. What stays
    hidden is one field: ``CohortPayload.raw_cohort``, the selector tree
    ``CohortDefinition.to_dict()`` emits, whose dynamically-named
    ``bhvr_N`` keys would render as an untyped open object. It is a
    builder artifact — a consumer generating a filter uses ``id``.

    That is the one remaining place the runtime is looser than the
    schema, narrowed from the whole cohort value down to this field.

    Args:
        payload: A wire-named filter dict.

    Returns:
        True when any cohort entry carries ``raw_cohort``.
    """
    value = payload.get("value")
    if payload.get("property") != "$cohorts" or not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("cohort"), dict)
        and "raw_cohort" in item["cohort"]
        for item in value
    )


# =============================================================================
# Properties
# =============================================================================


class TestParityProbesAreNotVacuous:
    """Guards the guards: each parity quadrant is actually reachable.

    Both properties below short-circuit on payloads that do not apply to
    them, so a strategy that drifted into producing only nonsense — or a
    helper that always answered ``False`` — would leave them green while
    checking nothing. These four payloads pin one example of each
    quadrant, so the exemptions cannot rot into unconditional passes.
    """

    def test_both_layers_accept(self) -> None:
        """A plain equality filter is valid on both sides."""
        payload = {"property": "plan", "operator": "equals", "value": "pro"}
        assert _schema_accepts(payload)
        assert _runtime_error(payload) is None

    def test_documented_cross_field_rejection_is_reachable(self) -> None:
        """G6: schema-valid, runtime-rejected, and recognised as a residual.

        Calendar validity — ``"2025-13-45"`` matches the ``pattern`` and
        is not a real date. G1, the ``value`` / ``property_type``
        pairing, used to be the probe here; ``EqualityFilter`` now
        carries that rule as an ``if``/``then``, so the schema rejects it
        and it is no longer a residual to probe for.
        """
        payload = {
            "property": "$time",
            "operator": "was on",
            "value": "2025-13-45",
        }
        assert _schema_accepts(payload)
        error = _runtime_error(payload)
        assert error is not None
        assert _is_documented_stricter_rejection(payload, error)

    def test_integral_float_residual_is_reachable(self) -> None:
        """``1.0`` is an integer to JSON Schema and not to ``StrictInt``."""
        payload = {"property": "created", "operator": "was in the", "value": 1.0}
        assert _schema_accepts(payload)
        error = _runtime_error(payload)
        assert error is not None
        assert [entry["type"] for entry in error.errors()] == ["int_type"]
        assert _is_documented_stricter_rejection(payload, error)

    def test_public_cohort_shape_is_no_longer_hidden(self) -> None:
        """The saved-cohort wire shape is now in the schema, not exempt."""
        payload = {
            "property": "$cohorts",
            "operator": "contains",
            "value": [{"cohort": {"id": 1, "name": "PU", "negated": False}}],
            "property_type": "list",
        }
        assert _runtime_error(payload) is None
        assert _schema_accepts(payload)
        assert not _is_hidden_raw_cohort_shape(payload)

    def test_hidden_raw_cohort_shape_is_reachable(self) -> None:
        """An inline ``raw_cohort`` is runtime-valid and schema-invisible."""
        payload = {
            "property": "$cohorts",
            "operator": "contains",
            "value": [{"cohort": {"raw_cohort": {"bhvr_0": {}}, "name": "PU"}}],
            "property_type": "list",
        }
        assert _runtime_error(payload) is None
        assert not _schema_accepts(payload)
        assert _is_hidden_raw_cohort_shape(payload)

    def test_structural_rejection_is_not_mistaken_for_a_residual(self) -> None:
        """A structural failure must not pass the residual exemption.

        If ``_is_documented_stricter_rejection`` ever widened to accept
        every error code, ``test_schema_valid_implies_runtime_valid``
        would stop detecting real gaps. Two failures have to stay
        refused: an ordinary structural mismatch, and an ``int_type``
        raised on something that is not a ``float`` — the narrowing that
        keeps the integral-float exemption from swallowing real
        integer-type gaps.
        """
        payload = {"property": "plan", "operator": "equals", "value": {"n": 1}}
        structural = _runtime_error(payload)
        assert structural is not None
        assert not _is_documented_stricter_rejection(payload, structural)

        int_typed = {"property": "created", "operator": "was in the", "value": "7"}
        error = _runtime_error(int_typed)
        assert error is not None
        assert [entry["type"] for entry in error.errors()] == ["int_type"]
        assert not _is_documented_stricter_rejection(int_typed, error)


class TestSchemaRuntimeParity:
    """The generated schema and the runtime accept the same payloads."""

    @pytest.mark.parametrize("operator", _ALL_OPERATORS)
    @given(data=st.data())
    def test_schema_valid_implies_runtime_valid(
        self, operator: str, data: st.DataObject
    ) -> None:
        """Nothing the schema advertises is refused, bar the documented rules.

        This is the direction that matters to a consumer generating
        payloads from the schema: being told "yes" by the schema and
        "no" by the library is the defect class this union exists to
        close.

        Args:
            operator: The operator under test.
            data: Hypothesis' interactive draw object.
        """
        payload = data.draw(_PAYLOADS[operator])
        if not _schema_accepts(payload):
            return
        error = _runtime_error(payload)
        if error is None:
            return
        assert _is_documented_stricter_rejection(payload, error), (
            f"schema accepted but runtime rejected with a structural error, "
            f"which the schema should have expressed: {payload!r} -> "
            f"{[entry['type'] for entry in error.errors()]}"
        )

    @pytest.mark.parametrize("operator", _ALL_OPERATORS)
    @given(data=st.data())
    def test_runtime_valid_implies_schema_valid(
        self, operator: str, data: st.DataObject
    ) -> None:
        """Nothing the runtime accepts is missing from the schema.

        The lone exemption is ``CohortPayload.raw_cohort``, hidden on
        purpose. Any other leak would mean the schema under-describes the
        API — a consumer would reject a payload the library takes.

        Args:
            operator: The operator under test.
            data: Hypothesis' interactive draw object.
        """
        payload = data.draw(_PAYLOADS[operator])
        if _runtime_error(payload) is not None:
            return
        assert _schema_accepts(payload) or _is_hidden_raw_cohort_shape(payload), (
            f"runtime accepted a payload the schema rejects: {payload!r}"
        )

    @pytest.mark.parametrize("operator", _ALL_OPERATORS)
    @given(data=st.data())
    def test_validation_is_deterministic(
        self, operator: str, data: st.DataObject
    ) -> None:
        """Validating twice gives the same verdict.

        ``EqualityFilter`` normalizes a scalar operand in place via
        ``object.__setattr__``. Re-validating the same input must not
        drift — a normalizer that is not idempotent would make the
        schema true only on first contact.

        Args:
            operator: The operator under test.
            data: Hypothesis' interactive draw object.
        """
        payload = data.draw(_PAYLOADS[operator])
        first = _runtime_error(payload) is None
        second = _runtime_error(payload) is None
        assert first == second


class TestFactoryOutputMatchesSchema:
    """Everything the factories build is a payload the schema describes."""

    @given(
        value=st.text(min_size=1, max_size=8),
        resource_type=st.sampled_from(["events", "people"]),
    )
    def test_equality_factory_output_validates(
        self, value: str, resource_type: str
    ) -> None:
        """``FilterFactory.equals`` output re-validates through the union."""
        built = FilterFactory.equals("plan", value, resource_type=resource_type)  # type: ignore[arg-type]
        assert _ADAPTER.validate_python(built) == built

    @given(low=st.integers(max_value=0), high=st.integers(min_value=1))
    def test_range_factory_output_validates(self, low: int, high: int) -> None:
        """``FilterFactory.between`` output re-validates and stays a ``list``.

        The list is load-bearing: ``filter_to_selector`` gates the
        ``is between`` branch on ``isinstance(value, list)``.
        """
        built = FilterFactory.between("amount", low, high)
        assert isinstance(built.value, list)
        assert _ADAPTER.validate_python(built) == built

    @given(quantity=st.integers(min_value=1, max_value=1000))
    def test_relative_date_factory_output_validates(self, quantity: int) -> None:
        """``FilterFactory.in_the_last`` output re-validates through the union."""
        built = FilterFactory.in_the_last("created", quantity, "day")
        assert _ADAPTER.validate_python(built) == built

    @given(cohort_id=st.integers(min_value=1, max_value=10_000))
    def test_cohort_factory_output_validates(self, cohort_id: int) -> None:
        """``FilterFactory.in_cohort`` output survives a round trip.

        Its value is the shape hidden from the schema, so this is the
        runtime-only half of the ``$cohorts`` wire-shape exemption.
        """
        built = FilterFactory.in_cohort(cohort_id)
        assert _ADAPTER.validate_python(built) == built
