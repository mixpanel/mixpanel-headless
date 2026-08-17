# B8 review — Pair B (BLIND), Lens 1: CREDENTIAL-AT-REST SAFETY

**Status**: COMPLETE — GO. 62/62 adversarial probe checks green; zero
blocking findings; 4 non-blocking parity observations (O1-O4).
**Reviewer**: pair-B lens-1 (credential-at-rest). Blindness honored: no `b8-reviewA-*`
file or pair-A probe file read.
**Scope**: all B8 commits `597ef7d` (MAPFIX), `44fc912` (N1), `53a134e` (N2),
`8017fc4` (N3), `92a5f8a` (ARB-A fix commit — code only, resolution doc NOT read),
verified against Python sources at `ts-port/phase2-contract-support`.

## Hunt list (from the lens charter)

1. write/chmod race — secret bytes ever readable at wrong mode
2. secret-bearing tmp files left behind on failure paths
3. SecretStr mask leaking into persisted bytes (CRED-F3 lock presence + sufficiency)
4. callback server logging/echoing sensitive query params
5. DCR client secret handling
6. harness/notes artifacts carrying real-looking tokens

## Code-read pass (complete)

- `io-utils.ts` vs `io_utils.py:83-163`: tmp `O_EXCL` at literal 0o600, `fchmod`
  BEFORE first write, rename-or-unlink-own-tmp. No wrong-mode window on any write
  path. `mode & 0o077` guard precedes FS touch. MATCH.
- `storage.ts`: saveTokens/saveClientInfo → `#writeFile` → `atomicWriteBytes`
  (default 0600); reveal only in `saveTokens`; `OAuthClientInfo` carries NO secret
  field (`token.py:156-186`) so plain `JSON.stringify` at `:309` is safe. Repair
  path lstat-guarded (sanctioned R9.2 substitution, header-documented). MATCH.
- `token-payload.ts`/`token-store.ts`/`token-resolver.ts`: every tokens.json write
  routes through `tokenPayloadBytes` (explicit reveal) + `atomicWriteBytes`;
  rotation-keep re-wraps the OLD Secret (never a mask). MATCH
  (`token_resolver.py:174-243`).
- `bridge.ts` vs `bridge.py:278-369`: serializeBridge reveals at the designated
  site; export = parent mkdir 0700 + atomic 0600 (Python identical); the
  TS serializer builds the payload from scratch so no pydantic-mask residue can
  survive (Python overwrites the masked dump — TS never produces one). MATCH.
- `config.ts`/`config-writes.ts` vs `config.py:92-125,192-207`: `accountToBlock`
  is the single account writer (both `:598` add and `:677` update paths);
  `credentialText` unwraps params transaction-locally, re-wrapped by
  `parseAccount`, revealed only at persistence. `writeRaw` → atomic 0600, parent
  0700. MATCH.
- `me-cache.ts` vs `me.py:546-596`: dir chmod-failure RAISES ConfigError (PII
  posture); me.json atomic 0o600; member lists stripped. MATCH.
- `callback-server.ts` vs `callback_server.py`: no request logging anywhere (node
  http default is silent; Python suppresses `log_message`); the auth `code` is
  never echoed into HTML or details; error HTML interpolation escaped
  (html.escape twin incl. quotes). `expected_state`/`received_state` in
  server-side details = Python parity (`callback_server.py:251-267`), not secret.
- `client-registration.ts` vs `client_registration.py:54-170`: public client
  (`token_endpoint_auth_method: "none"`); only
  client_id/region/redirect_uri/scope/created_at persisted — a hypothetical
  `registration_access_token` in the DCR response is NOT persisted and appears in
  no detail bag (response_body only on FAILURE statuses). MATCH.
- `flow.ts` `#postTokenRequest`: `response_data: pythonStr(data)` on the
  200-parse-failure branch puts the full token-endpoint payload (incl. any
  access_token the IdP returned alongside a missing field) into error details —
  PYTHON-VERBATIM (`flow.py:596-605` `details={"response_data": str(data)}`);
  R10.7 parity, recorded as an observation, not a finding.
- Test isolation: `helpers.ts` real-home guard + `scrubMpEnv`; bridge/token tests
  override `HOME` to a tmp dir; `token-resolver.test.ts:522` homedir assertion is
  path-computation only (fake HOME). CRED-F3 round-trip lock present
  (`secret-roundtrip.test.ts`: reveal equality + on-disk plaintext + no-mask,
  add AND update paths).
- Repo-wide grep for real-looking token shapes (JWT/ghp_/AKIA/sk-): zero hits in
  `packages/node` + `throwaway/`.

## Findings

**ZERO blocking or major findings.** Every hunt-list item was probed
adversarially against the real surfaces and came back clean:

1. **write/chmod race** — none exists. `atomicWriteBytes` creates the tmp
   sibling `O_WRONLY|O_CREAT|O_EXCL` at LITERAL 0o600 and `fchmod`s to the
   requested (already `& 0o077`-validated) mode BEFORE the first write byte
   (`io-utils.ts:258-266` = `io_utils.py:142-146`). Probe P1 observed the tmp
   mode inside the write window across multiple short-write iterations: never
   any group/world bit, for both 0o600 and 0o400 requests.
2. **secret tmp files on failure paths** — none left behind. P2: rename
   failure, mid-write failure, and the `mode & 0o077` reject each leave the
   directory with only the intact original (mode reject provably touches NO
   filesystem state). P3: even a simulated hard crash (cleanup suppressed)
   leaks a tmp that is itself 0600 — the Python guarantee ("on-disk view never
   wider than 0o600 for the tmp window", `io_utils.py:101-106`) holds.
3. **CRED-F3 mask leakage** — lock PRESENT and SUFFICIENT. Exactly four
   on-disk reveal sites exist (`token-payload.ts`, `storage.ts saveTokens`,
   `bridge.ts serializeBridge`, `config.ts accountToBlock`), matching the
   B8-N2-notes §5 allowlist verbatim; grep over `packages/node/src` +
   `packages/core/src/{accounts,auth}` surfaced no other secret-adjacent
   serializer. The mandated Layer-3 round-trip lock exists
   (`secret-roundtrip.test.ts` — reveal equality + on-disk plaintext +
   explicit no-mask, for BOTH add and update). Probe P4 drove every writer
   (legacy v2 tokens + DCR client info, per-account tokens.json, TOML config
   SA+OT, bridge exports for all three account types, me.json) under a tmp
   HOME: zero `**********` anywhere, all files 0600, all `.mp` subdirs 0700,
   sentinels present ONLY in the designated reveal files, and the failed
   oauth_browser export left no partial file.
4. **callback server** — never logs and never echoes the code. Node `http`
   default is silent (Python parity: `log_message` suppressed); zero
   `console.*` in `packages/node/src`. Probe P6: success HTML omits the code;
   mismatch HTML omits both the code and the expected state (expected state
   lives only in the server-side error details, Python parity
   `callback_server.py:251-267`); `<script>` in `error_description` arrives
   escaped (`&lt;script&gt;`), the html.escape twin covering all five chars.
5. **DCR client secrets** — none exist to leak: the client is public
   (`token_endpoint_auth_method: "none"`), `OAuthClientInfo` carries no
   Secret-typed field (`token.py:156-186`), and only the five known fields
   are persisted — a hypothetical `registration_access_token` in the DCR
   response is dropped, not stored (`client-registration.ts:206-216`).
6. **harness artifacts** — clean. Repo-wide grep for real-looking token
   shapes (JWT `eyJ…`, `ghp_`, `AKIA…`, `sk-…`) over `packages/node` +
   `throwaway/`: zero hits; RUN records use descriptive sentinels and the
   N2 notes record the sentinel-sweep discipline (§3.6 row 7 executed, both
   probes' no-mask walks green).

## Observations (non-blocking, Python-parity — recorded for Phase-4 burn-in)

- **O1** `flow.ts:898` `response_data: pythonStr(data)`: the 200-response
  `fromTokenResponse`-failure branch serializes the WHOLE token-endpoint
  payload into `OAuthError.details` — if the IdP returns an `access_token`
  alongside a missing `expires_in`, that token lands in the error surface.
  VERBATIM Python (`flow.py:596-605`, `details={"response_data": str(data)}`);
  R10.7 forbids "improving" it. Suggest a Phase-4 burn-in ledger line.
- **O2** `token-resolver.ts:223` `validation_error: exc.message`: TS messages
  name FIELDS only ("OAuthTokens.access_token must be a secret string") — the
  Python twin stores `str(pydantic ValidationError)` which can embed the
  failing field's `input_value`. TS is equal-or-safer; no action.
- **O3** `MeCache.put` creates missing parent dirs (`mkdirSync recursive`,
  no mode) before the raise-guarded leaf chmod 0700 — a transient
  umask-default parent when MeCache runs before any token write. Python
  `mkdir(parents=True)` is identical (`me.py:563`); leaf dir is 0700 and
  me.json 0600 either way. Parity, not a finding.
- **O4** Untracked `.DS_Store` files sit in the TS worktree (never
  committed). Hygiene only; nothing credential-bearing.

## Probe log

- Probe file: `throwaway/b8-reviewB-atrest/probes.ts` (review-only; gate
  removes `throwaway/` after sign-off). Runner: `npx vite-node`.
- **Result: 62 checks, 0 failures** (P1 race ×6, P2 failure-hygiene ×8,
  P3 crash-leak ×3, P4 writer sweep ×~35 incl. per-file mask/mode/sentinel
  walk + ghost-export, P5 refresh-error sentinel sweep ×10 across transport /
  400-invalid_grant / 503 / 200-non-JSON / 200-missing-fields, P6 callback
  echo/XSS ×8).
- One probe-side fix during bring-up (unhandled-rejection timing on the
  mismatch case — probe defect, not library); P6b then confirmed the
  library's own behavior clean.
- Static sweeps: `reveal(` site census; `JSON.stringify` write-path census
  (only non-secret payloads: client info, refusal messages, bridge payload
  POST-reveal, me.json PII); `console.` census (zero); token-shape grep
  (zero); ARB-A fix commit diff re-audited — no new reveal/write sites.

## Verdict (lens 1, credential-at-rest)

**GO.** All B8 shards (N1/N2/N3), the MAPFIX, and the ARB-A fix commit are
clean under this lens; the CRED-F3 lock is present and sufficient; the R9.2
fd-hardening drop is confined to the documented lstat/stat TOCTOU window and
widens nothing observable at rest (leaked-tmp and tmp-window modes verified
owner-only by probe).
