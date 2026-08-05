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

from pydantic import Discriminator, GetCoreSchemaHandler, GetJsonSchemaHandler, Tag
from pydantic.json_schema import JsonSchemaValue
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
            pet: Annotated[Cat | Dog, MarkedDiscriminator("kind", error_type="bad_pet")]

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


def literal_values(member: Any, field: str) -> tuple[str, ...]:
    """Read every value a member's discriminator ``Literal`` accepts.

    Args:
        member: A union member — a ``BaseModel`` or a pydantic dataclass.
        field: The discriminator field name.

    Returns:
        The literal values, in declaration order.

    Raises:
        TypeError: If ``member`` has no ``Literal`` at ``field``.

    Example:
        ```python
        # Cat declares `kind: Literal["cat"]`
        literal_values(Cat, "kind")  # ("cat",)

        # Presence declares `operator: Literal["is set", "is not set"]`
        literal_values(Presence, "operator")  # ("is set", "is not set")
        ```
    """
    # A BaseModel keeps its fields on `model_fields`, a pydantic dataclass on
    # `__pydantic_fields__`; both map to `FieldInfo`. Most union members in this
    # package are dataclasses, so the string-discriminator path must read both.
    fields = getattr(member, "model_fields", None) or getattr(
        member, "__pydantic_fields__", None
    )
    if fields is None or field not in fields:
        raise TypeError(f"{member.__name__} has no pydantic field {field!r}")
    values = get_args(fields[field].annotation)
    if not values:
        raise TypeError(f"{member.__name__}.{field} must be a Literal")
    return tuple(str(value) for value in values)


def alternative_name(member: Any, field: str | None) -> str:
    """Name a union member: its discriminator literal, or its type name.

    A member claiming several literals cannot be named after any one of
    them, so it takes its type name instead — and the tag stops doubling
    as the payload value. :class:`MarkedDiscriminator` handles that by
    routing through a value-to-tag map rather than comparing directly.

    Args:
        member: A union member — a ``BaseModel`` or a pydantic dataclass.
        field: The discriminator field name, or None when routing is by shape.

    Returns:
        The member's sole literal when it has exactly one, otherwise its
        type name.

    Raises:
        TypeError: If ``member`` has no ``Literal`` at ``field``.

    Example:
        ```python
        # Cat declares `kind: Literal["cat"]`
        alternative_name(Cat, "kind")  # "cat"

        # Presence declares `operator: Literal["is set", "is not set"]`
        alternative_name(Presence, "operator")  # "Presence"

        # No field to read, so the type names itself
        alternative_name(Cat, None)  # "Cat"
        ```
    """
    if field is None:
        return str(member.__name__)
    values = literal_values(member, field)
    return values[0] if len(values) == 1 else str(member.__name__)


class MarkedDiscriminator:
    """``Annotated`` metadata that turns a plain union into a marked tagged union.

    A union built by hand with ``Field(discriminator=...)`` puts bare tags in
    error ``loc``s (see :class:`MarkedTag`), and a union built by a function
    call is invisible to mypy as a type. This marker solves both with one
    declaration: mypy reads the plain union straight off the ``Annotated``
    (metadata is never type-evaluated), and pydantic asks the marker for the
    schema, which builds the tagged union with :class:`MarkedTag` tags.

    Each member names itself — see :func:`alternative_name`. That one name
    becomes the member's tag and the value the discriminator returns to select
    it, so the two cannot disagree. The ``discriminator`` callable returns
    **unmarked** names; marking happens here, so routing functions stay plain.

    Example:
        ```python
        FlatSortConfig = Annotated[
            FlatLabelSortConfig | FlatValueSortConfig,
            MarkedDiscriminator(_flat_sort_discriminator),
        ]
        # mypy sees:  FlatLabelSortConfig | FlatValueSortConfig
        # runtime:    tags "#FlatLabelSortConfig" / "#FlatValueSortConfig"

        Pet = Annotated[Cat | Dog, MarkedDiscriminator("kind", error_type="invalid_pet")]
        # routing: {"kind": "cat", ...} -> Cat
        # message: "kind must be one of 'cat', 'dog'"

        # A member that cannot name itself, plus prose instead of a name list
        Step = Annotated[
            str | FlowStep,
            MarkedDiscriminator(
                _str_or("FlowStep"),
                members={"str": NonEmptyStr, "FlowStep": FlowStep},
                error_type="invalid_flow_step",
                message="each flow step must be an event name or a FlowStep",
            ),
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
            discriminator: A field name holding each member's name (read from
                dicts and instances alike), or a callable returning that name.
            members: Override for the runtime members when they differ from
                the annotated union's args — constrained aliases, hidden
                schema wrappers, or ``{name: member}`` when a member cannot
                name itself. Defaults to the union's args, in order.
            error_type: ``custom_error_type`` for an unroutable value. Omit
                when the discriminator is total (it can never fail to route),
                leaving pydantic's own tag errors in place.
            message: ``custom_error_message``, only used with ``error_type``.
                Defaults to a generated ``"<field> must be one of ..."``
                listing the member names; pass caller-facing prose when the
                generated list would not help.
        """
        self.discriminator = discriminator
        self.members = members
        self.error_type = error_type
        self.message = message
        self._json_schema_mapping: tuple[tuple[str, ...], ...] | None = None
        """Per member, the values it accepts — stashed for the JSON hook.

        In union order, so it zips against the generated branch list.
        Only set when routing is by a field name, the only case that can
        produce an OpenAPI ``discriminator``. Pydantic always builds the
        core schema before the JSON schema, so this is populated by the
        time the JSON hook reads it.
        """

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        """Build the tagged-union core schema for the annotated plain union.

        Args:
            source: The type this marker annotates — the plain union, unless
                ``members`` overrides it.
            handler: Pydantic's schema-generation handler.

        Returns:
            The core schema of the marked tagged union.

        Raises:
            TypeError: If ``source`` is not a union and no ``members``
                override was given — there is nothing to discriminate.
        """
        field, read = (
            (self.discriminator, by_field(self.discriminator))
            if isinstance(self.discriminator, str)
            else (None, self.discriminator)
        )
        members = self.members if self.members is not None else list(get_args(source))
        if not members:
            raise TypeError(
                "MarkedDiscriminator must annotate a union, or be given members="
            )
        accepts: list[tuple[str, ...]]
        if isinstance(members, dict):
            named = list(members.items())
            # A caller-supplied tag doubles as the value `read` returns.
            accepts = [(name,) for name, _member in named]
        else:
            named = [(alternative_name(member, field), member) for member in members]
            accepts = [
                literal_values(member, field) if field is not None else (name,)
                for name, member in named
            ]
        # Every value a member accepts routes to that member's single tag. The
        # two coincide for a single-valued Literal, where the tag *is* the
        # value; they diverge when a member claims several, and the tag falls
        # back to its type name.
        tags: dict[str | None, str] = {
            value: MarkedTag.of(name)
            for (name, _member), values in zip(named, accepts, strict=True)
            for value in values
        }

        def to_tag(value: Any) -> str | None:
            """Return ``value``'s marked tag, or None when it cannot be routed."""
            return tags.get(read(value))

        # Adopt the routing callable's identity: pydantic prints the
        # discriminator's `__name__` in a default tag error, and two guards in
        # test_query_models.py read that name and the return annotation
        # through `__wrapped__`.
        functools.update_wrapper(to_tag, read)

        message = self.message
        if self.error_type is not None and message is None:
            # List what a payload may carry, not what the members are called.
            message = f"{field or 'value'} must be one of " + ", ".join(
                repr(value) for values in accepts for value in values
            )
        routing = Discriminator(
            to_tag, custom_error_type=self.error_type, custom_error_message=message
        )
        # Routing by a field is the only case that can carry an OpenAPI
        # `discriminator`; a shape-routed union has no property to name.
        self._json_schema_mapping = tuple(accepts) if field is not None else None
        return handler.generate_schema(
            Annotated[
                Union[  # noqa: UP007 — subscripted with a tuple, `|` can't do this
                    tuple(Annotated[member, MarkedTag(name)] for name, member in named)
                ],
                routing,
            ]
        )

    def __get_pydantic_json_schema__(
        self, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        """Add the OpenAPI ``discriminator`` block that routing already implies.

        Pydantic emits that block only for ``Field(discriminator="x")``,
        because it cannot know what a callable routes on. This marker
        always routes through a callable — that is how the tag gets
        ``#``-marked — so pydantic stays silent even when we *do* know the
        mapping. We know it because we built it.

        Without the block a consumer can still pick a branch: every member
        pins the discriminator field to its own literal, so the ``oneOf``
        is decidable by scanning ``$defs``. The block just states the same
        thing directly::

            "oneOf": [{"$ref": "#/$defs/Equals"}, ...]        # decidable
            "discriminator": {                                 # ...and stated
                "propertyName": "operator",
                "mapping": {"equals": "#/$defs/Equals", ...}
            }

        It is a hint, not information — which is why it is safe to omit
        when it cannot be built truthfully. Three cases skip it: routing
        by shape (no property to name), a branch list whose length has
        drifted from the tag list, and any branch that is not a plain
        ``$ref`` (an inline subschema has nothing for ``mapping`` to
        point at).

        Args:
            schema: The core schema this marker produced.
            handler: Pydantic's JSON-schema handler.

        Returns:
            The generated JSON schema, with ``discriminator`` added when
            it can be stated truthfully.
        """
        json_schema = handler(schema)
        accepts = self._json_schema_mapping
        if accepts is None:
            return json_schema
        branches = json_schema.get("oneOf") or json_schema.get("anyOf")
        if not isinstance(branches, list) or len(branches) != len(accepts):
            return json_schema
        refs = [b.get("$ref") if isinstance(b, dict) else None for b in branches]
        if not all(isinstance(ref, str) for ref in refs):
            return json_schema
        # Keyed on the values a payload carries, not the tags. A member
        # claiming several literals contributes several entries pointing at
        # the same `$ref`, which OpenAPI allows.
        json_schema["discriminator"] = {
            "propertyName": self.discriminator,
            "mapping": {
                value: ref
                for values, ref in zip(accepts, refs, strict=True)
                for value in values
            },
        }
        return json_schema
