# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

`mixpanel_headless` is a complete programmable interface to Mixpanel analytics—Python library and CLI for discovery, querying, streaming, and entity management. Discover your schema, run live analytics (segmentation, funnels, retention), and manage entities via the Mixpanel App API.

| Context | Name | Example |
|---------|------|---------|
| PyPI package | `mixpanel_headless` | `pip install mixpanel_headless` |
| Python import | `mixpanel_headless` | `import mixpanel_headless as mp` |
| CLI command | `mp` | `mp query segmentation -e Login --from 2025-01-01` |

## Architecture

Layered architecture with `Workspace` class as the primary facade:

```
CLI (Typer)              → mp commands, output formatting
    ↓
Public API               → Workspace, auth module, exceptions, types
    ↓
Services                 → DiscoveryService, LiveQueryService
    ↓
Infrastructure           → ConfigManager, MixpanelAPIClient
```

**Capability areas:**
- **Discovery**: Explore schema (events, properties, funnels, cohorts, bookmarks, schema graph)
- **Live queries & streaming**: Call Mixpanel API directly (segmentation, funnels, retention, user profiles), stream events and profiles
- **Entity CRUD & Data Governance**: Create, read, update, delete dashboards, reports (bookmarks), cohorts, feature flags, experiments, alerts, annotations, webhooks, Lexicon definitions, drop filters, custom properties, custom events, and lookup tables via App API
- **Session replay**: Discover, sign, fetch, and analyze rrweb session recordings (`Workspace.replays_for_user` / `fetch_replay`, `Replay` / `ReplayBundle`, `mp replays`)

## Package Structure

```
src/mixpanel_headless/
├── __init__.py              # Public API exports
├── workspace.py             # Workspace facade — `use(account=, project=, workspace=, target=)`
├── auth_types.py            # Auth surface (Account union, Session, Region, OAuthTokens, …)
├── accounts.py              # `mp.accounts` — add/list/use/login/test/export-bridge/...
├── session.py               # `mp.session` — show/use the persisted [active] block
├── targets.py               # `mp.targets` — saved (account, project, workspace?) cursors
├── exceptions.py            # Exception hierarchy (incl. AccountInUseError, WorkspaceScopeError)
├── types.py                 # Result types (SegmentationResult, AccountSummary, …)
├── replay_labels.py         # Public replay label helpers (default_label_fn, selector_label_fn, url_normalizer)
├── _internal/               # Private implementation (do not import directly)
│   ├── config.py            # ConfigManager (TOML-backed)
│   ├── api_client.py        # MixpanelAPIClient (Session-bound; per-request OAuth bearer)
│   ├── me.py                # MeService + per-account MeCache (~/.mp/accounts/{name}/me.json)
│   ├── pagination.py        # Cursor-based App API pagination
│   ├── pacer.py             # Shared query ledger: client-side pacing for the Query API budget (httpx event hooks)
│   ├── auth/                # Auth subsystem
│   │   ├── account.py       # Account discriminated union + TokenResolver protocol
│   │   ├── session.py       # Session, Project, WorkspaceRef, ActiveSession
│   │   ├── resolver.py      # resolve_session(...) — env > param > target > bridge > config
│   │   ├── token_resolver.py # OnDiskTokenResolver (refresh + per-account paths)
│   │   ├── token.py         # OAuthTokens, OAuthClientInfo
│   │   ├── flow.py          # OAuthFlow (PKCE + callback)
│   │   ├── bridge.py        # BridgeFile v2 + load_bridge / export_bridge / remove_bridge
│   │   ├── storage.py       # account_dir + ensure_account_dir + atomic writes
│   │   ├── pkce.py          # PKCE challenge generation (RFC 7636)
│   │   ├── callback_server.py # Local HTTP callback server
│   │   └── client_registration.py # Dynamic Client Registration (RFC 7591)
│   ├── query/               # Query engine builders and validators
│   ├── replays/             # Session-replay analyzer + aggregators (vendored rrweb); public label helpers live in replay_labels.py
│   └── services/            # Discovery, LiveQuery, Replays services
└── cli/
    ├── main.py              # Typer entry point + global flags (-a / -p / -w / -t)
    ├── commands/            # account / project / workspace / target / session
    │                        # + query, inspect, dashboards, reports, cohorts, flags,
    │                        # experiments, alerts, annotations, webhooks, lexicon,
    │                        # drop-filters, custom-properties, custom-events,
    │                        # lookup-tables, schemas, business-context, replays
    ├── formatters.py        # JSON, JSONL, Table, CSV, Plain output
    └── utils.py             # Error handling, console helpers
```

## Code Quality Standards (STRICT)

This project enforces strict standards. CI will reject code that doesn't meet them.

### Type Safety (STRICT)

All code must be fully typed and pass `mypy --strict`. This is non-negotiable:
- No `Any` types without explicit justification
- Use `Literal` types for constrained string values
- All function signatures must have complete type annotations
- All return types must be explicitly declared

### Formatting & Linting (STRICT)

Code must pass `ruff format` and `ruff check`. Run `just check` before committing:
- Zero tolerance for lint errors
- Consistent formatting enforced by pre-commit hooks
- CI will fail on any violation

### Documentation (STRICT)

**Every class, method, and function has a docstring — no exceptions.** This covers public API, private/internal helpers (prefixed with `_`), module-level functions, nested functions, test fixtures, and test methods. Presence is enforced by [interrogate](https://interrogate.readthedocs.io/) in CI, `just check`, and the pre-commit hook: every definition in `src/` and `conformance/` (100%; `[tool.interrogate]` in `pyproject.toml` and the `justfile`), and 95% of `tests/`. Reviewers flag a new test or fixture that has no docstring, because the `tests/` gate is an aggregate.

Which sections a docstring needs depends on what the function does (Google style):
- **Summary**: Always. One line saying what it does.
- **Args**: When it takes parameters (other than `self` / `cls`). Describe each one; the type lives in the annotation, so don't repeat it.
- **Returns**: When it returns a non-`None` value. No `Returns: None` section for functions annotated `-> None`.
- **Raises**: Exceptions the function raises deliberately, including ones it lets propagate from a call as part of its contract. Not every exception that could conceivably occur.
- **Example**: Where behavior isn't obvious from the signature and summary. Public API methods usually have one; simple helpers don't need one.
- **Tests and fixtures**: A one-line summary is enough when it states what the test proves or what the fixture provides. Match the convention already used in the test file.
- **Vendored code** (e.g., `_internal/replays/rrweb_analyzer.py`): Follow the module's existing conventions.

**Example format**: Use markdown fenced code blocks with language hints, not doctest-style `>>>` operators:

```python
# CORRECT - markdown code fence with language hint
"""
Example:
    ```python
    result = my_function("input")
    # ["output"]
    ```
"""

# WRONG - doctest style (DO NOT USE)
"""
Example:
    >>> my_function("input")
    ["output"]
"""
```

A missing docstring will not pass code review. A missing section the rules above don't call for is not a defect.

## Test-Driven Development (STRICT)

This project follows **strict TDD**. Tests are not optional or an afterthought.

### The TDD Workflow

1. **Write tests FIRST** — Before any implementation code
2. **Tests define behavior** — The test is the specification
3. **Implement until tests pass** — Only write code to make tests green
4. **Refactor with confidence** — Tests protect against regressions

### TDD Rules (Non-Negotiable)

- **Never write implementation code without a failing test first**
- **Study existing test patterns** — Before writing any new test, read existing tests for the same module to understand established conventions, fixtures, and mocking strategies
- **Tests must pass in CI** — Never assume local success means CI success; local environments often have configuration that CI lacks
- **Coverage minimum: 90%** — CI fails if coverage drops below this threshold

### When Adding Tests

- Find and read the corresponding test file (e.g., `test_workspace.py` for `workspace.py`)
- Copy fixture patterns and mocking approaches exactly
- Use the same naming conventions and test organization

### Test Types

- **Unit tests**: Isolated, mocked dependencies
- **Integration tests**: Real component interaction
- **Property-based tests**: Invariants verified across random inputs (use Hypothesis)

### Property-Based Testing

This project uses [Hypothesis](https://hypothesis.works) for property-based testing. PBT tests verify invariants across randomly generated inputs, catching edge cases that example-based tests miss. Name PBT test files with `_pbt` suffix (e.g., `test_types_pbt.py`). Hypothesis profiles control example counts:
- `default`: 100 examples (local development)
- `dev`: 10 examples (fast iteration)
- `ci`: 200 examples, deterministic (CI/CD)

### Mutation Testing

This project uses [mutmut](https://mutmut.readthedocs.io/) for mutation testing. Mutation testing evaluates test quality by introducing small code changes (mutations) and verifying tests detect them:
- **Killed mutant**: Test fails when mutation introduced (good - test catches bugs)
- **Survived mutant**: Test passes despite mutation (test gap - needs improvement)
- **Mutation score**: Percentage of mutants killed (target: 80%+)

Run mutation testing:
```bash
just mutate              # Run on entire codebase (slow)
just mutate-results      # View results summary
just mutate-show 1       # Inspect specific mutant
just mutate-apply 1      # Apply mutation to see the change
just mutate-apply 0      # Reset to original code
just mutate-check        # Check score meets 80% threshold
```

## Key Design Decisions

- **Streaming data access**: API returns iterators for memory-efficient processing of large datasets
- **Account → Project → Workspace hierarchy** (042 redesign): every CLI verb and Python namespace maps to one of those three axes; `Workspace.use(account=, project=, workspace=)` is the single in-session switching method.
- **Three first-class account types**: `service_account` (Basic Auth), `oauth_browser` (PKCE, tokens auto-refreshed), `oauth_token` (static bearer for CI/agents). All managed through one unified surface.
- **Frictionless login** (043): `mp login` (CLI) and `accounts.login_unified()` (Python) collapse the old two-step `mp account add` + `mp account login` flow into one call. Auth-type detection is env-driven: `MP_USERNAME`+`MP_SECRET` → `service_account`; `MP_OAUTH_TOKEN` → `oauth_token`; otherwise `oauth_browser`. Region behavior is auth-type-specific: SA and `oauth_token` paths probe `us → eu → in` when `--region` is omitted; `oauth_browser` defaults to `us` (PKCE commits to a region before the post-login `/me` probe runs, so EU / India users must pass `--region eu|in` explicitly). Project and account name derive from the post-login `/me` response; workspace stays lazy and resolves on first workspace-scoped call.
- **Single resolver**: `resolve_session(...)` consults env → param → target → bridge → config in priority order; no silent cross-axis fallback.
- **Connection-pool preservation**: `ws.use(account=...)` rebuilds the auth header but reuses the underlying `httpx.Client` (same Python instance — verified by `id()` equality in `tests/integration/test_cross_project_iteration.py`).
- **Dependency injection**: Services accept dependencies as constructor arguments for testing.
- **Shared query ledger**: counted Query API requests (not Export, not App API) are paced against a file-locked JSON ledger per (host, project) under `{storage}/pacer/`, so every `mp` process and Python session on the machine shares one exact budget. Waits up to `MP_PACER_MAX_WAIT` (default 30 s; per request in Python, a total budget per `mp` command) are absorbed and the Authorization header is re-resolved after a wait; longer waits raise `RateLimitError` at once with the exact next-slot time and nothing sent; raised limits are learned from the `RateLimit-Policy` header of one free 429 probe or configured (a configured limit is a ceiling); unexplained 429s back off exponentially from window/limit up to one hour; 429s without a `RateLimit` header get the normal retry; and `MP_PACER=off` is byte-identical to the unpaced client.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `MP_USERNAME` | Service account username (also triggers `mp login` SA detection when paired with `MP_SECRET`) |
| `MP_SECRET` | Service account secret |
| `MP_OAUTH_TOKEN` | Raw OAuth 2.0 bearer token (alternative to service account; requires `MP_PROJECT_ID` + `MP_REGION`; triggers `mp login` `oauth_token` detection when set; ignored only when the full service-account env-var set — `MP_USERNAME` + `MP_SECRET` + `MP_PROJECT_ID` + `MP_REGION` — is also present) |
| `MP_PROJECT_ID` | Project ID |
| `MP_REGION` | Data residency (us, eu, in); when unset, `mp login` probes us → eu → in for SA / oauth_token paths and defaults to us for the browser PKCE path |
| `MP_WORKSPACE_ID` | Workspace ID for App API operations |
| `MP_AUTH_FILE` | Override path to the v2 Cowork bridge file |
| `MP_CONFIG_PATH` | Override config file location |
| `MP_API_BASE_URL` | Route every API family at one alternate host (read per request; trailing slash tolerated). Bypasses the per-region `ENDPOINTS` table: `query` → `{base}/api/query`, `export` → `{base}/api/2.0`, `engage` → `{base}/api/query/engage`, `app` → `{base}/api/app`. Plain `http://` bases are accepted (local / headless deployments only). `mp login`'s region probe collapses to a single probe at the base (`MP_REGION` when valid, else `us`). `MP_REGION` stays required for non-URL uses. |
| `MP_APP_BASE_URL` | Optional: re-home only the App API family at `{app_base}/api/app` (works alone or on top of `MP_API_BASE_URL`). Alone it does not collapse the `mp login` region probe — the persisted region still routes the live Query/Export/Engage families |
| `MP_PACER` | `on` (default; also `true`/`1`/`yes`) or `off` (also `false`/`0`/`no`), case-insensitive; TOML booleans accepted in config; an invalid value leaves pacing on. `off` turns off the shared query ledger: no pacer file reads or writes, behavior identical to the unpaced client. Config: `[settings] pacer = "on"\|"off"` |
| `MP_PACER_MAX_WAIT` | Longest wait in seconds (or `inf`) the pacer absorbs before raising `RateLimitError`; default `30`. Per request in Python; inside an `mp` command, a budget for the total of all pacer waits in the command. `inf` suits unattended jobs. Config: `[settings] pacer_max_wait = <number>` |
| `MP_PACER_QUERY_LIMIT` | Known Query API limit (queries per hour) for every project in the process; wins over `[settings.pacer_query_limits] "<project_id>" = <int>` in config. A configured limit is a ceiling: the lower of it and a fresh (7-day) server-learned limit applies, so a value set too low is never raised, even after 429s. The config value is ignored when `config.toml` is readable by group or others (mode must be `0600`) |

Recommended starter command: `mp login` (one-shot orchestrator covering region probe, `/me`-driven project pick, and account-name derivation; backed by `mp.accounts.login_unified()` in Python).

Config file: `~/.mp/config.toml`
OAuth browser tokens: `~/.mp/accounts/{account_name}/tokens.json` (per-account, atomic 0o600 writes)
OAuth client metadata: `~/.mp/oauth/client_{region}.json` (DCR — one client per region)
Cowork bridge: `~/.claude/mixpanel/auth.json` (default) or `$MP_AUTH_FILE`

## Development

**First-time setup after cloning**: `uv sync --all-extras` then `just install-hooks`
to install the git pre-commit hook. Without the hook, `ruff check` / `ruff format`
violations slip through to CI.

This project uses [just](https://github.com/casey/just) as a command runner.

**`just check` is a strict superset of CI** — if `just check` passes locally,
CI will pass. The only documented difference is that CI sets
`HYPOTHESIS_PROFILE=ci` (200 deterministic examples vs the local default 100),
which doesn't change pass/fail outcomes.

| Command | Description |
|---------|-------------|
| `just` | List all available commands |
| `just install-hooks` | One-time: install git pre-commit hook (block ruff/format failures) |
| `just check` | Run all checks (lint + fmt-check + typecheck + test-cov + build) |
| `just test` | Run tests (supports args: `just test -k foo`) |
| `just test-dev` | Run tests with dev Hypothesis profile (fast, 10 examples) |
| `just test-ci` | Run tests with CI Hypothesis profile (thorough, 200 examples) |
| `just test-pbt` | Run property-based tests only |
| `just test-pbt-dev` | Run PBT tests with dev profile |
| `just test-cov` | Run tests with coverage (fails if below 90%) |
| `just mutate` | Run mutation testing on entire codebase |
| `just mutate-results` | Show mutation testing results |
| `just mutate-show ID` | Show details for specific mutant |
| `just mutate-check` | Check mutation score meets 80% threshold |
| `just hypo-codemod` | Refactor deprecated Hypothesis code |
| `just hypo-write` | Generate property-based tests for a module |
| `just lint` | Lint code with ruff |
| `just fmt` | Format code with ruff |
| `just typecheck` | Type check with mypy |
| `just mp` | Run the CLI (supports args: `just mp --help`) |

```bash
# Run all checks before committing
just check

# Run specific tests
just test -k test_name

# Fast iteration on property-based tests
just test-pbt-dev
```

### CLI Debugging (IMPORTANT)

**Never suppress stderr when running CLI commands.** The `mp` CLI provides rich error messages, stack traces, and diagnostic information that are essential for debugging.

```bash
# WRONG - hides errors
uv run mp query segmentation -e login 2>/dev/null

# CORRECT - preserves error output
uv run mp query segmentation -e login
```

Suppressing stderr causes silent failures and makes it impossible to diagnose issues like rate limits, authentication errors, or malformed queries.

## Technology Stack

- Python 3.10+ with full type hints (mypy --strict compliant)
- Typer (CLI) + Rich (output formatting)
- jq (JSON filtering via `--jq` option for CLI commands)
- httpx (HTTP client), Pydantic (validation)
- Hypothesis (property-based testing), mutmut (mutation testing)
- uv (package manager), just (command runner)

## mixpanel-headless Plugin

This project includes a Claude Code plugin in `mixpanel-plugin/`. The plugin's skills teach Mixpanel analysis judgment on top of the `mixpanel_headless` library; for API facts (signatures, types, allowed values) they point at the library's built-in reference (`mp help` / `mp.help()`) instead of copying it. The skills need `mixpanel_headless` 0.3.0 or later, and they run it from a plugin-owned venv: setup creates `${CLAUDE_PLUGIN_DATA}/venv` (`~/.claude/plugins/data/mixpanel-headless-<source>/venv`; `uv venv` when uv exists, else `python3 -m venv`) and installs there only, never into the system or user Python. The skills call `${CLAUDE_PLUGIN_DATA}/venv/bin/python` and `.../bin/mp` by full path, and the venv survives plugin updates. `setup.sh` takes the venv path as its required first argument (`bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh ${CLAUDE_PLUGIN_DATA}/venv`); it checks `mp help` and `<venv>/bin/mp`, then prints the venv path. User-run `!` commands use the full CLI path (`${CLAUDE_PLUGIN_DATA}/venv/bin/mp login`), because `mp` is often not on `PATH`.

### Plugin Components

| Type | Name | Invocation |
|------|------|------------|
| **Skill** | `mixpanelyst` | Auto-triggered on analytics questions |
| **Skill** | `session-replay` | Auto-triggered on session replay questions (web and mobile recordings) |
| **Skill** | `dashboard-expert` | Auto-triggered on dashboard analysis, creation, modification |
| **Skill** | `auth` | `/mixpanel-headless:auth` (also auto-triggered on credential questions) — manage credentials, accounts, OAuth |
| **Skill** | `setup` | `/mixpanel-headless:setup` — create or upgrade the plugin venv (0.3.0 floor), verify it and credentials (user-invoked only) |
| **Script** | `auth_manager.py` | `${CLAUDE_PLUGIN_DATA}/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session` — session status JSON (also `account`, `project`, `workspace`, `target`) |

### Usage

```
# Setup
/mixpanel-headless:setup

# API lookup (no credentials, no network); the skills run the venv's mp by full path
mp help Workspace.query               # method signature + docstring + referenced types
mp help Workspace.query_funnel.math   # one parameter and its allowed values
mp help search cohort                 # fuzzy search across names, docstrings, enum members
mp help Filter                        # type fields + construction patterns + related methods
mp help Workspace --domain "feature flags"   # every method in one domain
python3 -m mixpanel_headless help types      # fallback when mp is not on PATH
```

In Python: `mp.help("Workspace.query")` prints the same text; `mp.reference.search("cohort")` returns structured results.

## Active Technologies
- Python 3.10+ (mypy --strict) + httpx (HTTP client), Pydantic v2 (validation), Typer (CLI), Rich (output)
- JSON files at `~/.mp/oauth/` (token + client info persistence)
- Mixpanel App API (remote CRUD for entities and data governance)
- Python 3.10+ with full type hints (mypy --strict) + httpx (HTTP client), Pydantic v2 (validation), pandas (DataFrames) (029-insights-query-api)
- N/A — live query only, no local persistence (029-insights-query-api)
- Python 3.10+ (mypy --strict) + httpx (HTTP), Pydantic v2 (validation), pandas (DataFrames) (031-shared-infra-extraction)
- Python 3.10+ (mypy --strict) + httpx (HTTP client), Pydantic v2 (validation), pandas (DataFrames) (033-retention-query)
- Python 3.10+ (mypy --strict) + Pydantic v2 (for existing `CreateCohortParams`), pandas (existing), Hypothesis (PBT) (035-cohort-definition-builder)
- N/A — pure types, no persistence (035-cohort-definition-builder)
- Python 3.10+ (mypy --strict) + Pydantic v2 (validation), httpx (HTTP), pandas (DataFrames), Hypothesis (PBT) (036-cohort-behaviors)
- Python 3.10+ (mypy --strict compliant) + Pydantic v2 (validation), httpx (HTTP client), Hypothesis (PBT), mutmut (mutation testing) (037-custom-properties-queries)
- N/A — pure query-building types, no persistence (037-custom-properties-queries)
- Python 3.10+ (mypy --strict compliant) + Pydantic v2 (validation/models), httpx (HTTP client), Typer (CLI), Rich (output), tomli/tomli_w (TOML read/write) (038-auth-project-workspace-redesign)
- TOML config file (`~/.mp/config.toml`), JSON cache files (`~/.mp/oauth/me_{region}.json`), JSON OAuth token files (`~/.mp/oauth/tokens_{region}.json`) (038-auth-project-workspace-redesign)
- Python 3.10+ (mypy --strict) + httpx (HTTP), Pydantic v2 (validation), pandas (DataFrames), Hypothesis (PBT) (039-query-user-engine)
- Python 3.10+ + httpx, Pydantic v2, Typer, Rich, pandas, Hypothesis (040-query-engine-completeness)
- N/A — query parameter types only, no persistence (040-query-engine-completeness)
- Python 3.10+ (mypy --strict) + httpx, Pydantic v2, Typer, Rich, Hypothesis, mutmut (043-frictionless-auth)
- TOML config (`~/.mp/config.toml`) + per-account state at `~/.mp/accounts/{name}/{tokens,client,me}.json` — schema unchanged from 042 (043-frictionless-auth)
- Python 3.10+ (mypy --strict) + httpx, Pydantic v2, pandas, Typer, Rich, Hypothesis, mutmut; vendored rrweb analyzer (pure stdlib) for session replay (044-session-replay)
- N/A — signed URLs are time-bounded bearer credentials handled in-process; no new on-disk persistence (044-session-replay)
- Python 3.10+ (mypy --strict) + httpx, Pydantic v2, Typer, Rich, pandas, Hypothesis, mutmut; stdlib-only URL parse/build module (045-report-links)
- N/A — unsaved-report slug records live on the Mixpanel server per project and region; no new on-disk persistence (045-report-links)

<!-- SPECKIT START -->
Current plan: [specs/045-report-links/plan.md](specs/045-report-links/plan.md)

For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan.
<!-- SPECKIT END -->

