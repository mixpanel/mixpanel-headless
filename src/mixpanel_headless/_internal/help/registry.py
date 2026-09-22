"""Static registries for the built-in help (Plan 047, D5 and D8).

Two hand-maintained tables live here:

- :data:`WORKSPACE_DOMAINS` groups every public ``Workspace`` method under a
  short lowercase domain title. It mirrors the section comments in
  ``workspace.py`` collapsed to about thirty domains. Names are explicit, not
  patterns, so ``tests/unit/help/test_registry_completeness.py`` can assert
  that every public method appears exactly once and that every registered
  name exists. A new ``Workspace`` method without a domain fails CI.
- :data:`REFERENCE_HINTS` maps query tokens (export names, ``Workspace``
  method names) to a hosted documentation page. The table replaces the
  plugin-local ``_REFERENCE_HINTS`` in the old ``help.py`` script. Every path
  is a source path relative to ``docs/`` so the same test can assert the
  page exists; :func:`hint_url` turns it into the hosted URL.

Nothing in this module imports ``Workspace`` or touches the network. The
tables are plain tuples so they are hashable and safe to cache.
"""

from __future__ import annotations

from typing import Final

# =============================================================================
# Workspace domains (D5)
# =============================================================================

WORKSPACE_DOMAINS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "session and switching",
        (
            "use",
            "close",
            "me",
            "projects",
            "workspaces",
            "list_workspaces",
            "resolve_workspace_id",
        ),
    ),
    (
        "discovery",
        (
            "events",
            "properties",
            "property_values",
            "subproperties",
            "funnels",
            "cohorts",
            "list_bookmarks",
            "top_events",
            "clear_discovery_cache",
        ),
    ),
    (
        "lexicon schemas",
        (
            "lexicon_schemas",
            "lexicon_schema",
            "schema_graph",
        ),
    ),
    (
        "streaming",
        (
            "stream_events",
            "stream_profiles",
        ),
    ),
    (
        "legacy live queries",
        (
            "segmentation",
            "funnel",
            "retention",
            "event_counts",
            "property_counts",
            "activity_feed",
            "query_saved_report",
            "query_saved_flows",
            "frequency",
            "segmentation_numeric",
            "segmentation_sum",
            "segmentation_average",
        ),
    ),
    (
        "insights query",
        (
            "query",
            "run_params",
            "build_params",
        ),
    ),
    (
        "funnel query",
        (
            "query_funnel",
            "run_funnel_params",
            "build_funnel_params",
        ),
    ),
    (
        "retention query",
        (
            "query_retention",
            "run_retention_params",
            "build_retention_params",
        ),
    ),
    (
        "flow query",
        (
            "query_flow",
            "run_flow_params",
            "build_flow_params",
        ),
    ),
    (
        "user query",
        (
            "query_user",
            "run_user_params",
            "build_user_params",
        ),
    ),
    (
        "report links",
        (
            "create_report_link",
            "resolve_report_link",
            "query_report_link",
            "saved_report_link",
        ),
    ),
    (
        "dashboards",
        (
            "list_dashboards",
            "create_dashboard",
            "get_dashboard",
            "update_dashboard",
            "delete_dashboard",
            "bulk_delete_dashboards",
            "favorite_dashboard",
            "unfavorite_dashboard",
            "pin_dashboard",
            "unpin_dashboard",
            "add_report_to_dashboard",
            "remove_report_from_dashboard",
            "list_blueprint_templates",
            "create_blueprint",
            "get_blueprint_config",
            "update_blueprint_cohorts",
            "finalize_blueprint",
            "create_rca_dashboard",
            "get_bookmark_dashboard_ids",
            "get_dashboard_erf",
            "update_report_link",
            "update_text_card",
        ),
    ),
    (
        "reports",
        (
            "list_bookmarks_v2",
            "create_bookmark",
            "get_bookmark",
            "update_bookmark",
            "delete_bookmark",
            "bulk_delete_bookmarks",
            "bulk_update_bookmarks",
            "bookmark_linked_dashboard_ids",
            "get_bookmark_history",
        ),
    ),
    (
        "cohorts",
        (
            "list_cohorts_full",
            "get_cohort",
            "create_cohort",
            "update_cohort",
            "delete_cohort",
            "bulk_delete_cohorts",
            "bulk_update_cohorts",
        ),
    ),
    (
        "feature flags",
        (
            "list_feature_flags",
            "create_feature_flag",
            "get_feature_flag",
            "update_feature_flag",
            "delete_feature_flag",
            "archive_feature_flag",
            "restore_feature_flag",
            "duplicate_feature_flag",
            "set_flag_test_users",
            "get_flag_history",
            "get_flag_limits",
        ),
    ),
    (
        "experiments",
        (
            "list_experiments",
            "create_experiment",
            "get_experiment",
            "update_experiment",
            "delete_experiment",
            "launch_experiment",
            "conclude_experiment",
            "decide_experiment",
            "archive_experiment",
            "restore_experiment",
            "duplicate_experiment",
            "list_erf_experiments",
        ),
    ),
    (
        "annotations",
        (
            "list_annotations",
            "create_annotation",
            "get_annotation",
            "update_annotation",
            "delete_annotation",
            "list_annotation_tags",
            "create_annotation_tag",
        ),
    ),
    (
        "webhooks",
        (
            "list_webhooks",
            "create_webhook",
            "update_webhook",
            "delete_webhook",
            "test_webhook",
        ),
    ),
    (
        "alerts",
        (
            "list_alerts",
            "create_alert",
            "get_alert",
            "update_alert",
            "delete_alert",
            "bulk_delete_alerts",
            "get_alert_count",
            "get_alert_history",
            "test_alert",
            "get_alert_screenshot_url",
            "validate_alerts_for_bookmark",
        ),
    ),
    (
        "lexicon governance",
        (
            "get_event_definitions",
            "update_event_definition",
            "delete_event_definition",
            "bulk_update_event_definitions",
            "get_property_definitions",
            "update_property_definition",
            "bulk_update_property_definitions",
            "list_lexicon_tags",
            "create_lexicon_tag",
            "update_lexicon_tag",
            "delete_lexicon_tag",
        ),
    ),
    (
        "drop filters",
        (
            "list_drop_filters",
            "create_drop_filter",
            "update_drop_filter",
            "delete_drop_filter",
            "get_drop_filter_limits",
        ),
    ),
    (
        "custom properties",
        (
            "list_custom_properties",
            "create_custom_property",
            "get_custom_property",
            "update_custom_property",
            "delete_custom_property",
            "validate_custom_property",
        ),
    ),
    (
        "custom events",
        (
            "create_custom_event",
            "list_custom_events",
            "update_custom_event",
            "delete_custom_event",
        ),
    ),
    (
        "lookup tables",
        (
            "list_lookup_tables",
            "upload_lookup_table",
            "mark_lookup_table_ready",
            "get_lookup_upload_url",
            "get_lookup_upload_status",
            "update_lookup_table",
            "delete_lookup_tables",
            "download_lookup_table",
            "get_lookup_download_url",
        ),
    ),
    (
        "tracking and history",
        (
            "get_tracking_metadata",
            "get_event_history",
            "get_property_history",
            "export_lexicon",
        ),
    ),
    (
        "schema registry",
        (
            "list_schema_registry",
            "create_schema",
            "create_schemas_bulk",
            "update_schema",
            "update_schemas_bulk",
            "delete_schemas",
        ),
    ),
    (
        "schema enforcement",
        (
            "get_schema_enforcement",
            "init_schema_enforcement",
            "update_schema_enforcement",
            "replace_schema_enforcement",
            "delete_schema_enforcement",
        ),
    ),
    (
        "data audit",
        (
            "run_audit",
            "run_audit_events_only",
        ),
    ),
    (
        "volume anomalies",
        (
            "list_data_volume_anomalies",
            "update_anomaly",
            "bulk_update_anomalies",
        ),
    ),
    (
        "deletion requests",
        (
            "list_deletion_requests",
            "create_deletion_request",
            "cancel_deletion_request",
            "preview_deletion_filters",
        ),
    ),
    (
        "business context",
        (
            "get_business_context",
            "set_business_context",
            "clear_business_context",
            "get_business_context_chain",
        ),
    ),
    (
        "session replay",
        (
            "list_replays",
            "events_for_replay",
            "events_for_replays",
            "sign_replay",
            "sign_replays",
            "fetch_replay",
            "stream_replay",
            "fetch_replays",
            "replays_for_user",
            "analyze_replay",
        ),
    ),
)
"""Ordered ``(domain title, method names)`` pairs covering every public ``Workspace`` method.

Titles are lowercase phrases in the order the plan lists them (D5). The
``ESCAPE HATCHES`` section of ``workspace.py`` holds only the ``api``
property, and properties are listed separately by the resolver, so that
section has no domain here.
"""

_DOMAIN_INDEX: Final[dict[str, str]] = {
    name: title for title, names in WORKSPACE_DOMAINS for name in names
}
"""Reverse index from method name to domain title, built once at import."""


def domain_of(method_name: str) -> str | None:
    """Return the domain title that lists a ``Workspace`` method.

    Args:
        method_name: A public ``Workspace`` method name, for example
            ``"query_funnel"``.

    Returns:
        The lowercase domain title, or ``None`` when the name is not a
        registered method (properties, private helpers, and unknown names
        all return ``None``).

    Example:
        ```python
        domain_of("create_dashboard")
        # "dashboards"
        domain_of("api")
        # None
        ```
    """
    return _DOMAIN_INDEX.get(method_name)


# =============================================================================
# Reference hints (D8)
# =============================================================================

DOCS_BASE: Final[str] = "https://mixpanel.github.io/mixpanel-headless/"
"""Root of the hosted documentation site (mkdocs, directory URLs)."""

WORKSPACE_HINT: Final[tuple[str, str]] = (
    "complete method signatures organized by domain",
    "api/workspace.md",
)
"""Hint for the bare ``Workspace`` query: ``(title, docs source path)`` (P17)."""

REFERENCE_HINTS: Final[tuple[tuple[tuple[str, ...], str, str], ...]] = (
    # --- typed query engines: most specific first ------------------------
    (
        ("query_user", "build_user_params", "run_user_params", "UserQueryResult"),
        "user profile queries — filtering, sorting, aggregate counts",
        "guide/query-users.md",
    ),
    (
        (
            "query_flow",
            "build_flow_params",
            "run_flow_params",
            "query_saved_flows",
            "FlowQueryResult",
            "FlowStep",
            "FlowTreeNode",
            "FlowStepNode",
            "FlowEdge",
            "FlowNodeType",
            "FlowAnchorType",
            "FlowCountType",
            "FlowChartType",
            "FlowConversionWindowUnit",
            "FlowSessionEvent",
            "FlowsResult",
        ),
        "FlowStep, NetworkX graph, anytree trees, modes",
        "guide/query-flows.md",
    ),
    (
        (
            "query_retention",
            "build_retention_params",
            "run_retention_params",
            "RetentionQueryResult",
            "RetentionEvent",
            "RetentionMathType",
            "RetentionAlignment",
            "RetentionMode",
            "RetentionUnboundedMode",
            "RetentionCohortData",
        ),
        "RetentionEvent, alignment, custom buckets",
        "guide/query-retention.md",
    ),
    (
        (
            "query_funnel",
            "build_funnel_params",
            "run_funnel_params",
            "FunnelQueryResult",
            "FunnelStep",
            "FunnelStepData",
            "Exclusion",
            "HoldingConstant",
            "FunnelMathType",
            "FunnelMode",
            "FunnelOrder",
            "FunnelReentryMode",
            "ConversionWindowUnit",
        ),
        "FunnelStep, Exclusion, HoldingConstant, conversion windows",
        "guide/query-funnels.md",
    ),
    (
        (
            "query",
            "build_params",
            "run_params",
            "QueryResult",
            "QueryMeta",
            "MathType",
            "PerUserAggregation",
            "InsightsMode",
            "QueryTimeUnit",
            "SegmentMethod",
            "TimeComparison",
            "TimeComparisonType",
            "TimeComparisonUnit",
            "Filter",
            "FilterOperator",
            "FilterPropertyType",
            "FilterDateUnit",
            "FiltersCombinator",
            "GroupBy",
            "ListItemGroupMode",
            "Formula",
            "Metric",
            "CohortBreakdown",
            "CohortMetric",
            "CohortDefinition",
            "CohortCriteria",
            "CohortAggregationType",
            "CustomPropertyRef",
            "InlineCustomProperty",
            "PropertyInput",
            "PropertySpec",
            "FrequencyFilter",
            "FrequencyFilterOperator",
            "FrequencyBreakdown",
        ),
        "MathType, Filter, GroupBy, Formula, validation rules",
        "guide/query.md",
    ),
    # --- session replay (044) ---------------------------------------------
    (
        (
            "list_replays",
            "events_for_replay",
            "events_for_replays",
            "sign_replay",
            "sign_replays",
            "fetch_replay",
            "stream_replay",
            "fetch_replays",
            "replays_for_user",
            "analyze_replay",
            "Replay",
            "ReplayBundle",
            "ReplayEvent",
            "ReplaySummary",
            "SignedReplay",
            "UserAction",
            "default_label_fn",
            "selector_label_fn",
            "url_normalizer",
            "SessionReplayError",
            "SessionReplayAccessError",
            "SignedURLExpiredError",
            "ReplayNotFoundError",
            "UnsupportedReplayFormatError",
        ),
        "session replay — discover, sign, fetch, and analyze rrweb recordings",
        "guide/session-replay.md",
    ),
    # --- report links (045) -----------------------------------------------
    (
        (
            "create_report_link",
            "resolve_report_link",
            "query_report_link",
            "saved_report_link",
            "ReportLink",
            "ResolvedReport",
            "ReportLinkQueryResult",
            "ReportLinkType",
            "BookmarkUrl",
            "ReportLinkError",
            "ReportLinkParseError",
            "UnsupportedReportLinkError",
            "ReportLinkNotFoundError",
            "ReportLinkScopeMismatchError",
            "ShortLinkResolutionError",
        ),
        "report links — share a query as a URL, resolve a URL back into params",
        "guide/report-links.md",
    ),
    # --- business context (AIE-147) ---------------------------------------
    (
        (
            "get_business_context",
            "set_business_context",
            "clear_business_context",
            "get_business_context_chain",
            "BusinessContext",
            "BusinessContextChain",
            "BusinessContextValidationError",
            "BUSINESS_CONTEXT_MAX_CHARS",
        ),
        "business context — org and project markdown that grounds AI assistants",
        "guide/business-context.md",
    ),
    # --- entity management: reports, dashboards, cohorts -------------------
    (
        (
            "create_bookmark",
            "update_bookmark",
            "get_bookmark",
            "delete_bookmark",
            "list_bookmarks_v2",
            "bulk_delete_bookmarks",
            "bulk_update_bookmarks",
            "bookmark_linked_dashboard_ids",
            "get_bookmark_history",
            "validate_bookmark",
            "query_saved_report",
            "CreateBookmarkParams",
            "UpdateBookmarkParams",
            "BulkUpdateBookmarkEntry",
            "Bookmark",
            "BookmarkMetadata",
            "BookmarkInfo",
            "BookmarkType",
            "BookmarkHistoryResponse",
            "BookmarkHistoryPagination",
            "BookmarkValidationError",
            "ValidationError",
            "SavedReportResult",
            "SavedReportType",
        ),
        "bookmark params, entity management",
        "guide/entity-management.md",
    ),
    (
        (
            "list_dashboards",
            "create_dashboard",
            "get_dashboard",
            "update_dashboard",
            "delete_dashboard",
            "bulk_delete_dashboards",
            "favorite_dashboard",
            "unfavorite_dashboard",
            "pin_dashboard",
            "unpin_dashboard",
            "add_report_to_dashboard",
            "remove_report_from_dashboard",
            "list_blueprint_templates",
            "create_blueprint",
            "get_blueprint_config",
            "update_blueprint_cohorts",
            "finalize_blueprint",
            "create_rca_dashboard",
            "get_bookmark_dashboard_ids",
            "get_dashboard_erf",
            "update_report_link",
            "update_text_card",
            "Dashboard",
            "DashboardRow",
            "DashboardRowContent",
            "CreateDashboardParams",
            "UpdateDashboardParams",
            "UpdateTextCardParams",
            "UpdateReportLinkParams",
            "BlueprintTemplate",
            "BlueprintConfig",
            "BlueprintCard",
            "BlueprintFinishParams",
            "CreateRcaDashboardParams",
            "RcaSourceData",
        ),
        "dashboards, reports, and cohorts (entity management)",
        "guide/entity-management.md",
    ),
    (
        (
            "list_cohorts_full",
            "get_cohort",
            "create_cohort",
            "update_cohort",
            "delete_cohort",
            "bulk_delete_cohorts",
            "bulk_update_cohorts",
            "Cohort",
            "CohortCreator",
            "CreateCohortParams",
            "UpdateCohortParams",
            "BulkUpdateCohortEntry",
        ),
        "cohort CRUD (entity management)",
        "guide/entity-management.md",
    ),
    # --- data governance (027 / 028) --------------------------------------
    (
        (
            "get_event_definitions",
            "update_event_definition",
            "delete_event_definition",
            "bulk_update_event_definitions",
            "get_property_definitions",
            "update_property_definition",
            "bulk_update_property_definitions",
            "list_lexicon_tags",
            "create_lexicon_tag",
            "update_lexicon_tag",
            "delete_lexicon_tag",
            "list_drop_filters",
            "create_drop_filter",
            "update_drop_filter",
            "delete_drop_filter",
            "get_drop_filter_limits",
            "list_custom_properties",
            "create_custom_property",
            "get_custom_property",
            "update_custom_property",
            "delete_custom_property",
            "validate_custom_property",
            "create_custom_event",
            "list_custom_events",
            "update_custom_event",
            "delete_custom_event",
            "list_lookup_tables",
            "upload_lookup_table",
            "mark_lookup_table_ready",
            "get_lookup_upload_url",
            "get_lookup_upload_status",
            "update_lookup_table",
            "delete_lookup_tables",
            "download_lookup_table",
            "get_lookup_download_url",
            "get_tracking_metadata",
            "get_event_history",
            "get_property_history",
            "export_lexicon",
            "list_schema_registry",
            "create_schema",
            "create_schemas_bulk",
            "update_schema",
            "update_schemas_bulk",
            "delete_schemas",
            "get_schema_enforcement",
            "init_schema_enforcement",
            "update_schema_enforcement",
            "replace_schema_enforcement",
            "delete_schema_enforcement",
            "run_audit",
            "run_audit_events_only",
            "list_data_volume_anomalies",
            "update_anomaly",
            "bulk_update_anomalies",
            "list_deletion_requests",
            "create_deletion_request",
            "cancel_deletion_request",
            "preview_deletion_filters",
            "EventDefinition",
            "PropertyDefinition",
            "PropertyResourceType",
            "CustomPropertyResourceType",
            "UpdateEventDefinitionParams",
            "UpdatePropertyDefinitionParams",
            "BulkEventUpdate",
            "BulkUpdateEventsParams",
            "BulkPropertyUpdate",
            "BulkUpdatePropertiesParams",
            "LexiconTag",
            "CreateTagParams",
            "UpdateTagParams",
            "DropFilter",
            "CreateDropFilterParams",
            "UpdateDropFilterParams",
            "DropFilterLimitsResponse",
            "CustomProperty",
            "ComposedPropertyValue",
            "CreateCustomPropertyParams",
            "UpdateCustomPropertyParams",
            "CustomPropertyType",
            "CustomEvent",
            "CustomEventAlternative",
            "CreateCustomEventParams",
            "LookupTable",
            "UploadLookupTableParams",
            "MarkLookupTableReadyParams",
            "LookupTableUploadUrl",
            "UpdateLookupTableParams",
            "SchemaEntry",
            "BulkCreateSchemasParams",
            "BulkCreateSchemasResponse",
            "BulkPatchResult",
            "DeleteSchemasResponse",
            "SchemaEnforcementConfig",
            "InitSchemaEnforcementParams",
            "UpdateSchemaEnforcementParams",
            "ReplaceSchemaEnforcementParams",
            "AuditResponse",
            "AuditViolation",
            "DataVolumeAnomaly",
            "UpdateAnomalyParams",
            "BulkUpdateAnomalyParams",
            "BulkAnomalyEntry",
            "EventDeletionRequest",
            "CreateDeletionRequestParams",
            "PreviewDeletionFiltersParams",
        ),
        "data governance — Lexicon, drop filters, custom properties and events, "
        "lookup tables, schema registry, enforcement, audits, anomalies, "
        "deletion requests",
        "guide/data-governance.md",
    ),
    # --- discovery ---------------------------------------------------------
    (
        (
            "schema_graph",
            "SchemaGraphResult",
            "events",
            "properties",
            "property_values",
            "subproperties",
            "SubPropertyInfo",
            "lexicon_schemas",
            "lexicon_schema",
            "LexiconSchema",
            "LexiconDefinition",
            "LexiconMetadata",
            "LexiconProperty",
            "EntityType",
            "top_events",
            "TopEvent",
            "funnels",
            "FunnelInfo",
            "cohorts",
            "SavedCohort",
            "CohortInfo",
            "list_bookmarks",
            "clear_discovery_cache",
            "EventNotFoundError",
        ),
        "schema_graph (event<->property map + coverage), events, properties, "
        "values, lexicon schemas",
        "guide/discovery.md",
    ),
    # --- streaming ---------------------------------------------------------
    (
        (
            "stream_events",
            "stream_profiles",
            "ProfilePageResult",
            "DateRangeTooLargeError",
        ),
        "stream events and profiles for ETL",
        "guide/streaming.md",
    ),
    # --- legacy live analytics ---------------------------------------------
    (
        (
            "segmentation",
            "funnel",
            "retention",
            "event_counts",
            "property_counts",
            "activity_feed",
            "frequency",
            "segmentation_numeric",
            "segmentation_sum",
            "segmentation_average",
            "SegmentationResult",
            "FunnelResult",
            "FunnelResultStep",
            "RetentionResult",
            "EventCountsResult",
            "PropertyCountsResult",
            "ActivityFeedResult",
            "UserEvent",
            "FrequencyResult",
            "NumericBucketResult",
            "NumericSumResult",
            "NumericAverageResult",
            "TimeUnit",
            "HourDayUnit",
            "CountType",
        ),
        "segmentation, funnels, retention (legacy live queries)",
        "guide/live-analytics.md",
    ),
    # --- auth and accounts (042 / 043) ------------------------------------
    (
        (
            "use",
            "close",
            "me",
            "projects",
            "workspaces",
            "list_workspaces",
            "resolve_workspace_id",
            "accounts",
            "session",
            "targets",
            "login_unified",
            "Account",
            "AccountType",
            "ServiceAccount",
            "OAuthBrowserAccount",
            "OAuthTokenAccount",
            "Session",
            "Project",
            "WorkspaceRef",
            "Region",
            "AccountSummary",
            "AccountTestResult",
            "OAuthLoginResult",
            "Target",
            "PublicWorkspace",
            "ConfigError",
            "AccountNotFoundError",
            "AccountExistsError",
            "AccountInUseError",
            "ProjectNotFoundError",
            "AuthenticationError",
            "OAuthError",
            "RegionProbeError",
            "RegionProbeNetworkError",
            "WorkspaceScopeError",
        ),
        "auth and accounts — account types, sessions, targets, in-session switching",
        "api/auth.md",
    ),
    # --- CLI ---------------------------------------------------------------
    (
        ("cli", "mp", "command", "commands"),
        "the mp command-line interface — every command, flag, and output format",
        "cli/commands.md",
    ),
)
"""Ordered ``(triggers, title, docs source path)`` hint rules (D8, P17).

``triggers`` are query tokens — export names and ``Workspace`` method
names. A query such as ``Workspace.query_funnel`` splits on ``.`` into the
tokens ``Workspace`` and ``query_funnel``; the first rule whose trigger set
intersects the token set wins. The old script matched whole tokens rather
than substrings because generic triggers such as ``query`` false-positive on
compound names like ``query_saved_report``; keep that rule in ``hints.py``.
Specific engines precede the generic insights rule so ``query_funnel``
picks the funnels page. Dashboards point at the entity-management guide
(F8): plugin-local ``dashboard-expert`` pointers belong in plugin markdown.
Every ``path`` is relative to ``docs/`` in the repository; use
:func:`hint_url` for the hosted URL.
"""


def hint_url(path: str) -> str:
    """Return the hosted URL for a docs source path.

    mkdocs serves the site with directory URLs (the default
    ``use_directory_urls: true``), and the ``llmstxt-md`` plugin publishes
    one ``index.md`` per page. A source page ``guide/query.md`` is therefore
    fetched at ``{DOCS_BASE}guide/query/index.md``, while a source
    ``index.md`` keeps its directory.

    Args:
        path: Docs source path relative to ``docs/``, for example
            ``"guide/query.md"``. A leading ``/`` or ``docs/`` prefix is
            tolerated.

    Returns:
        Absolute ``https`` URL ending in ``index.md``.

    Example:
        ```python
        hint_url("guide/entity-management.md")
        # "https://mixpanel.github.io/mixpanel-headless/guide/entity-management/index.md"
        hint_url("api/index.md")
        # "https://mixpanel.github.io/mixpanel-headless/api/index.md"
        ```
    """
    rel = path.strip().lstrip("/")
    if rel.startswith("docs/"):
        rel = rel[len("docs/") :]
    if rel.endswith(".md"):
        rel = rel[: -len(".md")]
    parts = [p for p in rel.split("/") if p]
    if parts and parts[-1] == "index":
        parts.pop()
    directory = "/".join(parts)
    return f"{DOCS_BASE}{directory}/index.md" if directory else f"{DOCS_BASE}index.md"
