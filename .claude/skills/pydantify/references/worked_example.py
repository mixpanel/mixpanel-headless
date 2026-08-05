"""A complete union in the shape this repo uses. Runnable.

    uv run python .claude/skills/pydantify/references/worked_example.py

Four models rather than the real eleven, but every pattern the skill
describes is here and exercised by the checks at the bottom:

- a base holding shared fields and config
- one model per *shape*, each claiming several literals
- rules as plain functions over primitives, in a section that imports no
  model
- a one-line validator hook whose body lives in that section
- a documented residual, with its direction named
- a composite model whose children point at a union omitting itself, so
  the illegal nesting is unrepresentable rather than rejected
- ``MarkedDiscriminator`` with ``error_type``, giving clean error paths
  and the OpenAPI ``discriminator`` block

Copy the shape, not the domain.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    model_validator,
)

from mixpanel_headless._internal.pydantic_utils import MarkedDiscriminator

# =============================================================================
# Field types
#
# Named aliases, not helper functions: `mypy --strict` rejects a function call
# used as an annotation, and only a name assigned a type expression directly is
# treated as a type alias.
# =============================================================================

Number = StrictInt | StrictFloat
"""Strict, so ``True`` and ``"5"`` never become ``1`` and ``5``."""

NumberPair = Annotated[list[Number], Field(min_length=2, max_length=2)]
"""Two numbers.

A ``list``, not a ``tuple``: a tuple renders as ``prefixItems`` and reports
``missing`` for a short input, and it stops downstream ``isinstance(v, list)``
checks from matching.
"""


# =============================================================================
# Rules
#
# Plain functions over primitives. Nothing here imports a model, which is what
# keeps the import acyclic once these move to their own module.
# =============================================================================

MSG_UNORDERED = "lower bound must not exceed upper (got {lo!r} > {hi!r})"


def check_bounds_ordered(value: list[float]) -> None:
    """Reject a range whose lower bound exceeds its upper.

    Args:
        value: The two-element range.

    Raises:
        ValueError: If the range runs backwards.
    """
    lo, hi = value
    if lo > hi:
        raise ValueError(MSG_UNORDERED.format(lo=lo, hi=hi))


# =============================================================================
# Models
#
# One per shape. An operator earns its own model only when it needs a different
# field or a different rule — so four comparison operators share one model.
# =============================================================================


class AbstractCondition(BaseModel):
    """Fields and config shared by every condition.

    ``Abstract`` so that :data:`Condition` — the name used in signatures
    — can be the union. The two cannot share a name: a union is an
    ``Annotated`` alias and carries neither classmethods nor
    ``isinstance``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    property: str


class PresenceCondition(AbstractCondition):
    """The property is or is not populated. No operand."""

    operator: Literal["is set", "is not set"]
    value: None = None


class NumericCondition(AbstractCondition):
    """The property compares against one number.

    Four operators, one shape. ``MarkedDiscriminator`` maps each literal
    onto this model, so grouping costs nothing at the routing layer.
    """

    operator: Literal["is greater than", "is less than", "is at least", "is at most"]
    value: Number


class RangeCondition(AbstractCondition):
    """The property falls within, or outside, two bounds.

    Ordering is a **documented residual**: JSON Schema cannot compare two
    elements of one array, so the schema accepts a reversed range that
    the runtime rejects. Runtime stricter than schema — the direction
    that merely needs surfacing, not the one that makes our own output
    invalid.
    """

    operator: Literal["is between", "not between"]
    value: NumberPair

    @model_validator(mode="after")
    def _check_order(self) -> RangeCondition:
        """Apply the ordering rule; body lives in the Rules section.

        Returns:
            ``self``, unchanged.
        """
        check_bounds_ordered(self.value)
        return self


class GroupCondition(AbstractCondition):
    """Every child condition must hold.

    The only composite. ``children`` points at :data:`AtomicCondition`,
    which omits this model, so a group inside a group cannot be built or
    even described in the schema.
    """

    operator: Literal["all of"]
    value: None = None
    children: Annotated[tuple[AtomicCondition, ...], Field(min_length=1)]


# =============================================================================
# The unions
#
# Written out literally. A helper that *returns* an `Annotated` makes the name a
# variable, and `mypy --strict` then rejects every annotation using it. For the
# same reason `AtomicCondition | GroupCondition` is unavailable — an `Annotated`
# union cannot be composed into another.
# =============================================================================

AtomicCondition = Annotated[
    PresenceCondition | NumericCondition | RangeCondition,
    MarkedDiscriminator("operator", error_type="invalid_child_operator"),
]
"""A condition holding no other conditions."""

Condition = Annotated[
    PresenceCondition | NumericCondition | RangeCondition | GroupCondition,
    MarkedDiscriminator("operator", error_type="invalid_operator"),
]
"""One condition, routed by ``operator``.

``MarkedDiscriminator`` rather than ``Field(discriminator="operator")``
for one reason: a plain discriminator copies the matched tag into the
error ``loc``, reporting a segment the caller never sent. Marked tags
come back ``#``-prefixed and ``is_meta_key`` strips them by shape.

Not because of the grouping — a plain discriminator accepts one model
owning several literals; it fails only when two models claim the same
value.

``error_type`` is load-bearing: without it an unroutable value reports
"Unable to extract tag" instead of naming what is accepted.
"""

GroupCondition.model_rebuild()

ADAPTER: TypeAdapter[Any] = TypeAdapter(Condition)


if __name__ == "__main__":
    import json

    from jsonschema import Draft202012Validator

    from mixpanel_headless._internal.pydantic_utils import is_meta_key

    schema = ADAPTER.json_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    print("branches      ", len(schema["oneOf"]))
    print(
        "discriminator ",
        schema["discriminator"]["propertyName"],
        "->",
        len(schema["discriminator"]["mapping"]),
        "operators",
    )

    print("\nevery operator routes:")
    for payload in (
        {"property": "p", "operator": "is set"},
        {"property": "p", "operator": "is at most", "value": 3},
        {"property": "p", "operator": "is between", "value": [1, 5]},
        {
            "property": "p",
            "operator": "all of",
            "children": [{"property": "q", "operator": "is set"}],
        },
    ):
        chosen = type(ADAPTER.validate_python(payload)).__name__
        print(f"  {payload['operator']:16} -> {chosen}")

    print("\nparity (schema-valid == runtime-valid, or a named residual):")
    for label, payload, residual in (
        (
            "bad comparand",
            {"property": "p", "operator": "is at most", "value": "x"},
            False,
        ),
        (
            "short range",
            {"property": "p", "operator": "is between", "value": [1]},
            False,
        ),
        (
            "reversed range",
            {"property": "p", "operator": "is between", "value": [5, 1]},
            True,
        ),
    ):
        schema_ok = validator.is_valid(payload)
        try:
            ADAPTER.validate_python(payload)
            runtime_ok = True
        except Exception:
            runtime_ok = False
        note = "  <- documented residual" if schema_ok != runtime_ok else ""
        print(f"  {label:15} schema={schema_ok!s:5} runtime={runtime_ok!s:5}{note}")
        assert schema_ok == runtime_ok or residual, label

    print("\nerror paths, tags stripped:")
    for label, payload in (
        ("unknown operator", {"property": "p", "operator": "nope"}),
        ("bad comparand", {"property": "p", "operator": "is at most", "value": "x"}),
        (
            "nested group",
            {
                "property": "p",
                "operator": "all of",
                "children": [{"property": "q", "operator": "all of"}],
            },
        ),
    ):
        try:
            ADAPTER.validate_python(payload)
        except Exception as exc:
            first = exc.errors()[0]  # type: ignore[attr-defined]
            clean = tuple(x for x in first["loc"] if not is_meta_key(x))
            print(f"  {label:17} {first['type']:26} {first['loc']} -> {clean}")
            assert not any(isinstance(x, str) and x.startswith("#") for x in clean), (
                label
            )

    assert "#" not in json.dumps(schema).replace("#/$defs/", ""), "marked tag leaked"
    print("\nall checks passed")
