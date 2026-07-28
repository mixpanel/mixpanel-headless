"""Discriminated-union helpers that keep pydantic's tags out of caller paths.

Pydantic inserts a meta key into every union error ``loc``: the tag of the
alternative it chose. It describes the validation rather than the data, so it is
in no caller's JSON and has to come out before the path is shown to anyone.

Stripping it by name needs a hand-maintained list of tag names, and breaks
outright when a tag equals a field name (``kind="property"`` beside a
``property`` field). Instead, every tag built here is prefixed with ``#``, which
cannot occur in a Python identifier or an alias — so a meta key is recognisable
by shape, with nothing to register and no collision possible.

That guarantee covers the tags we own. Undiscriminated unions get labels
pydantic names itself (``list[str]``, ``constrained-int``); those are matched by
shape too, but heuristically — see :func:`is_meta_key`.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Annotated, Any, Union, get_args

from pydantic import Discriminator, GetCoreSchemaHandler, Tag
from pydantic_core import CoreSchema


class MarkedTag(Tag):
    """A pydantic ``Tag`` prefixed so it can never equal a field name.

    Pydantic copies the chosen tag into the error ``loc``; the prefix marks it
    as a meta key, strippable from caller-facing paths.

    Issue with a plain discriminator:
        ```python
        class Cat(BaseModel):
            kind: Literal["cat"]
            name: str

        class Dog(BaseModel):
            kind: Literal["dog"]
            name: str

        class Home(BaseModel):
            pet: Cat | Dog = Field(discriminator="kind")

        Home.model_validate({"pet": {"kind": "cat", "name": 1}})
        # ValidationError, loc = ("pet", "cat", "name")
        #                                 ^^^^^
        # `cat` was never a key — the payload only has `kind` and `name`.
        # Deleting by name is unsafe: a tag can also be a real field name.
        ```

    How it works with ``MarkedTag``:
        ```python
        class Home(BaseModel):
            pet: discriminated_union([Cat, Dog], "kind", error_type="bad_pet")

        Home.model_validate({"pet": {"kind": "cat", "name": 1}})
        # ValidationError, loc = ("pet", "#cat", "name")
        # `#` is illegal in a key, so a tag is never mistaken for one.

        MarkedTag.of("cat")          # "#cat" — what to route to
        MarkedTag.is_marked("#cat")  # True   — what to strip
        ```
    """

    PREFIX = "#"

    def __init__(self, name: str) -> None:
        """Mark ``name`` and hand it to ``Tag``."""
        super().__init__(self.of(name))

    @staticmethod
    def of(name: str) -> str:
        """Return the marked tag string a discriminator must return."""
        return f"{MarkedTag.PREFIX}{name}"

    @staticmethod
    def is_marked(segment: str | int) -> bool:
        """Return whether ``segment`` is a marked tag.

        Example:
            ```python
            MarkedTag.is_marked("#cat")  # True
            MarkedTag.is_marked("cat")   # False
            MarkedTag.is_marked(0)       # False
            ```
        """
        return isinstance(segment, str) and segment.startswith(MarkedTag.PREFIX)


def is_meta_key(segment: str | int) -> bool:
    """Return whether this loc segment describes the validation, not the data.

    Marked tags are exact; pydantic's own labels are matched by shape —
    identifiers have no brackets, and no field is named ``constrained-*``.

    Example:
        ```python
        is_meta_key("#cat")             # True  — a MarkedTag
        is_meta_key("list[str]")        # True  — a pydantic label
        is_meta_key("constrained-int")  # True  — a pydantic label
        is_meta_key("name")             # False — a real field
        is_meta_key(0)                  # False — a list index
        ```
    """
    return MarkedTag.is_marked(segment) or (
        isinstance(segment, str)
        and ("[" in segment or segment.startswith("constrained-"))
    )


def by_field(field: str) -> Callable[[Any], str | None]:
    """Read ``field`` from a dict or a model instance.

    Example:
        ```python
        read = by_field("kind")
        read({"kind": "cat"})  # "cat"
        read({"kind": 7})      # None — not a string
        read({})               # None — absent
        ```
    """

    def read(value: Any) -> str | None:
        """Return ``field``'s value when it is a string."""
        found = (
            value.get(field) if isinstance(value, dict) else getattr(value, field, None)
        )
        return found if isinstance(found, str) else None

    read.__name__ = f"by_field_{field}"
    read.__qualname__ = read.__name__
    return read


def alternative_name(member: Any, field: str | None) -> str:
    """Name a union member: its discriminator literal, or its type name.

    Args:
        member: A union member — a ``BaseModel`` or a pydantic dataclass. With
            a ``field``, it must declare that field as a single-valued
            ``Literal``.
        field: The discriminator field name, or None when routing is by shape.

    Returns:
        The member's name, used for both its tag and the error message.

    Raises:
        TypeError: If ``member`` has no single-valued ``Literal`` at ``field``.

    Example:
        ```python
        # Cat declares `kind: Literal["cat"]`
        alternative_name(Cat, "kind")  # "cat"

        # No field to read, so the type names itself
        alternative_name(Cat, None)  # "Cat"
        ```
    """
    if field is None:
        return str(member.__name__)
    # A BaseModel keeps its fields on `model_fields`, a pydantic dataclass on
    # `__pydantic_fields__`; both map to `FieldInfo`. Most union members in this
    # package are dataclasses, so the string-discriminator path must read both.
    fields = getattr(member, "model_fields", None) or getattr(
        member, "__pydantic_fields__", None
    )
    if fields is None or field not in fields:
        raise TypeError(f"{member.__name__} has no pydantic field {field!r}")
    values = get_args(fields[field].annotation)
    if len(values) != 1:
        raise TypeError(f"{member.__name__}.{field} must be a single-valued Literal")
    return str(values[0])


def discriminated_union(
    members: list[Any] | dict[str, Any],
    discriminator: str | Callable[[Any], str | None],
    *,
    error_type: str | None = None,
    message: str | None = None,
) -> Any:
    """Build a discriminated union whose tags and error message cannot drift.

    Each member names itself — see :func:`alternative_name`. That one name
    becomes the member's :class:`MarkedTag` and the value the discriminator
    returns to select it, so the two cannot disagree.

    The ``discriminator`` callable returns **unmarked** names; marking happens
    here, so existing routing functions need no changes.

    Args:
        members: The union members in order, or ``{name: member}`` when a member
            cannot name itself.
        discriminator: A field name holding each member's name (read from dicts
            and instances alike), or a callable returning that name.
        error_type: ``custom_error_type`` for an unroutable value. Omit when
            the discriminator is total (it can never fail to route), leaving
            pydantic's own tag errors in place.
        message: ``custom_error_message``, only used with ``error_type``.
            Defaults to a generated ``"<field> must be one of ..."`` listing
            the member names; pass caller-facing prose when the generated list
            would not help.

    Returns:
        An ``Annotated`` union ready to use as a field type — a *value*, not a
        type expression, so mypy cannot use the name it is bound to as a type.
        Module-level aliases that must stay mypy-visible reach this through
        :class:`DiscriminatedUnion` instead of calling it directly.

    Example:
        ```python
        Pet = discriminated_union([Cat, Dog], "kind", error_type="invalid_pet")
        # tags:    "#cat", "#dog"
        # routing: {"kind": "cat", ...} -> Cat
        # message: "kind must be one of 'cat', 'dog'"

        # A member that cannot name itself, plus prose instead of a name list
        Step = discriminated_union(
            {"str": NonEmptyStr, "FlowStep": FlowStep},
            _str_or("FlowStep"),
            error_type="invalid_flow_step",
            message="each flow step must be an event name or a FlowStep",
        )
        ```
    """
    field, read = (
        (discriminator, by_field(discriminator))
        if isinstance(discriminator, str)
        else (None, discriminator)
    )
    if isinstance(members, dict):
        named = list(members.items())
    else:
        named = [(alternative_name(member, field), member) for member in members]
    tags: dict[str | None, str] = {name: MarkedTag.of(name) for name, _member in named}

    def to_tag(value: Any) -> str | None:
        """Return ``value``'s marked tag, or None when it cannot be routed."""
        return tags.get(read(value))

    # Adopt the routing callable's identity: pydantic prints the discriminator's
    # `__name__` in a default tag error, and two guards in test_query_models.py
    # read that name and the return annotation through `__wrapped__`.
    functools.update_wrapper(to_tag, read)

    if error_type is not None and message is None:
        message = f"{field or 'value'} must be one of " + ", ".join(
            repr(name) for name, _member in named
        )
    routing = Discriminator(
        to_tag, custom_error_type=error_type, custom_error_message=message
    )
    return Annotated[
        Union[  # noqa: UP007 — subscripted with a tuple, `|` cannot express this
            tuple(Annotated[member, MarkedTag(name)] for name, member in named)
        ],
        routing,
    ]


class DiscriminatedUnion:
    """``Annotated`` metadata that turns a plain-union alias into a tagged union.

    :func:`discriminated_union` returns a *value*, so a module-level alias
    bound to it is invisible to mypy as a type — which forced every alias into
    an ``if TYPE_CHECKING:`` twin declaration. Attaching this marker to an
    ``Annotated`` plain union collapses the two: mypy reads the union straight
    off the annotation (metadata is never type-evaluated), and pydantic asks
    the marker for the schema, which delegates to :func:`discriminated_union`
    — same tags, routing, custom errors, and JSON schema.

    Example:
        ```python
        FlatSortConfig = Annotated[
            FlatLabelSortConfig | FlatValueSortConfig,
            DiscriminatedUnion(_flat_sort_discriminator),
        ]
        ```
    """

    def __init__(
        self,
        discriminator: str | Callable[[Any], str | None],
        *,
        members: list[Any] | dict[str, Any] | None = None,
        error_type: str | None = None,
        message: str | None = None,
    ) -> None:
        """Store the union recipe; the schema is built when pydantic asks.

        Args:
            discriminator: A field name holding each member's name, or a
                callable returning it — passed through to
                :func:`discriminated_union` unchanged.
            members: Override for the runtime members when they differ from
                the annotated union's args (constrained aliases, members that
                cannot name themselves). Defaults to the union's args.
            error_type: ``custom_error_type`` for an unroutable value; see
                :func:`discriminated_union`.
            message: ``custom_error_message``, only used with ``error_type``.
        """
        self.discriminator = discriminator
        self.members = members
        self.error_type = error_type
        self.message = message

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Build the tagged-union core schema for the annotated plain union.

        Args:
            source: The type this marker annotates — the plain union, unless
                ``members`` overrides it.
            handler: Pydantic's schema-generation handler.

        Returns:
            The core schema of ``discriminated_union(members, ...)``.

        Raises:
            TypeError: If ``source`` is not a union and no ``members``
                override was given — there is nothing to discriminate.
        """
        members = self.members if self.members is not None else list(get_args(source))
        if not members:
            raise TypeError(
                "DiscriminatedUnion must annotate a union, or be given members="
            )
        return handler.generate_schema(
            discriminated_union(
                members,
                self.discriminator,
                error_type=self.error_type,
                message=self.message,
            )
        )
