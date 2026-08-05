# mixpanel_headless Package

A complete programmable interface to Mixpanel analytics—Python library and CLI for discovery, querying, streaming, and entity management.

**Design principles:**
- **Self-documenting**: Typed dataclasses with `.df` and `.to_dict()`, exceptions with structured context
- **Discovery-first**: List events, properties, funnels, cohorts, and bookmarks before querying
- **API-first**: Live API queries for analytics, streaming for data extraction

Public API for the Mixpanel data library. Import from here, not from `_internal`.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public exports (Workspace, exceptions, types) |
| `workspace.py` | Main facade class orchestrating all operations |
| `auth_types.py` | Auth surface (Account discriminated union + ServiceAccount/OAuthBrowserAccount/OAuthTokenAccount, Session, Region, OAuthTokens, etc.) |
| `accounts.py` | Functional API for account lifecycle (`mp.accounts.add/use/login/...`) |
| `session.py` | Functional API for active-session axes (`mp.session.show/use`) |
| `targets.py` | Functional API for named targets (account+project+workspace bundles) |
| `exceptions.py` | Exception hierarchy with structured error context |
| `types.py` | Result dataclasses (SegmentationResult, FunnelResult, etc.) + AccountSummary |
| `_literal_types.py` | Literal type aliases (TimeUnit, CountType, HourDayUnit) |
| `_internal/` | Private implementation (do not import directly) |
| `cli/` | Command-line interface |

## Auth Mental Model — Account → Project → Workspace

The 042 redesign organizes auth around three independent axes:

- **Account** — *who* is authenticating. Three types managed through one
  surface: `service_account` (Basic Auth), `oauth_browser` (PKCE flow,
  tokens auto-refreshed), `oauth_token` (static bearer for CI/agents).
  Add via `mp account add NAME --type {...} --region {us|eu|in} ...`.
- **Project** — *which Mixpanel project* the calls run against. Lives on
  the active account as `default_project`; can be overridden per-call
  via `Workspace(project="...")` or `--project`.
- **Workspace** — *which workspace inside the project*. Optional;
  lazy-resolves to the project's default workspace on first
  workspace-scoped call.

**Switching is a one-line operation:** `Workspace.use(account=...,
project=..., workspace=..., target=...)` returns `self` for chaining.
The underlying `httpx.Client` and per-account `/me` cache are preserved
across switches, so cross-project / cross-account iteration is O(1) per
turn (see `examples/cross_project.py`).

Persisted (account, project, workspace?) bundles are called **targets**
and act as named cursor positions:
`mp target add ecom --account team --project 3018488` then
`mp target use ecom`.

## Primary Entry Point

```python
import mixpanel_headless as mp

# Default — resolves the active account/project/workspace from
# `~/.mp/config.toml [active]` + the active account's default_project.
ws = mp.Workspace()

# Override per Workspace (env > param > target > bridge > config)
ws = mp.Workspace(account="team", project="3713224")
ws = mp.Workspace(target="ecom")
ws = mp.Workspace(session=mp.Session(account=..., project=..., workspace=...))

# In-session switching — fluent, O(1), no re-auth on project swap
ws.use(project="3018488").events()
ws.use(account="personal").events()    # rebuilds auth header; preserves _http
ws.use(target="ecom").events()         # applies all three axes atomically
ws.use(workspace=3448414).events()

# Standard usage
events = ws.events()
result = ws.segmentation(event="Login", from_date="2025-01-01", to_date="2025-01-31")
ws.close()

# Context manager (auto-cleanup)
with mp.Workspace() as ws:
    for event in ws.stream_events(from_date="2025-01-01", to_date="2025-01-31"):
        process(event)
```

## Functional Namespaces

- `mp.accounts.add(name, *, type, region, ..., derive_name=False)` — register a new account; `derive_name=True` opts into `/me`-driven naming for SA / oauth_token
- `mp.accounts.list()` — `list[AccountSummary]`
- `mp.accounts.use(name)` — set active account (clears workspace)
- `mp.accounts.login(name)` — run PKCE flow for an oauth_browser account
- `mp.accounts.login_unified(*, name=None, region=None, project=None, ...)` — orchestrator behind `mp login` (043 / AIE-117); composes region probe, project picker, name derivation, and re-login state machine
- `mp.accounts.test(name)` — probe `/me` and return `AccountTestResult`
- `mp.accounts.export_bridge(*, to, account=None)` — write a v2 Cowork bridge file
- `mp.accounts.remove_bridge(*, at=None)` — idempotent bridge removal
- `mp.targets.add(name, *, account, project, workspace=None)` — saved cursor
- `mp.targets.use(name)` — atomic apply (writes all three [active] axes in one save)
- `mp.session.show()` — read the persisted `[active]` block as `ActiveSession`
- `mp.session.use(account=, project=, workspace=, target=)` — write to `[active]`

## Workspace Methods

**Discovery** (self-documenting API): `events()`, `properties()`, `property_values()`, `funnels()`, `cohorts()`, `list_bookmarks()`, `top_events()`, `lexicon_schemas()`, `lexicon_schema()`, `schema_graph()`, `clear_discovery_cache()`

**Streaming**: `stream_events()`, `stream_profiles()`

**Core Analytics**: `segmentation()`, `funnel()`, `retention()`, `query_saved_report()`

**Typed Flow Queries**: `query_flow()`, `build_flow_params()`

**User Profile Queries**: `query_user()`, `build_user_params()`

**Extended Live Queries**: `event_counts()`, `property_counts()`, `activity_feed()`, `query_saved_flows()`, `frequency()`, `segmentation_numeric()`, `segmentation_sum()`, `segmentation_average()`

**Dashboard CRUD**: `list_dashboards()`, `create_dashboard()`, `get_dashboard()`, `update_dashboard()`, `delete_dashboard()`, `bulk_delete_dashboards()`, `favorite_dashboard()`, `unfavorite_dashboard()`, `pin_dashboard()`, `unpin_dashboard()`, `remove_report_from_dashboard()`, `list_blueprint_templates()`, `create_blueprint()`, `get_blueprint_config()`, `update_blueprint_cohorts()`, `finalize_blueprint()`, `create_rca_dashboard()`, `get_bookmark_dashboard_ids()`, `get_dashboard_erf()`, `update_report_link()`, `update_text_card()`

**Report/Bookmark CRUD**: `list_bookmarks_v2()`, `create_bookmark()`, `get_bookmark()`, `update_bookmark()`, `delete_bookmark()`, `bulk_delete_bookmarks()`, `bulk_update_bookmarks()`, `bookmark_linked_dashboard_ids()`, `get_bookmark_history()`

**Cohort CRUD**: `list_cohorts_full()`, `get_cohort()`, `create_cohort()`, `update_cohort()`, `delete_cohort()`, `bulk_delete_cohorts()`, `bulk_update_cohorts()`

**Feature Flag CRUD**: `list_feature_flags()`, `create_feature_flag()`, `get_feature_flag()`, `update_feature_flag()`, `delete_feature_flag()`, `archive_feature_flag()`, `restore_feature_flag()`, `duplicate_feature_flag()`, `set_flag_test_users()`, `get_flag_history()`, `get_flag_limits()`

**Experiment CRUD**: `list_experiments()`, `create_experiment()`, `get_experiment()`, `update_experiment()`, `delete_experiment()`, `launch_experiment()`, `conclude_experiment()`, `decide_experiment()`, `archive_experiment()`, `restore_experiment()`, `duplicate_experiment()`, `list_erf_experiments()`

**Annotation CRUD**: `list_annotations()`, `create_annotation()`, `get_annotation()`, `update_annotation()`, `delete_annotation()`, `list_annotation_tags()`, `create_annotation_tag()`

**Webhook CRUD**: `list_webhooks()`, `create_webhook()`, `update_webhook()`, `delete_webhook()`, `test_webhook()`

**Alert CRUD**: `list_alerts()`, `create_alert()`, `get_alert()`, `update_alert()`, `delete_alert()`, `bulk_delete_alerts()`, `get_alert_count()`, `get_alert_history()`, `test_alert()`, `get_alert_screenshot_url()`, `validate_alerts_for_bookmark()`

**Data Governance — Lexicon**: `get_event_definitions()`, `update_event_definition()`, `delete_event_definition()`, `bulk_update_event_definitions()`, `get_property_definitions()`, `update_property_definition()`, `bulk_update_property_definitions()`, `list_lexicon_tags()`, `create_lexicon_tag()`, `update_lexicon_tag()`, `delete_lexicon_tag()`, `get_tracking_metadata()`, `get_event_history()`, `get_property_history()`, `export_lexicon()`

**Data Governance — Drop Filters**: `list_drop_filters()`, `create_drop_filter()`, `update_drop_filter()`, `delete_drop_filter()`, `get_drop_filter_limits()`

**Data Governance — Custom Properties**: `list_custom_properties()`, `create_custom_property()`, `get_custom_property()`, `update_custom_property()`, `delete_custom_property()`, `validate_custom_property()`

**Data Governance — Lookup Tables**: `list_lookup_tables()`, `upload_lookup_table()`, `mark_lookup_table_ready()`, `get_lookup_upload_url()`, `get_lookup_upload_status()`, `update_lookup_table()`, `delete_lookup_tables()`, `download_lookup_table()`, `get_lookup_download_url()`

**Data Governance — Custom Events**: `list_custom_events()`, `create_custom_event()`, `update_custom_event()`, `delete_custom_event()`

**Business Context**: `get_business_context()`, `set_business_context()`, `clear_business_context()`, `get_business_context_chain()` — read/write the markdown documentation that grounds AI assistants (org and project scopes, 50,000-char cap)

**Escape Hatches**: `api` (MixpanelAPIClient)

## Exception Hierarchy

```
MixpanelHeadlessError
├── ConfigError
│   ├── AccountNotFoundError
│   └── AccountExistsError
├── APIError
│   ├── AuthenticationError
│   ├── RateLimitError
│   ├── QueryError
│   └── ServerError
├── OAuthError
│   └── RegionProbeError    # 043 / AIE-114 — raised when no region accepts the credential
└── WorkspaceScopeError
```

All exceptions provide `.to_dict()` for JSON serialization and structured `.details`.

## Result Types

All frozen dataclasses with:
- `.df` property: Lazy DataFrame conversion (cached)
- `.to_dict()`: JSON-serializable output

Key types: `SegmentationResult`, `FunnelResult`, `RetentionResult`, `SavedReportResult`, `FlowsResult`, `UserQueryResult`, `SchemaGraphResult`, `BookmarkInfo`, `Dashboard`, `CreateDashboardParams`, `UpdateDashboardParams`, `Bookmark`, `CreateBookmarkParams`, `UpdateBookmarkParams`, `Cohort`, `CreateCohortParams`, `UpdateCohortParams`, `BlueprintTemplate`, `BlueprintConfig`, `BookmarkHistoryResponse`

## Query Input Models (schema-exhaustive)

The query models in `query_models.py` (`InsightsQuery`, `FunnelQuery`,
`RetentionQuery`, `FlowQuery`) and every building block they reference
(`Filter`, `Metric`, `GroupBy`, cohort types) are designed so
`model_json_schema()` fully self-describes every valid input — no `Any`,
no bare `dict`, no `additionalProperties: true`, no leaked underscore
fields. This lets **other repositories import them directly** and drive
an LLM/MCP request schema off the generated JSON schema instead of
hand-maintaining AI types.

### Filters — `Filter`, `AbstractFilter`, `FilterFactory`

Three names, three jobs:

- **`Filter`** — the discriminated union routed on `operator`. This is
  what you annotate with.
- **`AbstractFilter`** — the `BaseModel` base holding the shared fields
  and config. The `isinstance` target. Not usable as an annotation for
  a specific filter, and it carries no factories.
- **`FilterFactory`** — a plain class (no fields, no instances) holding
  the 28 `FilterFactory.equals(...)`-style constructors. They exist
  because `operator` is the discriminator and so cannot carry a default:
  giving it one would make it optional in the schema while routing still
  required it. Without the factories every construction would spell out
  `operator="equals"`.

Eleven members, one per *shape* rather than per operator:

| Member | Operators |
|--------|-----------|
| `EqualityFilter` | `equals`, `does not equal` |
| `SubstringFilter` | `starts with`, `ends with` |
| `ContainmentFilter` | `contains`, `does not contain` |
| `NumericComparisonFilter` | `is greater than`, `is less than`, `is at least`, `is at most` |
| `NumericRangeFilter` | `is between`, `not between` |
| `PresenceFilter` | `is set`, `is not set` |
| `BooleanStateFilter` | `true`, `false` |
| `AbsoluteDateFilter` | `was on`, `was not on`, `was before`, `was since` |
| `DateRangeFilter` | `was between`, `was not between` |
| `RelativeDateFilter` | `was in the`, `was not in the`, `was in the next` |
| `CompoundFilter` | `list_contains` |

Containment is split from substring because only `contains` /
`does not contain` carry cohort membership: against the `$cohorts`
pseudo-property their value is `list[CohortRef]`, the structure
`FilterFactory.in_cohort()` builds. Splitting means `starts with` against
`$cohorts` is now rejected.

Each factory returns its member (`FilterFactory.equals(...) ->
EqualityFilter`), and every member subclasses `AbstractFilter`, so
`isinstance(f, AbstractFilter)` holds throughout. Functions that
*consume* filters take `Sequence[Filter]` (covariant), not
`list[Filter]`.

Per-shape members put the rules in the schema rather than in Python:
`PresenceFilter.value` is `null`-typed, `RelativeDateFilter.value`
carries `exclusiveMinimum: 0`, the range members bound their arrays at
exactly 2, and `CompoundFilter.list_item_filters` points at
**`AtomicFilter`** — a ten-member union that omits `CompoundFilter`,
making nested `list_contains` structurally impossible.

Routing goes through `MarkedDiscriminator`, like every other union in
the package, so the chosen member's tag stays strippable from
caller-facing error paths. It also emits the OpenAPI `discriminator`
block: `operator` mapped onto all 26 values.

Rules a field type cannot state live in
`_internal/pydantic_validators.py` as plain functions over primitives — the
module imports no model, which is what lets `types.py` import it for the
bodies of its validator hooks. Models are field declarations,
`model_config`, and one-line hooks.

Not to be confused with `_internal/validation.py`, at the other end of the
lifecycle: that one validates objects that already exist
(`validate_bookmark()`, `validate_query_args()`), so it imports `types`
rather than being imported by it.

**Residuals**, in two directions — see the `Filter` docstring:

- **Runtime ⊃ schema** (the direction to eliminate; the library's own
  output can be schema-invalid): one field, `CohortPayload.raw_cohort`.
  It holds the selector tree `CohortDefinition.to_dict()` emits, whose
  dynamically-named `bhvr_N` keys would render as an untyped open
  object. Schema-side `CohortPayload` therefore requires `id`.
- **Schema ⊃ runtime** (a generator can emit it, so the runtime error
  must be legible): endpoint ordering on the range members, calendar
  validity of dates, and integral floats on `RelativeDateFilter.value`
  (`StrictInt` refuses `1.0`, which JSON Schema's `"type": "integer"`
  accepts).

The equality `value` / `property_type` pairing used to sit in the second
group; `EqualityFilter` now states it as an `if`/`then` in its schema, so
both layers agree. `tests/test_filter_union_pbt.py` asserts schema-valid
⟺ runtime-valid across the operator × property_type × value-kind grid,
exempting exactly the residuals above.

### Payload rendering — `mixpanel_model_dump`

These models are two things at once: the schema an AI/MCP consumer
generates against, and the translation layer into Mixpanel's payload
formats. So they render themselves, rather than being taken apart from
outside by a builder.

`AbstractMixpanelModel` is the base; `mixpanel_model_dump(fmt)` is the entry
point. `fmt="default"` is a plain `model_dump()`; the other three name
endpoint dialects:

| `fmt` | consumer | notes |
|-------|----------|-------|
| `bookmark` | bookmarks / reports | `filterValue`, `filterOperator`, …; `property_type` becomes two keys |
| `segfilter` | flows step filters | operator symbols, `MM/DD/YYYY` dates, stringified numbers |
| `flow_where` | flat flow `where` | **lossy** — `CompoundFilter` and `RelativeDateFilter` raise `PayloadFormatError` |

Subclasses override only the hook whose output differs
(`_dump_bookmark`, `_segfilter_operand`, …), so shape differences live
with the shape. That is what removed the four operator frozensets
`segfilter.py` used to keep in parallel with the member split — one of
which listed `"between"`, an operator that does not exist.

`build_filter_entry`, `build_segfilter_entry` and
`build_flow_where_entries` remain as the call-site API. They now
delegate, and keep only what a single filter cannot know: the `where[i]`
position, the empty-list guard, and the `listItemFilters` backfill.

`filter_to_selector` is deliberately not a dialect — it compiles an
expression string, not a payload.

When adding or changing any of this, follow `.claude/skills/pydantify/`.

Declarative cohort inputs (exported from the package root):
- `PropertyCriterion`, `BehavioralCriterion`, `CohortReferenceCriterion`
  — the criterion alternatives of an inline cohort definition.
- `InlineCohort` — a fully declarative cohort (`{operator, criteria}`)
  accepted anywhere a `CohortDefinition` is; `.to_dict()` matches the
  builder payload format. Builder instances (`CohortDefinition`, `CohortCriteria`)
  still work at runtime; the schema renders the declarative `InlineCohort` alternative.

## Type Aliases

For type hints in consuming code:
- `TimeUnit = Literal["day", "week", "month"]`
- `HourDayUnit = Literal["hour", "day"]`
- `CountType = Literal["general", "unique", "average"]`
