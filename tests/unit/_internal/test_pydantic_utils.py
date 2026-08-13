"""Tests for ``_internal.pydantic_utils`` — union tags that cannot be mistaken for fields.

Why ``#``-marked tags exist at all: see ``_internal.pydantic_utils``. These
tests pin the behaviour that rationale buys.

The models here replicate the shapes that made this necessary (a criterion whose
``kind`` value collides with its own field name, a structurally-routed union, a
dataclass with validation aliases) rather than importing them, so a pydantic
upgrade that changes ``loc`` shape fails here first. Paths are rendered through
the real ``_error_location_to_json_path``.

Each test spells out its payload, the raw ``loc``, and the cleaned path —
deliberately repetitive, so a test reads on its own.

Run: uv run pytest tests/unit/_internal/test_pydantic_utils.py -v
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, Tag, ValidationError
from pydantic.dataclasses import dataclass as pyd_dataclass

from mixpanel_headless._internal.bookmark_schema import _error_location_to_json_path
from mixpanel_headless._internal.pydantic_utils import (
    MarkedDiscriminator,
    MarkedTag,
    alternative_name,
    by_field,
    is_meta_key,
)


def to_json_path(error_location: tuple[object, ...]) -> str:
    """Render an error location the way callers see it (no prefix)."""
    return _error_location_to_json_path(error_location, "")


def _tagged_union_nodes(node: object) -> Iterator[dict[str, Any]]:
    """Yield every ``tagged-union`` node in a core-schema tree.

    Args:
        node: Any fragment of a ``__pydantic_core_schema__`` tree.

    Yields:
        Each dict whose ``type`` is ``"tagged-union"``, in traversal order.
    """
    if isinstance(node, dict):
        if node.get("type") == "tagged-union":
            yield node
        for value in node.values():
            yield from _tagged_union_nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _tagged_union_nodes(value)


# ---------------------------------------------------------------------------
# Models: a kind-routed union and a structurally-routed one
# ---------------------------------------------------------------------------


class Cat(BaseModel):
    """The module docstring's example, as a real fixture."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["cat"]
    name: str = Field(strict=True)


class Dog(BaseModel):
    """Second alternative of the ``Cat | Dog`` union."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["dog"]
    name: str = Field(strict=True)


class PropertyCriterion(BaseModel):
    """Property criterion. Its ``kind`` value and ``property`` field collide."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["property"]
    property: str = Field(min_length=1)
    value: str = Field(min_length=1)


class BehavioralCriterion(BaseModel):
    """Event-frequency criterion."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["behavioral"]
    event: str = Field(min_length=1)


class CohortReferenceCriterion(BaseModel):
    """Saved-cohort membership criterion."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["cohort_reference"]
    cohort_id: int = Field(gt=0, strict=True)


class InlineCohort(BaseModel):
    """Group of criteria. Recursive: a node may be another group."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["group"]
    criteria: list[CohortNode] = Field(min_length=1)


# One declaration serves both readers: mypy reads the plain union off the
# ``Annotated``; pydantic asks ``MarkedDiscriminator`` for the tagged union.
CohortNode = Annotated[
    PropertyCriterion | BehavioralCriterion | CohortReferenceCriterion | InlineCohort,
    MarkedDiscriminator("kind", error_type="invalid_cohort_node"),
]

InlineCohort.model_rebuild()


class Metric(BaseModel):
    """Structural union member — no shared discriminator field."""

    model_config = ConfigDict(extra="forbid")
    event: str = Field(min_length=1)
    name: str = Field(min_length=1)


EventItem = Annotated[
    str | Metric,
    MarkedDiscriminator(
        lambda v: "str" if isinstance(v, str) else "Metric",
        error_type="invalid_event",
    ),
]


class Query(BaseModel):
    """``str | Metric``, routed by shape like the real query models."""

    model_config = ConfigDict(extra="forbid")
    events: list[EventItem]


class Untagged(BaseModel):
    """Undiscriminated unions, whose labels pydantic names itself."""

    model_config = ConfigDict(extra="forbid")
    x: str | list[str] = ""
    n: (
        Annotated[int, Field(strict=True, ge=0)]
        | Annotated[float, Field(strict=True, ge=0)]
    ) = 0


@pyd_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class AliasedFilter:
    """Private field names exposed under public aliases, like the real Filter."""

    _property: str = Field(validation_alias="property")
    _value: str = Field(default="", validation_alias="value")


class Aliased(BaseModel):
    """Holder for the aliased dataclass."""

    model_config = ConfigDict(extra="forbid")
    where: list[AliasedFilter]


# ---------------------------------------------------------------------------
# Routing failures — no alternative chosen, so no tag inserted
# ---------------------------------------------------------------------------


def test_kind_omitted() -> None:
    """A criterion without ``kind`` cannot be routed."""
    payload = {"kind": "group", "criteria": [{"property": "plan", "value": "premium"}]}

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == (
        "kind must be one of 'property', 'behavioral', 'cohort_reference', 'group'"
    )
    assert err["loc"] == ("criteria", 0)
    assert to_json_path(err["loc"]) == "criteria[0]"


def test_bogus_kind() -> None:
    """An unknown ``kind`` gets the same message; the loc stays at the union."""
    payload = {"kind": "group", "criteria": [{"kind": "bogus", "cohort_id": 7}]}

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == (
        "kind must be one of 'property', 'behavioral', 'cohort_reference', 'group'"
    )
    assert err["loc"] == ("criteria", 0)
    assert to_json_path(err["loc"]) == "criteria[0]"


# ---------------------------------------------------------------------------
# Tags that would collide if they were bare names
# ---------------------------------------------------------------------------


def test_tag_sharing_a_field_name() -> None:
    """``#property`` the tag and ``property`` the field are now distinguishable."""
    payload = {
        "kind": "group",
        "criteria": [{"kind": "property", "property": "", "value": "US"}],
    }

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "String should have at least 1 character"
    assert err["loc"] == ("criteria", 0, "#property", "property")
    assert to_json_path(err["loc"]) == "criteria[0].property"


def test_error_on_a_sibling_of_the_colliding_tag() -> None:
    """Same collision, but the error is on ``value``."""
    payload = {
        "kind": "group",
        "criteria": [{"kind": "property", "property": "plan", "value": ""}],
    }

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "String should have at least 1 character"
    assert err["loc"] == ("criteria", 0, "#property", "value")
    assert to_json_path(err["loc"]) == "criteria[0].value"


def test_missing_field_needs_no_special_case() -> None:
    """``value`` is absent from the input, but the rule never consults the input."""
    payload = {"kind": "group", "criteria": [{"kind": "property", "property": "plan"}]}

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["type"] == "missing"
    assert err["loc"] == ("criteria", 0, "#property", "value")
    assert to_json_path(err["loc"]) == "criteria[0].value"


def test_nested_groups_carry_one_tag_per_level() -> None:
    """Recursion inserts a tag at every level; all are prefixed, all are dropped."""
    payload = {
        "kind": "group",
        "criteria": [
            {
                "kind": "group",
                "criteria": [{"kind": "cohort_reference", "cohort_id": "42"}],
            }
        ],
    }

    with pytest.raises(ValidationError) as exc_info:
        InlineCohort.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "Input should be a valid integer"
    assert err["loc"] == (
        "criteria",
        0,
        "#group",
        "criteria",
        0,
        "#cohort_reference",
        "cohort_id",
    )
    assert to_json_path(err["loc"]) == "criteria[0].criteria[0].cohort_id"


def test_class_name_tag() -> None:
    """A structurally-routed union uses the same prefix."""
    payload = {"events": [{"event": "Purchase", "name": ""}]}

    with pytest.raises(ValidationError) as exc_info:
        Query.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "String should have at least 1 character"
    assert err["loc"] == ("events", 0, "#Metric", "name")
    assert to_json_path(err["loc"]) == "events[0].name"


def test_class_name_tag_as_the_final_segment() -> None:
    """The whole alternative failed, so the tag is the last segment."""
    payload = {"events": [123]}

    with pytest.raises(ValidationError) as exc_info:
        Query.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "Input should be a valid dictionary or instance of Metric"
    assert err["loc"] == ("events", 0, "#Metric")
    assert to_json_path(err["loc"]) == "events[0]"


# ---------------------------------------------------------------------------
# Segments that must survive, and the one shape not covered
# ---------------------------------------------------------------------------


def test_aliased_field_survives() -> None:
    """``loc`` carries the validation alias, which is what the caller sent."""
    payload = {"where": [{"property": "plan", "value": 123}]}

    with pytest.raises(ValidationError) as exc_info:
        Aliased.model_validate(payload)
    err = exc_info.value.errors()[0]

    assert err["msg"] == "Input should be a valid string"
    assert err["loc"] == ("where", 0, "value")
    assert to_json_path(err["loc"]) == "where[0].value"


def test_real_field_named_like_a_tag_survives() -> None:
    """A genuine ``property`` field carries no prefix, so it is never dropped."""
    assert to_json_path(("group_by", 0, "property", "formula")) == (
        "group_by[0].property.formula"
    )


def test_undiscriminated_union_labels_are_not_covered() -> None:
    """A union with no Discriminator labels its alternatives with bare type names.

    We do not control those, so the prefix rule cannot see them: ``str`` here
    survives into the path. The bracket rule still catches ``list[str]``. The
    fix is to discriminate the union, not to grow a list of type names.
    """
    payload = {"x": [123]}

    with pytest.raises(ValidationError) as exc_info:
        Untagged.model_validate(payload)
    first, second = exc_info.value.errors()

    assert first["loc"] == ("x", "str")
    assert to_json_path(first["loc"]) == "x.str"  # not cleaned

    assert second["loc"] == ("x", "list[str]", 0)
    assert to_json_path(second["loc"]) == "x[0]"


def test_constrained_number_labels_are_dropped() -> None:
    """Bounded numeric alternatives are labelled ``constrained-int`` / ``-float``."""
    payload = {"n": -5}

    with pytest.raises(ValidationError) as exc_info:
        Untagged.model_validate(payload)
    first, second = exc_info.value.errors()

    assert first["loc"] == ("n", "constrained-int")
    assert to_json_path(first["loc"]) == "n"

    assert second["loc"] == ("n", "constrained-float")
    assert to_json_path(second["loc"]) == "n"


# ---------------------------------------------------------------------------
# The helpers, unit by unit
# ---------------------------------------------------------------------------


def test_marked_tag_marks_and_recognises() -> None:
    """Construction, routing and detection all agree on the prefix."""
    assert MarkedTag("cat").tag == "#cat"
    assert MarkedTag.of("cat") == "#cat"
    assert MarkedTag.is_marked("#cat") is True
    assert MarkedTag.is_marked("cat") is False
    assert MarkedTag.is_marked(0) is False


def test_marked_tag_is_a_pydantic_tag() -> None:
    """Pydantic must treat it as an ordinary Tag."""
    assert isinstance(MarkedTag("cat"), Tag)


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("#cat", True),
        ("list[str]", True),
        ("constrained-int", True),
        ("constrained-float", True),
        ("name", False),
        ("property", False),
        (0, False),
    ],
    ids=str,
)
def test_is_meta_key(segment: str | int, expected: bool) -> None:
    """Only pydantic's own inventions are meta; real keys and indexes are not."""
    assert is_meta_key(segment) is expected


def test_by_field_reads_dicts_and_instances() -> None:
    """The discriminant is read the same way from JSON and from Python."""
    read = by_field("kind")

    assert read({"kind": "cat"}) == "cat"
    assert read(Cat(kind="cat", name="Ada")) == "cat"
    assert read({"kind": 7}) is None
    assert read({}) is None


def test_alternative_name_reads_the_literal() -> None:
    """A member with a discriminator field names itself from its Literal."""
    assert alternative_name(Cat, "kind") == "cat"
    assert alternative_name(Cat, None) == "Cat"


def test_alternative_name_rejects_a_non_singular_literal() -> None:
    """An ambiguous discriminator field fails at import, not at validation."""

    class Ambiguous(BaseModel):
        kind: Literal["a", "b"]

    with pytest.raises(TypeError, match="single-valued Literal"):
        alternative_name(Ambiguous, "kind")


def test_alternative_name_reads_a_pydantic_dataclass() -> None:
    """A pydantic dataclass names itself too, though it has no ``model_fields``.

    Dataclasses keep their fields on ``__pydantic_fields__``. Most of the
    package's union members — ``Filter``, ``Metric``, ``GroupBy`` — are
    dataclasses, so the string-discriminator path has to read both.
    """

    @pyd_dataclass(frozen=True)
    class DataclassCat:
        kind: Literal["cat"] = "cat"

    assert not hasattr(DataclassCat, "model_fields")
    assert alternative_name(DataclassCat, "kind") == "cat"
    assert alternative_name(DataclassCat, None) == "DataclassCat"


def test_dataclass_members_route_by_field() -> None:
    """Dataclass members name themselves too, so callers need no dict of names."""

    @pyd_dataclass(frozen=True)
    class StringLeg:
        kind: Literal["string"] = "string"
        value: str = ""

    @pyd_dataclass(frozen=True)
    class NumberLeg:
        kind: Literal["number"] = "number"
        value: float = 0.0

    class Holder(BaseModel):
        leg: Annotated[
            StringLeg | NumberLeg,
            MarkedDiscriminator("kind", error_type="invalid_leg"),
        ]

    assert Holder(leg={"kind": "number", "value": 3.0}).leg.value == 3.0

    with pytest.raises(ValidationError) as exc_info:
        Holder(leg={"kind": "number", "value": "woof"})
    assert exc_info.value.errors()[0]["loc"][:2] == ("leg", "#number")


def test_omitting_error_type_leaves_pydantic_errors_untouched() -> None:
    """A total discriminator needs no custom error, so none is attached."""
    # No discriminator field, so members name themselves from their type.
    TotalNode = Annotated[
        Cat | Dog,
        MarkedDiscriminator(lambda v: "Cat" if v.get("kind") == "cat" else "Dog"),
    ]

    class Holder(BaseModel):
        """Holder for the total-router alias."""

        pet: TotalNode

    with pytest.raises(ValidationError) as exc_info:
        Holder.model_validate({"pet": {"kind": "dog", "name": 1}})
    err = exc_info.value.errors()[0]

    assert err["loc"] == ("pet", "#Dog", "name")
    assert err["type"] == "string_type"
    assert to_json_path(err["loc"]) == "pet.name"


def test_wrapper_adopts_the_routing_callables_identity() -> None:
    """``inspect.signature`` must see through to the real routing function.

    The guard in ``tests/test_query_models.py`` reads the discriminator's
    return annotation to tell a total router from one that can fail; without
    ``functools.update_wrapper`` every union would look identical.
    """
    import inspect

    def route_pet(value: object) -> str:
        """Total router — never returns None."""
        return "cat"

    class Holder(BaseModel):
        """Holder whose union routes through ``route_pet``."""

        pet: Annotated[Cat | Dog, MarkedDiscriminator(route_pet)]

    (node,) = _tagged_union_nodes(Holder.__pydantic_core_schema__)
    discriminator = node["discriminator"]

    assert discriminator.__name__ == "route_pet"
    # `from __future__ import annotations` keeps annotations as strings.
    assert inspect.signature(discriminator).return_annotation == "str"


# ---------------------------------------------------------------------------
# MarkedDiscriminator — one declaration serving mypy and runtime
# ---------------------------------------------------------------------------


# The single-declaration form: mypy reads the plain union straight off the
# ``Annotated`` (metadata is never type-evaluated); pydantic asks the marker
# for the schema and gets the marked tagged union.
PetNode = Annotated[Cat | Dog, MarkedDiscriminator("kind", error_type="invalid_pet")]

# ``str`` alone cannot carry the ``min_length`` constraint, so the runtime
# members are supplied explicitly while the static union stays honest. The
# dict form also names members that cannot name themselves (``Annotated``
# aliases have no ``__name__``).
NonEmptyEntry = Annotated[
    str | Cat,
    MarkedDiscriminator(
        lambda v: "str" if isinstance(v, str) else "Cat",
        members={"str": Annotated[str, Field(min_length=1)], "Cat": Cat},
        error_type="invalid_entry",
    ),
]


class PetHolder(BaseModel):
    """Holder for the single-declaration ``PetNode`` alias."""

    model_config = ConfigDict(extra="forbid")
    pet: PetNode


class EntryHolder(BaseModel):
    """Holder for the ``members=``-override alias."""

    model_config = ConfigDict(extra="forbid")
    entry: NonEmptyEntry


def test_single_declaration_routes_and_marks_tags() -> None:
    """The alias validates, routes, and marks tags from one declaration.

    The typed assignment below is the static half of the claim: mypy sees
    ``Cat | Dog`` through the ``Annotated``, so this line type-checks without
    any ``TYPE_CHECKING`` twin (``just typecheck`` covers this file).
    """
    holder = PetHolder.model_validate({"pet": {"kind": "dog", "name": "Rex"}})
    pet: Cat | Dog = holder.pet

    assert isinstance(pet, Dog)
    assert pet.name == "Rex"

    with pytest.raises(ValidationError) as exc_info:
        PetHolder.model_validate({"pet": {"kind": "dog", "name": 1}})
    err = exc_info.value.errors()[0]

    assert err["loc"] == ("pet", "#dog", "name")
    assert to_json_path(err["loc"]) == "pet.name"


def test_members_default_from_the_annotated_union() -> None:
    """With no ``members=``, the list and its order come from the union args."""
    with pytest.raises(ValidationError) as exc_info:
        PetHolder.model_validate({"pet": {"kind": "bogus"}})
    err = exc_info.value.errors()[0]

    assert err["type"] == "invalid_pet"
    assert err["msg"] == "kind must be one of 'cat', 'dog'"


def test_explicit_members_override_the_annotated_union() -> None:
    """``members=`` wins over the union args when the runtime types differ.

    The empty string fails ``min_length=1``, which only the runtime member
    carries — the static ``str`` in the union would have accepted it.
    """
    with pytest.raises(ValidationError) as exc_info:
        EntryHolder.model_validate({"entry": ""})
    err = exc_info.value.errors()[0]

    assert err["loc"] == ("entry", "#str")
    assert to_json_path(err["loc"]) == "entry"


def test_explicit_message_overrides_the_generated_one() -> None:
    """Prose wins where a bare name list would not help the caller."""
    ProseNode = Annotated[
        Cat | Dog,
        MarkedDiscriminator(
            "kind", error_type="invalid_pet", message="pet must be a cat or a dog"
        ),
    ]

    class Holder(BaseModel):
        """Holder for the prose-message alias."""

        pet: ProseNode

    with pytest.raises(ValidationError) as exc_info:
        Holder.model_validate({"pet": {"kind": "bogus"}})
    err = exc_info.value.errors()[0]

    assert err["type"] == "invalid_pet"
    assert err["msg"] == "pet must be a cat or a dog"


def test_core_schema_is_a_tagged_union_with_marked_choices() -> None:
    """The built core schema carries marked choices and the router's identity.

    The guards in ``tests/test_query_models.py`` walk core schemas and read
    exactly these — the choice keys and the discriminator's ``__name__`` —
    so this pins what they depend on.
    """
    (node,) = _tagged_union_nodes(PetHolder.__pydantic_core_schema__)

    assert sorted(node["choices"]) == ["#cat", "#dog"]
    assert node["discriminator"].__name__ == "by_field_kind"


def test_json_schema_renders_the_plain_union() -> None:
    """The marker leaves no trace in JSON schema — just a ``oneOf`` of members.

    Other repositories drive MCP request schemas off ``model_json_schema()``,
    so the tags and the discriminator must stay out of the rendering.
    """
    schema = PetHolder.model_json_schema()

    assert schema["properties"]["pet"] == {
        "oneOf": [{"$ref": "#/$defs/Cat"}, {"$ref": "#/$defs/Dog"}],
        "title": "Pet",
    }
    assert set(schema["$defs"]) == {"Cat", "Dog"}


def test_marker_rejects_a_non_union_source() -> None:
    """Annotating a single type fails at model build with a pointed message."""
    NotAUnion = Annotated[Cat, MarkedDiscriminator("kind")]

    with pytest.raises(TypeError, match="members="):

        class Holder(BaseModel):
            """Holder that should never finish building."""

            pet: NotAUnion
