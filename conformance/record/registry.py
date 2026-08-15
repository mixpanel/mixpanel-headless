"""Entry-point registry for the record plugin and corpus runner (design D4.4).

One registry, two consumers: the recorder wraps every entry at record time
and the Python corpus runner (design D7) resolves ``call.api`` back through
the SAME table, so recorder and runner can never disagree about entry points.

Contents (PR-3 — complete per design D4/D1.2):

- **Builder entries** (design D4.1/D4.2): the five ``Workspace.build_*``
  facades plus the curated module-level builders, serializers, transforms,
  replay-label helpers, and boundary entries.
- **Validator entries** (design D4.2 items 6/7): module-level ``validate_*``
  functions with structural ``validation_errors`` output (design D4.3).
- **Wire entries** (design D1.2): EVERY public method of
  ``MixpanelAPIClient`` and ``Workspace`` — generated mechanically from the
  class ``__dict__`` then hand-audited (audit notes on the constants
  below) — plus ``ReplaysService`` public methods, ``OAuthFlow``'s refresh
  path, ``probe_region``, and ``pagination.paginate_all``. State-mutating
  methods with no return contract carry ``kind="wire_state"`` and only ever
  appear as ``call.setup[]`` entries (design D2).
- **Gate entries** (design D13): the pythonCompat reference wrappers and
  the wire-stub mirror client from ``conformance/record/pycompat_ref.py``.
- **Adapter-backed entries** (design D4.2 items 5/9): contracts whose
  library callable has the wrong shape resolve to
  ``conformance/record/adapters.py`` shims that delegate to the real code.
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
        output_codec: Output codec name; ``json`` is the generic default
            (dispatch table: ``conformance.record.codecs.encode_output``).
    """

    api: str
    target: str
    kind: str
    capability: str
    input_codec: str = "kwargs"
    output_codec: str = "json"


_CLIENT_MODULE = "mixpanel_headless._internal.api_client"
_WORKSPACE_MODULE = "mixpanel_headless.workspace"
_REPLAYS_MODULE = "mixpanel_headless._internal.services.replays"
_BUILDERS_MODULE = "mixpanel_headless._internal.bookmark_builders"
_VALIDATION_MODULE = "mixpanel_headless._internal.validation"
_USER_BUILDERS_MODULE = "mixpanel_headless._internal.query.user_builders"
_USER_VALIDATORS_MODULE = "mixpanel_headless._internal.query.user_validators"
_PYCOMPAT_MODULE = "conformance.record.pycompat_ref"
_ADAPTERS_MODULE = "conformance.record.adapters"

_CLIENT_STATE_NAMES = frozenset({"close", "set_workspace_id", "use", "with_project"})
"""MixpanelAPIClient methods that mutate state / return siblings (D1.2).

Hand-audit note: ``use``/``with_project`` return client instances (never a
serializable measured result) and ``close``/``set_workspace_id`` have no
return contract — all four reproduce client state at replay by re-execution
as ``call.setup[]`` entries (design D2)."""

_CLIENT_SKIP_NAMES = frozenset({"set_workspace_resolver"})
"""Audited out: internal wiring surface invoked by Workspace.__init__ with a
callable argument; recording it would prepend an unreplayable setup entry to
every Workspace-facade vector."""

_WORKSPACE_STATE_NAMES = frozenset({"close", "use", "clear_discovery_cache"})
"""Workspace methods with no return contract (D1.2 wire_state examples).

Hand-audit note: every other Workspace public method either returns data or
fires the transport with an observable request contract, so it stays
``wire_api`` even when it returns ``None`` (e.g. ``clear_business_context``
— its request side is the contract)."""

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
    capability: str = "",
) -> tuple[RegistryEntry, ...]:
    """Mechanically enumerate a class's public methods as wire entries (D1.2).

    Args:
        cls: The class whose ``__dict__`` is scanned.
        api_prefix: Vector-name prefix (``api_client`` / ``workspace`` /
            ``replays``).
        module: Import path of the defining module for ``target`` strings.
        state_names: Method names registered as ``wire_state``.
        skip_names: Method names excluded from the registry entirely.
        capability: Fixed capability for every entry, or ``""`` to defer
            to the emit-time endpoint table. ``ReplaysService`` entries pin
            ``"replays"`` — their CDN hosts are not in the endpoint table,
            so deferring misfiled them under ``entities`` (PR-5 audit).

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
                capability=capability,
            )
        )
    return tuple(entries)


def _facade_entries() -> tuple[RegistryEntry, ...]:
    """Return the five Workspace facade builder entries (design D4.1).

    Returns:
        One ``builder`` entry per facade, sorted by method name.
    """
    return tuple(
        RegistryEntry(
            api=f"workspace.{name}",
            target=f"{_WORKSPACE_MODULE}:Workspace.{name}",
            kind=KIND_BUILDER,
            capability=capability,
        )
        for name, capability in sorted(_WORKSPACE_BUILDER_CAPABILITIES.items())
    )


def _module_builder_entries() -> tuple[RegistryEntry, ...]:
    """Return the curated module-level builder entries (design D4.2).

    Covers D4.2 items 1-5 and 8-9: the three Filter translation paths, the
    clock-hazard date builders, ``normalize_on_expression``, the export
    transforms, the replay-label helpers, the cohort boundary entries, and
    the ``_iter_jsonl_lines`` chunk adapter. (Item 6/7 validators live in
    :func:`_validator_entries`; item 10, the ``bookmark_enums`` snapshot,
    is a PR-7 emit artifact, not a callable.)

    Returns:
        The builder entries in design-document order.
    """
    return (
        # D4.2 item 1 — Filter translation paths (bookmark dialect).
        RegistryEntry(
            api="bookmark_builders.build_filter_entry",
            target=f"{_BUILDERS_MODULE}:build_filter_entry",
            kind=KIND_BUILDER,
            capability="filters",
        ),
        RegistryEntry(
            api="bookmark_builders.build_filter_section",
            target=f"{_BUILDERS_MODULE}:build_filter_section",
            kind=KIND_BUILDER,
            capability="filters",
        ),
        RegistryEntry(
            api="bookmark_builders.build_frequency_filter_entry",
            target=f"{_BUILDERS_MODULE}:build_frequency_filter_entry",
            kind=KIND_BUILDER,
            capability="filters",
        ),
        # D4.2 item 1 — segmentation-expression dialect.
        RegistryEntry(
            api="segfilter.build_segfilter_entry",
            target="mixpanel_headless._internal.segfilter:build_segfilter_entry",
            kind=KIND_BUILDER,
            capability="filters",
        ),
        # D4.2 item 1 — engage selector dialect.
        RegistryEntry(
            api="user_builders.filter_to_selector",
            target=f"{_USER_BUILDERS_MODULE}:filter_to_selector",
            kind=KIND_BUILDER,
            capability="engage",
            output_codec="selector_str",
        ),
        RegistryEntry(
            api="user_builders.filters_to_selector",
            target=f"{_USER_BUILDERS_MODULE}:filters_to_selector",
            kind=KIND_BUILDER,
            capability="engage",
            output_codec="selector_str",
        ),
        RegistryEntry(
            api="user_builders.extract_cohort_filter",
            target=f"{_USER_BUILDERS_MODULE}:extract_cohort_filter",
            kind=KIND_BUILDER,
            capability="engage",
        ),
        # D4.2 item 2 — clock-hazard date builders (frozen clock, D1.4).
        RegistryEntry(
            api="bookmark_builders.build_date_range",
            target=f"{_BUILDERS_MODULE}:build_date_range",
            kind=KIND_BUILDER,
            capability="bookmarks",
        ),
        RegistryEntry(
            api="bookmark_builders.build_time_section",
            target=f"{_BUILDERS_MODULE}:build_time_section",
            kind=KIND_BUILDER,
            capability="bookmarks",
        ),
        # D4.2 item 3 — pure string normalization (differential smoke entry).
        RegistryEntry(
            api="expressions.normalize_on_expression",
            target="mixpanel_headless._internal.expressions:normalize_on_expression",
            kind=KIND_BUILDER,
            capability="segmentation",
        ),
        # D4.2 item 4 — export transforms (deterministic UUID + frozen clock).
        RegistryEntry(
            api="transforms.transform_event",
            target="mixpanel_headless._internal.transforms:transform_event",
            kind=KIND_BUILDER,
            capability="streaming",
        ),
        RegistryEntry(
            api="transforms.transform_profile",
            target="mixpanel_headless._internal.transforms:transform_profile",
            kind=KIND_BUILDER,
            capability="streaming",
        ),
        # D4.2 item 5 — replay label helpers; selector_label_fn is recorded
        # as (attr, action) -> label via the flattening adapter.
        RegistryEntry(
            api="replay_labels.url_normalizer",
            target="mixpanel_headless.replay_labels:url_normalizer",
            kind=KIND_BUILDER,
            capability="replays",
        ),
        RegistryEntry(
            api="replay_labels.default_label_fn",
            target="mixpanel_headless.replay_labels:default_label_fn",
            kind=KIND_BUILDER,
            capability="replays",
        ),
        RegistryEntry(
            api="replay_labels.selector_label_fn",
            target=f"{_ADAPTERS_MODULE}:selector_label_fn",
            kind=KIND_BUILDER,
            capability="replays",
        ),
        # D4.2 item 7 (non-validator half) — root-model lookup, encoded as
        # the model NAME string.
        RegistryEntry(
            api="bookmark_schema.get_root_model_for_bookmark_type",
            target=(
                "mixpanel_headless._internal.bookmark_schema:"
                "get_root_model_for_bookmark_type"
            ),
            kind=KIND_BUILDER,
            capability="bookmarks",
            output_codec="model_name",
        ),
        # D4.2 item 8 — cohort boundary entries in the delegation chains.
        RegistryEntry(
            api="types._sanitize_raw_cohort",
            target="mixpanel_headless.types:_sanitize_raw_cohort",
            kind=KIND_BUILDER,
            capability="cohorts",
        ),
        RegistryEntry(
            api="types.CohortDefinition.to_dict",
            target="mixpanel_headless.types:CohortDefinition.to_dict",
            kind=KIND_BUILDER,
            capability="cohorts",
        ),
        # D4.2 item 9 — chunk-boundary contract via the response adapter.
        RegistryEntry(
            api="api_client._iter_jsonl_lines",
            target=f"{_ADAPTERS_MODULE}:iter_jsonl_lines",
            kind=KIND_BUILDER,
            capability="streaming",
        ),
        # D3.1 item 3 — rrweb analyzer seed golden (PR-7 authored vectors
        # freeze Python outputs over the sample-replay-001 fixture).
        RegistryEntry(
            api="rrweb_analyzer.analyze",
            target=f"{_ADAPTERS_MODULE}:analyze_rrweb",
            kind=KIND_BUILDER,
            capability="replays",
        ),
    )


def _validator_entries() -> tuple[RegistryEntry, ...]:
    """Return the module-level validator entries (design D4.2 items 6/7).

    All emit ``list[ValidationError]`` serialized structurally as
    ``[{path, code, severity}]`` (design D4.3 — never message-parsed).

    Returns:
        One ``validator`` entry per module validator.
    """
    validation_names = (
        "validate_time_args",
        "validate_group_by_args",
        "validate_funnel_args",
        "validate_retention_args",
        "validate_flow_args",
        "validate_flow_bookmark",
        "validate_query_args",
        "validate_bookmark",
        "validate_sorting_block",
    )
    entries = [
        RegistryEntry(
            api=f"validation.{name}",
            target=f"{_VALIDATION_MODULE}:{name}",
            kind=KIND_VALIDATOR,
            capability="validation",
            output_codec="validation_errors",
        )
        for name in validation_names
    ]
    entries.extend(
        RegistryEntry(
            api=f"user_validators.{name}",
            target=f"{_USER_VALIDATORS_MODULE}:{name}",
            kind=KIND_VALIDATOR,
            capability="validation",
            output_codec="validation_errors",
        )
        for name in ("validate_user_args", "validate_user_params")
    )
    entries.append(
        RegistryEntry(
            api="bookmark_schema.validate_with_pydantic",
            target="mixpanel_headless._internal.bookmark_schema:validate_with_pydantic",
            kind=KIND_VALIDATOR,
            capability="validation",
            output_codec="validation_errors",
        )
    )
    return tuple(entries)


def _gate_entries() -> tuple[RegistryEntry, ...]:
    """Return the D13 hello-world gate entries (compat + wire stub).

    The compat wrappers are pure builders (CPython is the oracle); the
    wire-stub methods are ``wire_api`` entries replayed through
    ``VectorTransport``/``VectorFetch`` by the two runners. The stub's
    ``close`` is lifecycle plumbing and is audited out.

    Returns:
        The gate entries, compat first.
    """
    compat = tuple(
        RegistryEntry(
            api=f"compat.{name}",
            target=f"{_PYCOMPAT_MODULE}:{name}",
            kind=KIND_BUILDER,
            capability="compat",
        )
        for name in ("zfill", "python_str", "python_float_str")
    )
    wirestub = tuple(
        RegistryEntry(
            api=f"wirestub.{name}",
            target=f"{_PYCOMPAT_MODULE}:WireStubClient.{name}",
            kind=KIND_WIRE_API,
            capability="compat",
        )
        for name in ("request", "request_sequence", "stream_chunks")
    )
    return compat + wirestub


def _module_wire_entries() -> tuple[RegistryEntry, ...]:
    """Return the non-class wire entries (design D1.2 tail list).

    ``OAuthFlow``'s registered surface is exactly its refresh path
    (``refresh_tokens`` — design D1.2 names "``OAuthFlow.refresh``";
    ``login``/``exchange_code`` are the interactive PKCE flow, excluded as
    layer3_deferred per design D2 item 3, and ``get_valid_token`` is a
    convenience over refresh). ``probe_region_for_credential`` is a thin
    orchestration wrapper the design does not name — audited out.

    Returns:
        The ``oauth_flow`` / ``region_probe`` / ``pagination`` entries.
    """
    return (
        RegistryEntry(
            api="oauth_flow.refresh_tokens",
            target="mixpanel_headless._internal.auth.flow:OAuthFlow.refresh_tokens",
            kind=KIND_WIRE_API,
            capability="auth",
        ),
        RegistryEntry(
            api="region_probe.probe_region",
            target="mixpanel_headless._internal.auth.region_probe:probe_region",
            kind=KIND_WIRE_API,
            capability="auth",
        ),
        RegistryEntry(
            api="pagination.paginate_all",
            target="mixpanel_headless._internal.pagination:paginate_all",
            kind=KIND_WIRE_API,
            capability="pagination",
        ),
    )


def build_registry() -> tuple[RegistryEntry, ...]:
    """Assemble the full registry tuple (design D4.4 ``REGISTRY``).

    Imports the library lazily so that merely importing this module in
    tooling contexts stays cheap until the registry is actually built.

    Returns:
        All entries: facades, module builders, validators, gate entries,
        then the mechanical class wire enumerations and module-level wire
        entries.
    """
    from mixpanel_headless._internal.api_client import MixpanelAPIClient
    from mixpanel_headless._internal.services.replays import ReplaysService
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
    replays_entries = _wire_entries_for_class(
        ReplaysService,
        api_prefix="replays",
        module=_REPLAYS_MODULE,
        state_names=frozenset(),
        skip_names=frozenset(),
        capability="replays",
    )
    return (
        _facade_entries()
        + _module_builder_entries()
        + _validator_entries()
        + _gate_entries()
        + client_entries
        + workspace_entries
        + replays_entries
        + _module_wire_entries()
    )


REGISTRY: tuple[RegistryEntry, ...] = build_registry()
"""The registry of record (design D4.4) — one table, two consumers."""

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
