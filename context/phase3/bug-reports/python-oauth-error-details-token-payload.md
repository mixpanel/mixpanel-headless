# Bug report: OAuth error `details.response_data` carries the full (plaintext) token payload

- **Filed**: 2026-08-16 (B9-ARB-B, pair-B blind review `b9-reviewB-threat.md` F3;
  extends the B8 pair-B lens-1 observation O1 / `B8-notes.md` Phase-4 ledger line 1)
- **File**: `src/mixpanel_headless/_internal/auth/flow.py`
- **Affected lines** (support branch `ts-port/phase2-contract-support`):
  `:596-605` — `_post_token_request`'s missing-required-fields branch raises
  `OAuthError(..., details={"response_data": str(data)})` where `data` is the FULL
  parsed 200 token-endpoint response body.
- **Status**: OPEN — hardening-class R10.7 queue item (Python-first: fix in Python,
  re-record, re-pin; TS follows). TS reproduces the behavior verbatim
  (`packages/core/src/auth/oauth-http.ts:245` after the B9-R2 §3.1 hoist — shared
  by the node refresh path AND the browser `completeLogin` exchange path).

## The defect

A 200 token response that parses as JSON but fails `OAuthTokens.from_token_response`
(e.g. `{"access_token": "SECRET", "refresh_token": "SECRET"}` missing `expires_in`,
or any field-shape mismatch) produces an `OAuthError` whose `details["response_data"]`
contains the stringified payload — live bearer/refresh material in plaintext. The
value never passes through `Secret`, so any consumer that serializes error details
(logging, `str(exc.details)`, telemetry pipelines; in the BROWSER build,
`JSON.stringify(err.details)` inside Sentry/Bugsnag/`window.onerror` wrappers)
exfiltrates the credential.

Repro (pair-B threat probe F, B9): canned IdP returning
`{"access_token": "SECRET_AT", "refresh_token": "SECRET_RT"}` through the browser
`completeLogin` → `code: OAUTH_TOKEN_ERROR`,
`details: {"response_data": "{'access_token': 'SECRET_AT', 'refresh_token': 'SECRET_RT'}"}`.

## Severity assessment

The branch fires only on a MALFORMED-but-200 IdP response, so live exposure requires
a misbehaving token endpoint — low probability, high impact (bearer material into
error-reporting pipelines). Raised from "re-examine in Phase 4" (B8 O1) to an
explicit R10.7 fix-queue item by the B9 browser exposure: the same code path now
runs in browsers, where error-detail exfiltration via telemetry is the default
posture, and the payload is the user's own live login.

## Suggested Python-first fix

Redact token-bearing keys before embedding: e.g.
`details={"response_data": str({k: ("<redacted>" if k in {"access_token", "refresh_token", "id_token"} else v) for k, v in data.items()})}`
(or drop `response_data` and keep only the field names / the validation error).
Then re-record the 7 `oauth_flow.` vectors (none currently assert `response_data`
content — check before assuming a re-pin is needed) and mirror the change in
`packages/core/src/auth/oauth-http.ts`.

## Interim mitigations (landed at B9-ARB-B, TS docs only — no behavior change, R10.7)

- `packages/browser/README.md` "Using the redirect flow safely": scrub
  `error.details` before forwarding to telemetry.
- `packages/core/src/auth/oauth-http.ts` throw-site comment naming both consumer
  paths and this report.
- Phase-4 outbound ledger row 1 re-scoped (b9-packets.md §10 erratum): cite
  `oauth-http.ts:245` (shared node refresh + browser exchange), not `flow.ts:898`.
