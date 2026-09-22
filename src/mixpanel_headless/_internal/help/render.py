"""Pure renderers for the built-in API reference.

Every function here maps a :class:`~.models.HelpEntry` or
:class:`~.models.SearchResult` to a string. There is no I/O, no Rich, and no
import from any help module other than :mod:`.models`. Output never contains
Rich markup, so the literal ``[property]`` and ``[method]`` tags survive when
the CLI prints through ``typer.echo``. Returned strings carry no trailing
newline; callers add one with ``print``.

Formats
-------

- ``text`` keeps the plugin script's shape (agents and the skill parse it
  visually): a multi-line signature block, Google sections, two-column rows
  padded to ``NAME_WIDTH``, ``Used by Workspace (N methods):`` rows, a
  ``See also`` line, and one ``---`` / ``Tip:`` / ``WebFetch(url=...)`` block
  per hint.
- ``markdown`` uses ``#`` for the entry title, ``##`` per section, fenced
  ``python`` blocks for signatures and examples, pipe tables where the text
  format has columns, and hints as links under ``## Further reading``.
- ``json`` is ``json.dumps(entry.to_dict(), indent=2)``.

Packing conventions the assembler must follow
----------------------------------------------

The model has no kind-specific fields, so a few kinds reuse generic slots:

- ``method`` / ``function``: ``signature`` holds the callable; ``entry.name``
  (the display name, e.g. ``Workspace.query``) is printed as the callable
  name. The domain shown in ``See also (<domain>):`` is the title of
  ``entry.groups[0]`` **when ``groups`` has exactly one group**; its items are
  not rendered in this view and may be empty. With zero or several groups the
  line is a plain ``See also: ...``.
- ``property``: ``signature`` is a ``SignatureDoc`` with no params whose
  ``returns`` is the property type; ``None`` prints the bare name.
- ``parameter``: ``signature.params`` holds exactly one ``ParamDoc`` (the
  parameter) and ``signature.name`` is the parent method. Allowed values come
  from ``entry.values``, falling back to ``ParamDoc.values``. The description
  comes from ``doc.body``, then ``doc.summary``, then ``entry.summary``,
  falling back to ``ParamDoc.description``.
- ``class`` / ``model`` / ``dataclass``: ``bases``, ``config``,
  ``construction``, ``fields``, ``properties``, ``methods``, ``used_by`` map
  one-to-one to sections. Construction rows print as
  ``<ClassName>.<factory>(params)`` under ``Construction (N):``; the
  factories are classmethods or staticmethods.
- ``enum``: each member is a ``FieldDoc(name=MEMBER, annotation=<value type>,
  default=repr(value))`` in ``fields``; ``values`` holds the member names.
  When ``fields`` is empty the table falls back to ``values`` (names only).
- ``literal``: ``values`` holds the allowed values in declaration order.
- ``alias``: ``values`` holds the member display names for the
  ``Name = A | B`` header; ``referenced_types`` holds ``(name, summary)``
  rows for members that are library types.
- ``exception``: ``bases[0]`` is the direct base shown in the header
  (``Exception`` when ``bases`` is empty). The subclass tree is one ``Group``
  titled ``"Subclasses"`` whose items carry their nesting in
  ``MemberDoc.depth``; the text format indents two spaces per level, the
  markdown table prints the bare name. ``used_by`` rows print under
  ``Raised by Workspace (N methods):`` and omit ``()`` when ``params`` is
  empty.
- ``module``: members come from ``groups`` when non-empty (one
  ``Title (N):`` block each), else from ``methods`` under ``Members (N):``.
- ``constant``: ``bases[0]`` is the type name and ``values[0]`` is the value
  display string; either may be absent.
- ``listing``: ``groups`` render as ``Title (N):`` blocks. Rows tag the
  summary with ``[property]`` or ``[method]`` when the member kind is one of
  those; other kinds print name and summary only. ``MemberDoc.depth`` nests
  an exception tree: the text format indents two spaces per level, the
  markdown table prints the bare name.
- ``overview``: ``summary`` is the version string printed after the name;
  ``doc.body`` is the grammar text; ``groups`` render as tables whose rows
  show the compact signature when a member has one.
- a ``SearchResult`` (no kind; it is not a ``HelpEntry``): hits render in the order given with
  ``[category ]`` padded to nine characters inside the brackets and a name
  column sized to the longest hit. A miss prints ``No matches for "term"``
  and then ``Did you mean?`` with ``suggestions`` when there are any.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Iterable, Sequence

from .models import (
    HELP_FORMATS,
    FieldDoc,
    Group,
    HelpEntry,
    HelpFormat,
    HelpKind,
    MemberDoc,
    ParamDoc,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)

NAME_WIDTH = 42
"""Column width for the name in two-column rows (matches the script's ``:42s``)."""

LINE_WIDTH = 88
"""Target maximum line width for wrapped value lists and argument descriptions."""

CATEGORY_WIDTH = 9
"""Width of the ``[category ]`` column in search rows (matches the script's ``:9s``)."""

_MEMBER_TAG_KINDS: frozenset[str] = frozenset({"property", "method"})
"""Member kinds whose listing rows carry a literal ``[kind]`` tag."""

Block = list[str]
"""A block of output lines; blocks are joined with one blank line between them."""


# =============================================================================
# Public dispatch
# =============================================================================


def render(entry: HelpEntry | SearchResult, format: HelpFormat = "text") -> str:
    """Render an entry or search result in the requested format.

    Args:
        entry: The structured result to render.
        format: One of ``"text"``, ``"markdown"``, ``"json"``.

    Returns:
        The rendered string without a trailing newline.

    Raises:
        ValueError: When ``format`` is not one of ``HELP_FORMATS``.

    Example:
        ```python
        text = render(describe("Workspace.query"))
        blob = render(search("cohort"), "json")
        ```
    """
    if format not in HELP_FORMATS:
        allowed = ", ".join(HELP_FORMATS)
        raise ValueError(f"Unknown help format {format!r}; expected one of: {allowed}")
    if isinstance(entry, SearchResult):
        search_renderers: dict[HelpFormat, Callable[[SearchResult], str]] = {
            "text": render_search_text,
            "markdown": render_search_markdown,
            "json": render_search_json,
        }
        return search_renderers[format](entry)
    entry_renderers: dict[HelpFormat, Callable[[HelpEntry], str]] = {
        "text": render_text,
        "markdown": render_markdown,
        "json": render_json,
    }
    return entry_renderers[format](entry)


def render_json(entry: HelpEntry) -> str:
    """Render an entry as indented JSON.

    Args:
        entry: The entry to render.

    Returns:
        ``json.dumps(entry.to_dict(), indent=2)``.
    """
    return json.dumps(entry.to_dict(), indent=2)


def render_search_json(result: SearchResult) -> str:
    """Render a search result as indented JSON.

    Args:
        result: The search result to render.

    Returns:
        ``json.dumps(result.to_dict(), indent=2)``.
    """
    return json.dumps(result.to_dict(), indent=2)


def render_text(entry: HelpEntry) -> str:
    """Render an entry as plain text in the script-compatible layout.

    Args:
        entry: The entry to render.

    Returns:
        The text rendering without a trailing newline.

    Raises:
        ValueError: When ``entry.kind`` is not a ``HelpKind`` at runtime;
            every ``HelpKind`` has a renderer.
    """
    renderer = _TEXT_RENDERERS.get(entry.kind)
    if renderer is None:
        raise ValueError(f"No text renderer for help kind {entry.kind!r}")
    return _join_blocks(renderer(entry) + _text_tail(entry))


def render_markdown(entry: HelpEntry) -> str:
    """Render an entry as markdown.

    Args:
        entry: The entry to render.

    Returns:
        The markdown rendering without a trailing newline.

    Raises:
        ValueError: When ``entry.kind`` is not a ``HelpKind`` at runtime;
            every ``HelpKind`` has a renderer.
    """
    renderer = _MD_RENDERERS.get(entry.kind)
    if renderer is None:
        raise ValueError(f"No markdown renderer for help kind {entry.kind!r}")
    return _join_blocks(renderer(entry) + _md_tail(entry))


def render_search_text(result: SearchResult) -> str:
    """Render a search result as fixed-width text rows.

    Args:
        result: The search result to render.

    Returns:
        ``# Search: "term" — N matches`` followed by one row per hit, or
        ``No matches for "term"`` followed by ``Did you mean?`` suggestions.
    """
    if not result.hits:
        blocks: list[Block] = [[f'No matches for "{result.term}"']]
        if result.suggestions:
            blocks.append(["Did you mean?", *(f"  {s}" for s in result.suggestions)])
        return _join_blocks(blocks)
    name_width = max(len(hit.name) for hit in result.hits)
    rows = [
        _rstrip(
            f"  [{hit.category:<{CATEGORY_WIDTH}}] {hit.name:<{name_width}}  {hit.summary}"
        )
        for hit in result.hits
    ]
    header = f'# Search: "{result.term}" \u2014 {len(result.hits)} matches'
    return _join_blocks([[header], rows])


def render_search_markdown(result: SearchResult) -> str:
    """Render a search result as a markdown table or a suggestion list.

    Args:
        result: The search result to render.

    Returns:
        The markdown rendering without a trailing newline.
    """
    if not result.hits:
        blocks: list[Block] = [[f'No matches for "{result.term}"']]
        if result.suggestions:
            blocks.append(["## Did you mean?"])
            blocks.append([f"- `{s}`" for s in result.suggestions])
        return _join_blocks(blocks)
    header = f'# Search: "{result.term}" \u2014 {len(result.hits)} matches'
    table = _md_table(
        ("Category", "Name", "Summary"),
        [(hit.category, f"`{hit.name}`", hit.summary) for hit in result.hits],
    )
    return _join_blocks([[header], table])


# =============================================================================
# Shared helpers
# =============================================================================


def _rstrip(line: str) -> str:
    """Strip trailing whitespace from one line.

    Args:
        line: The line to clean.

    Returns:
        The line without trailing spaces, so an empty summary leaves no padding.
    """
    return line.rstrip()


def _join_blocks(blocks: Iterable[Block]) -> str:
    """Join non-empty blocks with one blank line between them.

    Args:
        blocks: Blocks of lines; empty blocks are skipped.

    Returns:
        The joined text without a trailing newline.
    """
    return "\n\n".join("\n".join(block) for block in blocks if block)


def _two_col(rows: Iterable[tuple[str, str]], indent: str = "  ") -> Block:
    """Format ``(name, summary)`` rows with the name padded to ``NAME_WIDTH``.

    Args:
        rows: Pairs to format; names print verbatim, so callers pass any
            nesting indent already applied (see ``_nested_label``).
        indent: Prefix for every row.

    Returns:
        One line per row, trailing whitespace removed.
    """
    return [
        _rstrip(f"{indent}{name:<{NAME_WIDTH}} {summary}") for name, summary in rows
    ]


def _section(title: str, lines: Sequence[str]) -> Block:
    """Prefix a block of lines with a title line, or return nothing when empty.

    Args:
        title: The section title, printed as-is (include any trailing colon).
        lines: Body lines.

    Returns:
        ``[title, *lines]`` or ``[]`` when ``lines`` is empty.
    """
    return [title, *lines] if lines else []


def _wrap_values(
    values: Sequence[str], *, indent: str = "  ", width: int = LINE_WIDTH
) -> Block:
    """Wrap values joined by `` | `` into lines no wider than ``width`` when possible.

    Continuation lines start with ``| `` so every separator stays visible,
    as in the ``MathType`` value list. A single value longer than ``width``
    still prints on its own line.

    Args:
        values: Values in display order.
        indent: Prefix for every line.
        width: Maximum line width.

    Returns:
        Wrapped lines, or ``[]`` for no values.

    Example:
        ```python
        _wrap_values(("a", "b", "c"), width=9)
        # ["  a | b", "  | c"]
        ```
    """
    if not values:
        return []
    lines: Block = []
    current = f"{indent}{values[0]}"
    for value in values[1:]:
        candidate = f"{current} | {value}"
        if len(candidate) > width:
            lines.append(current)
            current = f"{indent}| {value}"
        else:
            current = candidate
    lines.append(current)
    return lines


def _signature_items(
    sig: SignatureDoc, render_param: Callable[[ParamDoc], str]
) -> list[str]:
    """Return the comma-separated items of a signature, markers included.

    Each parameter is passed through ``render_param``. A bare ``/`` follows
    the last ``positional_only`` parameter of each run, and a bare ``*``
    precedes the first ``keyword_only`` parameter unless a ``var_positional``
    parameter (``*args``) already opened the keyword-only section.

    Args:
        sig: The signature.
        render_param: Formats one parameter (compact or annotated form).

    Returns:
        The items in call order; ``[]`` when there are no parameters.

    Example:
        ```python
        _signature_items(sig, lambda p: p.name)   # ["a", "/", "b", "*", "c"]
        ```
    """
    items: list[str] = []
    keyword_section_open = False
    params = sig.params
    for index, param in enumerate(params):
        if param.kind == "var_positional":
            keyword_section_open = True
        elif param.kind == "keyword_only" and not keyword_section_open:
            items.append("*")
            keyword_section_open = True
        items.append(render_param(param))
        ends_positional_only_run = param.kind == "positional_only" and (
            index + 1 == len(params) or params[index + 1].kind != "positional_only"
        )
        if ends_positional_only_run:
            items.append("/")
    return items


def _compact_param(param: ParamDoc) -> str:
    """Format one parameter as ``name`` or ``name=default``.

    Args:
        param: The parameter.

    Returns:
        The compact form without an annotation.
    """
    return param.name if param.default is None else f"{param.name}={param.default}"


def _annotated_param(param: ParamDoc) -> str:
    """Format one parameter as ``name: annotation = default``.

    Args:
        param: The parameter.

    Returns:
        The form used by the multi-line signature block; the annotation and
        default parts are omitted when absent.
    """
    annotation = f": {param.annotation}" if param.annotation else ""
    default = "" if param.default is None else f" = {param.default}"
    return f"{param.name}{annotation}{default}"


def _compact_signature(sig: SignatureDoc, prefix: str = "") -> str:
    """Format a one-line signature with parameter names and defaults only.

    Args:
        sig: The signature to format.
        prefix: Text placed before the name, for example ``"Filter."``.

    Returns:
        ``prefix + name(p1, p2=default)`` with ``/`` and ``*`` markers where
        the parameter kinds require them; ``name()`` when there are no params.

    Example:
        ```python
        _compact_signature(signature_doc(Workspace.segmentation))
        # "segmentation(event, *, from_date, to_date, on=None, unit='day', where=None)"
        ```
    """
    params = ", ".join(_signature_items(sig, _compact_param))
    return f"{prefix}{sig.name}({params})"


def _signature_block(name: str, sig: SignatureDoc) -> Block:
    """Format the multi-line signature block.

    Args:
        name: Display name printed before the opening parenthesis.
        sig: The signature.

    Returns:
        ``Name(...)`` when there are no params and no return; ``Name() -> R``
        when only a return exists; otherwise one indented ``p: ann = default``
        line per parameter (plus a bare ``*,`` or ``/,`` line where the
        parameter kinds require one), then ``) -> R`` or ``)``.
    """
    returns = f" -> {sig.returns}" if sig.returns else ""
    if not sig.params:
        return [f"{name}(...)"] if not returns else [f"{name}(){returns}"]
    items = _signature_items(sig, _annotated_param)
    lines = [f"{name}("]
    for index, item in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"    {item}{comma}")
    lines.append(f"){returns}")
    return lines


def _member_label(member: MemberDoc, prefix: str = "") -> str:
    """Return the compact signature of a member, or its bare name.

    Args:
        member: The member.
        prefix: Prefix for the signature (class name plus dot for constructors).

    Returns:
        ``prefix + name(params)`` for callables with a signature, else ``name``.
    """
    if member.signature is None:
        return member.name
    return _compact_signature(member.signature, prefix=prefix)


def _nested_label(member: MemberDoc, label: str | None = None) -> str:
    """Indent a member's text label by two spaces per nesting level.

    Args:
        member: The member; ``member.depth`` selects the indent.
        label: The text to indent; defaults to ``member.name``.

    Returns:
        ``"  " * depth`` followed by the label; a depth of ``0`` returns the
        label unchanged.

    Example:
        ```python
        _nested_label(MemberDoc("RateLimitError", "exception", depth=2))
        # "    RateLimitError"
        ```
    """
    return f"{'  ' * member.depth}{member.name if label is None else label}"


def _tagged_summary(member: MemberDoc) -> str:
    """Prefix a listing summary with a literal ``[kind]`` tag for members.

    Args:
        member: The member.

    Returns:
        ``"[property] ..."`` / ``"[method] ..."`` for those kinds, else the
        bare summary.
    """
    if member.kind in _MEMBER_TAG_KINDS:
        return _rstrip(f"[{member.kind}] {member.summary}")
    return member.summary


def _field_row(field: FieldDoc) -> str:
    """Format one ``Fields (public):`` row.

    Args:
        field: The field.

    Returns:
        ``name: annotation`` followed, when present, by `` (required)`` or
        `` = default``, ``[constraints]``, ``alias → jsonName``, and
        ``  # values: a | b``.
    """
    parts = [f"{field.name}: {field.annotation}"]
    if field.required:
        parts.append("(required)")
    elif field.default is not None:
        parts.append(f"= {field.default}")
    if field.constraints:
        parts.append(f"[{', '.join(field.constraints)}]")
    if field.alias:
        parts.append(f"alias \u2192 {field.alias}")
    row = " ".join(parts)
    if field.values:
        row += f"  # values: {' | '.join(field.values)}"
    return row


def _usage_label(usage: UsageDoc) -> str:
    """Format one compact ``Used by`` / ``Raised by`` row.

    Args:
        usage: The usage.

    Returns:
        ``method(param, param)``, or ``method`` when there are no params.
    """
    if not usage.params:
        return usage.method
    return f"{usage.method}({', '.join(usage.params)})"


def _used_by_title(entry: HelpEntry) -> str:
    """Return the used-by section title for an entry kind.

    Args:
        entry: The entry.

    Returns:
        ``Raised by Workspace (N methods):`` for exceptions, else
        ``Used by Workspace (N methods):``.
    """
    verb = "Raised by" if entry.kind == "exception" else "Used by"
    return f"{verb} Workspace ({len(entry.used_by)} methods):"


def _see_also_domain(entry: HelpEntry) -> str | None:
    """Return the domain title for the ``See also`` line, if unambiguous.

    Args:
        entry: The entry.

    Returns:
        The title of the single group when ``groups`` has exactly one, else
        ``None``.
    """
    return entry.groups[0].title if len(entry.groups) == 1 else None


def _description(entry: HelpEntry) -> str:
    """Return the prose to print for an entry: body, else summary.

    Args:
        entry: The entry.

    Returns:
        ``doc.body``, else ``doc.summary``, else ``entry.summary``, else ``""``.
    """
    return entry.doc.body or entry.doc.summary or entry.summary


def _indent_lines(text: str, prefix: str = "    ") -> Block:
    """Indent every line of a text block.

    Args:
        text: Text with embedded newlines.
        prefix: Indentation added to each line; blank lines stay empty.

    Returns:
        The indented lines.
    """
    return [f"{prefix}{line}" if line else "" for line in text.splitlines()]


def _wrap_pair(name: str, description: str) -> Block:
    """Wrap one ``name: description`` item of an ``Args:`` / ``Raises:`` section.

    Args:
        name: Item name.
        description: Item description (single-space joined).

    Returns:
        Lines indented by four spaces with an eight-space hanging indent.
    """
    text = f"{name}: {description}" if description else f"{name}:"
    return textwrap.wrap(
        text,
        width=LINE_WIDTH,
        initial_indent="    ",
        subsequent_indent="        ",
        break_long_words=False,
        break_on_hyphens=False,
    )


# =============================================================================
# Text: shared section builders
# =============================================================================


def _text_doc(entry: HelpEntry, *, placeholder: bool) -> list[Block]:
    """Build the docstring blocks: description, Args, Returns, Raises, Example, Notes.

    Args:
        entry: The entry.
        placeholder: Print ``(no docstring)`` when there is no description.

    Returns:
        Blocks in Google section order; empty sections are skipped.
    """
    blocks: list[Block] = []
    description = _description(entry)
    if description:
        blocks.append(description.splitlines())
    elif placeholder:
        blocks.append(["(no docstring)"])
    doc = entry.doc
    args_lines = [line for name, desc in doc.args for line in _wrap_pair(name, desc)]
    blocks.append(_section("Args:", args_lines))
    blocks.append(_section("Returns:", _indent_lines(doc.returns)))
    raise_lines = [line for name, desc in doc.raises for line in _wrap_pair(name, desc)]
    blocks.append(_section("Raises:", raise_lines))
    blocks.append(_section("Example:", _indent_lines(doc.example)))
    blocks.append(_section("Notes:", _indent_lines(doc.notes)))
    return blocks


def _text_tail(entry: HelpEntry) -> list[Block]:
    """Build the trailing blocks: referenced types, used by, see also, hints.

    ``alias`` entries render ``referenced_types`` in their header instead, so
    the block is skipped for that kind.

    Args:
        entry: The entry.

    Returns:
        Blocks in that order; empty sections are skipped.
    """
    blocks: list[Block] = []
    if entry.kind != "alias":
        blocks.append(
            _section(
                f"Referenced types ({len(entry.referenced_types)}):",
                _two_col(entry.referenced_types),
            )
        )
    blocks.append(
        _section(_used_by_title(entry), [f"  {_usage_label(u)}" for u in entry.used_by])
    )
    if entry.see_also:
        domain = _see_also_domain(entry)
        label = f"See also ({domain}):" if domain else "See also:"
        blocks.append([f"{label} {', '.join(entry.see_also)}"])
    for hint in entry.hints:
        blocks.append(
            ["---", f"Tip: For {hint.title},", f'     WebFetch(url="{hint.url}")']
        )
    return blocks


def _text_groups(groups: Iterable[Group], *, signatures: bool) -> list[Block]:
    """Build one ``Title (N):`` block per group.

    Args:
        groups: The groups.
        signatures: Print the compact signature instead of the bare name.

    Returns:
        One block per group; a group with no items still prints its title.
        Each row's name is indented two spaces per ``MemberDoc.depth``.
    """
    blocks: list[Block] = []
    for group in groups:
        rows = [
            (
                _nested_label(m, _member_label(m) if signatures else None),
                _tagged_summary(m),
            )
            for m in group.items
        ]
        blocks.append([f"{group.title} ({len(group.items)}):", *_two_col(rows)])
    return blocks


# =============================================================================
# Text: per-kind renderers
# =============================================================================


def _text_callable(entry: HelpEntry) -> list[Block]:
    """Render a ``method`` or ``function`` entry.

    Args:
        entry: The entry.

    Returns:
        Signature block followed by the docstring blocks.
    """
    head = (
        _signature_block(entry.name, entry.signature)
        if entry.signature is not None
        else [entry.name]
    )
    return [head, *_text_doc(entry, placeholder=True)]


def _text_property(entry: HelpEntry) -> list[Block]:
    """Render a ``property`` entry as ``Name -> ret`` plus docstring.

    Args:
        entry: The entry.

    Returns:
        Header block followed by the docstring blocks.
    """
    returns = entry.signature.returns if entry.signature is not None else None
    head = f"{entry.name} -> {returns}" if returns else entry.name
    return [[head], *_text_doc(entry, placeholder=True)]


def _text_parameter(entry: HelpEntry) -> list[Block]:
    """Render a ``parameter`` entry: annotation line, allowed values, description.

    Args:
        entry: The entry.

    Returns:
        Header block (with an ``Allowed values:`` list when present) followed
        by the description block.
    """
    param = (
        entry.signature.params[0]
        if entry.signature and entry.signature.params
        else None
    )
    head = entry.name
    values = entry.values
    description = _description(entry)
    if param is not None:
        head += f": {param.annotation}" if param.annotation else ""
        head += f" = {param.default}" if param.default is not None else ""
        values = values or param.values
        description = description or param.description
    header: Block = [head]
    if values:
        header.extend(["Allowed values:", *_wrap_values(values)])
    return [header, description.splitlines() if description else []]


def _text_class(entry: HelpEntry) -> list[Block]:
    """Render a ``class``, ``model``, or ``dataclass`` entry.

    Args:
        entry: The entry.

    Returns:
        Header, docstring, Construction, Fields, Properties, and Methods
        blocks. The ``Construction (N):`` count covers classmethods and
        staticmethods alike; the model does not tell them apart.
    """
    bases = ", ".join(entry.bases) if entry.bases else "(none)"
    header = [f"class {entry.name}", f"  Inherits: {bases}"]
    if entry.config:
        header.append("  Config: " + ", ".join(f"{k}={v}" for k, v in entry.config))
    construction = [
        f"  {_member_label(m, prefix=f'{entry.name}.')}" for m in entry.construction
    ]
    fields = [f"  {_field_row(f)}" for f in entry.fields]
    properties = _two_col((m.name, _tagged_summary(m)) for m in entry.properties)
    methods = _two_col((_member_label(m), m.summary) for m in entry.methods)
    return [
        header,
        *_text_doc(entry, placeholder=True),
        _section(f"Construction ({len(entry.construction)}):", construction),
        _section("Fields (public):", fields),
        _section("Properties:", properties),
        _section("Methods:", methods),
    ]


def _text_enum(entry: HelpEntry) -> list[Block]:
    """Render an ``enum`` entry: header, member table, docstring.

    Args:
        entry: The entry.

    Returns:
        Header block with the member table, then the docstring blocks.
    """
    header = [f"enum {entry.name}"]
    if entry.fields:
        width = max(len(f.name) for f in entry.fields)
        header.extend(f"  {f.name:<{width}}  = {f.default}" for f in entry.fields)
    else:
        header.extend(f"  {v}" for v in entry.values)
    return [header, *_text_doc(entry, placeholder=False)]


def _text_literal(entry: HelpEntry) -> list[Block]:
    """Render a ``literal`` entry: ``Name = Literal[N values]`` plus wrapped values.

    Args:
        entry: The entry.

    Returns:
        Header block followed by the description block.
    """
    header = [
        f"{entry.name} = Literal[{len(entry.values)} values]",
        *_wrap_values(entry.values),
    ]
    return [header, *_text_doc(entry, placeholder=False)]


def _text_alias(entry: HelpEntry) -> list[Block]:
    """Render an ``alias`` entry: ``Name = A | B`` plus one row per member.

    Args:
        entry: The entry.

    Returns:
        Header block followed by the description block.
    """
    header = [
        f"{entry.name} = {' | '.join(entry.values)}",
        *_two_col(entry.referenced_types),
    ]
    return [header, *_text_doc(entry, placeholder=False)]


def _text_exception(entry: HelpEntry) -> list[Block]:
    """Render an ``exception`` entry: header, docstring, subclass tree.

    Args:
        entry: The entry.

    Returns:
        Header block, docstring blocks, then one block per group
        (``Subclasses``); subclass names indent two spaces per ``depth``.
    """
    base = entry.bases[0] if entry.bases else "Exception"
    header = [f"exception {entry.name}({base})"]
    groups = [
        _section(
            f"{g.title}:", _two_col((_nested_label(m), m.summary) for m in g.items)
        )
        for g in entry.groups
    ]
    return [header, *_text_doc(entry, placeholder=True), *groups]


def _text_module(entry: HelpEntry) -> list[Block]:
    """Render a ``module`` entry: header, docstring, members.

    Args:
        entry: The entry.

    Returns:
        Header block, docstring blocks, then group blocks or ``Members (N):``.
    """
    if entry.groups:
        members = _text_groups(entry.groups, signatures=True)
    else:
        rows = _two_col((_member_label(m), m.summary) for m in entry.methods)
        members = [_section(f"Members ({len(entry.methods)}):", rows)]
    return [[f"module {entry.name}"], *_text_doc(entry, placeholder=True), *members]


def _text_constant(entry: HelpEntry) -> list[Block]:
    """Render a ``constant`` entry as ``NAME: type = value`` plus docstring.

    Args:
        entry: The entry.

    Returns:
        Header block followed by the docstring blocks.
    """
    head = entry.name
    if entry.bases:
        head += f": {entry.bases[0]}"
    if entry.values:
        head += f" = {entry.values[0]}"
    return [[head], *_text_doc(entry, placeholder=False)]


def _text_listing(entry: HelpEntry) -> list[Block]:
    """Render a ``listing`` entry: header line then ``Title (N):`` groups.

    Args:
        entry: The entry.

    Returns:
        Header block followed by one block per group.
    """
    head = f"{entry.name}: {entry.summary}" if entry.summary else entry.name
    return [[head], *_text_groups(entry.groups, signatures=False)]


def _text_overview(entry: HelpEntry) -> list[Block]:
    """Render the ``overview`` entry: ``name version``, grammar body, group tables.

    Args:
        entry: The entry.

    Returns:
        Header block, body block, then one block per group.
    """
    head = f"{entry.name} {entry.summary}".rstrip()
    body = _description(entry).splitlines()
    return [[head], body, *_text_groups(entry.groups, signatures=True)]


_TEXT_RENDERERS: dict[HelpKind, Callable[[HelpEntry], list[Block]]] = {
    "overview": _text_overview,
    "class": _text_class,
    "model": _text_class,
    "dataclass": _text_class,
    "enum": _text_enum,
    "literal": _text_literal,
    "alias": _text_alias,
    "exception": _text_exception,
    "function": _text_callable,
    "method": _text_callable,
    "property": _text_property,
    "parameter": _text_parameter,
    "module": _text_module,
    "constant": _text_constant,
    "listing": _text_listing,
}
"""Text renderer per kind; every ``HelpKind`` has one."""


# =============================================================================
# Markdown: shared helpers
# =============================================================================


def _md_cell(text: str) -> str:
    """Escape a table cell so pipes and newlines do not break the table.

    Args:
        text: Cell text.

    Returns:
        The text with ``|`` escaped and newlines collapsed to spaces.
    """
    return text.replace("|", "\\|").replace("\n", " ")


def _md_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> Block:
    """Build a pipe table.

    Args:
        headers: Column titles.
        rows: Row cells; each row has ``len(headers)`` cells.

    Returns:
        Header, separator, and one line per row; ``[]`` when there are no rows.
    """
    lines = [f"| {' | '.join(_md_cell(c) for c in row)} |" for row in rows]
    if not lines:
        return []
    head = f"| {' | '.join(headers)} |"
    sep = f"| {' | '.join('---' for _ in headers)} |"
    return [head, sep, *lines]


def _md_fence(lines: Sequence[str]) -> Block:
    """Wrap lines in a ``python`` fence.

    Args:
        lines: Code lines.

    Returns:
        The fenced block.
    """
    return ["```python", *lines, "```"]


def _md_section(title: str, body: Block) -> list[Block]:
    """Build a ``## title`` heading block followed by a body block.

    Args:
        title: Heading text without the ``## `` prefix.
        body: Body lines.

    Returns:
        ``[[heading], body]`` or ``[]`` when ``body`` is empty.
    """
    return [[f"## {title}"], body] if body else []


def _md_doc(entry: HelpEntry) -> list[Block]:
    """Build the markdown docstring blocks.

    Args:
        entry: The entry.

    Returns:
        Description paragraph, then ``## Args`` / ``Returns`` / ``Raises`` /
        ``Example`` / ``Notes`` sections when present.
    """
    blocks: list[Block] = []
    description = _description(entry)
    if description:
        blocks.append(description.splitlines())
    doc = entry.doc
    blocks += _md_section("Args", [f"- `{n}`: {d}" for n, d in doc.args])
    blocks += _md_section("Returns", doc.returns.splitlines())
    blocks += _md_section("Raises", [f"- `{n}`: {d}" for n, d in doc.raises])
    if doc.example:
        example = doc.example.splitlines()
        if "```" not in doc.example:
            example = _md_fence(example)
        blocks += _md_section("Example", example)
    blocks += _md_section("Notes", doc.notes.splitlines())
    return blocks


def _md_tail(entry: HelpEntry) -> list[Block]:
    """Build the trailing markdown sections: referenced types, used by, see also, hints.

    Args:
        entry: The entry.

    Returns:
        Sections in that order; empty ones are skipped.
    """
    blocks: list[Block] = []
    if entry.kind != "alias":
        blocks += _md_section(
            "Referenced types",
            _md_table(
                ("Type", "Summary"), [(f"`{n}`", s) for n, s in entry.referenced_types]
            ),
        )
    verb = "Raised by" if entry.kind == "exception" else "Used by"
    blocks += _md_section(
        f"{verb} Workspace", [f"- `{_usage_label(u)}`" for u in entry.used_by]
    )
    if entry.see_also:
        domain = _see_also_domain(entry)
        title = f"See also ({domain})" if domain else "See also"
        blocks += _md_section(title, [", ".join(f"`{n}`" for n in entry.see_also)])
    blocks += _md_section(
        "Further reading", [f"- [{h.title}]({h.url})" for h in entry.hints]
    )
    return blocks


def _md_groups(groups: Iterable[Group], *, signatures: bool) -> list[Block]:
    """Build one ``## Title (N)`` table per group.

    Args:
        groups: The groups.
        signatures: Show the compact signature instead of the bare name.

    Returns:
        Heading and table blocks per group. Names print bare; nesting depth
        is not shown in markdown.
    """
    blocks: list[Block] = []
    for group in groups:
        rows = [
            (
                f"`{_member_label(m) if signatures else m.name}`",
                _tagged_summary(m),
            )
            for m in group.items
        ]
        blocks.append([f"## {group.title} ({len(group.items)})"])
        blocks.append(_md_table(("Name", "Summary"), rows))
    return blocks


# =============================================================================
# Markdown: per-kind renderers
# =============================================================================


def _md_callable(entry: HelpEntry) -> list[Block]:
    """Render a ``method`` or ``function`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced signature, then docstring sections.
    """
    blocks: list[Block] = [[f"# {entry.name}"]]
    if entry.signature is not None:
        blocks.append(_md_fence(_signature_block(entry.name, entry.signature)))
    return blocks + _md_doc(entry)


def _md_property(entry: HelpEntry) -> list[Block]:
    """Render a ``property`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced ``Name -> ret`` line, then docstring sections.
    """
    returns = entry.signature.returns if entry.signature is not None else None
    head = f"{entry.name} -> {returns}" if returns else entry.name
    return [[f"# {entry.name}"], _md_fence([head]), *_md_doc(entry)]


def _md_parameter(entry: HelpEntry) -> list[Block]:
    """Render a ``parameter`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced annotation line, allowed values, description.
    """
    text_blocks = _text_parameter(entry)
    head = text_blocks[0][0]
    param = (
        entry.signature.params[0]
        if entry.signature and entry.signature.params
        else None
    )
    values = entry.values or (param.values if param else ())
    description = _description(entry) or (param.description if param else "")
    blocks: list[Block] = [[f"# {entry.name}"], _md_fence([head])]
    if values:
        blocks.append(["**Allowed values:** " + ", ".join(f"`{v}`" for v in values)])
    if description:
        blocks.append(description.splitlines())
    return blocks


def _md_class(entry: HelpEntry) -> list[Block]:
    """Render a ``class``, ``model``, or ``dataclass`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, inherits/config lines, docstring, and section tables.
    """
    bases = ", ".join(f"`{b}`" for b in entry.bases) if entry.bases else "(none)"
    meta = [f"Inherits: {bases}"]
    if entry.config:
        meta.append("Config: " + ", ".join(f"`{k}={v}`" for k, v in entry.config))
    blocks: list[Block] = [[f"# {entry.name}"], meta, *_md_doc(entry)]
    blocks += _md_section(
        "Construction",
        _md_fence(
            [_member_label(m, prefix=f"{entry.name}.") for m in entry.construction]
        )
        if entry.construction
        else [],
    )
    blocks += _md_section(
        "Fields",
        _md_table(
            ("Field", "Type", "Default", "Notes"),
            [_md_field_row(f) for f in entry.fields],
        ),
    )
    blocks += _md_section(
        "Properties",
        _md_table(
            ("Property", "Summary"),
            [(f"`{m.name}`", _tagged_summary(m)) for m in entry.properties],
        ),
    )
    blocks += _md_section(
        "Methods",
        _md_table(
            ("Method", "Summary"),
            [(f"`{_member_label(m)}`", m.summary) for m in entry.methods],
        ),
    )
    return blocks


def _md_field_row(field: FieldDoc) -> tuple[str, str, str, str]:
    """Build the four cells of a markdown field row.

    Args:
        field: The field.

    Returns:
        ``(name, type, default, notes)`` where notes joins constraints, alias,
        and inline values with ``; ``.
    """
    if field.required:
        default = "(required)"
    elif field.default is not None:
        default = f"`{field.default}`"
    else:
        default = ""
    notes: list[str] = list(field.constraints)
    if field.alias:
        notes.append(f"alias \u2192 {field.alias}")
    if field.values:
        notes.append(f"values: {' | '.join(field.values)}")
    return (f"`{field.name}`", f"`{field.annotation}`", default, "; ".join(notes))


def _md_enum(entry: HelpEntry) -> list[Block]:
    """Render an ``enum`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, member table, then docstring sections.
    """
    if entry.fields:
        rows = [(f"`{f.name}`", f"`{f.default}`") for f in entry.fields]
    else:
        rows = [(f"`{v}`", "") for v in entry.values]
    return [
        [f"# enum {entry.name}"],
        _md_table(("Member", "Value"), rows),
        *_md_doc(entry),
    ]


def _md_literal(entry: HelpEntry) -> list[Block]:
    """Render a ``literal`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced header plus wrapped values, then docstring sections.
    """
    fence = _md_fence(
        [
            f"{entry.name} = Literal[{len(entry.values)} values]",
            *_wrap_values(entry.values),
        ]
    )
    return [[f"# {entry.name}"], fence, *_md_doc(entry)]


def _md_alias(entry: HelpEntry) -> list[Block]:
    """Render an ``alias`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced ``Name = A | B`` line, member table, docstring sections.
    """
    fence = _md_fence([f"{entry.name} = {' | '.join(entry.values)}"])
    table = _md_table(
        ("Member", "Summary"), [(f"`{n}`", s) for n, s in entry.referenced_types]
    )
    return [[f"# {entry.name}"], fence, table, *_md_doc(entry)]


def _md_exception(entry: HelpEntry) -> list[Block]:
    """Render an ``exception`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, docstring sections, then one table per group (``Subclasses``);
        names print bare, nesting depth is not shown in markdown.
    """
    base = entry.bases[0] if entry.bases else "Exception"
    blocks: list[Block] = [[f"# exception {entry.name}({base})"], *_md_doc(entry)]
    for group in entry.groups:
        rows = [(f"`{m.name}`", m.summary) for m in group.items]
        blocks += _md_section(group.title, _md_table(("Name", "Summary"), rows))
    return blocks


def _md_module(entry: HelpEntry) -> list[Block]:
    """Render a ``module`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, docstring sections, then member tables.
    """
    blocks: list[Block] = [[f"# module {entry.name}"], *_md_doc(entry)]
    if entry.groups:
        blocks += _md_groups(entry.groups, signatures=True)
    else:
        rows = [(f"`{_member_label(m)}`", m.summary) for m in entry.methods]
        blocks += _md_section("Members", _md_table(("Member", "Summary"), rows))
    return blocks


def _md_constant(entry: HelpEntry) -> list[Block]:
    """Render a ``constant`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, fenced ``NAME: type = value`` line, docstring sections.
    """
    return [[f"# {entry.name}"], _md_fence(_text_constant(entry)[0]), *_md_doc(entry)]


def _md_listing(entry: HelpEntry) -> list[Block]:
    """Render a ``listing`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        Title, optional summary, then one table per group.
    """
    blocks: list[Block] = [[f"# {entry.name}"]]
    if entry.summary:
        blocks.append([entry.summary])
    return blocks + _md_groups(entry.groups, signatures=False)


def _md_overview(entry: HelpEntry) -> list[Block]:
    """Render the ``overview`` entry in markdown.

    Args:
        entry: The entry.

    Returns:
        ``# name version`` title, grammar body, then group tables.
    """
    head = f"# {entry.name} {entry.summary}".rstrip()
    body = _description(entry).splitlines()
    return [[head], body, *_md_groups(entry.groups, signatures=True)]


_MD_RENDERERS: dict[HelpKind, Callable[[HelpEntry], list[Block]]] = {
    "overview": _md_overview,
    "class": _md_class,
    "model": _md_class,
    "dataclass": _md_class,
    "enum": _md_enum,
    "literal": _md_literal,
    "alias": _md_alias,
    "exception": _md_exception,
    "function": _md_callable,
    "method": _md_callable,
    "property": _md_property,
    "parameter": _md_parameter,
    "module": _md_module,
    "constant": _md_constant,
    "listing": _md_listing,
}
"""Markdown renderer per kind; every ``HelpKind`` has one."""


__all__ = [
    "CATEGORY_WIDTH",
    "LINE_WIDTH",
    "NAME_WIDTH",
    "render",
    "render_json",
    "render_markdown",
    "render_search_json",
    "render_search_markdown",
    "render_search_text",
    "render_text",
]
