"""Built-in API reference: ``help()``, ``describe()``, ``search()``, ``render()``.

This module is the public face of the offline help system. It
introspects the installed ``mixpanel_headless`` package and answers questions
about its own surface — signatures, fields, enum values, Literal aliases,
exception trees, ``Workspace`` domains — without a network call, without a
config file, and without building a ``Workspace``.

Three ways to use it:

```python
import mixpanel_headless as mp

mp.help("Workspace.query")                  # print reference text
entry = mp.reference.describe("Filter")     # structured HelpEntry
hits = mp.reference.search("cohort")        # structured SearchResult
```

The CLI twin is ``mp help QUERY...`` (also ``python3 -m mixpanel_headless
help QUERY...``).

Importing this module is cheap: the introspection machinery loads lazily on
the first call, so ``import mixpanel_headless`` does not pay for it.
"""

from __future__ import annotations

import enum
import inspect
import json
import sys
import types
import typing
from collections.abc import Callable
from typing import TYPE_CHECKING, TextIO

from mixpanel_headless._internal.help.models import (
    HELP_FORMATS,
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
    SearchHit,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)
from mixpanel_headless.exceptions import HelpDomainError, HelpLookupError

if TYPE_CHECKING:
    from mixpanel_headless._internal.help.resolve import Target

__all__ = [
    "DocSections",
    "FieldDoc",
    "Group",
    "HelpEntry",
    "HelpFormat",
    "HelpKind",
    "HelpLookupError",
    "Hint",
    "MemberDoc",
    "ParamDoc",
    "SearchHit",
    "SearchResult",
    "SignatureDoc",
    "UsageDoc",
    "clear_cache",
    "describe",
    "help",
    "render",
    "search",
]

_PACKAGE = "mixpanel_headless"
_WORKSPACE = "Workspace"
_LLMS_URL = "https://mixpanel.github.io/mixpanel-headless/llms.txt"
_MISS_HITS = 5
"""How many search hits a ``describe()`` miss carries."""

_SEARCH_USAGE = (
    "Usage: help('search <term>')\n"
    "  Case-insensitive substring search over exports, Workspace members,\n"
    "  enum members, and Literal values. Example: help('search cohort')."
)
"""Text printed for a bare ``search`` query."""

_TYPES_LISTING_GROUPS: tuple[tuple[str, ExportKind], ...] = (
    ("models", "model"),
    ("dataclasses", "dataclass"),
    ("enums", "enum"),
    ("literal aliases", "literal"),
    ("other aliases", "alias"),
    ("protocols and plain classes", "class"),
)
"""Group titles of the ``types`` listing, in display order, with their kind."""

_CALLABLE_KINDS: frozenset[str] = frozenset({"method", "function"})


# =============================================================================
# Public API
# =============================================================================


def help(
    query: str | object | None = None,
    *,
    format: HelpFormat = "text",
    file: TextIO | None = None,
    hints: bool = True,
    domain: str | None = None,
) -> None:
    """Print reference help for the library, a type, a method, or a search.

    Works offline: no credentials, no network, no config file. The text is
    plain (no Rich markup) so it is safe to paste into a prompt or a file.

    Query grammar (tokens are split on whitespace, so ``"search cohort"``
    and ``"search   cohort"`` are equal):

    | Query | Result kind | Notes |
    | --- | --- | --- |
    | ``None`` or ``""`` | ``overview`` | Version, import line, entry points, domain table, grammar summary, ``llms.txt`` link. |
    | ``Workspace`` | ``listing`` | Methods grouped by domain; properties first. ``domain=`` filters to one group (case-insensitive, unique prefix accepted). |
    | ``Workspace.<method>`` | ``method`` | Signature, docstring, referenced types, see also, hint. |
    | ``Workspace.<property>`` | ``property`` | Return annotation and docstring. |
    | ``Workspace.<method>.<param>`` | ``parameter`` | Annotation, default, allowed values, description. |
    | ``<Model>`` (Pydantic) | ``model`` | Bases, config, construction, fields, properties, methods, used by, hint. |
    | ``<Dataclass>`` | ``dataclass`` | Same, with dataclass field rules. |
    | ``<Enum>`` | ``enum`` | Member table and used by. |
    | ``<LiteralAlias>`` | ``literal`` | Allowed values, one-line description, used by with parameter names. |
    | ``<UnionAlias>`` / ``Account`` | ``alias`` | Expanded members, each with its first doc line. |
    | ``<Exception>`` | ``exception`` | Base, docstring, subclasses, ``Workspace`` methods that raise it. |
    | ``<Class>.<member>`` | ``method`` / ``property`` | Any public class, not only ``Workspace``. |
    | ``<function>`` | ``function`` | ``login_unified``, ``validate_bookmark``, label helpers. |
    | ``accounts`` / ``session`` / ``targets`` | ``module`` | ``__all__`` members with first doc lines and compact signatures. |
    | ``<constant>`` | ``constant`` | Value and type. |
    | ``types`` | ``listing`` | Public types grouped by kind. No hints. |
    | ``exceptions`` | ``listing`` | Indented tree from ``MixpanelHeadlessError``. No hints. |
    | ``search <term>`` | ``search`` | Case-insensitive substring search. |
    | ``help`` | ``function`` | This table. |
    | miss | (printed) | ``No help entry ...``, ``Did you mean?`` suggestions, first five search hits. |

    Objects are accepted too: ``help(mp.Filter)``, ``help(ws.query)``,
    ``help(mp.accounts)``.

    Args:
        query: Query text, a public object, or ``None`` for the overview.
        format: ``"text"`` (default), ``"markdown"``, or ``"json"``.
        file: Destination stream; defaults to ``sys.stdout``.
        hints: Print the hosted-documentation ``Tip:`` block when one applies.
        domain: Restrict the ``Workspace`` listing to one domain title. Any
            other query with ``domain`` set raises ``HelpDomainError``.

    Returns:
        ``None``. The rendered text is written to ``file``.

    Raises:
        ValueError: When ``format`` is not ``text``, ``markdown``, or ``json``.
        HelpDomainError: When ``domain`` names no registered domain, several
            domains (ambiguous prefix), or is given for a query other than
            ``Workspace``. A plain lookup miss does **not** raise; it prints
            the message and suggestions instead, even when ``domain`` is set.

    Example:
        ```python
        import mixpanel_headless as mp

        mp.help()                                # overview
        mp.help("Workspace", domain="funnel query")
        mp.help("Workspace.query.events")        # one parameter
        mp.help("MathType")                      # Literal alias values
        mp.help("search cohort")                 # search
        mp.help("Filter", format="json")         # machine-readable
        ```
    """
    if format not in HELP_FORMATS:
        allowed = ", ".join(HELP_FORMATS)
        raise ValueError(f"Unknown help format {format!r}; expected one of: {allowed}")
    out = file if file is not None else sys.stdout
    if isinstance(query, str) and not isinstance(query, enum.Enum):
        from mixpanel_headless._internal.help.resolve import parse_query

        mode, payload = parse_query(query)
        if mode == "search":
            if not payload:
                print(_search_usage(format), file=out)
                return
            print(render(search(payload), format), file=out)
            return
        query = None if mode == "overview" else payload
    try:
        entry = describe(query, hints=hints, domain=domain)
    except HelpDomainError:
        raise
    except HelpLookupError as exc:
        print(render_miss(exc, format), file=out)
        return
    print(render(entry, format), file=out)


def describe(
    query: str | object,
    *,
    hints: bool = True,
    domain: str | None = None,
) -> HelpEntry:
    """Resolve a query and assemble its structured ``HelpEntry``.

    This is the assembler behind :func:`help`. It resolves the query (a dotted
    string from the package root or a public object), then builds one entry
    per ``HelpKind`` from signatures, docstrings, fields, relations, and hints.

    Args:
        query: Dotted query text (``"Workspace.query"``, ``"Filter"``,
            ``"types"``), a public object (``mp.Filter``, ``ws.query``,
            ``mp.accounts``), or ``None`` / ``""`` for the overview.
        hints: Include hosted-documentation hints. ``False`` yields
            ``hints=()`` on every entry.
        domain: Restrict the ``Workspace`` listing to one domain title
            (case-insensitive; a unique prefix is accepted).

    Returns:
        The assembled entry.

    Raises:
        HelpLookupError: When the query matches nothing. The error carries
            ``suggestions`` and the first five search ``hits``. Raised for
            a name miss even when ``domain`` is set.
        HelpDomainError: When the query resolved but ``domain`` was rejected:
            it is given for a query other than ``Workspace`` (``reason``
            ``not_workspace``), names no registered domain (``unknown``; the
            error carries every title in ``domains``), or matches several
            titles (``ambiguous``; the candidates are in ``domains``).

    Example:
        ```python
        entry = describe("Workspace.query_funnel")
        entry.signature.params[0].name     # "steps"
        entry.to_dict()["kind"]            # "method"
        ```
    """
    from mixpanel_headless._internal.help.resolve import resolve

    query_text = query if isinstance(query, str) else None
    try:
        target = resolve(query)
    except HelpLookupError as exc:
        raise _with_hits(exc) from None
    if domain is not None and not _is_workspace_class(target):
        raise HelpDomainError(
            query_text if query_text is not None else target.qualname,
            domain=domain,
            reason="not_workspace",
        )
    entry = _assemble(target, domain=domain)
    return entry if hints else _without_hints(entry)


def search(term: str, *, limit: int | None = None) -> SearchResult:
    """Search the public surface for a case-insensitive substring.

    Matches names first, then first docstring lines, then enum members and
    Literal values. Hits are ordered by tier, then by ``(category, name)``.

    Args:
        term: Text to look for.
        limit: Keep at most this many hits; ``None`` keeps all.

    Returns:
        The search result. On a miss ``hits`` is empty and ``suggestions``
        holds close names.

    Raises:
        HelpLookupError: When ``term`` is empty or whitespace only.
        ValueError: When ``limit`` is negative.

    Example:
        ```python
        search("retention").hits[0].name     # "RetentionCohortData"
        search("Filtr").suggestions          # ("Filter", ...)
        ```
    """
    from mixpanel_headless._internal.help.search import search as _search

    return _search(term, limit=limit)


def render(entry: HelpEntry | SearchResult, format: HelpFormat = "text") -> str:
    """Render an entry or a search result as text, markdown, or JSON.

    Args:
        entry: A ``HelpEntry`` from :func:`describe` or a ``SearchResult``
            from :func:`search`.
        format: ``"text"`` (default), ``"markdown"``, or ``"json"``.

    Returns:
        The rendered string without a trailing newline.

    Raises:
        ValueError: When ``format`` is not one of the three formats.

    Example:
        ```python
        print(render(describe("MathType"), "markdown"))
        ```
    """
    from mixpanel_headless._internal.help.render import render as _render

    return _render(entry, format)


def clear_cache() -> None:
    """Drop every per-process help cache.

    Clears the inventory, resolved type hints, relations (used by, raised
    by, exception map), and the search index. The next call rebuilds them
    from the live package.
    """
    from mixpanel_headless._internal.help import (
        introspect,
        inventory,
        relations,
    )
    from mixpanel_headless._internal.help import (
        search as search_module,
    )

    search_module.clear_cache()
    relations.clear_cache()
    introspect.clear_cache()
    inventory.clear_cache()


# =============================================================================
# help() helpers
# =============================================================================


def _search_usage(format: HelpFormat) -> str:
    """Return the usage text for a bare ``search`` query.

    Args:
        format: The requested output format.

    Returns:
        A JSON object with a ``usage`` key for ``json``; the plain usage
        text otherwise.
    """
    if format == "json":
        return json.dumps({"usage": _SEARCH_USAGE}, indent=2)
    return _SEARCH_USAGE


def render_miss(exc: HelpLookupError, format: HelpFormat) -> str:
    """Render a lookup miss: the error message, then the first search hits.

    Shared by :func:`help` and the ``mp help`` command so both print the
    same text for the same miss. Not part of ``__all__``; the public entry
    points are :func:`help` (prints it) and :func:`describe` (raises the
    error it renders).

    Args:
        exc: The lookup error raised by :func:`describe`. ``exc.message``
            already carries the ``Did you mean: a, b?`` tail when there
            are suggestions.
        format: The requested output format.

    Returns:
        For ``json`` an object with ``error`` (the message), ``query``,
        ``suggestions``, and ``hits``; otherwise the message followed, when
        there are hits, by the search view of the first five.

    Example:
        ```python
        from mixpanel_headless import HelpLookupError, reference

        try:
            reference.describe("zzqq")
        except HelpLookupError as exc:
            print(reference.render_miss(exc, "text"))
            # No help entry for 'zzqq'.
        ```
    """
    hits = exc.hits[:_MISS_HITS]
    if format == "json":
        payload = {
            "error": exc.message,
            "query": exc.query,
            "suggestions": list(exc.suggestions),
            "hits": [hit.to_dict() for hit in hits],
        }
        return json.dumps(payload, indent=2)
    blocks: list[str] = [exc.message]
    if hits:
        blocks.append(render(SearchResult(term=exc.query, hits=hits), format))
    return "\n\n".join(blocks)


def _with_hits(exc: HelpLookupError) -> HelpLookupError:
    """Attach the first search hits for the missed query to a resolver error.

    Args:
        exc: The error raised by the resolver (``hits`` is always empty
            there, and ``query`` is never blank because blank text resolves
            to the overview).

    Returns:
        A new error with the same ``query`` and ``suggestions`` plus up to
        five search hits.
    """
    from mixpanel_headless._internal.help.search import search as _search

    hits = _search(exc.query, limit=_MISS_HITS).hits
    return HelpLookupError(exc.query, suggestions=exc.suggestions, hits=hits)


def _without_hints(entry: HelpEntry) -> HelpEntry:
    """Return a copy of ``entry`` with ``hints=()``.

    Args:
        entry: The assembled entry.

    Returns:
        The same entry when it has no hints; otherwise a copy without them.
    """
    if not entry.hints:
        return entry
    import dataclasses

    return dataclasses.replace(entry, hints=())


def _is_workspace_class(target: Target) -> bool:
    """Tell whether a target is the ``Workspace`` class itself.

    Args:
        target: The resolved target.

    Returns:
        ``True`` for the bare ``Workspace`` query (or the class / an instance
        passed as an object).
    """
    return target.kind == "class" and target.qualname == _WORKSPACE


# =============================================================================
# Assembly
# =============================================================================


def _assemble(target: Target, *, domain: str | None) -> HelpEntry:
    """Build the entry for a resolved target.

    Args:
        target: The resolved target.
        domain: Domain filter, only meaningful for the ``Workspace`` listing.

    Returns:
        The entry for the target's kind.

    Raises:
        HelpDomainError: When ``domain`` names no registered domain.
        HelpLookupError: When a ``parameter`` target is absent from its
            owner's rendered signature.
    """
    if target.kind == "overview":
        return _overview_entry()
    if target.kind == "listing":
        return _types_listing() if target.qualname == "types" else _exceptions_listing()
    if _is_workspace_class(target):
        return _workspace_listing(domain)
    return _ENTRY_BUILDERS[target.kind](target)


def _hints(qualname: str, kind: HelpKind) -> tuple[Hint, ...]:
    """Pick the documentation hint for a query.

    Args:
        qualname: The canonical query string.
        kind: The entry kind.

    Returns:
        A one-element tuple or ``()``.
    """
    from mixpanel_headless._internal.help.hints import hints_for, tokens

    return hints_for(tokens(qualname), kind=kind)


def _doc(obj: object) -> DocSections:
    """Parse the docstring of an object.

    Args:
        obj: Any object; ``inspect.getdoc`` handles inheritance.

    Returns:
        The parsed sections (all empty for an undocumented object).
    """
    from mixpanel_headless._internal.help.docstrings import parse_docstring

    return parse_docstring(inspect.getdoc(obj))


def _summary(obj: object) -> str:
    """Return the first docstring line of an object.

    Args:
        obj: Any object.

    Returns:
        The first non-empty summary line, or ``""``.
    """
    from mixpanel_headless._internal.help.docstrings import first_line

    return first_line(inspect.getdoc(obj))


def _alias_doc(name: str) -> str:
    """Return the ``ALIAS_DOCS`` line for an export name.

    Args:
        name: Export name of a Literal / Union alias or a module constant.

    Returns:
        The one-line description, or ``""`` when none is registered.
    """
    from mixpanel_headless._literal_types import ALIAS_DOCS

    return ALIAS_DOCS.get(name, "")


def _member_summary(obj: object, kind: MemberKind, name: str) -> str:
    """Return the listing summary for a member or export.

    Args:
        obj: The runtime object.
        kind: Its classification.
        name: Its export name (used for alias docs).

    Returns:
        ``ALIAS_DOCS`` text for Literal / Union aliases and constants,
        else the first docstring line.
    """
    if kind in ("literal", "alias", "constant"):
        return _alias_doc(name)
    return _summary(obj)


def _member_doc(name: str, obj: object, kind: MemberKind) -> MemberDoc:
    """Build a ``MemberDoc`` with a compact signature for callables.

    Args:
        name: Member name.
        obj: The runtime object.
        kind: Its classification.

    Returns:
        The member row; ``signature`` is set for ``method`` / ``function``
        kinds only.
    """
    from mixpanel_headless._internal.help.introspect import signature_doc

    signature = signature_doc(obj, name=name) if kind in _CALLABLE_KINDS else None
    return MemberDoc(name, kind, _member_summary(obj, kind, name), signature)


# -----------------------------------------------------------------------------
# overview and listings
# -----------------------------------------------------------------------------


def _overview_entry() -> HelpEntry:
    """Build the package overview entry.

    The domain table is packed as text in ``doc.body`` (two columns) so the
    whole view stays under 60 lines; ``groups`` is empty.

    Returns:
        The ``overview`` entry.
    """
    import mixpanel_headless as package
    from mixpanel_headless._internal.help.inventory import workspace_members
    from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS

    entry_points = (
        ("mp.help(query)", "print reference text (this view)"),
        ("mp.reference.describe(query)", "structured HelpEntry"),
        ("mp.reference.search(term)", "structured SearchResult"),
        ("mp.reference.render(entry, fmt)", "text | markdown | json"),
        ("mp help QUERY...", "CLI (no auth); also: python3 -m mixpanel_headless help"),
    )
    grammar = (
        "Workspace | Workspace.<method> | Workspace.<method>.<param>",
        "<Type> | <Enum> | <LiteralAlias> | <Exception> | <function>",
        "accounts | session | targets | types | exceptions | help",
        "search <term>",
    )
    cells = [f"{title} ({len(names)})" for title, names in WORKSPACE_DOMAINS]
    half = (len(cells) + 1) // 2
    rows = [
        f"  {left:<40} {right}".rstrip()
        for left, right in zip(cells[:half], cells[half:] + [""], strict=False)
    ]
    member_count = len(workspace_members())
    lines = [
        "import mixpanel_headless as mp",
        "",
        "Entry points:",
        *(f"  {name:<34} {text}" for name, text in entry_points),
        "",
        "Queries (mp.help('help') for the full table):",
        *(f"  {line}" for line in grammar),
        "",
        f"Workspace domains ({len(WORKSPACE_DOMAINS)} domains, {member_count} members;"
        " mp.help('Workspace', domain=...)):",
        *rows,
        "",
        f"Docs index for agents: {_LLMS_URL}",
    ]
    body = "\n".join(lines)
    return HelpEntry(
        kind="overview",
        name=_PACKAGE,
        qualname=_PACKAGE,
        summary=package.__version__,
        doc=DocSections(summary=_summary(package), body=body),
    )


def _types_listing() -> HelpEntry:
    """Build the ``types`` listing: public types grouped by kind.

    ``Workspace`` is the facade, not a type, so it is left out.

    Returns:
        The ``listing`` entry with six groups and no hints.
    """
    from mixpanel_headless._internal.help.inventory import exports_of_kind

    groups = tuple(
        Group(
            title,
            tuple(
                MemberDoc(
                    row.name, row.kind, _member_summary(row.obj, row.kind, row.name)
                )
                for row in exports_of_kind(kind)
                if row.name != "Workspace"
            ),
        )
        for title, kind in _TYPES_LISTING_GROUPS
    )
    total = sum(len(group.items) for group in groups)
    return HelpEntry(
        kind="listing",
        name="types",
        qualname="types",
        summary=f"{total} public types",
        doc=DocSections(),
        groups=groups,
    )


def _exceptions_listing() -> HelpEntry:
    """Build the ``exceptions`` listing as an indented tree.

    Returns:
        The ``listing`` entry with one ``Exceptions`` group and no hints.
    """
    from mixpanel_headless._internal.help.relations import exception_tree

    items = tuple(
        MemberDoc(f"{'  ' * depth}{name}", "exception", _export_summary(name))
        for name, depth in exception_tree()
    )
    return HelpEntry(
        kind="listing",
        name="exceptions",
        qualname="exceptions",
        summary=f"{len(items)} exceptions",
        doc=DocSections(),
        groups=(Group("Exceptions", items),),
    )


def _export_summary(name: str) -> str:
    """Return the first docstring line of an export by name.

    Args:
        name: Export name.

    Returns:
        The summary, or ``""`` when the name is not an export.
    """
    from mixpanel_headless._internal.help.inventory import export

    row = export(name)
    return _summary(row.obj) if row is not None else ""


def _workspace_listing(domain: str | None) -> HelpEntry:
    """Build the grouped ``Workspace`` listing.

    Args:
        domain: ``None`` for every group (properties first, then the
            registry order); otherwise a domain title or unique prefix.

    Returns:
        The ``listing`` entry.

    Raises:
        HelpDomainError: When ``domain`` matches no title or several titles.
    """
    from mixpanel_headless._internal.help.inventory import workspace_members
    from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS
    from mixpanel_headless.workspace import Workspace

    kinds = dict(workspace_members())
    domains = WORKSPACE_DOMAINS
    groups: list[Group] = []
    if domain is not None:
        title = _match_domain(domain)
        domains = tuple(pair for pair in WORKSPACE_DOMAINS if pair[0] == title)
    else:
        properties = tuple(
            MemberDoc(
                name, "property", _summary(inspect.getattr_static(Workspace, name))
            )
            for name, kind in workspace_members()
            if kind == "property"
        )
        groups.append(Group("properties", properties))
    for title, names in domains:
        items = tuple(
            _member_doc(name, getattr(Workspace, name), kinds.get(name, "method"))
            for name in names
        )
        groups.append(Group(title, items))
    return HelpEntry(
        kind="listing",
        name=_WORKSPACE,
        qualname=_WORKSPACE,
        summary=_summary(Workspace),
        doc=_doc(Workspace),
        groups=tuple(groups),
        hints=_hints(_WORKSPACE, "listing"),
    )


def _match_domain(domain: str) -> str:
    """Match a user-typed domain against the registry titles.

    Only the ``Workspace`` listing accepts a domain, so the error's
    ``query`` is always ``"Workspace"``.

    Args:
        domain: Domain text; case-insensitive; a unique prefix is accepted.

    Returns:
        The registered title.

    Raises:
        HelpDomainError: ``reason="ambiguous"`` with the candidate titles in
            ``domains`` when several share the prefix; ``reason="unknown"``
            with every title in ``domains`` when nothing matches.
    """
    from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS

    titles = tuple(title for title, _ in WORKSPACE_DOMAINS)
    wanted = " ".join(domain.split()).casefold()
    if wanted in titles:
        return wanted
    prefixed = (
        tuple(title for title in titles if title.startswith(wanted)) if wanted else ()
    )
    if len(prefixed) == 1:
        return prefixed[0]
    if prefixed:
        raise HelpDomainError(
            _WORKSPACE, domain=domain, domains=prefixed, reason="ambiguous"
        )
    raise HelpDomainError(_WORKSPACE, domain=domain, domains=titles, reason="unknown")


# -----------------------------------------------------------------------------
# callables
# -----------------------------------------------------------------------------


def _callable_entry(target: Target) -> HelpEntry:
    """Build a ``method`` or ``function`` entry.

    Args:
        target: A callable target.

    Returns:
        The entry. ``see_also`` and the single domain ``Group`` are set only
        for ``Workspace.<method>`` queries.
    """
    from mixpanel_headless._internal.help.introspect import signature_doc
    from mixpanel_headless._internal.help.relations import referenced_types, see_also

    display = target.member or target.qualname
    owner = target.owner if isinstance(target.owner, type) else None
    domain_title, siblings = see_also(target.qualname)
    groups = (Group(domain_title, ()),) if domain_title else ()
    return HelpEntry(
        kind=target.kind,
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(target.obj),
        doc=_doc(target.obj),
        signature=signature_doc(target.obj, name=display, owner=owner),
        groups=groups,
        referenced_types=referenced_types(target.obj),
        see_also=siblings,
        hints=_hints(target.qualname, target.kind),
    )


def _property_entry(target: Target) -> HelpEntry:
    """Build a ``property`` entry: return annotation plus docstring.

    Args:
        target: A property target (``obj`` is the descriptor).

    Returns:
        The entry; ``signature.returns`` is the getter's return annotation.
    """
    from mixpanel_headless._internal.help.introspect import format_type

    descriptor = target.obj
    getter = descriptor.fget if isinstance(descriptor, property) else None
    returns: str | None = None
    if getter is not None:
        try:
            annotation = inspect.signature(getter).return_annotation
        except (TypeError, ValueError):
            annotation = inspect.Signature.empty
        if annotation is not inspect.Signature.empty:
            returns = format_type(annotation)
    name = target.member or target.qualname
    return HelpEntry(
        kind="property",
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(descriptor),
        doc=_doc(descriptor),
        signature=SignatureDoc(name=name, returns=returns),
        hints=_hints(target.qualname, "property"),
    )


def _parameter_entry(target: Target) -> HelpEntry:
    """Build a ``parameter`` entry from the owning callable's signature.

    Args:
        target: A parameter target (``owner`` is the callable, ``member``
            the parameter name).

    Returns:
        The entry; ``signature.params`` holds exactly the one ``ParamDoc``.

    Raises:
        HelpLookupError: When the owner's rendered signature has no
            parameter of that name (the resolver and the signature builder
            disagree). The owner is the only suggestion.
    """
    from mixpanel_headless._internal.help.introspect import signature_doc

    owner_name = target.owner_name or ""
    method = owner_name.rsplit(".", 1)[-1]
    full = signature_doc(target.owner, name=method)
    wanted = target.member or ""
    param = next((p for p in full.params if p.name.lstrip("*") == wanted), None)
    if param is None:
        raise HelpLookupError(
            target.qualname, suggestions=(owner_name,) if owner_name else ()
        )
    return HelpEntry(
        kind="parameter",
        name=target.qualname,
        qualname=target.qualname,
        summary=param.description,
        doc=DocSections(summary=param.description, body=param.description),
        signature=SignatureDoc(name=method, params=(param,), returns=full.returns),
        values=param.values,
        hints=_hints(target.qualname, "parameter"),
    )


# -----------------------------------------------------------------------------
# classes, enums, aliases, exceptions, modules, constants
# -----------------------------------------------------------------------------


def _class_entry(target: Target) -> HelpEntry:
    """Build a ``class``, ``model``, or ``dataclass`` entry.

    Args:
        target: A class target.

    Returns:
        The entry with bases, config (models only), construction, fields,
        properties, methods, used by, and hint.
    """
    from pydantic import BaseModel

    from mixpanel_headless._internal.help.introspect import (
        bases_doc,
        class_sections,
        dataclass_fields_doc,
        model_config_doc,
        pydantic_fields_doc,
    )
    from mixpanel_headless._internal.help.relations import used_by

    cls = typing.cast("type", target.obj)
    construction, properties, methods = class_sections(cls)
    fields: tuple[FieldDoc, ...] = ()
    config: tuple[tuple[str, str], ...] = ()
    if target.kind == "model" and issubclass(cls, BaseModel):
        fields = pydantic_fields_doc(cls)
        config = model_config_doc(cls)
    elif target.kind == "dataclass":
        fields = dataclass_fields_doc(cls)
    return HelpEntry(
        kind=target.kind,
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(cls),
        doc=_doc(cls),
        bases=bases_doc(cls),
        config=config,
        construction=construction,
        fields=fields,
        properties=properties,
        methods=methods,
        used_by=used_by(target.qualname),
        hints=_hints(target.qualname, target.kind),
    )


def _enum_entry(target: Target) -> HelpEntry:
    """Build an ``enum`` entry: member table, docstring, used by.

    Args:
        target: An enum class target.

    Returns:
        The entry; each member is a ``FieldDoc`` and ``values`` holds names.
    """
    from mixpanel_headless._internal.help.introspect import (
        bases_doc,
        enum_members,
        enum_values,
    )
    from mixpanel_headless._internal.help.relations import used_by

    cls = typing.cast("type[enum.Enum]", target.obj)
    fields = tuple(
        FieldDoc(name=name, annotation=type(cls[name].value).__name__, default=value)
        for name, value in enum_members(cls)
    )
    return HelpEntry(
        kind="enum",
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(cls),
        doc=_doc(cls),
        bases=bases_doc(cls),
        fields=fields,
        values=enum_values(cls),
        used_by=used_by(target.qualname),
        hints=_hints(target.qualname, "enum"),
    )


def _literal_entry(target: Target) -> HelpEntry:
    """Build a ``literal`` entry: allowed values, docs line, used by.

    Args:
        target: A Literal alias target.

    Returns:
        The entry.
    """
    from mixpanel_headless._internal.help.introspect import allowed_values
    from mixpanel_headless._internal.help.relations import used_by

    summary = _alias_doc(target.qualname)
    return HelpEntry(
        kind="literal",
        name=target.qualname,
        qualname=target.qualname,
        summary=summary,
        doc=DocSections(summary=summary, body=summary),
        values=allowed_values(target.obj),
        used_by=used_by(target.qualname),
        hints=_hints(target.qualname, "literal"),
    )


def _alias_members(obj: object) -> tuple[object, ...]:
    """Expand a Union / Annotated alias into its member types.

    Args:
        obj: The alias object.

    Returns:
        The union members; for ``Annotated[X, ...]`` the members of ``X``
        (or ``X`` itself when it is not a union).
    """
    if typing.get_origin(obj) is typing.Annotated:
        obj = typing.get_args(obj)[0]
    if typing.get_origin(obj) in (typing.Union, types.UnionType):
        return tuple(typing.get_args(obj))
    return (obj,)


def _alias_entry(target: Target) -> HelpEntry:
    """Build an ``alias`` entry: expanded members with first doc lines.

    Args:
        target: A Union / Annotated alias target.

    Returns:
        The entry; ``values`` holds member display names and
        ``referenced_types`` the ``(name, summary)`` rows for members that
        are exports.
    """
    from mixpanel_headless._internal.help.introspect import format_type
    from mixpanel_headless._internal.help.inventory import export
    from mixpanel_headless._internal.help.relations import used_by

    members = _alias_members(target.obj)
    values = tuple(format_type(member) for member in members)
    referenced: list[tuple[str, str]] = []
    for member, display in zip(members, values, strict=True):
        row = export(display)
        if row is not None and row.obj is member:
            referenced.append((display, _summary(member)))
    summary = _alias_doc(target.qualname)
    return HelpEntry(
        kind="alias",
        name=target.qualname,
        qualname=target.qualname,
        summary=summary,
        doc=DocSections(summary=summary, body=summary),
        values=values,
        referenced_types=tuple(referenced),
        used_by=used_by(target.qualname),
        hints=_hints(target.qualname, "alias"),
    )


def _exception_entry(target: Target) -> HelpEntry:
    """Build an ``exception`` entry: base, docstring, subclass tree, raised by.

    Args:
        target: An exception class target.

    Returns:
        The entry. The subclass tree is one ``Group`` titled ``Subclasses``
        whose item names carry two leading spaces per nesting level; the
        group is omitted for a leaf exception.
    """
    from mixpanel_headless._internal.help.introspect import bases_doc
    from mixpanel_headless._internal.help.relations import exception_tree, raised_by

    cls = typing.cast("type[BaseException]", target.obj)
    items = tuple(
        MemberDoc(f"{'  ' * (depth - 1)}{name}", "exception", _export_summary(name))
        for name, depth in exception_tree(cls)[1:]
    )
    return HelpEntry(
        kind="exception",
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(cls),
        doc=_doc(cls),
        bases=bases_doc(cls),
        groups=(Group("Subclasses", items),) if items else (),
        used_by=raised_by(target.qualname),
        hints=_hints(target.qualname, "exception"),
    )


def _module_entry(target: Target) -> HelpEntry:
    """Build a ``module`` entry: ``__all__`` members with summaries.

    Args:
        target: A namespace-module target.

    Returns:
        The entry with one ``Members`` group.
    """
    from mixpanel_headless._internal.help.inventory import classify, module_members

    module = typing.cast("types.ModuleType", target.obj)
    items = tuple(
        _member_doc(name, getattr(module, name), classify(getattr(module, name)))
        for name in module_members(module)
    )
    return HelpEntry(
        kind="module",
        name=target.qualname,
        qualname=target.qualname,
        summary=_summary(module),
        doc=_doc(module),
        groups=(Group("Members", items),),
        hints=_hints(target.qualname, "module"),
    )


def _constant_entry(target: Target) -> HelpEntry:
    """Build a ``constant`` entry: value and type.

    An enum member (``FeatureFlagStatus.ENABLED``) is typed by its enum and
    summarised by the enum's docstring; a plain export is typed by its
    Python type and summarised from ``ALIAS_DOCS``.

    Args:
        target: A constant target.

    Returns:
        The entry; ``bases[0]`` is the type name and ``values[0]`` the value.
    """
    obj = target.obj
    if isinstance(obj, enum.Enum):
        type_name = type(obj).__name__
        value = repr(obj.value)
        summary = _summary(type(obj))
    else:
        type_name = type(obj).__name__
        value = repr(obj)
        summary = _alias_doc(target.qualname)
    return HelpEntry(
        kind="constant",
        name=target.qualname,
        qualname=target.qualname,
        summary=summary,
        doc=DocSections(summary=summary, body=summary),
        bases=(type_name,),
        values=(value,),
        hints=_hints(target.qualname, "constant"),
    )


_ENTRY_BUILDERS: dict[HelpKind, Callable[[Target], HelpEntry]] = {
    "method": _callable_entry,
    "function": _callable_entry,
    "property": _property_entry,
    "parameter": _parameter_entry,
    "class": _class_entry,
    "model": _class_entry,
    "dataclass": _class_entry,
    "enum": _enum_entry,
    "literal": _literal_entry,
    "alias": _alias_entry,
    "exception": _exception_entry,
    "module": _module_entry,
    "constant": _constant_entry,
}
"""Entry builder per target kind.

``overview`` and ``listing`` are absent on purpose: their entries are
synthesized without a ``Target`` object, and ``_assemble`` handles them
before consulting this table. Together the two cover every ``HelpKind``.
"""
