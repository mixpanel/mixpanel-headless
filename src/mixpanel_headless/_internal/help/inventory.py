"""Public-surface inventory for the built-in help.

The inventory is the deduplicated, sorted ``mixpanel_headless.__all__``.
``dir()`` is never used for the package root, so a name reaches the
help system only when the package exports it on purpose. Each row is an
:class:`Export` that pairs the name with its :func:`classify` kind and the
runtime object.

Three more views complete the surface every other help module builds on:

- :func:`workspace_members` — public ``Workspace`` properties and methods;
- :func:`module_members` — a namespace module's ``__all__``;
- :func:`exports_of_kind` / :func:`export` — filtered and keyed access.

The inventory is built once per process and cached in module state.
:func:`clear_cache` drops the cache. Building it imports nothing outside the
package, reads no config file, and never constructs a ``Workspace``.
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import types
import typing
from dataclasses import dataclass, field

from pydantic import BaseModel

from mixpanel_headless._internal.help.models import HelpKind

__all__ = [
    "Export",
    "classify",
    "clear_cache",
    "export",
    "exports_of_kind",
    "inventory",
    "inventory_names",
    "module_members",
    "workspace_members",
]


@dataclass(frozen=True, slots=True)
class Export:
    """One public export of ``mixpanel_headless``.

    ``obj`` is excluded from equality and hashing, so two rows compare equal
    when their ``name`` and ``kind`` match.

    Attributes:
        name: Export name as it appears in ``__all__``.
        kind: Classification from :func:`classify`.
        obj: The runtime object bound to ``name`` on the package.
    """

    name: str
    kind: HelpKind
    obj: object = field(compare=False)


_ALIAS_ORIGINS: frozenset[object] = frozenset(
    {typing.Union, types.UnionType, typing.Annotated}
)
"""``typing.get_origin`` results that mark a ``Union`` / ``Annotated`` alias."""


def classify(obj: object) -> HelpKind:
    """Classify a runtime object into one ``HelpKind``.

    The rules apply in this order, and the first match wins:

    1. module → ``module``
    2. class that subclasses ``BaseException`` → ``exception``
    3. class that subclasses ``enum.Enum`` → ``enum``
    4. class that subclasses Pydantic ``BaseModel`` → ``model``
    5. dataclass → ``dataclass``
    6. any other class (plain classes, ``Protocol`` classes, ``TypedDict``
       classes) → ``class``
    7. runtime ``typing.Literal`` → ``literal``
    8. ``typing.Union``, PEP 604 ``X | Y``, or ``typing.Annotated`` → ``alias``
    9. function, builtin, method, or descriptor (``inspect.isroutine``) →
       ``function``
    10. anything else (``int`` / ``str`` / ``float`` values, instances) →
        ``constant``

    Args:
        obj: The object to classify.

    Returns:
        The ``HelpKind`` for ``obj``.

    Example:
        ```python
        classify(mp.Filter)        # "dataclass"
        classify(mp.MathType)      # "literal"
        classify(mp.accounts)      # "module"
        ```
    """
    if isinstance(obj, types.ModuleType):
        return "module"
    if isinstance(obj, type):
        if issubclass(obj, BaseException):
            return "exception"
        if issubclass(obj, enum.Enum):
            return "enum"
        if issubclass(obj, BaseModel):
            return "model"
        if dataclasses.is_dataclass(obj):
            return "dataclass"
        return "class"
    origin = typing.get_origin(obj)
    if origin is typing.Literal:
        return "literal"
    if origin in _ALIAS_ORIGINS or isinstance(obj, types.UnionType):
        return "alias"
    if inspect.isroutine(obj):
        return "function"
    return "constant"


_INVENTORY: tuple[Export, ...] | None = None
_BY_NAME: dict[str, Export] = {}
_WORKSPACE_MEMBERS: tuple[tuple[str, HelpKind], ...] | None = None


def _build_inventory() -> tuple[Export, ...]:
    """Build the inventory rows from ``mixpanel_headless.__all__``.

    The package is imported lazily so this module can be imported from
    anywhere inside the package without an import cycle.

    Returns:
        Rows sorted by name, one per unique ``__all__`` entry.
    """
    import mixpanel_headless as package

    names = sorted(set(package.__all__))
    return tuple(
        Export(
            name=name, kind=classify(getattr(package, name)), obj=getattr(package, name)
        )
        for name in names
    )


def inventory() -> tuple[Export, ...]:
    """Return the cached public inventory.

    Returns:
        The deduplicated, name-sorted rows for ``mixpanel_headless.__all__``.
        Repeated calls return the identical tuple until :func:`clear_cache`.
    """
    global _INVENTORY
    if _INVENTORY is None:
        _INVENTORY = _build_inventory()
        _BY_NAME.clear()
        _BY_NAME.update({row.name: row for row in _INVENTORY})
    return _INVENTORY


def inventory_names() -> tuple[str, ...]:
    """Return the sorted export names.

    Returns:
        One name per inventory row, in the same order as :func:`inventory`.
    """
    return tuple(row.name for row in inventory())


def export(name: str) -> Export | None:
    """Look up one inventory row by exact name.

    Args:
        name: Export name. Dotted paths, private names, and case variants
            never match; the resolver handles those.

    Returns:
        The row, or ``None`` when ``name`` is not an export.
    """
    inventory()
    return _BY_NAME.get(name)


def exports_of_kind(kind: HelpKind) -> tuple[Export, ...]:
    """Return the inventory rows of one kind, in name order.

    Args:
        kind: The ``HelpKind`` to filter on.

    Returns:
        Matching rows; empty when no export has that kind.
    """
    return tuple(row for row in inventory() if row.kind == kind)


def _build_workspace_members() -> tuple[tuple[str, HelpKind], ...]:
    """Collect the public ``Workspace`` properties and methods.

    Classification uses ``inspect.getattr_static`` so a property is never
    evaluated. Public attributes that are neither callable nor a property
    are skipped; ``Workspace`` defines none.

    Returns:
        ``(name, kind)`` pairs sorted by name; ``kind`` is ``"property"`` or
        ``"method"`` (instance, class, and static methods all count).
    """
    from mixpanel_headless.workspace import Workspace

    members: list[tuple[str, HelpKind]] = []
    for name in sorted(dir(Workspace)):
        if name.startswith("_"):
            continue
        attribute = inspect.getattr_static(Workspace, name)
        if isinstance(attribute, property):
            members.append((name, "property"))
        elif callable(getattr(Workspace, name)):
            members.append((name, "method"))
    return tuple(members)


def workspace_members() -> tuple[tuple[str, HelpKind], ...]:
    """Return the cached public ``Workspace`` members.

    Returns:
        ``(name, kind)`` pairs sorted by name, kind ``"property"`` or
        ``"method"``. Repeated calls return the identical tuple until
        :func:`clear_cache`.
    """
    global _WORKSPACE_MEMBERS
    if _WORKSPACE_MEMBERS is None:
        _WORKSPACE_MEMBERS = _build_workspace_members()
    return _WORKSPACE_MEMBERS


def module_members(mod: types.ModuleType) -> tuple[str, ...]:
    """Return the public member names of a module.

    The public namespaces ``accounts``, ``session``, and ``targets`` define
    ``__all__``, which is authoritative. A module without ``__all__`` falls
    back to its public (non-underscore) attribute names.

    Args:
        mod: The module to list.

    Returns:
        Sorted, deduplicated member names.
    """
    declared = getattr(mod, "__all__", None)
    if declared is not None:
        return tuple(sorted(set(declared)))
    return tuple(sorted(name for name in vars(mod) if not name.startswith("_")))


def clear_cache() -> None:
    """Drop the cached inventory and ``Workspace`` member list.

    The next call to :func:`inventory` or :func:`workspace_members` rebuilds
    the cache from the live package.
    """
    global _INVENTORY, _WORKSPACE_MEMBERS
    _INVENTORY = None
    _WORKSPACE_MEMBERS = None
    _BY_NAME.clear()
