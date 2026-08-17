# Pair-B (blind) Lens 1 — AUTH/SECURITY review of fix (d) + (c) regression threat

Reviewer: pair-B, blind to bugfix-reviewA-* and its resolution per orchestrator
ruling (ARB-A code diffs reviewed as part of the branch; pair-A notes NOT read).
Scope: Python `ts-port/python-bugfix-batch` (bddc576..20c7d6b) vs
`ts-port/phase2-contract-support`; TS `main` (a382687..b7152da) vs 8fa150d.
Bar = fix-of-record docs + inbound-ledger row 2. Status: COMPLETE.

## Method

- Traced EVERY raise/throw site in `flow.py::_post_token_request` (:553-638)
  and `oauth-http.ts::postTokenRequest` that embeds response material.
- Message-channel audit: `OAuthTokens.from_token_response` /
  `fromTokenResponse` raise messages embed only key names /
  `expires_in` raw value — no token values reach the OAuthError MESSAGE in
  either language. `exc.args`, `repr`, `str`, `to_dict()` all probed.
- Probe harness (Python `/tmp/probe_d.py`, uv run; TS temp vitest file, run
  then deleted): 200 responses with 8 malformed shapes, secrets planted,
  leak-scanned across str/repr/args/details/to_dict (Python) and
  message/toString/details/JSON.stringify/toDict (TS).
- Fix (c) fuzz (`/tmp/probe_c.py`): 24 body shapes on the 403 sniff.

## Fix (d) — verdict on the RECORDED contract: correctly implemented, twins byte-parity

- Canonical repro from the fix-of-record (`{access_token, refresh_token}`
  missing `expires_in`): NO leak on any surface in either language;
  `<redacted>` present; field names + non-secret values (scope, token_type,
  unknown keys) preserved — no legitimate diagnostic field dropped.
- Error codes stable (`OAUTH_TOKEN_ERROR` / `OAUTH_REFRESH_ERROR`), R5.4
  honored. New tests (test_auth_flow.py `TestTokenPayloadRedaction`, TS
  oauth-flow-login/refresh twins) + re-recorded `test_auth_flow.jsonl`
  vector lock it. ARB-A F1 non-dict guard prevents the AttributeError crash
  and mirrors TS `isPlainRecord` — verified identical behavior by probe.
- Consumers: NO production code in either repo reads
  `details["response_data"]` / `details["response_body"]`; only tests pin
  them. Redaction drops nothing callers need. B9 FB-3 doc locks (browser
  README caveat + oauth-http JSDoc) were updated in 2b72ce1 as required by
  ground state.

## Fix (d) — residual credential channels (probe-CONFIRMED, both languages, identical)

| # | Channel | Probe result |
|---|---|---|
| F-B1 | **200 body that fails JSON parse** → `details["response_body"] = response.text` VERBATIM (flow.py:610-615; oauth-http.ts non-JSON branch). Truncated JSON `{"access_token": "SECRET_TRUNC", "refr` and `{"access_token":"SECRET_GARB"}garbage` both leak the live token into details + to_dict/toDict. Same misbehaving-IdP threat model as the fixed branch (proxy truncation/garbage is arguably MORE likely than a well-formed-but-wrong JSON payload). | LEAK (Py+TS) |
| F-B2 | **Shallow redaction**: only top-level `access_token`/`refresh_token`/`id_token` keys. Envelope shapes leak: `{"result": {"access_token": "SECRET_NEST"}}` and `{"tokens": ["SECRET_L1"]}` render secrets verbatim in `response_data`. (Alt key names `accessToken` also pass through — inherent to key-based redaction, per fix-of-record design; noted, not counted separately.) | LEAK (Py+TS) |
| F-B3 | **Non-dict 200 JSON body rendered as-is** (ARB-A F1 / isPlainRecord branch): a bare JSON string body `"SECRET_BARE"` → `response_data == "SECRET_BARE"`. This exact unredacted rendering is now LOCKED by tests in both languages (`assert exc.details["response_data"] == str(body)`, TS `toBe(...)`) — a later hardening pass will need an R10.2-conscious assertion flip. | LEAK (Py+TS) |
| — | Non-200 branches (:583-605) embed `response.text` — IdP ERROR bodies; token material only if the IdP echoes tokens on 4xx/5xx. Out of the fix-of-record threat model. | note only |

## Fix (d) — documentation overclaims (falsified by the probes above)

- `packages/browser/README.md` now says "bearer material no longer flows
  through it" and downgrades details-scrubbing to "good hygiene". FALSE for
  F-B1/F-B2/F-B3 — and this text REPLACED the B9 FB-3 mandatory-scrub
  warning, i.e. the interim mitigation was retired while residual channels
  remain. The scrub-before-telemetry advice should stay normative (or the
  channels closed).
- `flow.py` Security docstring + oauth-http.ts JSDoc: "keeps only field
  names and non-secret values" — false for nested payloads (F-B2) and the
  non-JSON branch is not mentioned at all.

## Fix (c) — CLEAN

- 24-shape fuzz (42, 1.5, True, False, 0, None, -0.0, "", [], {}, 1e308,
  bare flag string, flag-as-element, flag-as-substring-of-element, nested
  list/dict/deep-nested, invalid JSON, non-JSON text): ZERO crashes; every
  outcome a coded `MixpanelHeadlessError`; uniform SUBSTRING semantics
  across dict/list/scalar exactly per the fix-of-record suggested fix
  (list substring case now correctly `SessionReplayAccessError`).
- TS twin: `pyTruthy` + TypeError throw retired in the same change
  (R10.7 flip discipline honored); `jsonDumpsLike` extended to all scalar
  shapes incl. bool/bigint/JsonNumber/Infinity; new
  `TestSensitiveData403BodyShapes` suite covers list-substring, truthy and
  falsy scalars, string body, bare Infinity.
- No new leak: `body_text` is sniff-local; `response_body` attachment to
  QueryError/SessionReplayAccessError is pre-existing behavior and carries
  analytics error bodies, not credentials.

## Findings summary (for the arbiter)

1. MAJOR — F-B1 non-JSON-200 `response_body` verbatim embed (Py flow.py:614,
   TS oauth-http.ts non-JSON branch). Residual live-credential channel.
2. MAJOR — F-B2 shallow redaction misses nested/list-nested token values
   (Py flow.py:626-633, TS oauth-http.ts redaction map). Matches the
   fix-of-record's "e.g." suggestion literally but not its goal.
3. MINOR — F-B3 bare-string 200 body embedded verbatim AND test-locked as
   unredacted in both languages.
4. MINOR — README/docstring overclaim + retirement of the FB-3 mandatory
   scrub guidance while F-B1..F-B3 remain open.
5. NONE on fix (c) — fuzz clean, parity clean, no new leak.

No findings on: message/args/repr channels (clean), detail-field
completeness (nothing dropped), error-code stability, consumer breakage,
R10.7 flip discipline for (c)/(d) twins.
