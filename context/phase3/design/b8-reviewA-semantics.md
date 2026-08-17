# B8 review — Pair A, Lens 1: storage/protocol semantics (b8-reviewA-semantics.md)

**Status**: COMPLETE · 2026-08-16 · reviewer: fable (adversarial, doubled-review pair A)
Scope: all B8 commits since B8-DL — TS `597ef7d` (MAPFIX), `44fc912` (N1), `53a134e` (N2),
`8017fc4` (N3) — diffed branch-by-branch against Python source @ `ts-port/phase2-contract-support`.

## Checklist (lens mandate)

- [ ] config.py TOML round-trip (schema, defaults, missing-file, malformed)
- [ ] io_utils atomic write sequence (tmp-write/rename order, 0600 timing, symlink refusal point)
- [ ] token file lifecycle incl. refresh persistence (get_valid_token vs OnDiskTokenResolver worlds)
- [ ] bridge v2 read/write/remove
- [ ] callback server port fallback + response pages
- [ ] OAuthFlow.refresh exact request body vs test_auth_flow.py:527-528
- [ ] DCR persistence
- [ ] R10.9 harness re-runs from RUN records
- [ ] 3 crash-window probes of my own
- [ ] MAPFIX ordered-entries semantics

## Findings (ranked; verdicts per P3-2(d))

### F-A1-1 · MAJOR · CONFIRMED — bridge startup-materialization not wired into any default node composition
`workspace.py:476-513`: a bare `Workspace()` loads the bridge AND materializes oauth_browser
tokens to `~/.mp/accounts/{name}/tokens.json` ("bridge is the authoritative source of truth
at startup"). The node port ships `materializeBridgeTokens` + `loadBridgeForStartup`
(`packages/node/src/auth/bridge.ts:583-618`) — but NOTHING in `packages/node/src` calls
`loadBridgeForStartup` (grep: sole non-test caller is bridge.ts itself). The default wiring
`createNodeResolverSources` (`auth-effects.ts:198-202`) routes through core
`resolverSourcesFromEffects`, whose bridge rung is the PURE `effects.bridge.load()`
(`resolver-seams.ts:48`); `resolverSeamsFromEffects` likewise. Three-way inconsistency:
- `bridge.ts:602-611` JSDoc CLAIMS "B8-N3's default `ResolverSources` wiring calls THIS
  (not the pure `loadBridge`) at facade construction" — false as shipped;
- B8-N2-notes disclosure #1 recorded exactly this as "an N3 obligation" — N3 notes never
  mention it (no `loadBridgeForStartup`/materialization entry);
- packet §4.1 row 5 spells the default sources as "env + config + `bridge.load()`" (the
  pure loader), so the packet and the N2 obligation conflict and NOBODY resolved it.
Failure scenario (the Cowork courier contract, Python-green): fresh VM, `MP_AUTH_FILE`
bridge with an oauth_browser account + fresh tokens, NO per-account tokens.json. Python
`Workspace()` → first API call succeeds (materialized tokens served by OnDiskTokenResolver).
Node consumer following the exported default (`new Workspace({sources:
createNodeResolverSources()})` per its own JSDoc example) → session resolves from the
bridge, but `getBrowserToken` finds no tokens.json → `OAuthError OAUTH_TOKEN_ERROR`
("No OAuth tokens found for account…"). The Layer-3 lock
(`workspace-bridge-materialization.test.ts`) passes only because it calls
`loadBridgeForStartup()` BY HAND. Fix direction (arbiter's pick): a node-level startup
composition (e.g. `createNodeResolverSources({startup: true})` or a
`createNodeWorkspaceSources()` that calls `loadBridgeForStartup`), or an explicit
ratified disclosure that the materialization side effect is the caller's duty at node
level — plus correcting the bridge.ts JSDoc and closing the N2→N3 obligation either way.

### F-A1-2 · MINOR · CONFIRMED — undisclosed I/O-error CLASS divergences on the degrade-to-null read paths
Three sites where the TS catch is broader/narrower than Python's, changing the error class
reachable from a hostile/corrupt FS state (none disclosed in shard notes; N2 disclosures
#2/#3 cover adjacent corners only):
(a) `storage.ts` `#readFile` (:338-354): catch-all around `JSON.parse(readCredentialText(…))`
    maps a plain errno error (e.g. EACCES reading a root-owned 0600 file — lstat passes,
    open fails) to the "Corrupted or invalid JSON" warn + `null`; Python's catch is
    `(json.JSONDecodeError, ValueError, UnicodeDecodeError)` + CredentialPathError
    (`storage.py:408-419`) — a plain OSError PROPAGATES out of `load_tokens`.
(b) `bridge.ts` `loadBridge` (:230-239): wraps the strict-decode TypeError
    (UnicodeDecodeError twin) into ConfigError; Python's catch is `(OSError,
    json.JSONDecodeError)` (`bridge.py:181`) — UnicodeDecodeError propagates RAW.
(c) `me-cache.ts` `get` (:168-184): same as (b) — decode TypeError becomes the corrupt-file
    debug path; Python (`me.py:514`) catches only `(json.JSONDecodeError, OSError)`.
Each affects only corrupt/permission-anomalous files (never a well-formed store), so
severity minor — but the family should be one disclosed class in the batch notes, or
aligned (the arbiter may prefer alignment since (a) can hide a real permission problem
as "no tokens").

### F-A1-3 · MINOR · CONFIRMED — exportBridge invalid-pin error class deviates undisclosed
`bridge.ts` `exportBridge` (:459-476) wraps invalid `project`/`workspace` pins in
`ConfigError("Invalid bridge fields: …")`. Python `export_bridge` constructs
`BridgeFile(...)` with NO try/except (`bridge.py:357-364`) — pydantic `ValidationError`
propagates RAW (the Python docstring claims ConfigError but the code does not wrap, and
`accounts.export_bridge` (`accounts.py:963-1010`) does not wrap either). No Layer-3 assert
pins either class (`test_bridge_export.py` asserts ConfigError only for symlink cases).
Needs a disclosure line or an arbiter alignment ruling (the established convention maps
pydantic ValidationError → ParamValidationError, not ConfigError).

### F-A1-4 · MINOR · CONFIRMED — `sortKeys` uses UTF-16 sort at a `sort_keys=True` port site (R11.5)
`bridge.ts:407-419` `sortKeys` sorts with default `Array.prototype.sort` (UTF-16 code-unit
order); Python `json.dumps(sort_keys=True)` (`bridge.py:311`) sorts by codepoint. R11.5
(`sortedByCodepoint`, `compat/codepoint.ts`) exists for exactly this. Divergent only for
non-BMP `headers` keys and byte-format-only (JSON semantics unchanged; both sides parse
either), but the bridge file is the ONE cross-language artifact both runtimes read, and the
rulebook comparator is a one-line import.

### F-A1-5 · MINOR · CONFIRMED — `^\d+$` ASCII narrowing vs Python's Unicode `\d` is nowhere disclosed
`BridgeFile.project` pattern: pydantic/CPython `\d` matches Unicode Nd ("٤٢" ACCEPTED by
Python) vs JS `/^\d+$/` ASCII-only (REJECTED) — `bridge.ts:128`, `validatedProject`
(:497), and by extension every B7 `isdigit` → `/^\d+$/` site the packet's caution #1
mandates. The regex SPELLING is packet-prescribed, but the resulting Nd accept/reject
divergence appears in no disclosure ledger (B7 or B8), while pair-B's own lens is told to
probe "unicode + Nd-digit region/env values". Recommend one batch-level disclosure line
(behavioral alignment would contradict the packet spelling — arbiter to record).

### F-A1-6 · MINOR · CONFIRMED — config readRaw rethrows lstat errno errors Python wraps in ConfigError
`config.ts` `readRaw` (:354-365) wraps only `CredentialPathError` from the symlink probe;
Python `_read_raw` catches ANY `OSError` from `reject_if_symlink` (`config.py:180-183`) —
an lstat EACCES (config under an unreadable directory) becomes `ConfigError` in Python but
a raw errno error in TS (note `existsSync` would swallow it next line, so TS cannot reach
the empty-config path either). Narrow permission-anomaly edge; wrap the errno-error case
too, or disclose with F-A1-2's family.

### Observations (no finding)
- OBS-1 io-utils win32: Python's docstring claims fstat invariants are skipped on Windows
  but the guard is `hasattr(os, "fstat")` (true there); TS skips mode checks on win32
  explicitly. POSIX-gated tests; Windows out of scope (plan §2.2).
- OBS-2 `deleteAll`: Python `glob("*.json")` skips dotfiles; TS `endsWith(".json")` doesn't.
- OBS-3 `setdefaultBlock`/`blockAt` degrade non-table top-level sections to detached `{}`
  (silent no-op) where Python crashes with TypeError — disclosed inline
  (`config.ts:126-129`) but absent from the notes ledger; fold into the F-A1-2 disclosure.
- OBS-4 `token-store.ts` `readTokens` checks `existsSync` BEFORE any symlink probe (dangling
  symlink → silent null, breaking the probe-before-exists discipline every twin site
  follows). No Python twin (seam abstraction; notes disclosure #4 flags it for pair A) —
  acceptable as-is, worth an arbiter style ruling.
- OBS-5 `client-registration.ts:188` uses `"client_id" in data` (prototype-chain `in`)
  rather than `Object.hasOwn` (watchlist #7). Behaviorally inert for this fixed key.
- OBS-6 flow.ts OAUTH_PORT_ERROR message renders the port list without Python's
  parenthesized-list spelling — message text, out of contract (R5.4).

## Verification log

### io-utils.ts vs io_utils.py (N1) — REVIEWED
- atomicWriteBytes: mode&0o077 guard before any FS touch ✓; open OUTSIDE cleanup scope
  (foreign-tmp EEXIST preserved, caution #10) ✓; fchmod-before-write ✓; short-write loop ✓;
  close in finally ✓; rename after close ✓; unlink-our-tmp suppresses ENOENT only ✓;
  pid+counter tmp substitution header-cited ✓.
- readCredentialBytes: symlink→ELOOP, non-regular→EINVAL, mode&0o077→EPERM (skipped win32),
  size>1MiB→EFBIG; ENOENT propagates raw (FileNotFoundError twin) ✓. Order regular→mode→size
  matches _enforce_credential_file_invariants ✓. Dirfd-walk/O_NOFOLLOW drop header-documented
  (sanctioned R9.2) ✓.
- readCappedSecretFromStdin: cap check BEFORE decode ✓; strict UTF-8 ✓; pythonStrip ✓;
  empty→ConfigError ✓.
- OBS-1 (no finding): Python's docstring claims Windows skips fstat invariants but code guards
  on hasattr(os,"fstat") (true on Windows); TS skips mode check on win32 explicitly. POSIX-gated
  tests, Windows out of scope — behavior identical on target platform.

### config.ts vs config.py (N1) — REVIEWED
- _read_raw: symlink probe before existence ✓; missing → {} ✓; TOML error + OSError-class →
  ConfigError wrap, decode errors propagate ✓ (see CANDIDATE-1 for the lstat-EACCES edge).
- _mutate → transaction(): read-once, body, whole-file validateRaw, write-once ✓.
- _write_raw: parent mkdir 0o700 + suppress-chmod tighten + atomic 0600 ✓ (trailing-newline
  cosmetic delta disclosed inline, formatting out of contract per packet §0.4).
- applySetActive/applyClearActive/applyUpdateAccount/applyAddAccount branch-by-branch match;
  duplicate add → PLAIN ConfigError (B-E2E-F1) ✓; token XOR ✓; type-incompat errors ✓.
- apply_session: ValueError→ParamValidationError twin raised BEFORE transaction ✓; project→
  explicit-else-active account, non-str → ConfigError ✓; one transaction ✓.
- apply_target: wholesale [active] replace ✓ (no workspace → prior pin cleared);
  default_project sync ✓; unknown target/deleted account → ConfigError ✓.
- validateWorkspaceId: VALUE check Number.isInteger && >0 (caution #1) ✓.
- list_accounts/list_targets sorted, non-dict blocks skipped ✓; refs map built over sorted
  target names ✓.
- CANDIDATE-1 (minor): lstat EACCES in rejectIfSymlink → Python wraps in ConfigError
  (except OSError at config.py:182-183); TS readRaw rethrows the bare errno error
  (only CredentialPathError is wrapped). Narrow corruption/permission edge.
- CANDIDATE-2 (obs): non-table top-level sections (`active = 5`): Python raises TypeError
  (uncoded crash); TS setdefaultBlock/blockAt degrade to detached {} (silent no-op write).
  Disclosed inline in config.ts:126-129 as out-of-contract. Verify notes disclosure.

### config-writes.ts (N1) — REVIEWED
- FR-045 promotion exactly once, in adapter transaction, is_first evaluated BEFORE insert ✓
  (verified against accounts.py:475-489 — `is_first = not (raw.get("accounts") or {})` twin).
  setActive workspace-null clear one transaction ✓.

### flow.ts refresh half vs flow.py:118-226,442-605 (N2) — REVIEWED
- Region validation: OAUTH_CONFIG_ERROR, sorted region list ✓.
- refresh no-refresh-token: truthiness on account_name (`!== null && !== ""` = Python `if
  account_name`) for hint AND details shape {} vs {account_name} ✓ raised BEFORE any request ✓.
- Form body: {grant_type, refresh_token, client_id} insertion order via Object.entries →
  urlEncodePairs → quotePlus (verified char-for-char urllib quote_plus twin: safe set
  ALPHA/DIGIT/`_.-~`, space→+, uppercase %XX over UTF-8 — NOT URLSearchParams/
  encodeURIComponent) ✓ matches test_auth_flow.py:527-529 asserts + the recorded body_text.
- Transport failure → OAuthError(errorCode, {url: tokenUrl}) only for MixpanelHttpError ✓.
- invalid_grant probe: 400/401 only ✓; isPlainRecord canonical guard (watchlist #13) ✓;
  parse failure → false ✓; REVOKED requires operation === "Token refresh" ✓ (exchange generic).
- Revoked details ALWAYS carry account_name (null when absent) ✓; generic spreads only when
  truthy ✓ — the three shapes of caution #5 all verified.
- 200 non-JSON → errorCode + {response_body} + content-type in message ✓; fromTokenResponse
  failure → {response_data: pythonStr(data)} ✓; parseLossless everywhere (GATE-R5) ✓.
- get_valid_token: no tokens → OAUTH_TOKEN_ERROR; fresh → reveal; expired+no client info →
  OAUTH_REFRESH_ERROR; refresh → saveTokens LEGACY v2 path (two-worlds rule) → reveal ✓;
  isExpired({now}) injectable clock ✓.
- login half (N3): step order PKCE→port→DCR→authorize URL→completers race→exchange→optional
  persist ✓; error_q-consultation-only-after-310s semantics preserved ✓; stderr banner text +
  trailing newline parity ✓; OAUTH_PORT_ERROR / OAUTH_BROWSER_ERROR(+authorize_url details) /
  OAUTH_TIMEOUT / generic-wrap OAUTH_TOKEN_ERROR branches ✓; exchange_code form order
  (grant_type, code, redirect_uri, client_id, code_verifier) ✓; AbortSignal loser-cancel is a
  header-documented TS-only substitution (Python leaks daemon threads) — behavior-neutral.
- parsePastedRedirect: strip→empty→error param→missing code/state→state mismatch branch order ✓
  (verify parseQs semantics separately).
- CANDIDATE-3 (minor/verify): login OAUTH_PORT_ERROR message renders `[19284, 19285, ...]`
  (join with ", " inside []) vs Python f"({CALLBACK_PORTS})" which renders a LIST
  "[19284, 19285, 19286, 19287]" inside parens — TS drops the parens. Message text out of
  contract (R5.4) — no finding, recorded as observation only.

### storage.ts vs storage.py (N2) — REVIEWED
- storageRoot env falsiness ✓; accountDir pattern + coded ValueError twin ✓; ensureAccountDir
  0o700 + defensive chmod ✓; validateRegion 2-lower ✓; _ensure_dir ✓.
- checkAndFixPermissions: lstat substitution for _fchmod_no_follow (header-documented R9.2
  drop); symlinked dir/file never chmodded, warn-only ✓; != 0o700 / != 0o600 repair ✓.
- save_tokens reveal-site discipline ✓ (explicit field unwrap, refresh_token only when
  non-null) ✓; load_tokens str() coercions via pythonStr ✓ degrade-to-null classes ✓.
- delete_tokens exists→unlink ✓; delete_all *.json ✓; clear_me_cache me_*.json count ✓.
- CANDIDATE-4 (minor): #readFile swallows non-CredentialPathError I/O errors (e.g. EACCES on
  the open/read of a root-owned 0600 file) as "Corrupted or invalid JSON" → null; Python's
  except clause is (json.JSONDecodeError, ValueError, UnicodeDecodeError) + CredentialPathError
  — a plain OSError (EACCES) PROPAGATES out of _read_file/load_tokens in Python but degrades
  to null in TS. Class divergence on a reachable FS state.
- OBS-2 (no finding): delete_all Python glob("*.json") skips dotfiles (glob `*` never matches
  a leading dot); TS endsWith(".json") also deletes ".foo.json". Cleanup-helper edge only.

### token-resolver.ts vs token_resolver.py (N2) — REVIEWED
- Symlink-probe-before-exists ✓; the four OAUTH_TOKEN_ERROR shapes (symlink / missing /
  unreadable / malformed with validation_error detail) ✓; expired+no-refresh
  {account_name, region, path} ✓; rotation-keep (token_resolver.py:236-241) ✓; atomic
  rewrite via tokenPayloadBytes (verified twin of token.py:188-212 — key order + omitted
  refresh_token) ✓; missing region client info → OAUTH_REFRESH_ERROR ✓; static path inline
  wins / env falsiness `undefined || ""` = Python `if not value` ✓; bare token (no Bearer) ✓.
- Default refresh seam = fresh OAuthStorage + OAuthFlow per refresh, matching
  token_resolver.py:208-234 lazy construction ✓.

### bridge.ts vs bridge.py (N2) — REVIEWED
- Search order explicit > MP_AUTH_FILE (truthy) > defaults ✓; symlink probe before existence
  at every read ✓; v2 schema: extra=forbid, Literal[2], oauth_browser-requires-tokens
  model validator, headers string-map ✓; export: parent mkdir 0o700, atomic 0o600, secrets
  revealed ONLY in serializeBridge ✓; snapshot semantics (no refresh) in readBrowserTokens ✓;
  removeBridge resolution order + returns-deleted ✓; materializeBridgeTokens vs
  workspace.py:476-513 (always-overwrite, falsy scope → "read", ensure_account_dir 0700,
  token_payload_bytes) ✓; loadBridgeForStartup = ctor composition ✓.
- CANDIDATE-5 (minor): serializeBridge's `sortKeys` uses `Object.keys().sort()` (UTF-16
  code-unit order) where Python `json.dumps(sort_keys=True)` sorts by codepoint — R11.5
  (`sortedByCodepoint`) exists for exactly this port site. Divergent only for non-BMP header
  names (byte-format only, JSON semantics unchanged), but it is a literal `sorted()` port
  site and the rulebook comparator is one import away.
- CANDIDATE-6 (minor): exportBridge wraps invalid project/workspace pins in ConfigError
  ("Invalid bridge fields: …"); Python `export_bridge` calls `BridgeFile(...)` with NO
  try/except — pydantic ValidationError propagates RAW (bridge.py:357-364; the docstring
  claims ConfigError but the code does not wrap, and accounts.export_bridge does not wrap
  either). Error-CLASS divergence on invalid pins; no Layer-3 assert either way — needs a
  disclosure or an arbiter alignment ruling.
- CANDIDATE-7 (minor): BridgeFile `project` pattern — Python/pydantic `^\d+$` is
  Unicode-aware (`\d` = Nd; "٤٢" ACCEPTED) vs JS `/^\d+$/` ASCII-only (REJECTED). Same
  narrowing exists at every B7 `isdigit` → `/^\d+$/` site (packet §7 caution 1 mandates the
  regex spelling), so this is packet-consistent — but the Nd acceptance divergence itself
  appears nowhere in the disclosures. Recommend a batch-level disclosure line.
- OBS-3: loadBridge wraps ALL read/decode errors in ConfigError; Python lets
  UnicodeDecodeError (not in the `(OSError, JSONDecodeError)` catch) propagate raw. Same
  class-divergence family as CANDIDATE-4, opposite direction.

### me-cache.ts vs me.py:413-607 (N2) — REVIEWED
- Default dir bypasses MP_OAUTH_STORAGE_DIR exactly like me.py:459 (header-documented;
  effects wrapper injects accountDir(name)) ✓; get: symlink warn/null, TTL strict-greater
  over injected seconds clock, corrupt→debug null, schema-drift→warn+unlink+null ✓;
  put: mkdir then chmod-failure RAISES coded ConfigError {path} (caution 12) ✓;
  member_list/unified_member_list strip ✓; cached_at stamp ✓; 0o600 atomic ✓;
  ordered-map write + lossless ordered re-read (MAPFIX round-trip) ✓.
- OBS-4 (same family as CANDIDATE-4/OBS-3): invalid-UTF-8 cache file — Python propagates
  UnicodeDecodeError (only JSONDecodeError/OSError are caught at me.py:514); TS swallows the
  fatal-decode TypeError as the corrupt-file debug path → null.

### callback-server.ts vs callback_server.py (N3) — REVIEWED
- CALLBACK_PORTS [19284..19287] in-order bind loop ✓; exact-port mode + OAUTH_PORT_ERROR
  {port} ✓; all-busy → OAUTH_PORT_ERROR {ports} ✓; one-shot handle_request semantics ✓
  (first request decides — incl. Python's quirk that a stray non-callback GET consumes the
  one shot and surfaces the missing-code/state error; TS ports it: NO path check, matching
  do_GET); SUCCESS_HTML/_ERROR_HTML verbatim ✓; html.escape(quote=True) twin exact
  (& < > " ' in the & -first order) ✓; state-mismatch details {expected_state,
  received_state} server-side only ✓; provider-error details {error, error_description} ✓;
  non-GET → 501 + consumed shot + OAUTH_TIMEOUT-shaped error, matching
  BaseHTTPRequestHandler ✓; timeout → OAUTH_TIMEOUT {timeout_seconds} ✓; TS-only
  AbortSignal loser-cancel header-documented (Python leaks daemon threads) ✓.

### query-params.ts (parseQs/pythonUnquote) — REVIEWED
- parse_qs defaults replicated: split '&', no-`=` dropped, blank value dropped (checked on
  RAW value pre-decode, as CPython does), name unquoted after +→space, repeated names in
  order ✓. pythonUnquote: consecutive %XX runs decoded per-run as UTF-8 replacement,
  malformed escapes left literal incl. '%' ✓; U+FFFD-count boundary disclosed in header ✓.

### client-registration.ts vs client_registration.py (N3) — REVIEWED
- Cache check BEFORE region validation (Python order) + redirect_uri match gate ✓;
  zero-fetch fast path ✓; DCR body keys in insertion order ✓; 429 branch {region,
  status_code, retry_after} ✓; is_success = 2xx ✓; malformed → OAUTH_REGISTRATION_ERROR
  {region, response_body} ✓; created_at via injectable clock ✓; persist-BEFORE-return ✓
  (crash between register and persist re-registers — ported, not improved).

### pkce.ts vs pkce.py — REVIEWED
- token_bytes(64) → 86-char base64url verifier; S256 challenge 43-char ✓. The packet-sketch
  "token_urlsafe(32)" discrepancy is header-disclosed with Python-as-arbiter ✓.

### token.ts core touch (§0.3.2) — REVIEWED
- pythonUtcIsoformat: +00:00 always, no fractional digits at µs==0 else exactly 6,
  microsecond rounding with carry ✓; isExpired/fromTokenResponse optional {now} seams,
  existing callers unchanged ✓; the Phase-2 TODO(port) marker REMOVED ✓.

### B8-MAPFIX (597ef7d) — REVIEWED
- Lossless parser captures source key order in a non-enumerable LOSSLESS_KEY_ORDER sidecar
  attached only when JS enumeration diverges; duplicate keys keep FIRST position with LAST
  value (json.loads dict rule) ✓; toNativeJson propagates the sidecar ✓; model-base
  'ordered-dict' container reconstructs ReadonlyMaps from orderedEntries (or Map input) ✓;
  defaultAccountName first-org pick = `entries().next()` = `next(iter(...))` ✓; me-cache
  writes the three container maps via a Map-aware stringifier so the round-trip preserves
  order ✓; exclusion-removal proof: out-of-order fuzz now runs (below).

### wire-auth.ts binding (§3.4) — REVIEWED
- Honest: constructs the REAL node OAuthFlow (region "us" per the recorded scheme_host),
  frozen record-epoch clock, tmp-dir storage stub never consulted, calls the real
  refreshTokens; output walk is codec-only; errors rethrown as WireCoreError wrapping the
  real OAuthError; absent account_name omitted ✓. NO batch-status flip in the module
  commits ✓ (bound-while-pending).

### token-store.ts / auth-effects.ts / env.ts / fs-seams.ts — REVIEWED
- TokenStore members match their Python twins (writeTokens=_persist_browser_tokens shape;
  removeAccountDir=_safe_rmtree_warn warn-never-raise incl. message shape;
  clientInfoPath=_client_info_path via defaultStorageDir; accountDirExists=SEM-F2) ✓.
- createNodeAuthEffects: every UNPORTED_AUTH_SEAMS member real; oauthFlow.login always
  persist:false (B7 contract); persistActive over persistActiveToConfig closes the
  UNPORTED_RESOLVER_SEAM residue; narrate = stderr write ✓. BUT see F-A1-1 for the
  bridge-startup materialization hole in the default sources composition.
- env.ts: call-time process.env getters ✓; raw values, falsiness left to resolver core ✓.
- fs-seams.ts nodeReadFile: plain read, no credential hardening (W7-D1 contract) ✓.

## Harness re-runs (P3-2(d) item 5) — ALL REPRODUCE, recorded seeds

| Harness | Recorded | Re-run result |
|---|---|---|
| throwaway/b8-n1/io-config-probes.ts | 74 checks 0 fail | 74 checks, 0 failures ✓ |
| throwaway/b8-n1/config-model-fuzz.ts | runs 500 ops 2994 err-agree 2220 div 0 seed 20260816 | identical ✓ |
| throwaway/b8-n1/io-fuzz.ts | 500+500 examples div 0 seed 20260816 | identical ✓ |
| throwaway/b8-n2/fs-probes.ts | 53 checks | 53 checks, 0 failures ✓ |
| throwaway/b8-n2/refresh-probes.ts | 77 checks | 77 checks, 0 failures ✓ |
| throwaway/b8-n2/fuzz.ts | 5 surfaces ×500 seed 20260816 | all zero-divergence ✓ |
| throwaway/b8-n3/probes.ts | 53 checks | 53 passed, 0 failed ✓ |
| throwaway/b8-n3/fuzz.ts | 4 surfaces ×500 seed 20260816 | all zero-divergence ✓ |
| throwaway/b8-mapfix/org-order-fuzz.ts | 1000 examples div 0 | identical ✓ |
| throwaway/b8-mapfix CPython diff | naming 600 / workspace 400 div 0 | re-run end-to-end (emit + uv run py_driver): identical ✓ |
| npm run conformance | 3,251 PASS / 0 FAIL / 0 UNPORTED @ 70c904dc | identical ✓ (oauth_flow. still pending — flip is the gate's) |
| packages/node/test | 348 tests | 348 passed ✓ |

## Reviewer crash-window probes (3 fresh, beyond the RUN rows)

`throwaway/b8-reviewA-semantics-probes.ts` — 13 checks, 0 failures:
1. close()-failure AFTER a fully successful write → error propagates, rename skipped,
   original byte-identical, tmp cleaned (Python finally-close parity).
2. rename failure under a NON-default requested mode (0o400) → original bytes AND mode
   (0o600) untouched, tmp cleaned, error propagated.
3. Symlink planted MID-TRANSACTION (between ConfigManager readRaw and writeRaw) → the
   rename replaces the LINK inode, target file untouched, replacement is a regular 0o600
   file, post-swap round-trip works. CPython parity verified LIVE against the real
   ConfigManager (`uv run` probe: identical outcome — target "VICTIM" intact, is_link
   False, mode 0o600, header round-trips).

## Checklist closure

- [x] config.py TOML round-trip (schema, defaults, missing-file, malformed) — F-A1-6, OBS-3
- [x] io_utils atomic write sequence — clean (probes 1-2 + RUN row 1)
- [x] token file lifecycle incl. refresh persistence (both persistence worlds) — clean
- [x] bridge v2 read/write/remove — F-A1-3/4/5 + F-A1-1 (startup wiring)
- [x] callback server port fallback + response pages — clean
- [x] OAuthFlow.refresh exact request body vs test_auth_flow.py:527-529 — clean
  (quotePlus byte-grammar verified; vectors + N2 fuzz surface E lock it)
- [x] DCR persistence — clean (persist-before-return, region-shared path)
- [x] R10.9 harness re-runs — all reproduce (table above)
- [x] 3 own crash-window probes — green, incl. live CPython parity for probe 3
- [x] MAPFIX ordered-entries semantics — clean end-to-end

**Status: COMPLETE — 1 MAJOR (F-A1-1), 5 MINOR, 6 observations. Everything else verified
faithful branch-by-branch against the Python source ranges of packet §2.1/§3.1/§4.1.**

