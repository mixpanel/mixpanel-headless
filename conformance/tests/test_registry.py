"""Unit tests for the full entry-point registry (design D4.4, PR-3).

The PR-3 done-criterion test lives here: iterate the WHOLE ``REGISTRY`` and
prove every target imports, resolves, introspects, and wraps cleanly — the
exact operations the record plugin performs at ``activate()`` and the
corpus runner performs at replay (one registry, two consumers).
"""

from __future__ import annotations

import inspect
import unittest.mock as umock

from conformance.record.codecs import UnencodableValueError, encode_output
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    KIND_WIRE_API,
    KIND_WIRE_STATE,
    REGISTRY,
    REGISTRY_BY_API,
    resolve_callable,
    resolve_owner,
)

_VALID_KINDS = frozenset({KIND_BUILDER, KIND_VALIDATOR, KIND_WIRE_API, KIND_WIRE_STATE})
"""The four registry kinds (design D4.4 + D1.2)."""

_KNOWN_OUTPUT_CODECS = frozenset(
    {"json", "validation_errors", "model_name", "selector_str"}
)
"""Output codec names ``conformance.record.codecs.encode_output`` dispatches."""


def test_api_names_are_unique() -> None:
    """Every registry entry has a distinct dotted vector name (design D4.4).

    Raises:
        AssertionError: If two entries share an ``api`` name.
    """
    assert len(REGISTRY_BY_API) == len(REGISTRY)


def test_every_kind_is_valid() -> None:
    """All entries carry one of the four D4.4/D1.2 kinds.

    Raises:
        AssertionError: If an entry has an unknown kind.
    """
    bad = [entry.api for entry in REGISTRY if entry.kind not in _VALID_KINDS]
    assert bad == []


def test_builder_and_validator_entries_have_capabilities() -> None:
    """Builder/validator entries name their corpus directory (design D3).

    Only mechanically-enumerated class wire entries may leave ``capability``
    empty (the emit-time endpoint table assigns theirs).

    Raises:
        AssertionError: If a builder or validator entry lacks a capability.
    """
    bad = [
        entry.api
        for entry in REGISTRY
        if entry.kind in (KIND_BUILDER, KIND_VALIDATOR) and not entry.capability
    ]
    assert bad == []


def test_output_codecs_are_dispatchable() -> None:
    """Every entry's output codec is known to ``encode_output`` (design D4.4).

    Registry and codec table must agree; an unknown name would surface as
    an ``UnencodableValueError`` on the first recorded call.

    Raises:
        AssertionError: If an entry names an unregistered output codec.
    """
    bad = [
        entry.api
        for entry in REGISTRY
        if entry.output_codec not in _KNOWN_OUTPUT_CODECS
    ]
    assert bad == []


def test_unknown_output_codec_fails_loudly() -> None:
    """``encode_output`` rejects unknown codec names (never silent fallback).

    Raises:
        AssertionError: If the unknown-codec guard is missing.
    """
    try:
        encode_output("no_such_codec", 1)
    except UnencodableValueError:
        return
    raise AssertionError("unknown output codec did not raise")


def test_every_target_resolves_and_wraps_cleanly() -> None:
    """PR-3 done criterion: the whole REGISTRY resolves and wraps.

    For every entry: the target imports and resolves to a callable, its
    signature introspects (required by the plugin's kwargs binding and the
    emit-time api-index), and ``unittest.mock.patch.object`` can install
    and remove a wrapper at the resolved owner/attribute — exactly what
    ``RecordSession._wrap_registry`` does per session.

    Raises:
        AssertionError: If any entry fails any step.
    """

    def _stub(*args: object, **kwargs: object) -> None:
        """Do-nothing wrapper stand-in for the patch check.

        Args:
            *args: Ignored.
            **kwargs: Ignored.
        """
        del args, kwargs

    for entry in REGISTRY:
        func = resolve_callable(entry)
        assert callable(func), entry.api
        signature = inspect.signature(func)
        assert signature is not None, entry.api

        owner, attr = resolve_owner(entry)
        # Classmethod access (getattr) mints a fresh bound method per
        # lookup, so identity checks must compare the STATIC descriptor
        # (the coded-guard entries register classmethod targets — RR-7).
        original = inspect.getattr_static(owner, attr)
        patcher = umock.patch.object(owner, attr, _stub)
        patcher.start()
        try:
            assert inspect.getattr_static(owner, attr) is not original, entry.api
        finally:
            patcher.stop()
        assert inspect.getattr_static(owner, attr) is original, entry.api


def test_wire_enumeration_covers_the_design_seams() -> None:
    """The D1.2 wire enumeration includes every named seam family.

    Spot-checks one representative per seam: ``api_client`` (P1-P3),
    ``replays`` (P4), ``oauth_flow`` (P5), ``region_probe`` (P6), plus
    ``workspace`` facade-adjacent wire methods and the pagination module
    entry.

    Raises:
        AssertionError: If a seam representative is missing or miskinded.
    """
    expectations = {
        "api_client.segmentation": KIND_WIRE_API,
        "api_client.set_workspace_id": KIND_WIRE_STATE,
        "api_client.upload_to_signed_url": KIND_WIRE_API,
        "workspace.query": KIND_WIRE_API,
        "workspace.use": KIND_WIRE_STATE,
        "replays.walk_cdn_async": KIND_WIRE_API,
        "oauth_flow.refresh_tokens": KIND_WIRE_API,
        "region_probe.probe_region": KIND_WIRE_API,
        "pagination.paginate_all": KIND_WIRE_API,
        "wirestub.request": KIND_WIRE_API,
    }
    for api, kind in expectations.items():
        entry = REGISTRY_BY_API.get(api)
        assert entry is not None, api
        assert entry.kind == kind, api


def test_builder_registry_covers_the_design_d42_list() -> None:
    """Every design D4.1/D4.2 builder/validator contract is registered.

    Raises:
        AssertionError: If a design-mandated entry is missing.
    """
    required = {
        # D4.1 facades
        "workspace.build_params",
        "workspace.build_funnel_params",
        "workspace.build_flow_params",
        "workspace.build_retention_params",
        "workspace.build_user_params",
        # D4.2 item 1
        "bookmark_builders.build_filter_entry",
        "bookmark_builders.build_filter_section",
        "bookmark_builders.build_frequency_filter_entry",
        "segfilter.build_segfilter_entry",
        "user_builders.filter_to_selector",
        "user_builders.filters_to_selector",
        "user_builders.extract_cohort_filter",
        # D4.2 item 2
        "bookmark_builders.build_date_range",
        "bookmark_builders.build_time_section",
        # D4.2 item 3
        "expressions.normalize_on_expression",
        # D4.2 item 4
        "transforms.transform_event",
        "transforms.transform_profile",
        # D4.2 item 5
        "replay_labels.url_normalizer",
        "replay_labels.default_label_fn",
        "replay_labels.selector_label_fn",
        # D4.2 item 6
        "validation.validate_time_args",
        "validation.validate_group_by_args",
        "validation.validate_funnel_args",
        "validation.validate_retention_args",
        "validation.validate_flow_args",
        "validation.validate_flow_bookmark",
        "validation.validate_query_args",
        "validation.validate_bookmark",
        "validation.validate_sorting_block",
        "user_validators.validate_user_args",
        "user_validators.validate_user_params",
        # D4.2 item 7
        "bookmark_schema.validate_with_pydantic",
        "bookmark_schema.get_root_model_for_bookmark_type",
        # D4.2 item 8
        "types._sanitize_raw_cohort",
        "types.CohortDefinition.to_dict",
        # D4.2 item 9
        "api_client._iter_jsonl_lines",
        # D13 gate
        "compat.zfill",
        "compat.python_str",
        "compat.python_float_str",
    }
    missing = sorted(required - set(REGISTRY_BY_API))
    assert missing == []


def test_validators_use_the_structural_output_codec() -> None:
    """All validator entries emit structural errors (design D4.3).

    Raises:
        AssertionError: If a validator entry uses a different output codec.
    """
    bad = [
        entry.api
        for entry in REGISTRY
        if entry.kind == KIND_VALIDATOR and entry.output_codec != "validation_errors"
    ]
    assert bad == []


def test_replays_wire_entries_carry_replays_capability() -> None:
    """ReplaysService wire entries pin capability ``replays`` (PR-5 audit).

    CDN hosts are absent from the emit-time endpoint table, so deferring
    to it misfiled ``replays.fetch_files`` vectors under ``entities``.

    Raises:
        AssertionError: If any replays entry lacks the capability.
    """
    from conformance.record.registry import REGISTRY

    replays_entries = [e for e in REGISTRY if e.api.startswith("replays.")]
    assert replays_entries
    assert all(e.capability == "replays" for e in replays_entries)


# ---------------------------------------------------------------------------
# Coded-guard error_only entries (coding-pass design §5 item 2, RR-7)
# ---------------------------------------------------------------------------


def test_error_only_defaults_false_for_existing_entries() -> None:
    """Pre-existing entries carry ``error_only=False`` (flag is opt-in).

    Raises:
        AssertionError: If a non-guard entry is marked error_only.
    """
    assert REGISTRY_BY_API["workspace.build_params"].error_only is False
    assert REGISTRY_BY_API["types.CohortDefinition.to_dict"].error_only is False


def test_coded_guard_entries_registered_and_resolvable() -> None:
    """The B1 constructor-guard families are registered as error_only builders.

    Every guard entry must resolve to a patchable owner/attr pair so the
    plugin can wrap it (classmethods resolve through their class).

    Raises:
        AssertionError: If an entry is missing, mis-kinded, or unresolvable.
    """
    expected = (
        "types.TimeComparison",
        "types.Metric",
        "types.Formula",
        "types.Filter",
        "types.Filter.on",
        "types.Filter.before",
        "types.Filter.since",
        "types.Filter.in_the_last",
        "types.Filter.not_in_the_last",
        "types.Filter.in_the_next",
        "types.Filter.date_between",
        "types.Filter.date_not_between",
        "types.Filter.list_contains",
        "types.Filter.in_cohort",
        "types.Filter.not_in_cohort",
        "types.ListItemGroupMode",
        "types.GroupBy",
        "types.FrequencyBreakdown",
        "types.FrequencyFilter",
        "types.Exclusion",
        "types.HoldingConstant",
        "types.FlowStep",
        "types.CohortCriteria.did_event",
        "types.CohortCriteria.did_not_do_event",
        "types.CohortCriteria.has_property",
        "types.CohortCriteria.in_cohort",
        "types.CohortCriteria.not_in_cohort",
        "types.CohortDefinition",
        "types.CohortDefinition.all_of",
        "types.CohortDefinition.any_of",
        "types.CohortBreakdown",
        "types.CohortMetric",
        "types.ReplaySummary",
        "types.SignedReplay",
        "types.UserAction",
        "types.ReplayEvent",
        "types.Replay",
        "types.ReplayBundle",
    )
    for api in expected:
        entry = REGISTRY_BY_API[api]
        assert entry.error_only is True, api
        assert entry.kind == KIND_BUILDER, api
        owner, attr = resolve_owner(entry)
        assert hasattr(owner, attr), api


def test_b2_flow_builder_entries_registered_and_resolvable() -> None:
    """The B2 bookmark_builders guard seams are registered plain builders.

    Coding-pass design §4 B2: ``build_group_section``,
    ``build_flow_property_filter``, and ``build_flow_cohort_filter`` carry
    coded guards (BB1-BB8) but were previously unregistered, leaving those
    guards invisible to the recorder. They register as ordinary (NOT
    error_only) builder entries — their success outputs are recordable.

    Raises:
        AssertionError: If an entry is missing, mis-kinded, flagged
            error_only, or unresolvable.
    """
    expected = (
        "bookmark_builders.build_group_section",
        "bookmark_builders.build_flow_property_filter",
        "bookmark_builders.build_flow_cohort_filter",
    )
    for api in expected:
        entry = REGISTRY_BY_API.get(api)
        assert entry is not None, api
        assert entry.kind == KIND_BUILDER, api
        assert entry.error_only is False, api
        assert entry.capability, api
        owner, attr = resolve_owner(entry)
        assert hasattr(owner, attr), api
        assert callable(resolve_callable(entry)), api
