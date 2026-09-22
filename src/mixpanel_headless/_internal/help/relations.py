"""Cross-references for the built-in API reference.

This module answers "what else is connected to this name?":

- :func:`used_by` — the ``Workspace`` methods whose **parameters** accept an
  exported type (the "Used by Workspace" section), with the parameter names.
- :func:`referenced_types` — the exported types named in a callable's
  parameter and return annotations (the "Referenced types" section).
- :func:`see_also` — the other methods in the same ``WORKSPACE_DOMAINS``
  domain.
- :func:`exception_tree`, :func:`subclasses_of`, :func:`raised_by` — the
  exported exception hierarchy and the ``Workspace`` methods whose
  ``Raises:`` section names an exception.

For every callable the module resolves
``typing.get_type_hints`` through :func:`~.introspect.resolved_hints` and
walks the hint tree with ``typing.get_args`` (through ``Union``, ``Optional``,
``list``, ``dict``, ``Sequence``, ``Callable``, and ``Annotated``). A
parameter references an export when the export object appears in that tree
by identity. Literal and Union aliases also match by value, because
``get_type_hints`` may inline an equal ``Literal[...]``. When hints cannot be
resolved (``{}``), the module falls back to a word-boundary regex on the
string annotation, so ``Cohort`` never matches ``CohortMetric``.

Results are cached per name in module state; :func:`clear_cache`
drops them. Nothing here touches the network, reads config, or constructs
a ``Workspace``.
"""

from __future__ import annotations

import inspect
import re
import typing

from mixpanel_headless._internal.help.docstrings import first_line, parse_docstring
from mixpanel_headless._internal.help.introspect import resolved_hints
from mixpanel_headless._internal.help.inventory import (
    Export,
    export,
    exports_of_kind,
    inventory,
    workspace_members,
)
from mixpanel_headless._internal.help.models import ExportKind, UsageDoc
from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS, domain_of

__all__ = [
    "clear_cache",
    "exception_tree",
    "raised_by",
    "referenced_types",
    "see_also",
    "subclasses_of",
    "used_by",
]

_TYPE_KINDS: frozenset[ExportKind] = frozenset(
    {"class", "model", "dataclass", "enum", "literal", "alias", "exception"}
)
"""Export kinds that count as *types* for ``referenced_types``."""

_VALUE_COMPARED_KINDS: frozenset[ExportKind] = frozenset({"literal", "alias"})
"""Kinds whose export object may be inlined by ``get_type_hints`` and so also match by ``==``."""

_Annotation = tuple[str, tuple[object, ...], str]
"""One annotation: ``(name, resolved hint tree nodes, string annotation)``.

``name`` is a parameter name or ``"return"``. ``nodes`` is empty when the
hints could not be resolved; ``text`` is then the only evidence.
"""

_USED_BY: dict[str, tuple[UsageDoc, ...]] = {}
_RAISED_BY: dict[str, tuple[UsageDoc, ...]] = {}
_METHOD_ANNOTATIONS: tuple[tuple[str, tuple[_Annotation, ...]], ...] | None = None
_RAISES: tuple[tuple[str, tuple[str, ...]], ...] | None = None
_EXCEPTIONS: dict[str, type[BaseException]] | None = None


# =============================================================================
# Annotation trees
# =============================================================================


def _walk(hint: object) -> list[object]:
    """Flatten a resolved hint into itself plus every nested argument.

    ``typing.get_args`` is applied recursively. The parameter list of a
    ``Callable[[A, B], R]`` arrives as a Python ``list``, which is expanded
    element by element so ``A`` and ``B`` are reached too.

    Args:
        hint: A resolved annotation object (class, alias, generic, ...).

    Returns:
        The hint followed by every reachable argument, in pre-order.
    """
    if isinstance(hint, list):
        nodes: list[object] = []
        for item in hint:
            nodes.extend(_walk(item))
        return nodes
    nodes = [hint]
    for arg in typing.get_args(hint):
        nodes.extend(_walk(arg))
    return nodes


def _annotation_text(annotation: object) -> str:
    """Return the string form of a source annotation for regex matching.

    Args:
        annotation: ``inspect.Parameter.annotation`` or
            ``Signature.return_annotation``; may be ``Parameter.empty``.

    Returns:
        ``""`` when the annotation is absent, the string itself under
        ``from __future__ import annotations``, else ``str(annotation)``.
    """
    if annotation is inspect.Parameter.empty:
        return ""
    return annotation if isinstance(annotation, str) else str(annotation)


def _annotations_of(func: object) -> tuple[_Annotation, ...]:
    """Collect the parameter and return annotations of a callable.

    Args:
        func: A function, method, or class. Objects without a signature
            yield an empty tuple.

    Returns:
        One ``(name, nodes, text)`` per annotated parameter plus a
        ``"return"`` entry when a return annotation exists. Parameters with
        no annotation (``self``, ``cls``) are skipped.
    """
    try:
        signature = inspect.signature(func)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()
    hints = resolved_hints(func)
    rows: list[_Annotation] = []
    entries = [(name, param.annotation) for name, param in signature.parameters.items()]
    entries.append(("return", signature.return_annotation))
    for name, annotation in entries:
        text = _annotation_text(annotation)
        if not text:
            continue
        nodes = tuple(_walk(hints[name])) if name in hints else ()
        rows.append((name, nodes, text))
    return tuple(rows)


def _matches(row: Export, nodes: tuple[object, ...], text: str) -> bool:
    """Decide whether one annotation references an export.

    Args:
        row: The inventory row to look for.
        nodes: Flattened resolved hint tree; empty when hints failed.
        text: String form of the source annotation.

    Returns:
        ``True`` when ``row.obj`` is in ``nodes`` by identity, when a
        Literal or Union alias in ``nodes`` equals ``row.obj``, or — only
        when ``nodes`` is empty — when ``row.name`` appears in ``text`` as a
        whole word.
    """
    if nodes:
        if any(node is row.obj for node in nodes):
            return True
        if row.kind in _VALUE_COMPARED_KINDS:
            return any(node == row.obj for node in nodes)
        return False
    return re.search(rf"\b{re.escape(row.name)}\b", text) is not None


def _method_annotations() -> tuple[tuple[str, tuple[_Annotation, ...]], ...]:
    """Return the cached annotation trees of every public ``Workspace`` method.

    Returns:
        ``(method name, annotations)`` pairs sorted by method name.
    """
    global _METHOD_ANNOTATIONS
    if _METHOD_ANNOTATIONS is None:
        from mixpanel_headless.workspace import Workspace

        _METHOD_ANNOTATIONS = tuple(
            (name, _annotations_of(getattr(Workspace, name)))
            for name, kind in workspace_members()
            if kind == "method"
        )
    return _METHOD_ANNOTATIONS


# =============================================================================
# used_by / referenced_types / see_also
# =============================================================================


def used_by(name: str) -> tuple[UsageDoc, ...]:
    """Return the ``Workspace`` methods whose parameters accept an export.

    Only parameters count; a method that merely *returns* the type is not a
    usage. Matching is exact, so ``Cohort`` does not match ``CohortMetric``.

    Args:
        name: An export name such as ``"Filter"`` or ``"MathType"``.

    Returns:
        One :class:`UsageDoc` per accepting method, sorted by method name,
        each listing the accepting parameter names in declaration order.
        Empty for unknown names and for types no method accepts. Repeated
        calls return the identical tuple until :func:`clear_cache`.

    Example:
        ```python
        used_by("MathType")
        # (UsageDoc("build_params", ("math",)), UsageDoc("query", ("math",)))
        ```
    """
    cached = _USED_BY.get(name)
    if cached is not None:
        return cached
    row = export(name)
    usages: list[UsageDoc] = []
    if row is not None:
        for method, annotations in _method_annotations():
            params = tuple(
                param
                for param, nodes, text in annotations
                if param != "return" and _matches(row, nodes, text)
            )
            if params:
                usages.append(UsageDoc(method, params))
    usages.sort(key=lambda usage: usage.method)
    result = tuple(usages)
    _USED_BY[name] = result
    return result


def _owner_name(func: object) -> str:
    """Return the class name that owns a method, from its ``__qualname__``.

    Args:
        func: The callable being documented.

    Returns:
        The first dotted segment of ``__qualname__`` when there is one
        (``"Workspace"`` for ``Workspace.query``), else ``""``.
    """
    qualname = getattr(func, "__qualname__", "")
    if not isinstance(qualname, str) or "." not in qualname:
        return ""
    return qualname.split(".", 1)[0]


def _summary(row: Export) -> str:
    """Return the one-line summary of an export for listings.

    Literal and Union aliases have no docstring of their own — their
    ``__doc__`` is the generic ``typing`` class text — so their line comes
    from ``ALIAS_DOCS``. Every other kind is read with ``inspect.getdoc``,
    the same call the rest of the help system uses, so inherited and
    indented docstrings give the same first line everywhere.

    Args:
        row: The inventory row.

    Returns:
        The first docstring line, the alias description, or ``""``.
    """
    if row.kind in _VALUE_COMPARED_KINDS:
        from mixpanel_headless._literal_types import ALIAS_DOCS

        return ALIAS_DOCS.get(row.name, "")
    return first_line(inspect.getdoc(row.obj))


def referenced_types(func: object) -> tuple[tuple[str, str], ...]:
    """Return the exported types named in a callable's annotations.

    Parameters and the return annotation both count. Only type-like kinds
    qualify (classes, models, dataclasses, enums, exceptions, Literal and
    Union aliases); functions, modules, and constants never appear. The
    owner class of a method (``Workspace`` for ``Workspace.query``) is
    excluded.

    Args:
        func: A function, method, or class. Objects without a signature
            yield an empty tuple.

    Returns:
        ``(name, summary)`` pairs sorted by name.

    Example:
        ```python
        referenced_types(Workspace.create_dashboard)
        # (("CreateDashboardParams", "Parameters for creating a new dashboard."),
        #  ("Dashboard", "A Mixpanel dashboard as returned by the App API."))
        ```
    """
    annotations = _annotations_of(func)
    if not annotations:
        return ()
    owner = _owner_name(func)
    found: list[tuple[str, str]] = []
    for row in inventory():
        if row.kind not in _TYPE_KINDS or row.name == owner:
            continue
        if any(_matches(row, nodes, text) for _name, nodes, text in annotations):
            found.append((row.name, _summary(row)))
    return tuple(found)


def see_also(qualname: str) -> tuple[str, tuple[str, ...]]:
    """Return the domain siblings of a ``Workspace`` method.

    Args:
        qualname: A help query string such as ``"Workspace.create_dashboard"``.

    Returns:
        ``(domain title, other method names in that domain sorted)``. Any
        query that is not ``Workspace.<registered method>`` — types,
        properties, parameters, unknown names — yields ``("", ())``.

    Example:
        ```python
        see_also("Workspace.create_dashboard")
        # ("dashboards", ("add_report_to_dashboard", "bulk_delete_dashboards", ...))
        ```
    """
    parts = qualname.split(".")
    if len(parts) != 2 or parts[0] != "Workspace":
        return ("", ())
    method = parts[1]
    title = domain_of(method)
    if title is None:
        return ("", ())
    names = dict(WORKSPACE_DOMAINS)[title]
    return (title, tuple(sorted(set(names) - {method})))


# =============================================================================
# Exceptions
# =============================================================================


def _exported_exceptions() -> dict[str, type[BaseException]]:
    """Return the cached ``name → class`` map of exported exceptions.

    Returns:
        Every inventory row of kind ``exception``, keyed by name.
    """
    global _EXCEPTIONS
    if _EXCEPTIONS is None:
        _EXCEPTIONS = {
            row.name: row.obj
            for row in exports_of_kind("exception")
            if isinstance(row.obj, type) and issubclass(row.obj, BaseException)
        }
    return _EXCEPTIONS


def _nearest_exported_base(exc: type) -> type | None:
    """Return the closest exported ancestor of an exception class.

    Args:
        exc: An exception class.

    Returns:
        The first class in ``exc.__mro__[1:]`` that is an export, or
        ``None`` when no ancestor is exported.
    """
    exported = _exported_exceptions()
    for base in exc.__mro__[1:]:
        if exported.get(base.__name__) is base:
            return base
    return None


def subclasses_of(exc: type) -> tuple[str, ...]:
    """Return the direct exported subclasses of an exception class.

    "Direct" means the nearest exported ancestor is ``exc``, so an
    unexported intermediate base does not hide its exported children. For
    a root that is not exported (``Exception``), the children are the
    exported classes with no exported ancestor at all.

    Args:
        exc: The parent exception class.

    Returns:
        Child names sorted alphabetically; empty for a leaf.
    """
    children: list[str] = []
    for name, cls in _exported_exceptions().items():
        if cls is exc or not issubclass(cls, exc):
            continue
        parent = _nearest_exported_base(cls)
        if parent is exc or (
            parent is None and exc.__name__ not in _exported_exceptions()
        ):
            children.append(name)
    return tuple(sorted(children))


def exception_tree(
    root: type[BaseException] | None = None,
) -> tuple[tuple[str, int], ...]:
    """Return the exported exception hierarchy as depth-first ``(name, depth)`` pairs.

    Args:
        root: The class to start from; defaults to ``MixpanelHeadlessError``.
            Pass ``APIError`` to obtain its subtree for the per-exception
            ``Subclasses`` group.

    Returns:
        The root at depth 0 followed by its descendants in pre-order,
        children sorted by name at every level.

    Example:
        ```python
        exception_tree()[:3]
        # (("MixpanelHeadlessError", 0), ("APIError", 1), ("AuthenticationError", 2))
        ```
    """
    if root is None:
        from mixpanel_headless.exceptions import MixpanelHeadlessError

        root = MixpanelHeadlessError
    exported = _exported_exceptions()
    rows: list[tuple[str, int]] = []

    def visit(cls: type, depth: int) -> None:
        """Append ``cls`` and recurse into its exported children.

        Args:
            cls: The exception class to record.
            depth: Its depth below the root.
        """
        rows.append((cls.__name__, depth))
        for child in subclasses_of(cls):
            visit(exported[child], depth + 1)

    visit(root, 0)
    return tuple(rows)


def _raises_index() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return the cached ``Raises:`` names of every public ``Workspace`` method.

    Returns:
        ``(method name, exception names as written)`` pairs sorted by method
        name. Names may be dotted (``mp.APIError``) or bare.
    """
    global _RAISES
    if _RAISES is None:
        from mixpanel_headless.workspace import Workspace

        _RAISES = tuple(
            (
                name,
                tuple(
                    exc
                    for exc, _desc in parse_docstring(
                        getattr(Workspace, name).__doc__
                    ).raises
                ),
            )
            for name, kind in workspace_members()
            if kind == "method"
        )
    return _RAISES


def raised_by(exc_name: str) -> tuple[UsageDoc, ...]:
    """Return the ``Workspace`` methods whose ``Raises:`` section names an exception.

    A documented name matches when its last dotted segment equals
    ``exc_name`` exactly, so both ``APIError`` and ``mp.APIError`` in a
    docstring match ``"APIError"``.

    Args:
        exc_name: Bare exception class name, for example ``"WorkspaceScopeError"``.

    Returns:
        One :class:`UsageDoc` per method with ``params=()``, sorted by
        method name. Repeated calls return the identical tuple until
        :func:`clear_cache`.
    """
    cached = _RAISED_BY.get(exc_name)
    if cached is not None:
        return cached
    result = tuple(
        UsageDoc(method, ())
        for method, names in sorted(_raises_index())
        if any(name.rsplit(".", 1)[-1] == exc_name for name in names)
    )
    _RAISED_BY[exc_name] = result
    return result


def clear_cache() -> None:
    """Drop every cached relation.

    The next call rebuilds the ``Workspace`` annotation trees, the
    ``Raises:`` index, the exception map, and the per-name results.
    """
    global _METHOD_ANNOTATIONS, _RAISES, _EXCEPTIONS
    _USED_BY.clear()
    _RAISED_BY.clear()
    _METHOD_ANNOTATIONS = None
    _RAISES = None
    _EXCEPTIONS = None
