# Bug report: `_handle_response` 403 branch raises `TypeError` for truthy non-dict/non-str JSON bodies

- **Filed**: 2026-08-15 (B2-HK, B0 follow-up obligation 4; found by B0-2 under R10.7)
- **File**: `src/mixpanel_headless/_internal/api_client.py`
- **Affected lines** (support branch `ts-port/phase2-contract-support`, post-PR-206):
  `:565-570` (the 403 `SESSION_RECORDING_SENSITIVE_DATA` sniff inside
  `_handle_response`, `:503-662`)
- **Status**: OPEN — latent Python bug, reproduced verbatim in TS per R10.7
  (bug-compatibility; TS must never fix it unilaterally). Locked on the TS side by
  `packages/core/test/client/internals.test.ts` R10.7 cases + the B0-2 edge harness
  cases `403-truthy-scalar`, `403-list-exact`, `403-list-substring` (RUN record in
  `context/phase3/notes/B0-notes.md`).

## The defect

```python
# api_client.py:565-570
body_text = (
    json.dumps(response_body)
    if isinstance(response_body, dict)
    else (response_body or "")
)
if "SESSION_RECORDING_SENSITIVE_DATA" in body_text:
```

`response_body` comes from `response.json()` (`:545-548`), whose runtime range is any
JSON value — not just `str | dict | None` as the local annotation claims. For a 403
whose JSON body is a **truthy non-dict, non-str** value (`42`, `1.5`, `true`),
`(response_body or "")` evaluates to the scalar itself and the `in` membership test
raises `TypeError: argument of type 'int' is not a container or iterable` — the
caller gets an uncoded `TypeError` instead of any `MixpanelHeadlessError`.

Two adjacent quirks of the same expression:

1. **List bodies silently pass through element-membership semantics**: for a JSON
   array body, `flag in body_text` is Python LIST membership — the flag matches only
   as an EXACT element (`["SESSION_RECORDING_SENSITIVE_DATA"]` →
   `SessionReplayAccessError`), never as a substring of an element
   (`["xSESSION_RECORDING_SENSITIVE_DATAy"]` → plain `QueryError`), unlike the
   substring semantics dict (serialized) and string bodies get.
2. **Falsy scalars** (`0`, `false`, `null`) coerce to `""` and take the plain
   `QueryError` "Permission denied" path — no crash, but by accident of truthiness.

## Repro (verified live 2026-08-15, this branch)

```python
import httpx
from pydantic import SecretStr
from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session

session = Session(
    account=ServiceAccount(name="repro", region="us", username="u", secret=SecretStr("s")),
    project=Project(id="12345"),
)
client = MixpanelAPIClient(session=session)
response = httpx.Response(
    403,
    headers={"content-type": "application/json"},
    content=b"42",
    request=httpx.Request("GET", "https://mixpanel.com/api/x"),
)
client._handle_response(response)
# TypeError: argument of type 'int' is not a container or iterable
```

Observed matrix (all confirmed against this branch):

| 403 JSON body | Outcome |
|---|---|
| `42` / `1.5` / `true` | **`TypeError` (uncoded crash)** |
| `0` / `false` / `null` | `QueryError` (Permission denied path) |
| `["SESSION_RECORDING_SENSITIVE_DATA"]` | `SessionReplayAccessError` (exact-element match) |
| `["xSESSION_RECORDING_SENSITIVE_DATAy"]` | `QueryError` (substring NOT matched in lists) |
| `{"error": "SESSION_RECORDING_SENSITIVE_DATA"}` | `SessionReplayAccessError` |
| `"SESSION_RECORDING_SENSITIVE_DATA denied"` | `SessionReplayAccessError` |

## Suggested fix (Python-first, when scheduled)

Serialize every non-str body for the sniff — e.g.
`body_text = response_body if isinstance(response_body, str) else json.dumps(response_body)`
(with `None` → `""`) — giving uniform substring semantics across dict/list/scalar
bodies and eliminating the crash.

## Porting/process constraints (R10.7 + P3-7)

Fixing this is an **R10.7 event**: fix on the Python support branch first, then
regenerate + re-pin the corpus (P3-7 re-sync trigger 3) and update the TS twin
(`packages/core/src/client/internals.ts` Python-truthiness helper + TypeError
throw) in the same coordinated change, updating the TS regression tests that
currently lock the bug-compatible behavior. Until then the TS port MUST keep
reproducing the TypeError verbatim. No corpus vector currently exercises these
bodies (the B0-2 coverage is Layer-3 + edge harness, not vectors), so the fix
window is open until a recorded vector locks the buggy branch.
