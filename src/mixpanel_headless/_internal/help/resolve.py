"""Query resolution for the built-in help.

This module answers one question: *what object does this query name, and
what kind is it?* It stops there. Signature extraction, field listing, and
rendering live in later modules that consume the :class:`Target` it returns.

Two entry points:

- :func:`parse_query` splits raw help text into a mode (``overview``,
  ``search``, ``describe``) and a payload. The public API routes ``search``
  to the search module and passes the ``describe`` payload to
  :func:`resolve`.
- :func:`resolve` turns a describe query — a string or an object — into a
  :class:`Target`. Misses raise :class:`~mixpanel_headless.HelpLookupError`
  with "Did you mean?" suggestions; ``hits`` is always empty here and
  the public API layer adds search hits.

String grammar: the first dotted segment must be an inventory
name — an exact match, else a unique case-insensitive match. Later
segments walk members: ``Workspace.query`` (method), ``Workspace.account``
(property), ``Workspace.query.events`` (parameter), ``Filter.equals``
(classmethod), ``FeatureFlagStatus.ENABLED`` (enum member, ``constant``),
``accounts.add`` (namespace-module function). ``types`` and ``exceptions``
are ``listing`` targets; ``None`` or blank text is the ``overview``. Private
names (leading underscore) never resolve.

Object grammar: classes, functions, and modules resolve by identity in
the inventory; bound methods resolve through their owner *class* (the
instance is never used and no config is read); properties resolve through
their getter; instances resolve to their exported class; anything outside
``mixpanel_headless`` raises.

Nothing here performs I/O.
"""

from __future__ import annotations

import difflib
import enum
import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from mixpanel_headless._internal.help.inventory import (
    Export,
    classify,
    inventory,
    inventory_names,
    module_members,
    workspace_members,
)
from mixpanel_headless._internal.help.models import HelpKind
from mixpanel_headless.exceptions import HelpLookupError

__all__ = [
    "QueryMode",
    "Target",
    "parse_query",
    "resolve",
    "suggestions_for",
]

QueryMode = Literal["describe", "search", "overview"]
"""How :func:`parse_query` routes a raw help string."""

_PACKAGE = "mixpanel_headless"
_LISTINGS: frozenset[str] = frozenset({"types", "exceptions"})
_CLASS_KINDS: frozenset[str] = frozenset(
    {"class", "model", "dataclass", "enum", "exception"}
)
_CALLABLE_KINDS: frozenset[str] = frozenset({"method", "function"})
_SELF_NAMES: frozenset[str] = frozenset({"self", "cls"})
_SUGGESTION_LIMIT = 5
_SUGGESTION_CUTOFF = 0.5


@dataclass(frozen=True, slots=True)
class Target:
    """What a help query resolved to.

    ``obj`` and ``owner`` are excluded from equality and hashing, so two
    targets compare equal when ``kind``, ``qualname``, ``owner_name``, and
    ``member`` match.

    Attributes:
        kind: Classification of the resolved object.
        qualname: Canonical query string that re-resolves to this target
            (``"Workspace.query"``, ``"Filter"``, ``"accounts.add"``,
            ``""`` for the overview).
        obj: The resolved object. ``None`` for ``listing`` targets. For a
            ``property`` it is the descriptor; for a ``parameter`` it is the
            ``inspect.Parameter``.
        owner: The object that holds ``member`` (a class, a module, or the
            callable that owns a parameter). ``None`` at the package root.
        owner_name: Canonical query string of ``owner``.
        member: The attribute or parameter name on ``owner``.
    """

    kind: HelpKind
    qualname: str
    obj: object = field(compare=False)
    owner: object | None = field(default=None, compare=False)
    owner_name: str | None = None
    member: str | None = None


# =============================================================================
# Grammar
# =============================================================================


def parse_query(text: str) -> tuple[QueryMode, str]:
    """Split raw help text into a routing mode and its payload.

    Tokens are split on whitespace, so ``"search   cohort"`` and
    ``"search cohort"`` are equal. Only a lowercase leading ``search``
    token selects search mode.

    Args:
        text: Raw query text, for example from ``mp help QUERY...``.

    Returns:
        ``("overview", "")`` for blank text; ``("search", term)`` when the
        first token is ``search`` (``term`` may be empty); otherwise
        ``("describe", query)`` with the tokens re-joined by single spaces.

    Example:
        ```python
        parse_query("search cohort")     # ("search", "cohort")
        parse_query("Workspace.query")   # ("describe", "Workspace.query")
        parse_query("")                  # ("overview", "")
        ```
    """
    tokens = text.split()
    if not tokens:
        return ("overview", "")
    if tokens[0] == "search":
        return ("search", " ".join(tokens[1:]))
    return ("describe", " ".join(tokens))


# =============================================================================
# Resolution entry point
# =============================================================================


def resolve(query: str | object | None) -> Target:
    """Resolve a describe query to a :class:`Target`.

    Args:
        query: ``None`` or blank text for the overview; a dotted path from
            the package root; or a public object. A ``str``-based
            enum member is an object, not text. A ``search ...``
            string is not accepted here — route it with :func:`parse_query`
            first; passed directly it is a plain miss.

    Returns:
        The resolved target.

    Raises:
        HelpLookupError: When the query names nothing public. ``suggestions``
            holds close export and ``Workspace`` member names at the
            root; the parent's close members (prefixed with the parent) on a
            dotted miss, or the parent itself when nothing is close; the
            candidate names on an ambiguous case-insensitive match.
            ``hits`` is always empty.

    Example:
        ```python
        resolve("Workspace.query").kind          # "method"
        resolve("Workspace.query.events").kind   # "parameter"
        resolve(mp.Filter).qualname              # "Filter"
        ```
    """
    if query is None:
        return _overview()
    if isinstance(query, str) and not isinstance(query, enum.Enum):
        return _resolve_text(query)
    return _resolve_object(query)


def suggestions_for(query: str) -> tuple[str, ...]:
    """Return root-level "Did you mean?" names for a missed query.

    Candidates are every export name plus every public ``Workspace`` member
    name; a member that is not also an export is displayed as
    ``Workspace.<name>``.

    Args:
        query: The text that matched nothing.

    Returns:
        Up to five close names in ``difflib`` order, duplicates removed;
        empty when nothing is close.
    """
    display: dict[str, str] = {name: name for name in inventory_names()}
    for member, _kind in workspace_members():
        display.setdefault(member, f"Workspace.{member}")
    return _close_matches(query, display)


# =============================================================================
# String queries
# =============================================================================


def _overview() -> Target:
    """Build the overview target for the package itself.

    Returns:
        The ``overview`` target; ``obj`` is the package module.
    """
    import mixpanel_headless as package

    return Target(kind="overview", qualname="", obj=package)


def _resolve_text(text: str) -> Target:
    """Resolve a string query.

    Args:
        text: Raw query text; surrounding whitespace is ignored.

    Returns:
        The resolved target.

    Raises:
        HelpLookupError: On a miss, an ambiguous match, a private segment, or
            a malformed path (empty segment).
    """
    query = text.strip()
    if not query:
        return _overview()
    if query in _LISTINGS:
        return Target(kind="listing", qualname=query, obj=None)
    segments = query.split(".")
    if any(not segment or segment.startswith("_") for segment in segments):
        raise HelpLookupError(query, suggestions=suggestions_for(query))
    target = _root_target(segments[0], query)
    for segment in segments[1:]:
        target = _member_target(target, segment, query)
    return target


def _root_target(head: str, query: str) -> Target:
    """Resolve the first dotted segment against the inventory.

    Args:
        head: First segment of the query.
        query: Full query text, for the error.

    Returns:
        The export target (the package-level ``help`` function is an
        ordinary export, so ``help`` resolves here too).

    Raises:
        HelpLookupError: When ``head`` is not an export (suggestions from
            :func:`suggestions_for`) or matches several exports
            case-insensitively (the candidates as suggestions).
    """
    rows = {row.name: row for row in inventory()}
    matches = _match(head, tuple(rows))
    if len(matches) > 1:
        raise HelpLookupError(query, suggestions=tuple(matches))
    if matches:
        return _export_target(rows[matches[0]])
    raise HelpLookupError(query, suggestions=suggestions_for(head))


def _export_target(row: Export) -> Target:
    """Build the root target for an inventory row.

    Args:
        row: The inventory row.

    Returns:
        A root target with the row's kind, name, and object.
    """
    return Target(kind=row.kind, qualname=row.name, obj=row.obj)


def _member_target(parent: Target, segment: str, query: str) -> Target:
    """Resolve one dotted segment below ``parent``.

    Args:
        parent: The target resolved so far.
        segment: The next segment.
        query: Full query text, for the error.

    Returns:
        A parameter target below a callable, a classified member below a
        module, or a method / property / enum-member target below a class.

    Raises:
        HelpLookupError: When ``parent`` has no members (Literal aliases,
            constants, properties, parameters) — the parent is the only
            suggestion — or when ``segment`` is not a member.
    """
    if parent.kind in _CALLABLE_KINDS:
        return _parameter_target(parent, segment, query)
    if parent.kind == "module":
        return _module_member_target(parent, segment, query)
    if parent.kind in _CLASS_KINDS:
        return _class_member_target(parent, segment, query)
    raise HelpLookupError(query, suggestions=(parent.qualname,))


def _parameter_target(parent: Target, segment: str, query: str) -> Target:
    """Resolve ``segment`` as a parameter of the callable ``parent``.

    Args:
        parent: A ``method`` or ``function`` target.
        segment: Parameter name (exact or unique case-insensitive).
        query: Full query text, for the error.

    Returns:
        A ``parameter`` target whose ``obj`` is the ``inspect.Parameter``.

    Raises:
        HelpLookupError: When the callable has no such parameter.
    """
    parameters = _parameters(parent.obj)
    name = _pick(segment, tuple(parameters), parent.qualname, query)
    return Target(
        kind="parameter",
        qualname=f"{parent.qualname}.{name}",
        obj=parameters[name],
        owner=parent.obj,
        owner_name=parent.qualname,
        member=name,
    )


def _parameters(obj: object) -> dict[str, inspect.Parameter]:
    """Return the documented parameters of a callable.

    ``self`` and ``cls`` are dropped; a callable without an inspectable
    signature has no parameters.

    Args:
        obj: The callable.

    Returns:
        Parameters by name in declaration order.
    """
    try:
        signature = inspect.signature(cast("Callable[..., object]", obj))
    except (TypeError, ValueError):
        return {}
    return {
        name: parameter
        for name, parameter in signature.parameters.items()
        if name not in _SELF_NAMES
    }


def _module_member_target(parent: Target, segment: str, query: str) -> Target:
    """Resolve ``segment`` as a public member of the namespace module ``parent``.

    Args:
        parent: A ``module`` target.
        segment: Member name (must be in the module's ``__all__``).
        query: Full query text, for the error.

    Returns:
        A target classified with :func:`classify`.

    Raises:
        HelpLookupError: When the module does not export ``segment``.
    """
    module = cast("types.ModuleType", parent.obj)
    name = _pick(segment, module_members(module), parent.qualname, query)
    obj = getattr(module, name)
    return Target(
        kind=classify(obj),
        qualname=f"{parent.qualname}.{name}",
        obj=obj,
        owner=module,
        owner_name=parent.qualname,
        member=name,
    )


def _class_member_target(parent: Target, segment: str, query: str) -> Target:
    """Resolve ``segment`` as a public member of the class ``parent``.

    Args:
        parent: A class-like target (``class``, ``model``, ``dataclass``,
            ``enum``, ``exception``).
        segment: Member name.
        query: Full query text, for the error.

    Returns:
        A ``property`` target (``obj`` is the descriptor), a ``constant``
        target for an enum member, or a ``method`` target (instance, class,
        and static methods alike; ``obj`` is ``getattr(cls, name)``).

    Raises:
        HelpLookupError: When the class has no such public member.
    """
    cls = cast("type", parent.obj)
    name = _pick(segment, _class_member_names(cls), parent.qualname, query)
    static = inspect.getattr_static(cls, name)
    kind: HelpKind
    obj: object
    if isinstance(static, property):
        kind, obj = "property", static
    elif issubclass(cls, enum.Enum) and name in cls.__members__:
        kind, obj = "constant", cls.__members__[name]
    else:
        kind, obj = "method", getattr(cls, name)
    return Target(
        kind=kind,
        qualname=f"{parent.qualname}.{name}",
        obj=obj,
        owner=cls,
        owner_name=parent.qualname,
        member=name,
    )


def _class_member_names(cls: type) -> tuple[str, ...]:
    """List the public members of a class that help can describe.

    Args:
        cls: The class.

    Returns:
        Sorted names of public properties, callables, and enum members.
        Plain data attributes (``model_config``, dataclass defaults) are
        skipped.
    """
    members = cls.__members__ if issubclass(cls, enum.Enum) else {}
    # Walk the MRO instead of ``dir(cls)``: ``Enum.__dir__`` hides inherited
    # methods (such as ``str.maketrans`` on a ``str`` enum) on Python 3.10.
    attributes: set[str] = set()
    for klass in cls.__mro__:
        attributes.update(vars(klass))
    names: list[str] = []
    for name in sorted(attributes | set(members)):
        if name.startswith("_"):
            continue
        if name in members:
            names.append(name)
            continue
        static = inspect.getattr_static(cls, name)
        if isinstance(static, property) or callable(getattr(cls, name, None)):
            names.append(name)
    return tuple(sorted(names))


# =============================================================================
# Name matching and suggestions
# =============================================================================


def _match(wanted: str, candidates: Sequence[str]) -> list[str]:
    """Match a name exactly, else case-insensitively.

    Args:
        wanted: The name as typed.
        candidates: Names to match against.

    Returns:
        ``[wanted]`` on an exact match; otherwise every candidate equal to
        ``wanted`` ignoring case (possibly several, possibly none).
    """
    if wanted in candidates:
        return [wanted]
    folded = wanted.casefold()
    return [candidate for candidate in candidates if candidate.casefold() == folded]


def _pick(wanted: str, candidates: Sequence[str], parent: str, query: str) -> str:
    """Pick the unique member name for ``wanted`` or raise with suggestions.

    Args:
        wanted: The segment as typed.
        candidates: Public member names of the parent.
        parent: Canonical query string of the parent, used as the prefix.
        query: Full query text, for the error.

    Returns:
        The matched candidate name.

    Raises:
        HelpLookupError: With the ambiguous candidates (prefixed) when several
            match case-insensitively; with the close members (prefixed) when
            none match; with the parent alone when nothing is close.
    """
    matches = _match(wanted, candidates)
    if len(matches) == 1:
        return matches[0]
    if matches:
        prefixed = tuple(f"{parent}.{match}" for match in matches)
        raise HelpLookupError(query, suggestions=prefixed)
    raise HelpLookupError(
        query, suggestions=_child_suggestions(wanted, candidates, parent)
    )


def _child_suggestions(
    wanted: str, candidates: Sequence[str], parent: str
) -> tuple[str, ...]:
    """Build "Did you mean?" suggestions for a dotted miss.

    Args:
        wanted: The segment that matched nothing.
        candidates: Public member names of the parent.
        parent: Canonical query string of the parent.

    Returns:
        Close member names prefixed with ``parent.``; ``(parent,)`` when no
        member is close.
    """
    close = _close_matches(wanted, {name: f"{parent}.{name}" for name in candidates})
    return close or (parent,)


def _close_matches(wanted: str, display: Mapping[str, str]) -> tuple[str, ...]:
    """Run ``difflib.get_close_matches`` and map keys to display names.

    Args:
        wanted: The text to compare.
        display: Candidate key → display string (both unique).

    Returns:
        Up to five display strings in similarity order.
    """
    matches = difflib.get_close_matches(
        wanted, list(display), n=_SUGGESTION_LIMIT, cutoff=_SUGGESTION_CUTOFF
    )
    return tuple(display[match] for match in matches)


# =============================================================================
# Object queries
# =============================================================================


def _resolve_object(obj: object) -> Target:
    """Resolve a live object to the same target as its string form.

    Args:
        obj: A class, function, bound or unbound method, property, module,
            the package, or an instance of an exported class.

    Returns:
        The resolved target.

    Raises:
        HelpLookupError: When ``obj`` is outside the public surface.
    """
    import mixpanel_headless as package

    if obj is package:
        return _overview()
    if isinstance(obj, property):
        if obj.fget is None:
            raise HelpLookupError(_label(obj))
        obj = obj.fget
    if isinstance(obj, types.ModuleType | type):
        row = _row_by_identity(obj)
        if row is None:
            raise HelpLookupError(_label(obj))
        return _export_target(row)
    if inspect.ismethod(obj):
        return _resolve_bound_method(obj)
    if inspect.isroutine(obj):
        return _resolve_routine(obj)
    row = _row_by_identity(type(obj))
    if row is None:
        raise HelpLookupError(_label(obj))
    return _export_target(row)


def _resolve_bound_method(method: types.MethodType) -> Target:
    """Resolve a bound method through its owner class.

    The instance is never used, so ``ws.query`` resolves without reading
    any state from ``ws``.

    Args:
        method: A bound method (instance-bound or class-bound classmethod).

    Returns:
        The ``<Owner>.<name>`` target.

    Raises:
        HelpLookupError: When the owner class is not an export.
    """
    owner = method.__self__
    owner_class = owner if isinstance(owner, type) else type(owner)
    row = _row_by_identity(owner_class)
    if row is None:
        raise HelpLookupError(_label(method))
    return _resolve_text(f"{row.name}.{method.__name__}")


def _resolve_routine(function: object) -> Target:
    """Resolve a plain function, builtin, or unbound method object.

    Args:
        function: Any object for which ``inspect.isroutine`` is true and
            that is not a bound method.

    Returns:
        The export target (by identity), the ``<Owner>.<name>`` target when
        ``__qualname__`` is dotted, or the ``<module>.<name>`` target when a
        namespace module exports it.

    Raises:
        HelpLookupError: When the function lives outside ``mixpanel_headless``,
            is a local function, or is not reachable from the public surface.
    """
    module = getattr(function, "__module__", None) or ""
    if module != _PACKAGE and not module.startswith(f"{_PACKAGE}."):
        raise HelpLookupError(_label(function))
    row = _row_by_identity(function)
    if row is not None:
        return _export_target(row)
    qualname = getattr(function, "__qualname__", "") or ""
    if "<locals>" in qualname:
        raise HelpLookupError(_label(function))
    if "." in qualname:
        target = _resolve_text(qualname)
        if _underlying(target.obj) is function:
            return target
        raise HelpLookupError(_label(function))
    for candidate in inventory():
        if candidate.kind != "module":
            continue
        namespace = cast("types.ModuleType", candidate.obj)
        if (
            qualname in module_members(namespace)
            and getattr(namespace, qualname) is function
        ):
            return _resolve_text(f"{candidate.name}.{qualname}")
    raise HelpLookupError(_label(function))


def _underlying(obj: object) -> object:
    """Unwrap a resolved member to the plain function behind it.

    Args:
        obj: A target object — a bound classmethod, a ``property``, or a
            plain function.

    Returns:
        The classmethod's ``__func__``, the property's getter, or ``obj``
        unchanged.
    """
    if isinstance(obj, property):
        return obj.fget
    return getattr(obj, "__func__", obj)


def _row_by_identity(obj: object) -> Export | None:
    """Find the inventory row whose object is ``obj``.

    Args:
        obj: Any object.

    Returns:
        The row, or ``None`` when no export is that exact object.
    """
    for row in inventory():
        if row.obj is obj:
            return row
    return None


def _label(obj: object) -> str:
    """Build the ``query`` text for an object miss.

    Args:
        obj: The object that did not resolve.

    Returns:
        Its ``__qualname__``, else ``__name__``, else ``repr``.
    """
    for attribute in ("__qualname__", "__name__"):
        value = getattr(obj, attribute, None)
        if isinstance(value, str) and value:
            return value
    return repr(obj)
