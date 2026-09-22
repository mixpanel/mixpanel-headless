"""Unit tests for ``mixpanel_headless._internal.help.introspect``.

Covers the signature and field introspection helpers:

- ``format_type`` on concrete annotations and strings.
- ``signature_doc`` on ``Workspace.query`` and local fixtures.
- ``dataclass_fields_doc`` and ``pydantic_fields_doc`` on local fixtures,
  plus private-field elision on ``Filter`` and ``Replay``.
- ``model_config_doc`` on a fixture that sets all four keys.
- ``class_sections`` on ``Filter``, ``QueryResult``, and a plain class.
- ``resolved_hints`` degrading to ``{}`` on ``FlowQueryResult``.

Real-library assertions lock counts measured on 2026-09-21: ``MathType`` has
22 values and ``Filter`` has 28 factory classmethods.
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, Union

import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from mixpanel_headless import (
    Filter,
    FlowQueryResult,
    QueryResult,
    Replay,
    Workspace,
)
from mixpanel_headless._internal.help import introspect
from mixpanel_headless._internal.help.introspect import (
    allowed_values,
    bases_doc,
    class_sections,
    clear_cache,
    dataclass_fields_doc,
    enum_members,
    enum_values,
    format_type,
    model_config_doc,
    pydantic_fields_doc,
    resolved_hints,
    signature_doc,
)
from mixpanel_headless._internal.help.models import (
    FieldDoc,
    MemberDoc,
    ParamDoc,
    SignatureDoc,
)

# =============================================================================
# Fixtures — small local types that exercise every branch
# =============================================================================


class Color(enum.Enum):
    """Fixture enum with two members."""

    RED = "red"
    GREEN = "green"


class Size(str, enum.Enum):
    """Fixture ``str`` enum with integer-like values."""

    SMALL = "s"
    LARGE = "l"


Mode = Literal["fast", "slow"]
"""Fixture Literal alias used as a parameter and field annotation."""


@dataclass
class Point:
    """Fixture dataclass with a default, a factory, a private field, and enums.

    Args:
        x: Horizontal coordinate.
        y: Vertical coordinate.
        tags: Free-form labels.
        color: Display color.
        mode: Rendering mode.
    """

    x: int
    y: int = 0
    tags: list[str] = field(default_factory=list)
    _cache: dict[str, int] = field(default_factory=dict, repr=False)
    color: Color = Color.RED
    mode: Mode = "fast"
    label: str | None = None


class Person(BaseModel):
    """Fixture model with required, factory, constrained, aliased, and None fields.

    Args:
        age: Age in years.
    """

    name: str = Field(..., max_length=50, min_length=1, description="Full name.")
    age: int = Field(default=0, ge=0, lt=150)
    code: str = Field(default="x", pattern=r"^[a-z]+$")
    tags: list[str] = Field(default_factory=list)
    nickname: str | None = None
    color: Color = Color.RED
    sizes: list[Size] = Field(default_factory=list)
    mode: Mode | None = None
    explicit: int = Field(default=1, alias="EXPLICIT")


class Camel(BaseModel):
    """Fixture model with every non-default config key and a public validator."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )

    display_name: str
    plain: int = 0

    @field_validator("plain")
    @classmethod
    def check_plain(cls, value: int) -> int:
        """Validator that must not appear in the methods listing.

        Args:
            value: Field value.

        Returns:
            The value unchanged.
        """
        return value

    @property
    def shout(self) -> str:
        """Upper-cased display name."""
        return self.display_name.upper()

    def greet(self, greeting: str = "hi") -> str:
        """Return a greeting.

        Args:
            greeting: Greeting word.

        Returns:
            The greeting plus the display name.
        """
        return f"{greeting} {self.display_name}"


class Plain:
    """Fixture plain class with a factory, a property, methods, and privates."""

    def __init__(self, value: int) -> None:
        """Store the value.

        Args:
            value: Any integer.
        """
        self.value = value

    @classmethod
    def from_string(cls, text: str) -> Plain:
        """Build from a string.

        Args:
            text: Digits.

        Returns:
            A new instance.
        """
        return cls(int(text))

    @staticmethod
    def zero() -> "Plain":  # noqa: UP037 - quoted return is the case under test
        """Build a zero instance.

        Returns:
            A new instance with value 0.
        """
        return Plain(0)

    @classmethod
    def count(cls, items: Sequence[int]) -> int:
        """Count items (not a constructor: returns ``int``).

        Args:
            items: Items to count.

        Returns:
            The number of items.
        """
        return len(items)

    @property
    def doubled(self) -> int:
        """Twice the value."""
        return self.value * 2

    def add(self, other: int, *rest: int, scale: float = 1.0, **extra: int) -> int:
        """Add numbers.

        Args:
            other: First addend.
            *rest: More addends.
            scale: Multiplier.
            **extra: Ignored.

        Returns:
            The sum.
        """
        return int((self.value + other + sum(rest)) * scale)

    def _hidden(self) -> None:
        """Private method that must not be listed."""


class Child(Plain):
    """Fixture subclass used for MRO and bases tests."""

    def extra(self) -> None:
        """Subclass-only method."""


class NoSignature:
    """Fixture callable whose ``__signature__`` makes ``inspect.signature`` raise."""

    __signature__ = 42

    def __call__(self) -> None:
        """Do nothing."""


def _plain_function(name: str, count: int = 1, *, mode: Mode = "fast") -> str:
    """Fixture module-level function with a keyword-only Literal parameter.

    Args:
        name: A name.
        count: Repeat count.
        mode: Speed.

    Returns:
        The name repeated.
    """
    return name * count


@pytest.fixture(autouse=True)
def _reset_cache() -> typing.Iterator[None]:
    """Clear the resolved-hints cache around every test.

    Yields:
        Nothing; the cache is cleared before and after the test body.
    """
    clear_cache()
    yield
    clear_cache()


# =============================================================================
# format_type
# =============================================================================


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (None, "None"),
        (type(None), "None"),
        (int, "int"),
        (str, "str"),
        (Filter, "Filter"),
        (Color, "Color"),
        (list[str], "list[str]"),
        (dict[str, int], "dict[str, int]"),
        (list[Filter], "list[Filter]"),
        (Optional[int], "int | None"),  # noqa: UP045 - the typing form is the case
        (Union[int, str], "int | str"),  # noqa: UP007 - the typing form is the case
        (Literal["a", "b"], "Literal['a', 'b']"),
        (Sequence[str], "Sequence[str]"),
        (typing.Any, "Any"),
        (typing.ForwardRef("Filter"), "Filter"),
        (Annotated[int, "meta"], "Annotated[int, 'meta']"),
    ],
)
def test_format_type_objects(annotation: object, expected: str) -> None:
    """Concrete annotation objects render as clean display strings.

    Args:
        annotation: The annotation under test.
        expected: The expected display string.
    """
    assert format_type(annotation) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MathType", "MathType"),
        ("str | None", "str | None"),
        ("typing.Optional[int]", "int | None"),
        ("Optional[Dict[str, int]]", "Dict[str, int] | None"),
        ("typing.Union[int, str, None]", "int | str | None"),
        ("Union[int, Optional[str]]", "int | str | None"),
        ("typing_extensions.Literal['a']", "Literal['a']"),
        ("<class 'int'>", "int"),
        ("list[<class 'int'>]", "list[int]"),
        ("NoneType", "None"),
        ("mixpanel_headless.types.Filter", "Filter"),
        ("list[mixpanel_headless._internal.auth.account.Account]", "list[Account]"),
        ("collections.abc.Iterator[Event]", "Iterator[Event]"),
        ("ForwardRef('Filter')", "Filter"),
        ("'Filter'", "Filter"),
        ("OptionalThing[int]", "OptionalThing[int]"),
        ("MyUnion[int]", "MyUnion[int]"),
        (
            "Literal['timeseries', 'total', 'table']",
            "Literal['timeseries', 'total', 'table']",
        ),
        ("", ""),
        ("Optional[int", "Optional[int"),
        ("Union[int, str", "Union[int, str"),
    ],
)
def test_format_type_strings(text: str, expected: str) -> None:
    """String annotations are cleaned but otherwise kept as written.

    Args:
        text: The source annotation string.
        expected: The expected display string.
    """
    assert format_type(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "typing.Optional[typing.Union[int, NoneType]]",
        "<class 'mixpanel_headless.types.Filter'>",
        "Optional[list[Optional[str]]]",
        "typiNoneTypeng.X",
    ],
)
def test_format_type_is_idempotent(text: str) -> None:
    """Applying ``format_type`` to its own output changes nothing.

    Args:
        text: An annotation string that needs several cleanup passes.
    """
    once = format_type(text)
    assert format_type(once) == once
    assert "typing." not in once
    assert "NoneType" not in once
    assert "<class" not in once


def test_format_type_keeps_alias_names_from_source() -> None:
    """The string annotation of ``Workspace.query``'s ``math`` stays ``MathType``."""
    param = inspect.signature(Workspace.query).parameters["math"]
    assert format_type(param.annotation) == "MathType"


# =============================================================================
# resolved_hints
# =============================================================================


def test_resolved_hints_resolves_workspace_query() -> None:
    """``Workspace.query`` resolves fully; ``math`` is a 22-value Literal."""
    hints = resolved_hints(Workspace.query)
    assert typing.get_origin(hints["math"]) is Literal
    assert len(typing.get_args(hints["math"])) == 22
    assert hints["return"] is QueryResult


def test_resolved_hints_returns_empty_dict_on_name_error() -> None:
    """``FlowQueryResult`` cannot resolve (``networkx`` is TYPE_CHECKING-only)."""
    with pytest.raises(NameError):
        typing.get_type_hints(FlowQueryResult)
    assert resolved_hints(FlowQueryResult) == {}


def test_resolved_hints_returns_empty_dict_for_non_annotatable() -> None:
    """Objects that ``get_type_hints`` rejects yield ``{}`` instead of raising."""
    assert resolved_hints(42) == {}
    assert resolved_hints("text") == {}


def test_resolved_hints_keeps_annotated_extras() -> None:
    """``include_extras=True`` keeps ``Annotated`` metadata."""

    def tagged(x: Annotated[int, "meta"]) -> None:
        """Fixture.

        Args:
            x: Tagged integer.
        """

    hints = resolved_hints(tagged)
    assert typing.get_origin(hints["x"]) is Annotated


def test_resolved_hints_caches_per_object_and_clear_cache_resets() -> None:
    """Repeated calls return equal hints; ``clear_cache`` drops the cache."""
    first = resolved_hints(Workspace.query)
    second = resolved_hints(Workspace.query)
    assert first == second
    assert introspect._HINTS_CACHE
    clear_cache()
    assert not introspect._HINTS_CACHE


def test_resolved_hints_returns_a_copy() -> None:
    """Mutating a returned dict does not corrupt the cache."""
    hints = resolved_hints(_plain_function)
    hints.clear()
    assert resolved_hints(_plain_function)["name"] is str


# =============================================================================
# allowed_values
# =============================================================================


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        (Literal["a", "b"], ("a", "b")),
        (Literal[1, True, "x"], ("1", "True", "x")),
        (Color, ("RED", "GREEN")),
        (Optional[Literal["a", "b"]], ("a", "b")),  # noqa: UP045
        (Union[Literal["a"], Literal["b", "c"]], ("a", "b", "c")),  # noqa: UP007
        (Union[Literal["a", "b"], Literal["b"]], ("a", "b")),  # noqa: UP007
        (Color | None, ("RED", "GREEN")),
        (list[Color], ("RED", "GREEN")),
        (dict[str, Size], ("SMALL", "LARGE")),
        (Annotated[Literal["x"], "meta"], ("x",)),
        (Union[Color, Size], ("RED", "GREEN", "SMALL", "LARGE")),  # noqa: UP007
        (str, ()),
        (int | None, ()),
        (list[str], ()),
        (None, ()),
        ("Literal['a']", ()),
        (Callable[[Color], Size], ("SMALL", "LARGE")),
    ],
)
def test_allowed_values(hint: object, expected: tuple[str, ...]) -> None:
    """Literal and enum hints yield their values in order; others yield ``()``.

    Args:
        hint: The resolved hint under test.
        expected: The expected value tuple.
    """
    assert allowed_values(hint) == expected


# =============================================================================
# signature_doc
# =============================================================================


def test_signature_doc_workspace_query() -> None:
    """``Workspace.query``: strings kept, values filled, ``self`` removed."""
    doc = signature_doc(Workspace.query)
    assert doc.name == "query"
    names = [param.name for param in doc.params]
    assert "self" not in names
    assert names[0] == "events"
    by_name = {param.name: param for param in doc.params}
    assert by_name["math"].annotation == "MathType"
    assert by_name["math"].default == "'total'"
    assert len(by_name["math"].values) == 22
    assert by_name["math"].values[:3] == ("total", "unique", "dau")
    assert by_name["mode"].values == ("timeseries", "total", "table")
    assert by_name["mode"].annotation == "Literal['timeseries', 'total', 'table']"
    assert by_name["last"].default == "30"
    assert by_name["last"].annotation == "int"
    assert by_name["cumulative"].default == "False"
    assert by_name["events"].default is None
    assert by_name["events"].annotation.startswith("str | Metric | CohortMetric")
    assert by_name["events"].description.startswith("Event name(s) to query.")
    assert by_name["where"].values == ()
    assert doc.returns == "QueryResult"


def test_signature_doc_every_param_has_a_description_on_workspace_query() -> None:
    """Every ``Workspace.query`` parameter has an ``Args:`` description."""
    doc = signature_doc(Workspace.query)
    assert all(param.description for param in doc.params)


def test_signature_doc_local_function() -> None:
    """Defaults use ``repr``; keyword-only Literal values and kinds are filled."""
    doc = signature_doc(_plain_function)
    assert doc == SignatureDoc(
        name="_plain_function",
        params=(
            ParamDoc("name", "str", None, "A name.", ()),
            ParamDoc("count", "int", "1", "Repeat count.", ()),
            ParamDoc(
                "mode", "Mode", "'fast'", "Speed.", ("fast", "slow"), "keyword_only"
            ),
        ),
        returns="str",
    )


def test_signature_doc_var_args_and_kwargs() -> None:
    """``*args`` and ``**kwargs`` keep their prefixes and kinds; ``self`` is dropped."""
    doc = signature_doc(Plain.add)
    assert [param.name for param in doc.params] == [
        "other",
        "*rest",
        "scale",
        "**extra",
    ]
    assert [param.kind for param in doc.params] == [
        "positional_or_keyword",
        "var_positional",
        "keyword_only",
        "var_keyword",
    ]
    by_name = {param.name: param for param in doc.params}
    assert by_name["*rest"].description == "More addends."
    assert by_name["**extra"].description == "Ignored."
    assert by_name["scale"].default == "1.0"
    assert doc.returns == "int"


def test_signature_doc_positional_only_kind() -> None:
    """Parameters before ``/`` are recorded as ``positional_only``."""

    def divide(numerator: int, denominator: int, /, precision: int = 2) -> float:
        """Fixture with two positional-only parameters.

        Args:
            numerator: Top.
            denominator: Bottom.
            precision: Rounding digits.

        Returns:
            The rounded quotient.
        """
        return round(numerator / denominator, precision)

    doc = signature_doc(divide)
    assert [(param.name, param.kind) for param in doc.params] == [
        ("numerator", "positional_only"),
        ("denominator", "positional_only"),
        ("precision", "positional_or_keyword"),
    ]


def test_signature_doc_workspace_segmentation_records_keyword_only() -> None:
    """``Workspace.segmentation`` keeps ``event`` positional and the rest keyword-only."""
    doc = signature_doc(Workspace.segmentation)
    assert doc.params[0].name == "event"
    assert doc.params[0].kind == "positional_or_keyword"
    assert doc.params[1].name == "from_date"
    assert doc.params[1].kind == "keyword_only"
    assert all(param.kind == "keyword_only" for param in doc.params[1:])
    payload = doc.to_dict()
    assert isinstance(payload["params"], list)
    assert payload["params"][1]["kind"] == "keyword_only"


def test_signature_doc_bound_classmethod_drops_cls() -> None:
    """A classmethod fetched from the class has no ``cls`` parameter."""
    doc = signature_doc(Filter.equals)
    assert doc.name == "equals"
    assert [param.name for param in doc.params] == [
        "property",
        "value",
        "resource_type",
    ]
    assert doc.params[2].values == ("events", "people")
    assert doc.returns == "Filter"


def test_signature_doc_unwraps_descriptor_with_owner() -> None:
    """A raw ``classmethod`` object from ``vars()`` is unwrapped via ``owner``."""
    raw = vars(Plain)["from_string"]
    assert isinstance(raw, classmethod)
    doc = signature_doc(raw, name="from_string", owner=Plain)
    assert [param.name for param in doc.params] == ["text"]
    assert doc.returns == "Plain"


def test_signature_doc_name_override() -> None:
    """``name=`` replaces the callable's own name."""
    assert signature_doc(_plain_function, name="fn").name == "fn"


def test_signature_doc_without_annotations() -> None:
    """A parameter with no annotation has ``annotation == ""`` and no return."""

    def bare(a, b=2):  # noqa: ANN001, ANN202
        """Fixture.

        Args:
            a: First.
            b: Second.
        """

    doc = signature_doc(bare)
    assert doc.params == (
        ParamDoc("a", "", None, "First.", ()),
        ParamDoc("b", "", "2", "Second.", ()),
    )
    assert doc.returns is None


def test_signature_doc_returns_none_for_none_annotation() -> None:
    """``-> None`` renders as ``"None"``, not as a missing return."""
    assert signature_doc(Plain.__init__).returns == "None"


def test_signature_doc_when_signature_unavailable() -> None:
    """When ``inspect.signature`` raises, the result has no params and no return."""
    doc = signature_doc(NoSignature(), name="mystery")
    assert doc == SignatureDoc(name="mystery", params=(), returns=None)


def test_signature_doc_on_a_class_uses_init_params() -> None:
    """Calling on a class documents the constructor parameters."""
    doc = signature_doc(Point)
    assert doc.name == "Point"
    names = [param.name for param in doc.params]
    assert names[:3] == ["x", "y", "tags"]
    by_name = {param.name: param for param in doc.params}
    assert by_name["x"].description == "Horizontal coordinate."
    assert by_name["mode"].values == ("fast", "slow")


# =============================================================================
# dataclass_fields_doc
# =============================================================================


def test_dataclass_fields_doc_fixture() -> None:
    """Defaults via ``repr``, factories as ``<name>``, private omitted, values filled."""
    docs = dataclass_fields_doc(Point)
    assert [doc.name for doc in docs] == ["x", "y", "tags", "color", "mode", "label"]
    by_name = {doc.name: doc for doc in docs}
    assert by_name["x"] == FieldDoc(
        "x", "int", None, True, (), None, (), "Horizontal coordinate."
    )
    assert by_name["y"].default == "0"
    assert by_name["y"].required is False
    assert by_name["tags"].default == "<list>"
    assert by_name["tags"].required is False
    assert by_name["color"].annotation == "Color"
    assert by_name["color"].default == "<Color.RED: 'red'>"
    assert by_name["color"].values == ("RED", "GREEN")
    assert by_name["mode"].annotation == "Mode"
    assert by_name["mode"].values == ("fast", "slow")
    assert by_name["mode"].description == "Rendering mode."
    assert by_name["label"].default == "None"
    assert by_name["label"].description == ""


def test_dataclass_fields_doc_filter_has_no_public_fields() -> None:
    """Every ``Filter`` field is private, so the public list is empty."""
    assert dataclass_fields_doc(Filter) == ()


def test_dataclass_fields_doc_replay_omits_private_caches() -> None:
    """``Replay`` shows its nine public fields and no ``_*_cache`` field."""
    docs = dataclass_fields_doc(Replay)
    names = [doc.name for doc in docs]
    assert not any(name.startswith("_") for name in names)
    assert names == [
        "replay_id",
        "distinct_id",
        "project_id",
        "start_time",
        "end_time",
        "retention_days",
        "rrweb_events",
        "actions",
        "mixpanel_events",
    ]
    assert len(names) == len(
        [f for f in dataclasses.fields(Replay) if not f.name.startswith("_")]
    )


def test_dataclass_fields_doc_non_dataclass_is_empty() -> None:
    """A class that is not a dataclass yields ``()``."""
    assert dataclass_fields_doc(Plain) == ()


# =============================================================================
# pydantic_fields_doc
# =============================================================================


def test_pydantic_fields_doc_person() -> None:
    """Required, factory, constraints, explicit alias, and None default."""
    docs = pydantic_fields_doc(Person)
    assert [doc.name for doc in docs] == [
        "name",
        "age",
        "code",
        "tags",
        "nickname",
        "color",
        "sizes",
        "mode",
        "explicit",
    ]
    by_name = {doc.name: doc for doc in docs}
    assert by_name["name"] == FieldDoc(
        name="name",
        annotation="str",
        default=None,
        required=True,
        constraints=("min_length=1", "max_length=50"),
        alias=None,
        values=(),
        description="Full name.",
    )
    assert by_name["age"].default == "0"
    assert by_name["age"].required is False
    assert by_name["age"].constraints == ("ge=0", "lt=150")
    assert by_name["age"].description == "Age in years."
    assert by_name["code"].constraints == ("pattern=^[a-z]+$",)
    assert by_name["code"].default == "'x'"
    assert by_name["tags"].default == "<list>"
    assert by_name["tags"].required is False
    assert by_name["nickname"].default is None
    assert by_name["nickname"].required is False
    assert by_name["nickname"].annotation == "str | None"
    assert by_name["explicit"].alias == "EXPLICIT"
    assert by_name["explicit"].default == "1"


def test_pydantic_fields_doc_inline_enum_and_literal_values() -> None:
    """Enum members appear inline, also inside ``list[...]`` and ``| None``."""
    by_name = {doc.name: doc for doc in pydantic_fields_doc(Person)}
    assert by_name["color"].values == ("RED", "GREEN")
    assert by_name["color"].default == "<Color.RED: 'red'>"
    assert by_name["sizes"].values == ("SMALL", "LARGE")
    assert by_name["mode"].values == ("fast", "slow")
    assert by_name["mode"].annotation == "Mode | None"


def test_pydantic_fields_doc_generated_alias() -> None:
    """An ``alias_generator`` alias is reported only when it differs from the name."""
    by_name = {doc.name: doc for doc in pydantic_fields_doc(Camel)}
    assert by_name["display_name"].alias == "displayName"
    assert by_name["display_name"].required is True
    assert by_name["plain"].alias is None


def test_pydantic_fields_doc_real_model_has_no_private_names() -> None:
    """A real library model lists no private names and keeps source aliases."""
    from mixpanel_headless import CreateCohortParams

    docs = pydantic_fields_doc(CreateCohortParams)
    assert docs
    assert not any(doc.name.startswith("_") for doc in docs)
    assert all(doc.annotation for doc in docs)


def test_pydantic_fields_doc_non_model_is_empty() -> None:
    """A class that is not a Pydantic model yields ``()``."""
    assert pydantic_fields_doc(Point) == ()  # type: ignore[arg-type]


# =============================================================================
# model_config_doc
# =============================================================================


def test_model_config_doc_all_four_keys() -> None:
    """All four tracked keys appear when set to non-default values."""
    assert model_config_doc(Camel) == (
        ("frozen", "True"),
        ("extra", "forbid"),
        ("populate_by_name", "True"),
        ("alias_generator", "to_camel"),
    )


def test_model_config_doc_defaults_are_empty() -> None:
    """A model with default config yields ``()``."""
    assert model_config_doc(Person) == ()


def test_model_config_doc_explicit_default_values_are_elided() -> None:
    """Keys set explicitly to their defaults are not reported."""

    class Defaulted(BaseModel):
        """Fixture with explicit default config."""

        model_config = ConfigDict(frozen=False, extra="ignore", populate_by_name=False)

    assert model_config_doc(Defaulted) == ()


# =============================================================================
# enum_values / enum_members
# =============================================================================


def test_enum_values_and_members() -> None:
    """Member names in definition order; members pair names with ``repr`` values."""
    assert enum_values(Color) == ("RED", "GREEN")
    assert enum_members(Color) == (("RED", "'red'"), ("GREEN", "'green'"))
    assert enum_members(Size) == (("SMALL", "'s'"), ("LARGE", "'l'"))


def test_enum_values_real_enum() -> None:
    """A real library enum yields every member name once."""
    from mixpanel_headless import FeatureFlagStatus

    values = enum_values(FeatureFlagStatus)
    assert values == tuple(member.name for member in FeatureFlagStatus)
    assert len(values) == len(set(values))


# =============================================================================
# class_sections
# =============================================================================


def test_class_sections_filter() -> None:
    """``Filter`` has 28 construction classmethods, no properties, no methods."""
    construction, properties, methods = class_sections(Filter)
    assert len(construction) == 28
    assert properties == ()
    assert methods == ()
    names = [member.name for member in construction]
    assert names == sorted(names)
    assert "equals" in names
    equals = next(member for member in construction if member.name == "equals")
    assert equals.kind == "method"
    assert equals.signature is not None
    assert equals.signature.returns == "Filter"
    assert equals.summary


def test_class_sections_query_result_has_df_property() -> None:
    """``QueryResult`` exposes ``df`` as a property with a summary."""
    _construction, properties, _methods = class_sections(QueryResult)
    df = next(member for member in properties if member.name == "df")
    assert df == MemberDoc("df", "property", df.summary, None)
    assert df.summary


def test_class_sections_plain_class() -> None:
    """A plain class splits constructors, properties, and methods; privates hidden."""
    construction, properties, methods = class_sections(Plain)
    assert [member.name for member in construction] == ["from_string", "zero"]
    assert [member.name for member in properties] == ["doubled"]
    assert [member.name for member in methods] == ["add", "count"]
    assert properties[0].signature is None
    assert properties[0].summary == "Twice the value."
    add = methods[0]
    assert add.signature is not None
    assert [(p.name, p.default) for p in add.signature.params] == [
        ("other", None),
        ("*rest", None),
        ("scale", "1.0"),
        ("**extra", None),
    ]
    assert add.summary == "Add numbers."


def test_class_sections_subclass_includes_inherited_members() -> None:
    """Members defined on an in-package base class are listed for the subclass."""
    construction, properties, methods = class_sections(Child)
    assert [member.name for member in construction] == ["from_string", "zero"]
    assert [member.name for member in properties] == ["doubled"]
    assert [member.name for member in methods] == ["add", "count", "extra"]


def test_class_sections_pydantic_model_skips_framework_and_validators() -> None:
    """Pydantic ``model_*`` helpers and registered validators are not listed."""
    construction, properties, methods = class_sections(Camel)
    assert construction == ()
    assert [member.name for member in properties] == ["shout"]
    assert [member.name for member in methods] == ["greet"]


def test_class_sections_enum_lists_nothing() -> None:
    """Enum machinery is not in ``mixpanel_headless``, so every section is empty."""
    assert class_sections(Color) == ((), (), ())


def test_class_sections_workspace_counts() -> None:
    """``Workspace`` has five public properties and every public method listed."""
    construction, properties, methods = class_sections(Workspace)
    assert construction == ()
    assert [member.name for member in properties] == [
        "account",
        "api",
        "project",
        "session",
        "workspace",
    ]
    expected = sorted(
        name
        for name, value in vars(Workspace).items()
        if not name.startswith("_") and inspect.isfunction(value)
    )
    assert [member.name for member in methods] == expected
    assert len(methods) >= 200


# =============================================================================
# bases_doc
# =============================================================================


def test_bases_doc() -> None:
    """Direct bases are named; ``object`` and ``BaseModel`` are dropped."""
    assert bases_doc(Filter) == ()
    assert bases_doc(Person) == ()
    assert bases_doc(Child) == ("Plain",)
    assert bases_doc(Size) == ("str", "Enum")
    assert bases_doc(QueryResult) == ("ResultWithDataFrame",)


def test_bases_doc_exception_chain() -> None:
    """An exception names its direct parent only."""
    from mixpanel_headless import APIError, MixpanelHeadlessError

    assert bases_doc(APIError) == ("MixpanelHeadlessError",)
    assert bases_doc(MixpanelHeadlessError) == ("Exception",)


# =============================================================================
# Defensive branches
# =============================================================================


def test_signature_doc_name_falls_back_to_type_name() -> None:
    """A callable object without ``__name__`` is named after its type."""
    assert signature_doc(NoSignature()).name == "NoSignature"


def test_class_sections_classmethod_without_return_is_a_method() -> None:
    """A classmethod with no return annotation is never construction."""

    class Bare:
        """Fixture."""

        @classmethod
        def make(cls):  # noqa: ANN206
            """Build without a return annotation."""
            return cls()

    construction, _properties, methods = class_sections(Bare)
    assert construction == ()
    assert [member.name for member in methods] == ["make"]


def test_pydantic_annotation_falls_back_when_source_is_annotated() -> None:
    """An ``Annotated[...]`` source annotation falls back to the resolved type."""

    class Wrapped(BaseModel):
        """Fixture whose source annotation is an ``Annotated`` wrapper."""

        code: Annotated[str, Field(max_length=3)]

    (doc,) = pydantic_fields_doc(Wrapped)
    assert doc.annotation == "str"
    assert doc.constraints == ("max_length=3",)
    assert doc.required is True


def test_pydantic_alias_helpers_tolerate_bad_generators() -> None:
    """A raising or non-callable alias generator yields no alias."""

    def boom(name: str) -> str:
        """Always raise.

        Args:
            name: Ignored.

        Returns:
            Never returns.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError(name)

    info = Person.model_fields["age"]
    assert introspect._pydantic_alias("age", info, boom) is None
    assert introspect._pydantic_alias("age", info, lambda name: name.upper()) == "AGE"
    assert introspect._alias_callable(42) is None
    assert introspect._alias_callable(None) is None


def test_model_config_doc_on_non_model_is_empty() -> None:
    """A class without ``model_config`` yields ``()``."""
    assert model_config_doc(Point) == ()  # type: ignore[arg-type]
