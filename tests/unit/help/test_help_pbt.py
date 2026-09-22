"""Property-based tests for the built-in help package (``_internal/help``).

Properties verified in this file:

- **Parser round trip** (``docstrings.parse_docstring``): a docstring built
  from random section texts parses back to those texts unchanged, and the
  parser never raises on arbitrary input.
- **Model serialization** (``models.HelpEntry.to_dict``): ``to_dict()`` never
  raises, is deterministic, and its output is JSON-serializable for random
  entries.
- **Resolve idempotence** (``resolve.resolve``): every export round-trips
  through its ``qualname``; random text raises nothing except
  ``HelpLookupError``; ``parse_query`` never raises.
- **Search invariants** (``search.search``): hits are case-insensitive, name
  hits shrink as the needle grows, every hit contains the needle in the
  field its ``matched_on`` names, and ``limit`` is never exceeded.

Later phases append their own sections here (``format_type`` idempotence,
resolve idempotence, search invariants). Keep each section under its own
banner comment.

Hypothesis profile defaults to 100 examples (``just test``); CI uses 200
(``just test-ci``); fast iteration uses 10 (``just test-pbt-dev``).
"""

from __future__ import annotations

import inspect
import json
import string
import typing
from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

import mixpanel_headless as mp
from mixpanel_headless import HelpLookupError
from mixpanel_headless._internal.help.docstrings import first_line, parse_docstring
from mixpanel_headless._internal.help.introspect import format_type
from mixpanel_headless._internal.help.models import (
    HELP_KINDS,
    MEMBER_KINDS,
    PARAM_KINDS,
    DocSections,
    FieldDoc,
    Group,
    HelpEntry,
    Hint,
    MemberDoc,
    ParamDoc,
    SearchHit,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)
from mixpanel_headless._internal.help.render import _signature_block
from mixpanel_headless._internal.help.resolve import parse_query, resolve
from mixpanel_headless._internal.help.search import search

# =============================================================================
# Strategies — docstring building blocks
# =============================================================================

# Words never contain ":" so no generated line can match a section header.
_WORD = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=8)
_LINE = st.lists(_WORD, min_size=1, max_size=6).map(" ".join)
_PARAGRAPH = st.lists(_LINE, min_size=1, max_size=4)
_PARAGRAPHS = st.lists(_PARAGRAPH, min_size=1, max_size=3)
_IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True)
_EXC_NAME = st.from_regex(r"[A-Z][a-zA-Z]{0,8}Error", fullmatch=True)


@dataclass(frozen=True)
class _DocSpec:
    """Ingredients of one generated docstring plus the parse result we expect.

    Attributes:
        header_indent: Number of spaces before every section header.
        paragraphs: Body paragraphs, each a list of lines.
        args: ``(name, description_lines)`` pairs for the ``Args:`` section.
        returns: Paragraphs for ``Returns:`` (empty list means no section).
        raises: ``(exception, description_lines)`` pairs for ``Raises:``.
        example: Example lines with their relative indent (empty means none).
        notes: Paragraphs for ``Note:`` (empty list means no section).
    """

    header_indent: int
    paragraphs: list[list[str]]
    args: list[tuple[str, list[str]]]
    returns: list[list[str]]
    raises: list[tuple[str, list[str]]]
    example: list[str]
    notes: list[list[str]]

    def render(self) -> str:
        """Build the docstring text in Google style.

        Returns:
            The docstring, with headers at ``header_indent`` and content four
            spaces deeper.
        """
        pad = " " * self.header_indent
        content = pad + "    "
        out: list[str] = []
        for paragraph in self.paragraphs:
            out.extend(paragraph)
            out.append("")
        if self.args:
            out.append(f"{pad}Args:")
            for name, lines in self.args:
                out.append(f"{content}{name}: {lines[0]}")
                out.extend(f"{content}    {line}" for line in lines[1:])
            out.append("")
        if self.returns:
            out.append(f"{pad}Returns:")
            out.extend(_indent_paragraphs(self.returns, content))
            out.append("")
        if self.raises:
            out.append(f"{pad}Raises:")
            for name, lines in self.raises:
                out.append(f"{content}{name}: {lines[0]}")
                out.extend(f"{content}    {line}" for line in lines[1:])
            out.append("")
        if self.example:
            out.append(f"{pad}Example:")
            out.extend(f"{content}{line}" for line in self.example)
            out.append("")
        if self.notes:
            out.append(f"{pad}Note:")
            out.extend(_indent_paragraphs(self.notes, content))
            out.append("")
        return "\n".join(out)

    def expected(self) -> DocSections:
        """Return the ``DocSections`` the parser must produce for ``render()``.

        Returns:
            The expected parse result.
        """
        return DocSections(
            summary=" ".join(self.paragraphs[0]),
            body=_join_paragraphs(self.paragraphs),
            args=tuple((name, " ".join(lines)) for name, lines in self.args),
            returns=_join_paragraphs(self.returns),
            raises=tuple((name, " ".join(lines)) for name, lines in self.raises),
            example="\n".join(self.example),
            notes=_join_paragraphs(self.notes),
        )


def _join_paragraphs(paragraphs: list[list[str]]) -> str:
    """Join paragraphs with one blank line between them.

    Args:
        paragraphs: Paragraphs, each a list of lines.

    Returns:
        The joined text, or an empty string when there are no paragraphs.
    """
    return "\n\n".join("\n".join(lines) for lines in paragraphs)


def _indent_paragraphs(paragraphs: list[list[str]], prefix: str) -> list[str]:
    """Indent paragraphs by ``prefix`` and separate them with blank lines.

    Args:
        paragraphs: Paragraphs, each a list of lines.
        prefix: Indentation prefix for every non-blank line.

    Returns:
        The indented lines.
    """
    out: list[str] = []
    for index, lines in enumerate(paragraphs):
        if index:
            out.append("")
        out.extend(prefix + line for line in lines)
    return out


def _example_lines() -> st.SearchStrategy[list[str]]:
    """Strategy for example lines whose first line has no extra indent.

    Returns:
        A strategy producing zero or more lines; later lines carry an extra
        indent of 0 or 4 spaces so dedent must keep relative indentation.
    """
    extra = st.sampled_from(["", "    "])
    rest = st.lists(
        st.tuples(extra, _LINE).map(lambda pair: pair[0] + pair[1]), max_size=4
    )
    return st.one_of(
        st.just([]),
        st.tuples(_LINE, rest).map(lambda pair: [pair[0], *pair[1]]),
    )


def _unique_pairs(
    names: st.SearchStrategy[str],
) -> st.SearchStrategy[list[tuple[str, list[str]]]]:
    """Strategy for ``(name, description_lines)`` pairs with unique names.

    Args:
        names: Strategy for the item names.

    Returns:
        A strategy producing zero to four pairs.
    """
    return st.lists(
        st.tuples(names, st.lists(_LINE, min_size=1, max_size=3)),
        max_size=4,
        unique_by=lambda pair: pair[0],
    )


_DOC_SPECS = st.builds(
    _DocSpec,
    header_indent=st.sampled_from([0, 4]),
    paragraphs=_PARAGRAPHS,
    args=_unique_pairs(_IDENT),
    returns=st.lists(_PARAGRAPH, max_size=2),
    raises=_unique_pairs(_EXC_NAME),
    example=_example_lines(),
    notes=st.lists(_PARAGRAPH, max_size=2),
)


# =============================================================================
# Parser round trip
# =============================================================================


@given(spec=_DOC_SPECS)
def test_parse_docstring_round_trips_generated_sections(spec: _DocSpec) -> None:
    """A docstring built from random sections parses back to those sections.

    Args:
        spec: Generated docstring ingredients.
    """
    assert parse_docstring(spec.render()) == spec.expected()


@given(spec=_DOC_SPECS)
def test_parse_docstring_matches_cleandoc_form(spec: _DocSpec) -> None:
    """Parsing the raw text and its ``inspect.cleandoc`` form gives the same result.

    Args:
        spec: Generated docstring ingredients.
    """
    raw = spec.render()
    assert parse_docstring(raw) == parse_docstring(inspect.cleandoc(raw))


@given(spec=_DOC_SPECS)
def test_body_reparses_to_itself(spec: _DocSpec) -> None:
    """Parsing ``body`` alone yields the same summary and body and nothing else.

    Args:
        spec: Generated docstring ingredients.
    """
    parsed = parse_docstring(spec.render())
    again = parse_docstring(parsed.body)
    assert again == DocSections(summary=parsed.summary, body=parsed.body)


@given(spec=_DOC_SPECS)
def test_first_line_is_first_summary_line(spec: _DocSpec) -> None:
    """``first_line`` returns the first physical line of the generated body.

    Args:
        spec: Generated docstring ingredients.
    """
    assert first_line(spec.render()) == spec.paragraphs[0][0]


@given(doc=st.one_of(st.none(), st.text()))
def test_parse_docstring_never_raises(doc: str | None) -> None:
    """``parse_docstring`` and ``first_line`` accept any text without raising.

    Args:
        doc: Arbitrary docstring input.
    """
    result = parse_docstring(doc)
    assert isinstance(result, DocSections)
    assert isinstance(first_line(doc), str)
    for name, description in (*result.args, *result.raises):
        assert name
        assert "\n" not in description


# =============================================================================
# Model serialization
# =============================================================================

_KIND = st.sampled_from(HELP_KINDS)
_MEMBER_KIND = st.sampled_from(MEMBER_KINDS)
_STR = st.text(max_size=20)
_OPT_STR = st.one_of(st.none(), _STR)
_STRS = st.lists(_STR, max_size=3).map(tuple)
_PAIRS = st.lists(st.tuples(_STR, _STR), max_size=3).map(tuple)

_PARAM_DOCS = st.builds(
    ParamDoc,
    name=_STR,
    annotation=_STR,
    default=_OPT_STR,
    description=_STR,
    values=_STRS,
    kind=st.sampled_from(PARAM_KINDS),
)
_SIGNATURES = st.builds(
    SignatureDoc,
    name=_STR,
    params=st.lists(_PARAM_DOCS, max_size=3).map(tuple),
    returns=_OPT_STR,
)
_CALLABLE_MEMBER_KINDS = frozenset({"method", "function"})


@st.composite
def _field_docs(draw: st.DrawFn) -> FieldDoc:
    """Draw a ``FieldDoc`` whose ``required`` flag agrees with its default.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A ``FieldDoc``; required fields never carry a default.
    """
    required = draw(st.booleans())
    default = None if required else draw(_OPT_STR)
    return FieldDoc(
        name=draw(_STR),
        annotation=draw(_STR),
        default=default,
        required=required,
        constraints=draw(_STRS),
        alias=draw(_OPT_STR),
        values=draw(_STRS),
        description=draw(_STR),
    )


@st.composite
def _member_docs(draw: st.DrawFn) -> MemberDoc:
    """Draw a ``MemberDoc`` whose signature agrees with its kind.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A ``MemberDoc``; only ``method`` / ``function`` members carry a signature.
    """
    kind = draw(_MEMBER_KIND)
    signature = draw(_SIGNATURES) if kind in _CALLABLE_MEMBER_KINDS else None
    return MemberDoc(
        name=draw(_STR),
        kind=kind,
        summary=draw(_STR),
        signature=signature,
        depth=draw(st.integers(min_value=0, max_value=3)),
    )


_FIELD_DOCS = _field_docs()
_MEMBER_DOCS = _member_docs()
_MEMBERS = st.lists(_MEMBER_DOCS, max_size=3).map(tuple)
_DOC_SECTIONS = st.builds(
    DocSections,
    summary=_STR,
    body=_STR,
    args=_PAIRS,
    returns=_STR,
    raises=_PAIRS,
    example=_STR,
    notes=_STR,
)
_HELP_ENTRIES = st.builds(
    HelpEntry,
    kind=_KIND,
    name=_STR,
    qualname=_STR,
    summary=_STR,
    doc=_DOC_SECTIONS,
    signature=st.one_of(st.none(), _SIGNATURES),
    bases=_STRS,
    config=_PAIRS,
    construction=_MEMBERS,
    fields=st.lists(_FIELD_DOCS, max_size=3).map(tuple),
    properties=_MEMBERS,
    methods=_MEMBERS,
    values=_STRS,
    groups=st.lists(st.builds(Group, title=_STR, items=_MEMBERS), max_size=2).map(
        tuple
    ),
    referenced_types=_PAIRS,
    used_by=st.lists(st.builds(UsageDoc, method=_STR, params=_STRS), max_size=3).map(
        tuple
    ),
    see_also=_STRS,
    hints=st.lists(st.builds(Hint, title=_STR, url=_STR), max_size=2).map(tuple),
)
_SEARCH_RESULTS = st.builds(
    SearchResult,
    term=_STR,
    hits=st.lists(
        st.builds(
            SearchHit,
            category=_MEMBER_KIND,
            name=_STR,
            summary=_STR,
            matched_on=st.sampled_from(["name", "doc", "member"]),
        ),
        max_size=3,
    ).map(tuple),
    suggestions=_STRS,
)


@given(entry=_HELP_ENTRIES)
def test_help_entry_to_dict_is_json_serializable(entry: HelpEntry) -> None:
    """``HelpEntry.to_dict()`` never raises and round-trips through JSON.

    Args:
        entry: A random ``HelpEntry``.
    """
    payload = entry.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload == entry.to_dict()
    assert payload["kind"] == entry.kind
    assert isinstance(hash(entry), int)


@given(result=_SEARCH_RESULTS)
def test_search_result_to_dict_is_json_serializable(result: SearchResult) -> None:
    """``SearchResult.to_dict()`` never raises and round-trips through JSON.

    Args:
        result: A random ``SearchResult``.
    """
    payload = result.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert len(payload["hits"]) == len(result.hits)  # type: ignore[arg-type]
    assert isinstance(hash(result), int)


# =============================================================================
# Signature separators
# =============================================================================

_SIG_PARAM_DOCS = st.builds(
    ParamDoc,
    name=_IDENT,
    annotation=_WORD,
    default=st.one_of(st.none(), _WORD),
    kind=st.sampled_from(PARAM_KINDS),
)
_IDENT_SIGNATURES = st.builds(
    SignatureDoc,
    name=_IDENT,
    params=st.lists(_SIG_PARAM_DOCS, min_size=1, max_size=6).map(tuple),
    returns=st.one_of(st.none(), _WORD),
)


@given(sig=_IDENT_SIGNATURES)
def test_signature_block_separator_invariants(sig: SignatureDoc) -> None:
    """The ``*`` and ``/`` markers follow the parameter kinds exactly.

    A bare ``*`` appears at most once, only before a keyword-only parameter,
    and never when a ``*args`` parameter precedes the keyword-only section. A
    ``/`` appears only directly after a positional-only parameter, and every
    positional-only run is closed by exactly one ``/``.

    Args:
        sig: A random signature with identifier names and mixed kinds.
    """
    lines = _signature_block(sig.name, sig)
    items = [line.strip().rstrip(",") for line in lines[1:-1]]
    kinds = [p.kind for p in sig.params]
    star_lines = [i for i, item in enumerate(items) if item == "*"]
    slash_lines = [i for i, item in enumerate(items) if item == "/"]
    assert len(items) == len(sig.params) + len(star_lines) + len(slash_lines)
    assert len(star_lines) <= 1
    first_kw = next((i for i, k in enumerate(kinds) if k == "keyword_only"), None)
    star_before_kw = first_kw is not None and "var_positional" in kinds[:first_kw]
    assert bool(star_lines) == (first_kw is not None and not star_before_kw)
    positional_only_count = kinds.count("positional_only")
    if positional_only_count:
        assert slash_lines
        for index in slash_lines:
            assert items[index - 1].split(":")[0].split(" =")[0] in {
                p.name for p in sig.params if p.kind == "positional_only"
            }
    else:
        assert not slash_lines
    assert not lines[-2].endswith(",")


# =============================================================================
# format_type
# =============================================================================

_TYPE_ATOMS = st.sampled_from(
    [
        "int",
        "str",
        "None",
        "NoneType",
        "typing.Any",
        "typing_extensions.Literal['a', 'b']",
        "Literal['timeseries', 'total']",
        "<class 'int'>",
        "<class 'mixpanel_headless.types.Filter'>",
        "mixpanel_headless.types.Filter",
        "mixpanel_headless._internal.auth.account.Account",
        "collections.abc.Sequence",
        "ForwardRef('Filter')",
        "'Filter'",
        "MathType",
        "OptionalThing",
    ]
)
"""Leaf annotation texts: names, noisy names, and quoted forward references."""

_TYPE_WRAPPERS = st.sampled_from(
    ["list", "dict", "Sequence", "typing.Optional", "Optional", "typing.Union", "Union"]
)
"""Generic and union wrappers that the cleaner must rewrite or keep."""


def _wrap(children: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    """Extend leaf annotation texts with generics and pipe unions.

    Args:
        children: Strategy for already-built annotation texts.

    Returns:
        A strategy producing ``Wrapper[a, b]`` and ``a | b`` forms.
    """
    generic = st.tuples(_TYPE_WRAPPERS, st.lists(children, min_size=1, max_size=3)).map(
        lambda pair: f"{pair[0]}[{', '.join(pair[1])}]"
    )
    union = st.lists(children, min_size=2, max_size=3).map(" | ".join)
    return st.one_of(generic, union)


_ANNOTATION_TEXTS = st.recursive(_TYPE_ATOMS, _wrap, max_leaves=8)
"""Annotation strings in the shapes ``inspect.signature`` and ``str(hint)`` produce."""


def _real_annotations() -> list[object]:
    """Collect every parameter and return annotation from ``Workspace`` members.

    Returns:
        Source annotations (strings under ``from __future__ import annotations``)
        plus the resolved hint objects, without duplicates by ``repr``.
    """
    seen: dict[str, object] = {}
    for name, member in vars(mp.Workspace).items():
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        signature = inspect.signature(member)
        for param in signature.parameters.values():
            if param.annotation is not inspect.Parameter.empty:
                seen.setdefault(repr(param.annotation), param.annotation)
        if signature.return_annotation is not inspect.Signature.empty:
            seen.setdefault(
                repr(signature.return_annotation), signature.return_annotation
            )
        try:
            hints = typing.get_type_hints(member, include_extras=True)
        except Exception:  # noqa: BLE001 - TYPE_CHECKING-only names are expected
            continue
        for hint in hints.values():
            seen.setdefault(repr(hint), hint)
    return list(seen.values())


_REAL_ANNOTATIONS = st.sampled_from(_real_annotations())
"""Real annotations drawn from the library's ``Workspace`` methods."""


def _assert_clean(text: str) -> None:
    """Assert a ``format_type`` result carries no module-prefix or repr noise.

    Args:
        text: Output of ``format_type``.
    """
    assert "typing." not in text
    assert "typing_extensions." not in text
    assert "<class" not in text
    assert "NoneType" not in text
    assert "ForwardRef(" not in text


@given(text=_ANNOTATION_TEXTS)
def test_format_type_strips_noise_from_annotation_texts(text: str) -> None:
    """Generated annotation strings come out clean and idempotent.

    Args:
        text: A generated annotation string.
    """
    once = format_type(text)
    _assert_clean(once)
    assert format_type(once) == once


@given(text=st.text(max_size=60))
def test_format_type_is_idempotent_on_arbitrary_text(text: str) -> None:
    """``format_type(format_type(x)) == format_type(x)`` for any string.

    Args:
        text: Arbitrary text.
    """
    once = format_type(text)
    assert isinstance(once, str)
    assert format_type(once) == once


@given(annotation=_REAL_ANNOTATIONS)
def test_format_type_real_workspace_annotations(annotation: object) -> None:
    """Real ``Workspace`` annotations (source strings and resolved hints) are clean.

    Args:
        annotation: A source annotation or resolved hint from a ``Workspace`` method.
    """
    once = format_type(annotation)
    assert once
    _assert_clean(once)
    assert format_type(once) == once


# =============================================================================
# resolve
# =============================================================================

_INVENTORY_NAMES = st.sampled_from(sorted(set(mp.__all__)))
_DOTTED = st.from_regex(r"[A-Za-z_.]{1,30}", fullmatch=True)


@given(name=_INVENTORY_NAMES)
def test_resolve_qualname_round_trips_for_every_export(name: str) -> None:
    """``resolve(resolve(name).qualname)`` gives back the same target.

    Args:
        name: An ``__all__`` entry.
    """
    first = resolve(name)
    assert first.qualname == name
    second = resolve(first.qualname)
    assert second == first
    assert second.obj is first.obj


@given(name=_INVENTORY_NAMES)
def test_resolve_object_form_matches_string_form(name: str) -> None:
    """Passing the exported object gives the same target as its name.

    Objects that are not classes, functions, or modules (Literal aliases,
    unions, constants) have no identity-based object form and are skipped.

    Args:
        name: An ``__all__`` entry.
    """
    obj = getattr(mp, name)
    if not (isinstance(obj, type) or inspect.isroutine(obj) or inspect.ismodule(obj)):
        return
    assert resolve(obj) == resolve(name)


@given(text=_DOTTED)
def test_resolve_dotted_text_raises_only_help_lookup_error(text: str) -> None:
    """Random dotted paths either resolve or raise ``HelpLookupError``.

    Args:
        text: Random text over letters, underscores, and dots.
    """
    try:
        target = resolve(text)
    except HelpLookupError as exc:
        assert exc.query == text
        assert exc.hits == ()
        assert len(exc.suggestions) <= 5
    else:
        assert target.kind in HELP_KINDS


@given(text=st.text(max_size=40))
def test_resolve_arbitrary_text_raises_only_help_lookup_error(text: str) -> None:
    """Arbitrary text never raises anything except ``HelpLookupError``.

    Args:
        text: Arbitrary text.
    """
    try:
        target = resolve(text)
    except HelpLookupError:
        return
    assert target.kind in HELP_KINDS


@given(text=st.text(max_size=40))
def test_parse_query_never_raises_and_returns_a_mode(text: str) -> None:
    """``parse_query`` accepts any text and returns a known mode and a payload.

    Args:
        text: Arbitrary text.
    """
    mode, payload = parse_query(text)
    assert mode in {"overview", "search", "describe"}
    assert payload == payload.strip()
    if mode == "overview":
        assert payload == ""


# =============================================================================
# search
# =============================================================================

_ASCII_TERMS = st.text(alphabet=string.ascii_letters, min_size=1, max_size=6)
"""Random ASCII-letter needles; ASCII keeps ``upper()`` / ``lower()`` a bijection."""

_ASCII_SUFFIXES = st.text(alphabet=string.ascii_letters + "_", min_size=1, max_size=3)
"""Random suffixes appended to a needle for the monotonicity property."""


@given(term=_ASCII_TERMS)
def test_search_hits_are_case_insensitive(term: str) -> None:
    """``search(t)`` and ``search(t.upper())`` return the same hits.

    Only ``hits`` are compared: ``term`` echoes the caller's text and
    ``suggestions`` come from case-sensitive ``difflib`` on a miss.

    Args:
        term: A random ASCII-letter needle.
    """
    assert search(term).hits == search(term.upper()).hits
    assert search(term).hits == search(term.lower()).hits


@given(term=_ASCII_TERMS, suffix=_ASCII_SUFFIXES)
def test_search_name_hits_shrink_when_the_needle_grows(term: str, suffix: str) -> None:
    """Name hits for ``t + s`` are a subset of the name hits for ``t``.

    Args:
        term: A random ASCII-letter needle.
        suffix: Random text appended to the needle.
    """
    longer = {h.name for h in search(term + suffix).hits if h.matched_on == "name"}
    shorter = {h.name for h in search(term).hits if h.matched_on == "name"}
    assert longer <= shorter


@given(term=_ASCII_TERMS)
def test_search_every_hit_contains_the_needle(term: str) -> None:
    """Each hit carries the needle in the field its ``matched_on`` names.

    A ``name`` hit has it in ``name``; a ``doc`` hit has it in ``summary``
    but not in ``name``; a ``member`` hit has it in the member text stored
    in ``summary`` and in neither ``name`` nor the entry's own doc line.

    Args:
        term: A random ASCII-letter needle.
    """
    needle = term.lower()
    result = search(term)
    keys = [(h.category, h.name) for h in result.hits]
    assert len(keys) == len(set(keys))
    for hit in result.hits:
        if hit.matched_on == "name":
            assert needle in hit.name.lower()
        else:
            assert needle not in hit.name.lower()
            assert needle in hit.summary.lower()
            if hit.matched_on == "member":
                assert hit.summary.startswith(("member ", "value "))
    if not result.hits:
        assert len(result.suggestions) <= 5


@given(term=_ASCII_TERMS, limit=st.integers(min_value=0, max_value=30))
def test_search_limit_is_never_exceeded(term: str, limit: int) -> None:
    """``limit`` bounds the hit count and keeps the untruncated prefix.

    Args:
        term: A random ASCII-letter needle.
        limit: A non-negative cap.
    """
    full = search(term)
    capped = search(term, limit=limit)
    assert len(capped.hits) <= limit
    assert capped.hits == full.hits[:limit]
    assert capped.term == full.term
