"""Unit tests for ``mixpanel_headless._internal.help.models``.

The models are frozen ``slots=True`` dataclasses. These tests lock:

- ``to_dict()`` output shape for every model (tuples become lists, nested
  models convert recursively, output is JSON-serializable);
- immutability (assignment raises ``FrozenInstanceError``) and hashability;
- the defaults that let callers build partial ``HelpEntry`` values;
- the construction invariants: ``MemberDoc`` rejects unknown kinds and a
  kind / signature mismatch, ``FieldDoc`` rejects a required field with a
  default;
- the ``EXPORT_KINDS`` / ``MEMBER_KINDS`` / ``HELP_KINDS`` / ``HELP_FORMATS``
  runtime constants and how each kind tuple extends the previous one.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from typing import get_args

import pytest

from mixpanel_headless._internal.help.models import (
    EXPORT_KINDS,
    HELP_FORMATS,
    HELP_KINDS,
    MEMBER_KINDS,
    PARAM_KINDS,
    DocSections,
    ExportKind,
    FieldDoc,
    Group,
    HelpEntry,
    HelpFormat,
    HelpKind,
    Hint,
    MemberDoc,
    MemberKind,
    ParamDoc,
    ParamKind,
    SearchHit,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def param() -> ParamDoc:
    """Return a ``ParamDoc`` with every field populated.

    Returns:
        A ``ParamDoc`` for an ``events`` parameter with two literal values.
    """
    return ParamDoc(
        name="events",
        annotation="str | Metric",
        default=None,
        description="Event name(s) to query.",
        values=("total", "unique"),
    )


@pytest.fixture
def signature(param: ParamDoc) -> SignatureDoc:
    """Return a ``SignatureDoc`` wrapping the ``param`` fixture.

    Args:
        param: The single parameter of the signature.

    Returns:
        A ``SignatureDoc`` named ``query`` returning ``QueryResult``.
    """
    return SignatureDoc(name="query", params=(param,), returns="QueryResult")


@pytest.fixture
def field() -> FieldDoc:
    """Return a ``FieldDoc`` with constraints, alias, and values.

    Returns:
        A fully populated ``FieldDoc``.
    """
    return FieldDoc(
        name="title",
        annotation="str",
        default=None,
        required=True,
        constraints=("max_length=255",),
        alias="dashboardTitle",
        values=("a", "b"),
        description="Dashboard title.",
    )


@pytest.fixture
def member(signature: SignatureDoc) -> MemberDoc:
    """Return a ``MemberDoc`` for a method with a signature.

    Args:
        signature: The signature attached to the member.

    Returns:
        A ``MemberDoc`` of kind ``method``.
    """
    return MemberDoc(
        name="query", kind="method", summary="Run a query.", signature=signature
    )


@pytest.fixture
def sections() -> DocSections:
    """Return a ``DocSections`` with every section populated.

    Returns:
        A fully populated ``DocSections``.
    """
    return DocSections(
        summary="Run a query.",
        body="Run a query.\n\nMore detail.",
        args=(("events", "Event names."), ("where", "Filter.")),
        returns="A QueryResult.",
        raises=(("QueryError", "On 400."),),
        example="```python\nws.query()\n```",
        notes="Be careful.",
    )


@pytest.fixture
def entry(
    signature: SignatureDoc,
    field: FieldDoc,
    member: MemberDoc,
    sections: DocSections,
) -> HelpEntry:
    """Return a ``HelpEntry`` with every collection populated.

    Args:
        signature: Signature for the entry.
        field: One field for ``fields``.
        member: One member for ``construction``, ``properties``, ``methods``, and groups.
        sections: Parsed docstring sections.

    Returns:
        A fully populated ``HelpEntry`` of kind ``class``.
    """
    return HelpEntry(
        kind="class",
        name="Filter",
        qualname="mixpanel_headless.Filter",
        summary="A filter.",
        doc=sections,
        signature=signature,
        bases=("object",),
        config=(("frozen", "True"),),
        construction=(member,),
        fields=(field,),
        properties=(member,),
        methods=(member,),
        values=("x", "y"),
        groups=(Group(title="Discovery", items=(member,)),),
        referenced_types=(("QueryResult", "Result of a query."),),
        used_by=(UsageDoc(method="query", params=("where",)),),
        see_also=("FrequencyFilter",),
        hints=(Hint(title="Guide", url="https://example.invalid/guide"),),
    )


# =============================================================================
# Constants
# =============================================================================


def test_export_kinds_matches_literal() -> None:
    """``EXPORT_KINDS`` holds exactly the ``ExportKind`` literal members, in order."""
    assert get_args(ExportKind) == EXPORT_KINDS
    assert set(EXPORT_KINDS) == {
        "module",
        "exception",
        "enum",
        "model",
        "dataclass",
        "class",
        "literal",
        "alias",
        "function",
        "constant",
    }
    assert len(EXPORT_KINDS) == len(set(EXPORT_KINDS))


def test_member_kinds_extends_export_kinds() -> None:
    """``MEMBER_KINDS`` is ``EXPORT_KINDS`` plus the two class-member kinds."""
    assert get_args(MemberKind) == MEMBER_KINDS
    assert (*EXPORT_KINDS, "method", "property") == MEMBER_KINDS


def test_help_kinds_extends_member_kinds() -> None:
    """``HELP_KINDS`` is ``MEMBER_KINDS`` plus the three entry-only kinds, and no ``search``."""
    assert get_args(HelpKind) == HELP_KINDS
    assert (*MEMBER_KINDS, "overview", "listing", "parameter") == HELP_KINDS
    assert "search" not in HELP_KINDS
    assert len(HELP_KINDS) == len(set(HELP_KINDS))


def test_help_formats_matches_literal() -> None:
    """``HELP_FORMATS`` holds exactly ``text``, ``markdown``, and ``json``."""
    assert get_args(HelpFormat) == HELP_FORMATS
    assert HELP_FORMATS == ("text", "markdown", "json")


def test_param_kinds_matches_literal() -> None:
    """``PARAM_KINDS`` holds the five ``inspect.Parameter`` kinds in declaration order."""
    assert get_args(ParamKind) == PARAM_KINDS
    assert PARAM_KINDS == (
        "positional_only",
        "positional_or_keyword",
        "var_positional",
        "keyword_only",
        "var_keyword",
    )


# =============================================================================
# to_dict() — leaf models
# =============================================================================


def test_hint_to_dict() -> None:
    """``Hint.to_dict()`` returns the two string fields."""
    hint = Hint(title="Guide", url="https://example.invalid")
    assert hint.to_dict() == {"title": "Guide", "url": "https://example.invalid"}


def test_param_doc_to_dict(param: ParamDoc) -> None:
    """``ParamDoc.to_dict()`` turns ``values`` into a list, keeps ``None``, and emits ``kind``."""
    assert param.to_dict() == {
        "name": "events",
        "annotation": "str | Metric",
        "default": None,
        "description": "Event name(s) to query.",
        "values": ["total", "unique"],
        "kind": "positional_or_keyword",
    }


def test_param_doc_to_dict_keyword_only_kind() -> None:
    """A keyword-only ``ParamDoc`` reports ``kind == "keyword_only"`` in ``to_dict()``."""
    param = ParamDoc(name="from_date", annotation="str", kind="keyword_only")
    assert param.kind == "keyword_only"
    assert param.to_dict()["kind"] == "keyword_only"


def test_signature_doc_to_dict(signature: SignatureDoc, param: ParamDoc) -> None:
    """``SignatureDoc.to_dict()`` converts nested params recursively."""
    assert signature.to_dict() == {
        "name": "query",
        "params": [param.to_dict()],
        "returns": "QueryResult",
    }


def test_field_doc_to_dict(field: FieldDoc) -> None:
    """``FieldDoc.to_dict()`` emits every field with lists for tuples."""
    assert field.to_dict() == {
        "name": "title",
        "annotation": "str",
        "default": None,
        "required": True,
        "constraints": ["max_length=255"],
        "alias": "dashboardTitle",
        "values": ["a", "b"],
        "description": "Dashboard title.",
    }


def test_member_doc_to_dict_with_signature(
    member: MemberDoc, signature: SignatureDoc
) -> None:
    """``MemberDoc.to_dict()`` nests the signature dict."""
    assert member.to_dict() == {
        "name": "query",
        "kind": "method",
        "summary": "Run a query.",
        "signature": signature.to_dict(),
    }


def test_member_doc_to_dict_without_signature() -> None:
    """``MemberDoc.to_dict()`` emits ``None`` when there is no signature."""
    member = MemberDoc(
        name="events", kind="property", summary="Events.", signature=None
    )
    assert member.to_dict()["signature"] is None


def test_group_to_dict(member: MemberDoc) -> None:
    """``Group.to_dict()`` converts its items recursively."""
    group = Group(title="Discovery", items=(member, member))
    result = group.to_dict()
    assert result["title"] == "Discovery"
    assert result["items"] == [member.to_dict(), member.to_dict()]


def test_usage_doc_to_dict() -> None:
    """``UsageDoc.to_dict()`` turns ``params`` into a list."""
    usage = UsageDoc(method="query", params=("math", "where"))
    assert usage.to_dict() == {"method": "query", "params": ["math", "where"]}


def test_doc_sections_to_dict(sections: DocSections) -> None:
    """``DocSections.to_dict()`` turns pair tuples into two-item lists."""
    assert sections.to_dict() == {
        "summary": "Run a query.",
        "body": "Run a query.\n\nMore detail.",
        "args": [["events", "Event names."], ["where", "Filter."]],
        "returns": "A QueryResult.",
        "raises": [["QueryError", "On 400."]],
        "example": "```python\nws.query()\n```",
        "notes": "Be careful.",
    }


def test_search_hit_to_dict() -> None:
    """``SearchHit.to_dict()`` emits the four scalar fields."""
    hit = SearchHit(
        category="method", name="Workspace.query", summary="Run.", matched_on="name"
    )
    assert hit.to_dict() == {
        "category": "method",
        "name": "Workspace.query",
        "summary": "Run.",
        "matched_on": "name",
    }


def test_search_result_to_dict() -> None:
    """``SearchResult.to_dict()`` nests hits and lists suggestions."""
    hit = SearchHit(
        category="model", name="Cohort", summary="A cohort.", matched_on="doc"
    )
    result = SearchResult(term="cohort", hits=(hit,), suggestions=("Cohorts",))
    assert result.to_dict() == {
        "term": "cohort",
        "hits": [hit.to_dict()],
        "suggestions": ["Cohorts"],
    }


# =============================================================================
# to_dict() — HelpEntry
# =============================================================================


def test_help_entry_to_dict_keys(entry: HelpEntry) -> None:
    """``HelpEntry.to_dict()`` emits one key per dataclass field, in field order."""
    expected = [f.name for f in dataclasses.fields(HelpEntry)]
    assert list(entry.to_dict().keys()) == expected


def test_help_entry_to_dict_nested(
    entry: HelpEntry,
    signature: SignatureDoc,
    field: FieldDoc,
    member: MemberDoc,
    sections: DocSections,
) -> None:
    """``HelpEntry.to_dict()`` converts every nested model and tuple."""
    result = entry.to_dict()
    assert result["kind"] == "class"
    assert result["name"] == "Filter"
    assert result["qualname"] == "mixpanel_headless.Filter"
    assert result["summary"] == "A filter."
    assert result["doc"] == sections.to_dict()
    assert result["signature"] == signature.to_dict()
    assert result["bases"] == ["object"]
    assert result["config"] == [["frozen", "True"]]
    assert result["construction"] == [member.to_dict()]
    assert result["fields"] == [field.to_dict()]
    assert result["properties"] == [member.to_dict()]
    assert result["methods"] == [member.to_dict()]
    assert result["values"] == ["x", "y"]
    assert result["groups"] == [{"title": "Discovery", "items": [member.to_dict()]}]
    assert result["referenced_types"] == [["QueryResult", "Result of a query."]]
    assert result["used_by"] == [{"method": "query", "params": ["where"]}]
    assert result["see_also"] == ["FrequencyFilter"]
    assert result["hints"] == [
        {"title": "Guide", "url": "https://example.invalid/guide"}
    ]


def test_help_entry_to_dict_is_json_serializable(entry: HelpEntry) -> None:
    """``json.dumps`` accepts the full ``to_dict()`` output and round-trips it."""
    payload = json.dumps(entry.to_dict())
    assert json.loads(payload) == entry.to_dict()


def test_search_result_to_dict_is_json_serializable() -> None:
    """``json.dumps`` accepts ``SearchResult.to_dict()``."""
    hit = SearchHit(category="enum", name="Region", summary="", matched_on="member")
    result = SearchResult(term="eu", hits=(hit,), suggestions=())
    assert json.loads(json.dumps(result.to_dict())) == result.to_dict()


# =============================================================================
# Defaults
# =============================================================================


def test_doc_sections_defaults() -> None:
    """``DocSections()`` with no arguments is all-empty."""
    empty = DocSections()
    assert empty.summary == ""
    assert empty.body == ""
    assert empty.args == ()
    assert empty.returns == ""
    assert empty.raises == ()
    assert empty.example == ""
    assert empty.notes == ""


def test_help_entry_minimal_defaults() -> None:
    """A ``HelpEntry`` built from the five required fields has empty collections."""
    entry = HelpEntry(
        kind="constant",
        name="DEFAULT_TIMEOUT",
        qualname="mixpanel_headless.DEFAULT_TIMEOUT",
        summary="Timeout.",
        doc=DocSections(summary="Timeout."),
    )
    assert entry.signature is None
    assert entry.bases == ()
    assert entry.config == ()
    assert entry.construction == ()
    assert entry.fields == ()
    assert entry.properties == ()
    assert entry.methods == ()
    assert entry.values == ()
    assert entry.groups == ()
    assert entry.referenced_types == ()
    assert entry.used_by == ()
    assert entry.see_also == ()
    assert entry.hints == ()


def test_help_entry_requires_core_fields() -> None:
    """``HelpEntry`` rejects construction without ``doc``."""
    with pytest.raises(TypeError):
        HelpEntry(kind="class", name="X", qualname="m.X", summary="")  # type: ignore[call-arg]


def test_param_doc_defaults() -> None:
    """``ParamDoc`` needs only ``name`` and ``annotation``; ``kind`` defaults to plain."""
    param = ParamDoc(name="x", annotation="int")
    assert param.default is None
    assert param.description == ""
    assert param.values == ()
    assert param.kind == "positional_or_keyword"


def test_signature_doc_defaults() -> None:
    """``SignatureDoc`` needs only ``name``."""
    sig = SignatureDoc(name="f")
    assert sig.params == ()
    assert sig.returns is None


def test_field_doc_defaults() -> None:
    """``FieldDoc`` needs only ``name`` and ``annotation``."""
    field = FieldDoc(name="x", annotation="int")
    assert field.default is None
    assert field.required is False
    assert field.constraints == ()
    assert field.alias is None
    assert field.values == ()
    assert field.description == ""


def test_member_doc_defaults() -> None:
    """``MemberDoc`` needs only ``name`` and ``kind``."""
    member = MemberDoc(name="x", kind="property")
    assert member.summary == ""
    assert member.signature is None


def test_search_result_defaults() -> None:
    """``SearchResult`` needs only ``term``."""
    result = SearchResult(term="x")
    assert result.hits == ()
    assert result.suggestions == ()


# =============================================================================
# Construction invariants
# =============================================================================

CALLABLE_MEMBER_KINDS: tuple[MemberKind, ...] = ("method", "function")
"""The member kinds that must carry a signature."""


def test_member_doc_rejects_unknown_kind() -> None:
    """A runtime kind outside ``MEMBER_KINDS`` raises ``ValueError``."""
    with pytest.raises(ValueError, match="Unknown member kind 'nonesuch'"):
        MemberDoc(name="x", kind=typing.cast("MemberKind", "nonesuch"))


@pytest.mark.parametrize("kind", CALLABLE_MEMBER_KINDS)
def test_member_doc_callable_kind_requires_signature(kind: MemberKind) -> None:
    """A ``method`` or ``function`` member without a signature raises ``ValueError``.

    Args:
        kind: One of the two callable member kinds.
    """
    with pytest.raises(ValueError, match=f"kind {kind!r} requires a signature"):
        MemberDoc(name="x", kind=kind)


@pytest.mark.parametrize(
    "kind", [k for k in MEMBER_KINDS if k not in CALLABLE_MEMBER_KINDS]
)
def test_member_doc_non_callable_kind_rejects_signature(kind: MemberKind) -> None:
    """Any other member kind with a signature raises ``ValueError``.

    Args:
        kind: A non-callable member kind.
    """
    with pytest.raises(ValueError, match=f"kind {kind!r} must not carry a signature"):
        MemberDoc(name="x", kind=kind, signature=SignatureDoc(name="x"))


@pytest.mark.parametrize("kind", MEMBER_KINDS)
def test_member_doc_accepts_every_kind_with_the_matching_signature(
    kind: MemberKind,
) -> None:
    """Every ``MemberKind`` constructs when the signature matches the kind.

    Args:
        kind: The member kind under test.
    """
    callable_kind = kind in CALLABLE_MEMBER_KINDS
    signature = SignatureDoc(name="x") if callable_kind else None
    member = MemberDoc(name="x", kind=kind, signature=signature)
    assert member.kind == kind
    assert (member.signature is not None) is callable_kind


def test_field_doc_rejects_required_with_default() -> None:
    """A required field that also has a default raises ``ValueError``."""
    with pytest.raises(ValueError, match="'x' is required but has default '1'"):
        FieldDoc(name="x", annotation="int", required=True, default="1")


def test_field_doc_accepts_consistent_required_and_default() -> None:
    """Required without a default, optional with one, and optional without one all construct."""
    assert FieldDoc(name="x", annotation="int", required=True).default is None
    assert FieldDoc(name="x", annotation="int", default="1").required is False
    assert FieldDoc(name="x", annotation="int").required is False


# =============================================================================
# Frozen and hashable
# =============================================================================


@pytest.mark.parametrize(
    ("instance", "attr"),
    [
        (Hint(title="t", url="u"), "title"),
        (ParamDoc(name="p", annotation="int"), "name"),
        (SignatureDoc(name="f"), "name"),
        (FieldDoc(name="f", annotation="int"), "name"),
        (MemberDoc(name="m", kind="method", signature=SignatureDoc(name="m")), "name"),
        (Group(title="g", items=()), "title"),
        (UsageDoc(method="m", params=()), "method"),
        (DocSections(), "summary"),
        (SearchHit(category="class", name="n", summary="", matched_on="name"), "name"),
        (SearchResult(term="t"), "term"),
    ],
    ids=lambda value: type(value).__name__ if not isinstance(value, str) else value,
)
def test_models_are_frozen(instance: object, attr: str) -> None:
    """Assigning to any field raises ``FrozenInstanceError``.

    Args:
        instance: A model instance.
        attr: A field name on that instance.
    """
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, attr, "changed")


def test_help_entry_is_frozen(entry: HelpEntry) -> None:
    """Assigning to a ``HelpEntry`` field raises ``FrozenInstanceError``."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.name = "Other"  # type: ignore[misc]


def test_models_use_slots() -> None:
    """Every model declares ``__slots__`` and has no ``__dict__``."""
    for cls in (
        Hint,
        ParamDoc,
        SignatureDoc,
        FieldDoc,
        MemberDoc,
        Group,
        UsageDoc,
        DocSections,
        HelpEntry,
        SearchHit,
        SearchResult,
    ):
        assert hasattr(cls, "__slots__"), cls.__name__
    assert not hasattr(DocSections(), "__dict__")


def test_help_entry_is_hashable_and_equal(entry: HelpEntry) -> None:
    """Equal entries hash equal and can be stored in a set."""
    twin = dataclasses.replace(entry)
    assert entry == twin
    assert hash(entry) == hash(twin)
    assert len({entry, twin}) == 1


def test_search_result_is_hashable() -> None:
    """``SearchResult`` with nested hits is hashable."""
    hit = SearchHit(category="class", name="Cohort", summary="", matched_on="name")
    result = SearchResult(term="cohort", hits=(hit,), suggestions=("a",))
    assert isinstance(hash(result), int)


def test_to_dict_returns_fresh_dict(entry: HelpEntry) -> None:
    """Each ``to_dict()`` call returns a new dict that callers may mutate."""
    first = entry.to_dict()
    first["name"] = "mutated"
    assert entry.to_dict()["name"] == "Filter"
