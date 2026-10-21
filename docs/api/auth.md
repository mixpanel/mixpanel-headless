# Auth

The auth surface in `mixpanel_headless` is organized around three independent axes — Account, Project, Workspace — with three first-class account types, a single resolver, and fluent in-session switching via `Workspace.use()`.

!!! tip "Explore on DeepWiki"
    🤖 **[Configuration Reference →](https://deepwiki.com/mixpanel/mixpanel-headless/7.3-configuration-reference)**

    Ask questions about account types, session axes, OAuth, or in-session switching.

## Overview

```python
import mixpanel_headless as mp

# Construct a Workspace from active config
ws = mp.Workspace()

# Override per Workspace (env > param > target > [active] > default_project)
ws = mp.Workspace(account="team", project="3713224")
ws = mp.Workspace(target="ecom")
ws = mp.Workspace(session=mp.Session(account=..., project=..., workspace=...))

# In-session switching — fluent, O(1), no re-auth on project swap
ws.use(project="3018488").events()
ws.use(account="personal").events()    # rebuilds auth header; preserves underlying HTTP client
ws.use(target="ecom").events()         # applies all three axes atomically
ws.use(workspace=3448414).events()

# Functional namespaces (also re-exported as mp.accounts / mp.session / mp.targets)
summaries = mp.accounts.list()
mp.accounts.use("team")
active = mp.session.show()             # ActiveSession
mp.targets.add("ecom", account="team", project="3018488", workspace=3448414)
```

See [Configuration](../getting-started/configuration.md) for the full setup walkthrough.

## Account Types

`Account` is a Pydantic discriminated union over three first-class variants. The `type` field selects the variant; each variant carries the credentials it needs.

```python
from mixpanel_headless import (
    Account,                      # discriminated union type
    ServiceAccount,               # type == "service_account"
    OAuthBrowserAccount,          # type == "oauth_browser"
    OAuthTokenAccount,            # type == "oauth_token"
    AccountType,                  # Literal["service_account" | "oauth_browser" | "oauth_token"]
    Region,                       # Literal["us" | "eu" | "in"]
)

account: Account = ServiceAccount(
    name="team",
    region="us",
    default_project="3018488",
    username="team-mp...",
    secret="...",
)

if isinstance(account, ServiceAccount):
    print(f"SA {account.name} → project {account.default_project}")
```

### ServiceAccount

Long-lived HTTP Basic Auth credentials. Best for CI / scripts / unattended automation.

::: mixpanel_headless.ServiceAccount
    options:
      show_root_heading: true
      show_root_toc_entry: true

### OAuthBrowserAccount

PKCE browser flow; access/refresh tokens persisted at `~/.mp/accounts/{name}/tokens.json` and auto-refreshed on expiry.

::: mixpanel_headless.OAuthBrowserAccount
    options:
      show_root_heading: true
      show_root_toc_entry: true

### OAuthTokenAccount

Static bearer token (CI / agents) — supplied inline or via an env var (`token_env`).

::: mixpanel_headless.OAuthTokenAccount
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Session Axes

A `Session` is the immutable resolved state for a single Workspace at construction time — account, project, optional workspace, and the auth headers they generate.

::: mixpanel_headless.Session
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.Project
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.WorkspaceRef
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.auth_types.ActiveSession
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Workspace.use() — In-Session Switching

`Workspace.use()` is the only in-session switching method. It returns `self` for fluent chaining and preserves the underlying `httpx.Client` and per-account `/me` cache across switches, so cross-project / cross-account iteration is O(1) per turn.

```python
import mixpanel_headless as mp

ws = mp.Workspace()                                # active session

# In-session switching (returns self for chaining)
ws.use(account="team")                              # implicitly clears workspace
ws.use(project="3018488")
ws.use(workspace=3448414)
ws.use(target="ecom")                               # apply all three at once

# Persist the new state
ws.use(project="3018488", persist=True)             # writes account.default_project; [active] only stores account + workspace

# Fluent chain
result = ws.use(project="3018488").segmentation(
    "Login", from_date="2026-04-01", to_date="2026-04-21"
)
```

Switching the active account clears the workspace (workspaces are project-scoped). The project re-resolves on account swap via `env > explicit > new account's default_project`. There is **no silent cross-axis fallback**: if an axis can't be resolved on the new account, `use()` raises `ConfigError`.

::: mixpanel_headless.Workspace.use
    options:
      show_root_heading: false
      show_root_toc_entry: false

### Snapshot mode (parallel iteration)

For parallel cross-project iteration, snapshot the resolved `Session` and construct a fresh `Workspace` per task:

```python
from concurrent.futures import ThreadPoolExecutor
import mixpanel_headless as mp

ws = mp.Workspace()
sessions = [
    ws.session.replace(project=mp.Project(id=p.id))
    for p in ws.projects()
]

def event_count(s: mp.Session) -> int:
    return len(mp.Workspace(session=s).events())

with ThreadPoolExecutor(max_workers=4) as pool:
    counts = list(pool.map(event_count, sessions))
```

## Functional Namespaces

The auth surface exposes three module-level namespaces re-exported from `mixpanel_headless`. These are the canonical Python API for managing accounts, the active session, and saved targets.

### `mp.accounts`

Account lifecycle: register, switch, probe, OAuth flows. The `login_unified` orchestrator below collapses the explicit `add` + `login` pair into a single conversational call (the Python entry point behind `mp login`).

::: mixpanel_headless.accounts
    options:
      show_root_heading: true
      show_root_toc_entry: true
      members:
        - list
        - add
        - update
        - remove
        - use
        - show
        - test
        - login
        - login_unified
        - logout
        - token

#### Frictionless login (`login_unified`)

Composes auth-type detection, region resolution, `/me` lookup, project picker, and account-name derivation into one call. Backs the CLI's `mp login` command.

```python
import mixpanel_headless as mp

# Browser PKCE — derives region, name, project from /me.
summary = mp.accounts.login_unified()
print(summary.user_email, summary.project_id, summary.project_name)

# Service account from env, region auto-probed (us → eu → in):
import os
os.environ["MP_USERNAME"] = "sa_xxx"
os.environ["MP_SECRET"] = "..."
summary = mp.accounts.login_unified()

# Re-login: refresh tokens for an existing account.
summary = mp.accounts.login_unified(name="acme-corp")

# Multi-project — supply a picker callback for non-CLI contexts.
def picker(me, sorted_projects):
    """Return the project_id you want to bind."""
    return sorted_projects[0][0]

summary = mp.accounts.login_unified(project_picker=picker)
```

Auth-type detection ladder (priority order):

1. Explicit `account_type=` (or the CLI's `--service-account` / `--token-env`).
2. `MP_USERNAME` + `MP_SECRET` set → `service_account`.
3. `MP_OAUTH_TOKEN` set → `oauth_token`.
4. Otherwise → `oauth_browser` (PKCE).

Region behavior is auth-type-specific. `service_account` and `oauth_token` paths probe `us → eu → in` against `/me` when `region=` is not passed, returning the first 200. `oauth_browser` commits to the supplied `region` (or defaults to `"us"`) before the PKCE redirect, then cross-checks the picked project's domain after the callback. EU and India browser users must pass `region="eu"` or `region="in"` explicitly.

Raises `RegionProbeError` / `RegionProbeNetworkError` if no region accepts the credential (SA / token paths only), `InvalidArgumentError` for mutually-incompatible flag combinations, `ProjectNotFoundError` for an explicit `project=` not visible to `/me`, and `AccountExistsError` when the derived name collides on the browser path. See [Exceptions](exceptions.md#oauth-exceptions) for the full set.

### `mp.session`

Read and write the persisted `[active]` block.

::: mixpanel_headless.session
    options:
      show_root_heading: true
      show_root_toc_entry: true
      members:
        - show
        - use

### `mp.targets`

Manage saved (account, project, optional workspace) cursor positions.

::: mixpanel_headless.targets
    options:
      show_root_heading: true
      show_root_toc_entry: true
      members:
        - list
        - add
        - remove
        - use
        - show

## Result Types

Read-only structured results returned from the namespaces above.

### AccountSummary

::: mixpanel_headless.AccountSummary
    options:
      show_root_heading: true
      show_root_toc_entry: true

### AccountTestResult

::: mixpanel_headless.AccountTestResult
    options:
      show_root_heading: true
      show_root_toc_entry: true

### OAuthLoginResult

::: mixpanel_headless.OAuthLoginResult
    options:
      show_root_heading: true
      show_root_toc_entry: true

### Target

::: mixpanel_headless.Target
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Credential Resolution Chain

When constructing a `Workspace`, each axis is resolved independently in this priority order:

1. **Environment variables** — the resolver reads `MP_USERNAME` + `MP_SECRET` + `MP_PROJECT_ID` + `MP_REGION` (service-account quad), `MP_OAUTH_TOKEN` + `MP_PROJECT_ID` + `MP_REGION` (OAuth-token triple), `MP_PROJECT_ID` (project axis), and `MP_WORKSPACE_ID` (workspace axis). `MP_ACCOUNT` is **not** consumed by the Python resolver — it only feeds the CLI's `--account` / `-a` flag via Typer's `envvar=` default.
2. **Constructor / CLI param** — `Workspace(account="...")`, `mp -a NAME ...`.
3. **Saved target** — `Workspace(target="ecom")`, `mp -t ecom ...`.
4. **Persisted active session** — the `[active]` block in `~/.mp/config.toml`.
5. **Account default** — `account.default_project` for the project axis.

See [Configuration → Credential Resolution Chain](../getting-started/configuration.md#credential-resolution-chain) for examples.

## OAuth Token Plumbing

Low-level types for OAuth token handling. Most users never touch these directly — `mp.accounts.login(name)` drives the full flow and `OnDiskTokenResolver` materializes refreshed tokens automatically.

### OAuthTokens

::: mixpanel_headless.auth_types.OAuthTokens
    options:
      show_root_heading: true
      show_root_toc_entry: true

### OAuthClientInfo

::: mixpanel_headless.auth_types.OAuthClientInfo
    options:
      show_root_heading: true
      show_root_toc_entry: true

### TokenResolver Protocol

::: mixpanel_headless.auth_types.TokenResolver
    options:
      show_root_heading: true
      show_root_toc_entry: true

### OnDiskTokenResolver

::: mixpanel_headless.auth_types.OnDiskTokenResolver
    options:
      show_root_heading: true
      show_root_toc_entry: true
