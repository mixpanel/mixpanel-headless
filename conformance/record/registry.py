"""Entry-point registry for the record plugin (design D4.4 — PR-2 scope).

One registry, two consumers: the recorder wraps every entry at record time
and the Python corpus runner (design D7) resolves ``call.api`` back through
the SAME table, so recorder and runner can never disagree about entry points.

PR-2 ships:

- the frozen :class:`RegistryEntry` dataclass exactly per design D4.4;
- the MECHANICAL wire enumeration (design D1.2) over ``MixpanelAPIClient``
  and ``Workspace`` public methods (``wire_api``/``wire_state`` kinds), with
  the ``build_*`` facades carved out as ``builder`` entries (design D4.1);
- the module-level wire entry ``pagination.paginate_all`` (the pilot's
  multi-request family drives it directly);
- placeholder builder entries (``expressions.normalize_on_expression`` plus
  the five Workspace facades) so the dual-seam path is exercised end-to-end.

PR-3 fills out the remaining D4.2 module builders/validators, the
``ReplaysService``/``OAuthFlow.refresh``/``probe_region`` wire entries, and
the hand-audit pass over this mechanical enumeration.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

KIND_BUILDER = "builder"
KIND_VALIDATOR = "validator"
KIND_WIRE_API = "wire_api"
KIND_WIRE_STATE = "wire_state"


@dataclass(frozen=True)
class RegistryEntry:
    """One recordable entry point (design D4.4 verbatim field set).

    Attributes:
        api: Dotted vector name, e.g. ``workspace.build_funnel_params`` or
            ``api_client.list_annotations``.
        target: Import path, ``module:function`` or ``module:Class.method``.
        kind: One of ``builder`` / ``validator`` / ``wire_api`` /
            ``wire_state`` (D1.2 extends the D4.4 comment set with the wire
            kinds).
        capability: Corpus directory for builder/module entries; empty string
            for mechanically-generated class wire entries, whose capability
            is assigned by the emit-time endpoint table (design D3).
        input_codec: Input codec name; ``kwargs`` is the generic default.
        output_codec: Output codec name; ``json`` is the generic default.
    """

    api: str
    target: str
    kind: str
    capability: str
    input_codec: str = "kwargs"
    output_codec: str = "json"


_CLIENT_MODULE = "mixpanel_headless._internal.api_client"
_WORKSPACE_MODULE = "mixpanel_headless.workspace"

_CLIENT_STATE_NAMES = frozenset({"close", "set_workspace_id", "use", "with_project"})
"""MixpanelAPIClient methods that mutate state / return siblings (D1.2)."""

_CLIENT_SKIP_NAMES = frozenset({"set_workspace_resolver"})
"""Audited out: internal wiring surface invoked by Workspace.__init__ with a
callable argument; recording it would prepend an unreplayable setup entry to
every Workspace-facade vector."""

_WORKSPACE_STATE_NAMES = frozenset({"close", "use", "clear_discovery_cache"})
"""Workspace methods with no return contract (D1.2 wire_state examples)."""

_WORKSPACE_BUILDER_CAPABILITIES = {
    "build_params": "bookmarks",
    "build_funnel_params": "funnels",
    "build_flow_params": "flows",
    "build_retention_params": "retention",
    "build_user_params": "engage",
}
"""The five D4.1 Workspace facades and their corpus capabilities."""


def _wire_entries_for_class(
    cls: type,
    *,
    api_prefix: str,
    module: str,
    state_names: frozenset[str],
    skip_names: frozenset[str],
) -> tuple[RegistryEntry, ...]:
    """Mechanically enumerate a class's public methods as wire entries (D1.2).

    Args:
        cls: The class whose ``__dict__`` is scanned.
        api_prefix: Vector-name prefix (``api_client`` / ``workspace``).
        module: Import path of the defining module for ``target`` strings.
        state_names: Method names registered as ``wire_state``.
        skip_names: Method names excluded from the registry entirely.

    Returns:
        Entries sorted by method name (deterministic registry order).
    """
    entries: list[RegistryEntry] = []
    for name, member in sorted(vars(cls).items()):
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        if name in skip_names or name in _WORKSPACE_BUILDER_CAPABILITIES:
            continue
        kind = KIND_WIRE_STATE if name in state_names else KIND_WIRE_API
        entries.append(
            RegistryEntry(
                api=f"{api_prefix}.{name}",
                target=f"{module}:{cls.__name__}.{name}",
                kind=kind,
                capability="",
            )
        )
    return tuple(entries)


def _builder_entries() -> tuple[RegistryEntry, ...]:
    """Return the PR-2 placeholder builder entries (PR-3 completes the set).

    Returns:
        The five D4.1 Workspace facades plus
        ``expressions.normalize_on_expression`` (D4.2 item 3).
    """
    entries = [
        RegistryEntry(
            api=f"workspace.{name}",
            target=f"{_WORKSPACE_MODULE}:Workspace.{name}",
            kind=KIND_BUILDER,
            capability=capability,
        )
        for name, capability in sorted(_WORKSPACE_BUILDER_CAPABILITIES.items())
    ]
    entries.append(
        RegistryEntry(
            api="expressions.normalize_on_expression",
            target="mixpanel_headless._internal.expressions:normalize_on_expression",
            kind=KIND_BUILDER,
            capability="segmentation",
        )
    )
    return tuple(entries)


def build_registry() -> tuple[RegistryEntry, ...]:
    """Assemble the full registry tuple (design D4.4 ``REGISTRY``).

    Imports the library lazily so that merely importing this module in
    tooling contexts stays cheap until the registry is actually built.

    Returns:
        All builder + wire entries, builder entries first, then class wire
        entries sorted by name, then module-level wire entries.
    """
    from mixpanel_headless._internal.api_client import MixpanelAPIClient
    from mixpanel_headless.workspace import Workspace

    client_entries = _wire_entries_for_class(
        MixpanelAPIClient,
        api_prefix="api_client",
        module=_CLIENT_MODULE,
        state_names=_CLIENT_STATE_NAMES,
        skip_names=_CLIENT_SKIP_NAMES,
    )
    workspace_entries = _wire_entries_for_class(
        Workspace,
        api_prefix="workspace",
        module=_WORKSPACE_MODULE,
        state_names=_WORKSPACE_STATE_NAMES,
        skip_names=frozenset(),
    )
    module_wire = (
        RegistryEntry(
            api="pagination.paginate_all",
            target="mixpanel_headless._internal.pagination:paginate_all",
            kind=KIND_WIRE_API,
            capability="pagination",
        ),
    )
    return _builder_entries() + client_entries + workspace_entries + module_wire


REGISTRY: tuple[RegistryEntry, ...] = build_registry()
"""The registry of record (design D4.4); PR-3 extends and hand-audits it."""

REGISTRY_BY_API: dict[str, RegistryEntry] = {entry.api: entry for entry in REGISTRY}
"""Lookup table keyed by dotted vector name."""


def resolve_owner(entry: RegistryEntry) -> tuple[Any, str]:
    """Resolve a registry entry to its patchable owner and attribute name.

    Args:
        entry: The registry entry to resolve.

    Returns:
        ``(owner, attr_name)`` where ``owner`` is a module (for module-level
        functions) or a class (for methods) and ``attr_name`` the attribute
        to wrap on it.

    Raises:
        ImportError: If the target module cannot be imported.
        AttributeError: If the class or attribute does not exist.
    """
    module_path, _, attr_path = entry.target.partition(":")
    module = importlib.import_module(module_path)
    if "." in attr_path:
        cls_name, method_name = attr_path.split(".", 1)
        return getattr(module, cls_name), method_name
    return module, attr_path


def resolve_callable(entry: RegistryEntry) -> Callable[..., Any]:
    """Resolve a registry entry to the underlying callable.

    Args:
        entry: The registry entry to resolve.

    Returns:
        The plain function object currently bound at the target location.

    Raises:
        ImportError: If the target module cannot be imported.
        AttributeError: If the attribute does not exist.
        TypeError: If the resolved attribute is not callable.
    """
    owner, attr = resolve_owner(entry)
    func = getattr(owner, attr)
    if not callable(func):
        raise TypeError(f"registry target {entry.target} is not callable")
    return func  # type: ignore[no-any-return]
