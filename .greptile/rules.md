# Review guidance for mixpanel_headless

## What matters most

1. Correct results from Mixpanel queries. A wrong number that looks right is the
   worst failure mode for an analytics library.
2. Correct account, project, and workspace resolution. Every call must go to the
   account, project, and workspace that the session resolved. There is no
   silent fallback across these axes.
3. Credentials never leak into logs, errors, reprs, or test output.
4. Behavior changes ship with tests written first.

## Session resolution

`resolve_session(...)` in `_internal/auth/resolver.py` builds the session for
API calls. It resolves the account, project, and workspace axes independently,
each in one order: environment, then explicit parameter, then saved target,
then the bridge file, then config. The config step is `[active].account` for
the account, the resolved account's `default_project` for the project (there is
no `[active].project`), and `[active].workspace` for the workspace.

The login and account-add flows (`mp login`, `mp account add`,
`accounts.login_unified()`) read `MP_USERNAME`, `MP_SECRET`, `MP_OAUTH_TOKEN`,
and `MP_PROJECT_ID` directly to create a new account. That is expected. Flag
other code that picks credentials, project, or region for an API call outside
`resolve_session`, uses a different order, or falls back from one axis to
another.

## Base URL routing

`MP_API_BASE_URL` routes every API family (query, export, engage, app) to one
host. `MP_APP_BASE_URL` routes only the App API family. Region still controls
the live query, export, and engage families when only `MP_APP_BASE_URL` is set.
Both variables are read on every request, never at import time, and every
endpoint lookup in the API client goes through `_endpoints_for`. Flag code that
reads the region endpoint table directly, caches an override at import time, or
labels or routes a request by region when an override applies.

## Connection reuse

`Workspace.use(account=...)` rebuilds the auth header but must reuse the same
`httpx.Client` instance, and `use(project=...)` and `use(workspace=...)` must
also keep it. `tests/integration/test_cross_project_iteration.py` checks this by
object identity. Flag changes that create a new client on account, project, or
workspace switch.

## Streaming

Event and profile streaming (`stream_events`, `stream_profiles`) return
iterators. Flag code that materializes a full stream into a list inside the
library.

## What not to comment on

- Formatting, import order, and lint issues (ruff enforces them).
- Type annotation completeness (mypy --strict enforces it).
- Docstring presence in src/ and conformance/ (interrogate requires 100% in CI).
- Recorded conformance artifacts. The ignore patterns exclude them, and a
  script regenerates them.
