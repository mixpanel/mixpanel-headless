"""Filter rules that field types cannot express.

Plain functions and constants over primitives. **Nothing here imports a
model** — that is what keeps the import acyclic, since ``types.py``
imports this module to give its validators a body.

Only rules that a field type cannot state live here. A shape belongs in
the annotation, where both the validator and the JSON schema can see it;
see ``.claude/skills/pydantify/``. What is left is the cross-field
pairings and the semantic checks JSON Schema has no form for.

Each function raises, returning nothing, so a caller reads as a single
line inside a ``model_validator``:

    ```python
    @model_validator(mode="after")
    def _check_order(self) -> DateRangeFilter:
        check_dates_ordered(self.value)
        return self
    ```
"""

from __future__ import annotations

import re
from datetime import date as dt_date
from typing import Any

COHORT_PROPERTY = "$cohorts"
"""The pseudo-property cohort-membership filters target."""

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
"""Shape of a payload date. Calendar validity is a separate, runtime-only check."""


# =============================================================================
# Messages
# =============================================================================

MSG_NEEDS_NUMERIC = "Filter operator '{op}' requires a numeric value, got {got!r}"
MSG_NEEDS_STRING = "Filter operator '{op}' requires a string value, got {got!r}"
MSG_NEEDS_STR_OR_LIST = (
    "Filter operator '{op}' requires a string or a list of strings, got {got!r}"
)
MSG_NEEDS_STR_LIST = "Filter operator '{op}' requires a list of strings, got {got!r}"

MSG_HAND_ROLLED_COHORT = (
    "Filters on '$cohorts' must be built via FilterFactory.in_cohort() / "
    "FilterFactory.not_in_cohort() (or the declarative InlineCohort / "
    "CohortReferenceCriterion inputs), not constructed by hand; "
    "only the value-less 'is set' / 'is not set' operators may "
    "target '$cohorts' directly "
    "(got operator={op!r}, value={got!r})"
)
"""Raised from two places, so it lives in one.

:func:`check_cohort_property` catches the models that may not touch
``$cohorts`` at all; :func:`check_cohort_value_pairing` catches the one
that may, but only with the cohort payload shape. Both refuse the same
mistake and must say so identically.
"""


# =============================================================================
# Schema fragments
# =============================================================================

EQUALITY_VALUE_RULE: dict[str, Any] = {
    "if": {
        "properties": {"property_type": {"const": "number"}},
        "required": ["property_type"],
    },
    "then": {
        "properties": {
            "value": {
                "anyOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}},
                ]
            }
        }
    },
    "else": {
        "properties": {
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            }
        }
    },
}
"""Schema half of the equality ``property_type``/``value`` pairing.

The pairing is cross-field, so no field type states it — but JSON Schema
can, via ``if``/``then``, which stops a schema-driven consumer generating
``{"property_type": "number", "value": "oops"}``.

``json_schema_extra`` is inert at validation time, so
:func:`check_value_matches_property_type` is the runtime half. The two
must agree; changing one without the other reintroduces the parity gap
this closes.
"""


# =============================================================================
# Dates
# =============================================================================


def validate_date(date_str: str) -> dt_date:
    """Validate a date string is YYYY-MM-DD and return the parsed date.

    Args:
        date_str: Date string to validate.

    Returns:
        Parsed ``datetime.date`` object.

    Raises:
        ValueError: If the format is wrong or the date is not real.
    """
    if not re.match(_DATE_PATTERN, date_str):
        raise ValueError(f"Date must be YYYY-MM-DD format (got '{date_str}')")
    try:
        return dt_date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(f"'{date_str}' is not a valid calendar date") from None


def check_is_real_date(value: str) -> str:
    """Reject a well-formed date string that is not a real calendar date.

    Paired with ``StringConstraints(pattern=…)`` on the annotation, which
    catches malformed input schema-side. Only calendar validity is left
    here, and it has no JSON Schema form.

    Args:
        value: A ``YYYY-MM-DD`` string that already matched the pattern.

    Returns:
        ``value``, unchanged — the payload format is a string, and parsing
        it to a ``date`` here would change the outgoing payload.

    Raises:
        ValueError: If ``value`` is not a real date, e.g. ``2025-02-30``.
    """
    validate_date(value)
    return value


def check_dates_ordered(value: list[str]) -> None:
    """Reject a date range whose start falls after its end.

    Both endpoints are pattern-checked ``YYYY-MM-DD``, so both are
    zero-padded — a format whose lexicographic order is its chronological
    order. No parsing needed.

    Args:
        value: The two-element date range.

    Raises:
        ValueError: If the range runs backwards.
    """
    start, end = value
    if start > end:
        raise ValueError(f"from_date must be before to_date (got '{start}' > '{end}')")


# =============================================================================
# Cohort membership
# =============================================================================


def has_cohort_payload_shape(operator: str, value: Any) -> bool:
    """Check whether a filter carries the cohort payload structure.

    The cohort constructors produce ``operator`` in
    ``{"contains", "does not contain"}`` and ``value`` shaped as a
    non-empty list of ``{"cohort": {...}}`` entries. Any ``$cohorts``
    filter not matching this was hand-rolled and would break the
    downstream builders.

    Args:
        operator: The filter's operator.
        value: The filter's value.

    Returns:
        True if the pair matches the cohort structure.
    """
    if operator not in ("contains", "does not contain"):
        return False
    if not isinstance(value, list) or len(value) == 0:
        return False
    return all(_cohort_of(item) is not None for item in value)


def _cohort_of(item: Any) -> Any:
    """Read the ``cohort`` payload off a payload entry.

    Called on both sides of validation, so it accepts the raw mapping and
    the parsed ``CohortRef`` alike.

    Args:
        item: One entry of a cohort filter's value.

    Returns:
        The payload, or None if the entry carries none.
    """
    if isinstance(item, dict):
        return item.get("cohort")
    return getattr(item, "cohort", None)


def check_cohort_property(property_: Any, operator: str, value: Any) -> None:
    """Refuse a ``$cohorts`` filter the cohort constructors did not build.

    For the models that may not target ``$cohorts`` at all. The one that
    may, but only with the payload shape, uses
    :func:`check_cohort_value_pairing`.

    Args:
        property_: The filter's property.
        operator: The filter's operator, for the message.
        value: The filter's value, for the message.

    Raises:
        ValueError: If ``$cohorts`` is targeted by a model that may not.
    """
    if property_ == COHORT_PROPERTY:
        raise ValueError(MSG_HAND_ROLLED_COHORT.format(op=operator, got=value))


def check_cohort_value_pairing(property_: Any, operator: str, value: Any) -> None:
    """Tie the cohort payload shape to the ``$cohorts`` property, both ways.

    A ``$cohorts`` filter must carry the structure the constructors
    build, and that structure must not be aimed at any other property.

    Args:
        property_: The filter's property.
        operator: The filter's operator.
        value: The filter's value.

    Raises:
        ValueError: If a ``$cohorts`` filter was hand-rolled, or a
            cohort-shaped value was aimed at another property.
    """
    if property_ == COHORT_PROPERTY:
        if not has_cohort_payload_shape(operator, value):
            raise ValueError(MSG_HAND_ROLLED_COHORT.format(op=operator, got=value))
    elif not isinstance(value, str):
        raise ValueError(MSG_NEEDS_STRING.format(op=operator, got=value))


# =============================================================================
# Equality
# =============================================================================


def check_value_matches_property_type(
    operator: str, property_type: str, value: Any
) -> None:
    """Enforce the equality ``property_type``/``value`` pairing at runtime.

    Runtime half of :data:`EQUALITY_VALUE_RULE`. A ``number`` property
    takes numeric operands; anything else takes strings.

    Args:
        operator: The filter's operator, for the message.
        property_type: The declared property type.
        value: The operand, scalar or list.

    Raises:
        ValueError: If the operand does not match ``property_type``.
    """
    operands = value if isinstance(value, list) else [value]
    if property_type == "number":
        if not all(isinstance(v, (int, float)) for v in operands):
            raise ValueError(MSG_NEEDS_NUMERIC.format(op=operator, got=value))
    elif not isinstance(value, list):
        raise ValueError(
            MSG_NEEDS_STR_OR_LIST.format(op=operator, got=type(value).__name__)
        )
    elif not all(isinstance(v, str) for v in value):
        raise ValueError(MSG_NEEDS_STR_LIST.format(op=operator, got=value))


# =============================================================================
# Value-less operators
# =============================================================================

_VALUE_LESS_HINT = {
    "is set": "equals",
    "is not set": "does not equal",
    "true": "equals",
    "false": "equals",
    "list_contains": "list_item_filters",
}
"""What the caller probably meant when they passed a value anyway."""


def check_no_value(operator: str, value: Any) -> None:
    """Reject a value on an operator that takes none.

    The bare ``None`` annotation already rejects it; this exists only for
    the message, which names the operator the caller likely wanted.

    Args:
        operator: The filter's operator.
        value: Whatever was supplied.

    Raises:
        ValueError: If ``value`` is not None.
    """
    if value is None:
        return
    hint = _VALUE_LESS_HINT.get(operator)
    suffix = f"; did you mean operator {hint!r}?" if hint else ""
    raise ValueError(
        f"Filter operator {operator!r} does not take a value (got {value!r}){suffix}"
    )


# =============================================================================
# list_contains arguments
# =============================================================================


def check_list_contains_args(
    item_filters: tuple[Any, ...],
    equals: dict[str, Any],
    quantifier: str,
) -> None:
    """Validate the two mutually exclusive ways of giving inner conditions.

    Args:
        item_filters: Positional inner filters.
        equals: Keyword equality shorthand.
        quantifier: ``"any"`` or ``"all"``.

    Raises:
        ValueError: If both shapes are mixed, neither is given, the
            quantifier is unknown, or a kwarg key is blank.
        TypeError: If a kwarg value is not ``str`` or ``list[str]``.
    """
    if item_filters and equals:
        raise ValueError(
            "list_contains: pass either positional Filter instances "
            "OR keyword equals shorthand, not both"
        )
    if not item_filters and not equals:
        raise ValueError("list_contains requires at least one inner condition")
    if quantifier not in ("any", "all"):
        raise ValueError(
            f"list_contains quantifier must be 'any' or 'all', got {quantifier!r}"
        )
    for key, value in equals.items():
        if not key.strip():
            raise ValueError("list_contains: kwarg keys must be non-empty strings")
        if not isinstance(value, (str, list)):
            raise TypeError(
                f"list_contains kwarg {key!r}: value must be str or "
                f"list[str], got {type(value).__name__}"
            )


def check_cohort_source(cohort_id: int | None, raw_cohort: Any) -> None:
    """Require exactly one of a saved-cohort id or an inline definition.

    Args:
        cohort_id: Saved-cohort id, if given.
        raw_cohort: Inline cohort definition, if given.

    Raises:
        ValueError: If neither or both are supplied.
    """
    if (cohort_id is None) == (raw_cohort is None):
        raise ValueError(
            "a cohort filter needs exactly one of 'id' or 'raw_cohort'; "
            f"got id={cohort_id!r}, raw_cohort={'set' if raw_cohort else None}"
        )


def normalize_equality_value(value: Any) -> Any:
    """Wrap a bare string equality operand in a list.

    ``{"operator": "equals", "value": "premium"}`` is the commonest
    payload there is, and the schema accepts it, so the runtime has to
    as well. The payload wants a list for strings.

    **Strings only.** Numeric equality goes out as a bare number, so
    wrapping one here would change the outgoing payload.

    A ``BeforeValidator``, not a mutation of the frozen model after the
    fact. The declared union still advertises the scalar, which is right
    for the input schema; a string operand is a list afterwards.

    Args:
        value: The operand as supplied.

    Returns:
        ``[value]`` for a bare string, otherwise ``value`` unchanged.
    """
    return [value] if isinstance(value, str) else value


def reject_stray_value(data: Any) -> None:
    """Apply :func:`check_no_value` to a not-yet-validated payload.

    Runs before the ``value: None`` annotation reports its own bare
    "Input should be None", so the caller gets the operator hint.

    Args:
        data: The raw input, whatever pydantic was handed. Anything that
            is not a mapping is left to the normal machinery.
    """
    if isinstance(data, dict):
        check_no_value(str(data.get("operator", "")), data.get("value"))


def reject_hand_rolled_cohort(data: Any) -> None:
    """Report a malformed ``$cohorts`` value as factory misuse.

    Runs before field validation, which would otherwise reject the value
    against ``str | list[CohortRef]`` and report what is structurally
    wrong without mentioning that constructors exist for this.

    Only the ``$cohorts`` direction. The converse — a cohort-shaped value
    aimed elsewhere — needs the parsed value and stays in the
    after-validator.

    Args:
        data: The raw input, before field validation.

    Raises:
        ValueError: If a ``$cohorts`` filter was hand-rolled.
    """
    if isinstance(data, dict) and data.get("property") == COHORT_PROPERTY:
        check_cohort_value_pairing(
            COHORT_PROPERTY, str(data.get("operator", "")), data.get("value")
        )
