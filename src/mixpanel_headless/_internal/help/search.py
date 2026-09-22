"""Case-insensitive substring search over the public surface.

:func:`search` ports the plugin script's ``help.py search`` onto the
inventory. It indexes three views of the library:

- every export in :func:`~mixpanel_headless._internal.help.inventory.inventory`,
  with its inventory kind as the category (``exception``, ``enum``, ``model``,
  ``dataclass``, ``class``, ``literal``, ``alias``, ``function``, ``module``,
  ``constant``); Literal aliases are ``literal``, not ``constant``, and
  Literal / Union aliases and constants carry their ``ALIAS_DOCS`` summary;
- every public ``Workspace`` member, displayed as ``Workspace.<name>`` with
  category ``method`` or ``property``;
- every ``__all__`` member of the namespace modules ``accounts``,
  ``session``, and ``targets``, displayed as ``<module>.<name>``.

Each entry matches in one of three tiers, and the highest tier wins:

1. ``name`` — the needle is in the display name;
2. ``doc`` — the needle is in the first docstring line;
3. ``member`` — the needle is in an enum member, indexed as
   ``member NAME = repr(value)`` (for example ``member ENABLED = 'enabled'``),
   or in a Literal value, indexed as ``value text``.

Hits are ordered by tier, then by ``(category, name)``. The index is keyed
on ``(category, name)``, so no pair repeats. A miss returns
``SearchResult(term, hits=(), suggestions=...)`` from
:func:`~mixpanel_headless._internal.help.resolve.suggestions_for` and
never raises for a non-empty term.

The text index is built once per inventory tuple and cached in module state.
:func:`clear_cache` drops it; a new inventory tuple (after
``inventory.clear_cache()``) also triggers a rebuild.
"""

from __future__ import annotations

import enum
import inspect
from dataclasses import dataclass

from mixpanel_headless._internal.help.docstrings import first_line
from mixpanel_headless._internal.help.introspect import allowed_values, enum_members
from mixpanel_headless._internal.help.inventory import (
    Export,
    classify,
    inventory,
    module_members,
    workspace_members,
)
from mixpanel_headless._internal.help.models import (
    MatchedOn,
    MemberKind,
    SearchHit,
    SearchResult,
)
from mixpanel_headless._internal.help.resolve import suggestions_for
from mixpanel_headless._literal_types import ALIAS_DOCS
from mixpanel_headless.exceptions import HelpLookupError

__all__ = ["clear_cache", "search"]


_NO_DOC_KINDS: frozenset[str] = frozenset({"literal", "alias", "constant"})
"""Kinds whose runtime object has no docstring of its own.

``inspect.getdoc`` on a ``Literal`` / ``Union`` alias or an ``int`` returns
the ``typing`` or builtin docstring, which is noise. These kinds read their
summary from ``ALIAS_DOCS`` instead and fall back to ``""``.
"""

_TIER_RANK: dict[MatchedOn, int] = {"name": 0, "doc": 1, "member": 2}
"""Sort rank for each ``matched_on`` tier (lower sorts first)."""


@dataclass(frozen=True, slots=True)
class _Entry:
    """One row of the search index.

    Attributes:
        category: Display category (inventory kind, ``method``, or ``property``).
        name: Display name; qualified for ``Workspace`` and module members.
        summary: First docstring line or ``ALIAS_DOCS`` text; ``""``
            when none exists.
        members: Searchable member texts for enums and Literal aliases, in
            definition order; empty for every other kind.
    """

    category: MemberKind
    name: str
    summary: str
    members: tuple[str, ...]

    def match(self, needle: str) -> SearchHit | None:
        """Return the hit for ``needle`` in the highest matching tier.

        Args:
            needle: Lower-cased search text; never empty.

        Returns:
            A ``SearchHit`` with ``matched_on`` set to the winning tier, or
            ``None`` when nothing in the entry contains ``needle``. A member
            hit shows the first matching member text as its summary.
        """
        if needle in self.name.lower():
            return SearchHit(self.category, self.name, self.summary, "name")
        if needle in self.summary.lower():
            return SearchHit(self.category, self.name, self.summary, "doc")
        for text in self.members:
            if needle in text.lower():
                return SearchHit(self.category, self.name, text, "member")
        return None


_INDEX: tuple[_Entry, ...] | None = None
_INDEX_SOURCE: tuple[Export, ...] | None = None


def _export_summary(row: Export) -> str:
    """Return the one-line summary for an inventory export.

    Args:
        row: The inventory row.

    Returns:
        ``ALIAS_DOCS[name]`` for Literal aliases, unions, and constants
        (``""`` when absent); otherwise the first docstring line.
    """
    if row.kind in _NO_DOC_KINDS:
        return ALIAS_DOCS.get(row.name, "")
    return first_line(inspect.getdoc(row.obj))


def _export_members(row: Export) -> tuple[str, ...]:
    """Return the searchable member texts for an inventory export.

    Args:
        row: The inventory row.

    Returns:
        ``member NAME = repr(value)`` per enum member, ``value text`` per
        Literal value, or ``()`` for every other kind.
    """
    if isinstance(row.obj, type) and issubclass(row.obj, enum.Enum):
        return tuple(
            f"member {name} = {value}" for name, value in enum_members(row.obj)
        )
    if row.kind == "literal":
        return tuple(f"value {value}" for value in allowed_values(row.obj))
    return ()


def _export_entries() -> list[_Entry]:
    """Build index rows for every inventory export.

    Returns:
        One row per export, category = inventory kind.
    """
    return [
        _Entry(row.kind, row.name, _export_summary(row), _export_members(row))
        for row in inventory()
    ]


def _workspace_entries() -> list[_Entry]:
    """Build index rows for the public ``Workspace`` members.

    Returns:
        One row per member named ``Workspace.<member>`` with category
        ``method`` or ``property`` and the member's first docstring line.
    """
    from mixpanel_headless.workspace import Workspace

    return [
        _Entry(
            kind,
            f"Workspace.{name}",
            first_line(inspect.getdoc(inspect.getattr_static(Workspace, name))),
            (),
        )
        for name, kind in workspace_members()
    ]


def _module_entries() -> list[_Entry]:
    """Build index rows for the members of every exported namespace module.

    Returns:
        One row per ``__all__`` member named ``<module>.<member>`` with the
        member's classified kind (``function`` for the current namespaces)
        and first docstring line.
    """
    entries: list[_Entry] = []
    for row in inventory():
        if row.kind != "module" or not inspect.ismodule(row.obj):
            continue
        for member in module_members(row.obj):
            obj = getattr(row.obj, member)
            entries.append(
                _Entry(
                    classify(obj),
                    f"{row.name}.{member}",
                    first_line(inspect.getdoc(obj)),
                    (),
                )
            )
    return entries


def _build_index() -> tuple[_Entry, ...]:
    """Build the deduplicated search index.

    Rows are keyed on ``(category, name)``; the first row for a key wins, so
    exports take precedence over any later view with the same display name.

    Returns:
        The index rows sorted by ``(category, name)``.
    """
    unique: dict[tuple[str, str], _Entry] = {}
    for entry in (*_export_entries(), *_workspace_entries(), *_module_entries()):
        unique.setdefault((entry.category, entry.name), entry)
    return tuple(sorted(unique.values(), key=lambda e: (e.category, e.name)))


def _index() -> tuple[_Entry, ...]:
    """Return the cached index, rebuilding it when the inventory changed.

    Returns:
        The index rows; the identical tuple on repeated calls until
        :func:`clear_cache` runs or the inventory tuple is replaced.
    """
    global _INDEX, _INDEX_SOURCE
    source = inventory()
    if _INDEX is None or _INDEX_SOURCE is not source:
        _INDEX = _build_index()
        _INDEX_SOURCE = source
    return _INDEX


def search(term: str, *, limit: int | None = None) -> SearchResult:
    """Search the public surface for a case-insensitive substring.

    Args:
        term: Text to look for. Surrounding whitespace is ignored for
            matching; the result echoes ``term`` as given. Inner spaces are
            part of the needle, not word separators.
        limit: Keep at most this many hits, from the front of the ordered
            list. ``None`` keeps every hit; ``0`` keeps none.

    Returns:
        A ``SearchResult`` whose ``hits`` are ordered by tier (``name``,
        ``doc``, ``member``) and then by ``(category, name)``, with no
        repeated ``(category, name)`` pair. On a miss ``hits`` is empty and
        ``suggestions`` holds up to five close names; the function
        never raises for a non-empty term.

    Raises:
        HelpLookupError: When ``term`` is empty or whitespace only. The
            error carries ``query=""`` and no suggestions; the public
            ``help("search")`` wrapper prints usage in that case.
        ValueError: When ``limit`` is negative.

    Example:
        ```python
        result = search("cohort", limit=3)
        [(h.category, h.name, h.matched_on) for h in result.hits]
        # [("class", "RetentionCohortData", "name"),
        #  ("dataclass", "CohortBreakdown", "name"),
        #  ("dataclass", "CohortCriteria", "name")]
        search("Filtr").suggestions
        # ("Filter", ...)
        ```
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")
    needle = term.strip().lower()
    if not needle:
        raise HelpLookupError("")
    matched = [hit for entry in _index() if (hit := entry.match(needle)) is not None]
    matched.sort(key=lambda h: (_TIER_RANK[h.matched_on], h.category, h.name))
    if not matched:
        return SearchResult(term=term, suggestions=suggestions_for(term.strip()))
    hits = tuple(matched if limit is None else matched[:limit])
    return SearchResult(term=term, hits=hits)


def clear_cache() -> None:
    """Drop the cached search index.

    The next :func:`search` call rebuilds the index from the live inventory.
    """
    global _INDEX, _INDEX_SOURCE
    _INDEX = None
    _INDEX_SOURCE = None
