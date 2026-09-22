"""Hosted-documentation hints for the built-in API reference.

:func:`hints_for` picks at most one :class:`~.models.Hint` for a query:

1. The bare ``Workspace`` query points at the hosted API page
   (:data:`~.registry.WORKSPACE_HINT`), whatever its kind.
2. Any other ``listing`` (``types``, ``exceptions``) gets no hint.
3. Otherwise the first :data:`~.registry.REFERENCE_HINTS` rule whose trigger
   set intersects the query's token set wins.

Tokens are **whole** words: :func:`tokens` splits a query on ``.`` and
whitespace only, so ``query_funnel`` stays one token and the generic
``query`` trigger cannot false-positive on ``query_saved_report``.
Comparison is case-insensitive so ``filter`` finds the ``Filter`` trigger.
The module is pure: it reads the registry tables and builds URLs, nothing
else.
"""

from __future__ import annotations

from typing import Final

from mixpanel_headless._internal.help.models import HelpKind, Hint
from mixpanel_headless._internal.help.registry import (
    REFERENCE_HINTS,
    WORKSPACE_HINT,
    hint_url,
)

__all__ = ["hints_for", "tokens"]

_WORKSPACE_TOKEN: Final[str] = "workspace"
"""Lowercased token that, alone, selects the ``Workspace`` API-page hint."""

_WORKSPACE_HINT: Final[Hint] = Hint(WORKSPACE_HINT[0], hint_url(WORKSPACE_HINT[1]))
"""The hint for the bare ``Workspace`` query, built once."""

_RULES: Final[tuple[tuple[frozenset[str], Hint], ...]] = tuple(
    (frozenset(trigger.lower() for trigger in triggers), Hint(title, hint_url(path)))
    for triggers, title, path in REFERENCE_HINTS
)
"""``REFERENCE_HINTS`` with lowercased trigger sets and prebuilt hints, in table order."""


def tokens(query: str) -> tuple[str, ...]:
    """Split a help query into whole tokens.

    Only ``.`` and whitespace separate tokens; underscores are kept so a
    method name such as ``query_funnel`` matches its trigger as one word.

    Args:
        query: Raw query text, for example ``"Workspace.query_funnel"`` or
            ``"search cohort"``.

    Returns:
        Non-empty tokens in order, original case preserved.

    Example:
        ```python
        tokens("Workspace.query_funnel")
        # ("Workspace", "query_funnel")
        ```
    """
    return tuple(part for part in query.replace(".", " ").split() if part)


def hints_for(query_tokens: tuple[str, ...], *, kind: HelpKind) -> tuple[Hint, ...]:
    """Return the documentation hint for a query, if any.

    Args:
        query_tokens: Output of :func:`tokens` for the query. Case does not
            matter.
        kind: The resolved ``HelpKind``; ``"listing"`` suppresses hints
            except for the bare ``Workspace`` query.

    Returns:
        A one-element tuple with the winning hint, or ``()``.

    Example:
        ```python
        hints_for(tokens("Workspace.query_funnel"), kind="method")[0].url
        # "https://mixpanel.github.io/mixpanel-headless/guide/query-funnels/index.md"
        hints_for(tokens("types"), kind="listing")
        # ()
        ```
    """
    lowered = tuple(token.lower() for token in query_tokens)
    if lowered == (_WORKSPACE_TOKEN,):
        return (_WORKSPACE_HINT,)
    if kind == "listing":
        return ()
    token_set = set(lowered)
    for triggers, hint in _RULES:
        if token_set & triggers:
            return (hint,)
    return ()
