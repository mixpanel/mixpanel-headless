"""Registry adapters for the built-in help (``help.*`` apis).

The help system's pure layer — query grammar, domain matching, hint
selection, tiered search, suggestions, the three renderers, and the two
error types — is language-neutral once its inputs are plain JSON. These
adapters give each piece a JSON-in / JSON-out shape so the authored help
vectors (``gen_help_vectors.py``) can freeze its behavior for other ports:

- Model inputs (``HelpEntry``, ``SearchResult``, ``SearchHit``) arrive as
  their ``to_dict()`` form and are rebuilt here. The corpus serializer
  sorts object keys, so the rebuild never depends on key order; rendered
  ``json`` output still follows ``to_dict()`` order.
- :func:`search` runs the real index pipeline (``build_index`` then
  ``search_index``) over a SUPPLIED index instead of the live inventory,
  and takes the "Did you mean?" candidates explicitly, so nothing depends
  on Python docstrings or export names.
- Hints come back as ``{title, path}`` with the docs source path of the
  winning rule instead of the hosted URL, which is site-specific.
- Errors come back as ``{class, code, message, details}`` objects; the
  vector schema's ``expect.error`` cannot carry a message, and the message
  text is part of the contract here.

All adapters delegate to the library code — they add shape, never behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from mixpanel_headless._internal.help import hints as help_hints
from mixpanel_headless._internal.help import render as help_render
from mixpanel_headless._internal.help import resolve as help_resolve
from mixpanel_headless._internal.help import search as help_search
from mixpanel_headless._internal.help.models import (
    DocSections,
    FieldDoc,
    Group,
    HelpEntry,
    HelpFormat,
    HelpKind,
    Hint,
    MatchedOn,
    MemberDoc,
    MemberKind,
    ParamDoc,
    ParamKind,
    SearchHit,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)
from mixpanel_headless._internal.help.registry import (
    REFERENCE_HINTS,
    WORKSPACE_HINT,
    hint_url,
)
from mixpanel_headless.exceptions import (
    HelpDomainError,
    HelpDomainReason,
    HelpLookupError,
)

# =============================================================================
# Model rebuilds from to_dict() form
# =============================================================================


def _pairs(rows: Sequence[Sequence[str]]) -> tuple[tuple[str, str], ...]:
    """Rebuild a pair tuple from its list-of-two-item-lists form.

    Args:
        rows: ``[[first, second], ...]``.

    Returns:
        ``((first, second), ...)``.
    """
    return tuple((str(first), str(second)) for first, second in rows)


def _param(data: Mapping[str, Any]) -> ParamDoc:
    """Rebuild a ``ParamDoc`` from its dict form.

    Args:
        data: ``ParamDoc.to_dict()`` output.

    Returns:
        The model.
    """
    return ParamDoc(
        name=data["name"],
        annotation=data["annotation"],
        default=data["default"],
        description=data["description"],
        values=tuple(data["values"]),
        kind=cast("ParamKind", data["kind"]),
    )


def _signature(data: Mapping[str, Any] | None) -> SignatureDoc | None:
    """Rebuild a ``SignatureDoc`` from its dict form.

    Args:
        data: ``SignatureDoc.to_dict()`` output, or ``None``.

    Returns:
        The model, or ``None``.
    """
    if data is None:
        return None
    return SignatureDoc(
        name=data["name"],
        params=tuple(_param(param) for param in data["params"]),
        returns=data["returns"],
    )


def _member(data: Mapping[str, Any]) -> MemberDoc:
    """Rebuild a ``MemberDoc`` from its dict form.

    Args:
        data: ``MemberDoc.to_dict()`` output.

    Returns:
        The model.
    """
    return MemberDoc(
        name=data["name"],
        kind=cast("MemberKind", data["kind"]),
        summary=data["summary"],
        signature=_signature(data["signature"]),
        depth=data["depth"],
    )


def _field(data: Mapping[str, Any]) -> FieldDoc:
    """Rebuild a ``FieldDoc`` from its dict form.

    Args:
        data: ``FieldDoc.to_dict()`` output.

    Returns:
        The model.
    """
    return FieldDoc(
        name=data["name"],
        annotation=data["annotation"],
        default=data["default"],
        required=data["required"],
        constraints=tuple(data["constraints"]),
        alias=data["alias"],
        values=tuple(data["values"]),
        description=data["description"],
    )


def _doc(data: Mapping[str, Any]) -> DocSections:
    """Rebuild a ``DocSections`` from its dict form.

    Args:
        data: ``DocSections.to_dict()`` output.

    Returns:
        The model.
    """
    return DocSections(
        summary=data["summary"],
        body=data["body"],
        args=_pairs(data["args"]),
        returns=data["returns"],
        raises=_pairs(data["raises"]),
        example=data["example"],
        notes=data["notes"],
    )


def entry_from_dict(data: Mapping[str, Any]) -> HelpEntry:
    """Rebuild a ``HelpEntry`` from its ``to_dict()`` form.

    Args:
        data: ``HelpEntry.to_dict()`` output (any key order).

    Returns:
        The entry; ``entry_from_dict(e.to_dict()) == e`` for every entry.

    Raises:
        KeyError: When a field is missing.
    """
    return HelpEntry(
        kind=cast("HelpKind", data["kind"]),
        name=data["name"],
        qualname=data["qualname"],
        summary=data["summary"],
        doc=_doc(data["doc"]),
        signature=_signature(data["signature"]),
        bases=tuple(data["bases"]),
        config=_pairs(data["config"]),
        construction=tuple(_member(row) for row in data["construction"]),
        fields=tuple(_field(row) for row in data["fields"]),
        properties=tuple(_member(row) for row in data["properties"]),
        methods=tuple(_member(row) for row in data["methods"]),
        values=tuple(data["values"]),
        value=data["value"],
        groups=tuple(
            Group(group["title"], tuple(_member(row) for row in group["items"]))
            for group in data["groups"]
        ),
        referenced_types=_pairs(data["referenced_types"]),
        used_by=tuple(
            UsageDoc(row["method"], tuple(row["params"])) for row in data["used_by"]
        ),
        domain=data["domain"],
        see_also=tuple(data["see_also"]),
        hints=tuple(Hint(row["title"], row["url"]) for row in data["hints"]),
    )


def hit_from_dict(data: Mapping[str, Any]) -> SearchHit:
    """Rebuild a ``SearchHit`` from its ``to_dict()`` form.

    Args:
        data: ``SearchHit.to_dict()`` output.

    Returns:
        The hit.
    """
    return SearchHit(
        category=cast("MemberKind", data["category"]),
        name=data["name"],
        summary=data["summary"],
        matched_on=cast("MatchedOn", data["matched_on"]),
    )


def result_from_dict(data: Mapping[str, Any]) -> SearchResult:
    """Rebuild a ``SearchResult`` from its ``to_dict()`` form.

    Args:
        data: ``SearchResult.to_dict()`` output.

    Returns:
        The result.
    """
    return SearchResult(
        term=data["term"],
        hits=tuple(hit_from_dict(row) for row in data["hits"]),
        suggestions=tuple(data["suggestions"]),
    )


def _error_dict(exc: HelpLookupError) -> dict[str, Any]:
    """Flatten a help error into its conformance shape.

    Args:
        exc: A ``HelpLookupError`` or ``HelpDomainError``.

    Returns:
        ``{"class", "code", "message", "details"}``.
    """
    return {
        "class": type(exc).__name__,
        "code": exc.code,
        "message": exc.message,
        "details": exc.details,
    }


# =============================================================================
# Grammar, hints, domains
# =============================================================================


def parse_query(text: str) -> list[str]:
    """Return ``resolve.parse_query(text)`` as a two-item list.

    Args:
        text: Raw help query text.

    Returns:
        ``[mode, payload]``.

    Example:
        ```python
        parse_query("search   cohort")
        # ['search', 'cohort']
        ```
    """
    mode, payload = help_resolve.parse_query(text)
    return [mode, payload]


def tokens(query: str) -> list[str]:
    """Return ``hints.tokens(query)`` as a list.

    Args:
        query: Raw help query text.

    Returns:
        The whole tokens in order.
    """
    return list(help_hints.tokens(query))


_PATH_BY_URL: dict[str, str] = {
    hint_url(path): path
    for path in (WORKSPACE_HINT[1], *(r[2] for r in REFERENCE_HINTS))
}
"""Hosted URL -> docs source path over every hint rule (paths are unique per URL)."""


def hints_for(tokens: list[str], kind: str) -> list[dict[str, str]]:
    """Return ``hints.hints_for`` with each hint as ``{title, path}``.

    Args:
        tokens: Query tokens (any case).
        kind: The resolved ``HelpKind``.

    Returns:
        Zero or one ``{"title", "path"}`` objects; ``path`` is the docs
        source path of the winning rule.
    """
    found = help_hints.hints_for(tuple(tokens), kind=cast("HelpKind", kind))
    return [{"title": hint.title, "path": _PATH_BY_URL[hint.url]} for hint in found]


def match_domain(domain: str) -> dict[str, Any]:
    """Match a ``domain=`` filter against the registered domain titles.

    Args:
        domain: The user-typed domain text.

    Returns:
        ``{"title": <registered title>}`` on a match, or
        ``{"error": {class, code, message, details}}`` when the domain is
        unknown or an ambiguous prefix.
    """
    from mixpanel_headless import reference

    try:
        return {"title": reference._match_domain(domain)}
    except HelpDomainError as exc:
        return {"error": _error_dict(exc)}


def suggestions(candidates: list[list[str]], query: str) -> list[str]:
    """Return the root-level "Did you mean?" names over supplied candidates.

    The live ``suggestions_for`` builds ``candidates`` from the inventory
    (export names, then ``Workspace`` members shown as
    ``Workspace.<name>``); this adapter takes them explicitly.

    Args:
        candidates: ``[[key, display], ...]``; ``key`` is compared,
            ``display`` returned. Keys must be unique.
        query: The missed text.

    Returns:
        Up to five display strings in ``difflib`` similarity order.
    """
    display = {row[0]: row[1] for row in candidates}
    return list(help_resolve._close_matches(query, display))


def child_suggestions(wanted: str, candidates: list[str], parent: str) -> list[str]:
    """Return the "Did you mean?" names for a dotted miss below ``parent``.

    Args:
        wanted: The segment that matched nothing.
        candidates: The parent's public member names.
        parent: Canonical query string of the parent.

    Returns:
        Close members prefixed with ``parent.``, or ``[parent]`` when none
        is close.
    """
    return list(help_resolve._child_suggestions(wanted, candidates, parent))


# =============================================================================
# Search
# =============================================================================


def search(
    index: list[dict[str, Any]],
    term: str,
    limit: int | None = None,
    suggestion_candidates: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Search a supplied index with the library's tier, sort, and limit rules.

    Args:
        index: Raw rows ``{category, name, summary, members}`` in view
            order; they go through ``build_index`` (first row per
            ``(category, name)`` wins, then sort) exactly as the live rows.
        term: The search term.
        limit: As ``reference.search``.
        suggestion_candidates: ``[[key, display], ...]`` for the miss
            suggestions (see :func:`suggestions`); none when omitted.

    Returns:
        ``SearchResult.to_dict()``; ``{"error": {class, code, message,
        details}}`` for a blank term; ``{"error": {"class": "ValueError",
        "message"}}`` for a negative ``limit``.
    """
    rows = help_search.build_index(
        help_search.IndexEntry(
            cast("MemberKind", row["category"]),
            row["name"],
            row["summary"],
            tuple(row["members"]),
        )
        for row in index
    )
    display = {row[0]: row[1] for row in suggestion_candidates or ()}
    try:
        result = help_search.search_index(
            rows,
            term,
            limit=limit,
            suggest=lambda text: help_resolve._close_matches(text, display),
        )
    except HelpLookupError as exc:
        return {"error": _error_dict(exc)}
    except ValueError as exc:
        return {"error": {"class": "ValueError", "message": str(exc)}}
    return result.to_dict()


# =============================================================================
# Rendering
# =============================================================================


def render(entry: dict[str, Any], format: str, code_lang: str = "python") -> str:
    """Render a ``HelpEntry`` given in its ``to_dict()`` form.

    Args:
        entry: ``HelpEntry.to_dict()`` output.
        format: ``"text"``, ``"markdown"``, or ``"json"``.
        code_lang: Markdown code-fence language (library default
            ``"python"``).

    Returns:
        The rendered string, without a trailing newline.
    """
    return help_render.render(
        entry_from_dict(entry), cast("HelpFormat", format), code_lang=code_lang
    )


def render_search(result: dict[str, Any], format: str) -> str:
    """Render a ``SearchResult`` given in its ``to_dict()`` form.

    Args:
        result: ``SearchResult.to_dict()`` output.
        format: ``"text"``, ``"markdown"``, or ``"json"``.

    Returns:
        The rendered string.
    """
    return help_render.render(result_from_dict(result), cast("HelpFormat", format))


def render_miss(
    query: str,
    format: str,
    suggestions: list[str] | None = None,
    hits: list[dict[str, Any]] | None = None,
) -> str:
    """Render a lookup miss as ``help()`` prints it.

    Args:
        query: The missed query.
        format: ``"text"``, ``"markdown"``, or ``"json"``.
        suggestions: Close names carried by the error.
        hits: ``SearchHit.to_dict()`` rows carried by the error; only the
            first five render.

    Returns:
        The rendered miss.
    """
    from mixpanel_headless import reference

    exc = HelpLookupError(
        query,
        suggestions=tuple(suggestions or ()),
        hits=tuple(hit_from_dict(row) for row in hits or ()),
    )
    return reference.render_miss(exc, cast("HelpFormat", format))


def search_usage(format: str) -> str:
    """Return the text ``help()`` prints for a bare ``search`` query.

    Args:
        format: ``"text"``, ``"markdown"``, or ``"json"``.

    Returns:
        The usage text, or a JSON object with a ``usage`` key for ``json``.
    """
    from mixpanel_headless import reference

    return reference._search_usage(cast("HelpFormat", format))


# =============================================================================
# Errors
# =============================================================================


def lookup_error(
    query: str,
    suggestions: list[str] | None = None,
    hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct a ``HelpLookupError`` and return its conformance shape.

    Args:
        query: The missed query.
        suggestions: Close names.
        hits: ``SearchHit.to_dict()`` rows.

    Returns:
        ``{"class", "code", "message", "details"}``.
    """
    exc = HelpLookupError(
        query,
        suggestions=tuple(suggestions or ()),
        hits=tuple(hit_from_dict(row) for row in hits or ()),
    )
    return _error_dict(exc)


def domain_error(
    query: str,
    domain: str,
    domains: list[str] | None = None,
    reason: str = "unknown",
) -> dict[str, Any]:
    """Construct a ``HelpDomainError`` and return its conformance shape.

    Args:
        query: The help query the filter was applied to.
        domain: The rejected domain text.
        domains: Titles to offer.
        reason: ``"unknown"``, ``"ambiguous"``, or ``"not_workspace"``.

    Returns:
        ``{"class", "code", "message", "details"}``.
    """
    exc = HelpDomainError(
        query,
        domain=domain,
        domains=tuple(domains or ()),
        reason=cast("HelpDomainReason", reason),
    )
    return _error_dict(exc)
