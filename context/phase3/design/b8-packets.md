# B8 design-lite packets — the node package (config, io_utils, auth storage/resolver/bridge, OAuth refresh + PKCE plumbing, on-disk MeCache)

**Status**: v1.0 · 2026-08-16 · P3-6 step 1 output for batch B8 (fable, ≤ high).
Spec of record: `phase3-playbook.md` v1.1 (B8 rows: P3-1 `:104`, scope row `:235-249`,
P3-3 doubling `:380-387`, P3-5 flip `:663`, P3-6 sharding `:769-772`) + all recorded
discrepancies (#1–#13) + `user-ratifications.md` — INCLUDING the **2026-08-16
org-ordering ruling** (FIX via order-preserving Map; supersedes the B7-ARB-A R2
exclusion). Inbound deferrals: `b7-packets.md` §7 outbound ledger + the B7 arbiter
resolutions (`b7-reviewA-resolution.md` SEM-F2 `TokenStore.accountDirExists`;
`b7-reviewB-resolution.md` CRED-F3 serialization round-trip lock + B-E2E-N1 FR-045
promotion layering + B-E2E-F1 duplicate-name error class) + `b6-packets.md` outbound
rows (`readFile` seam W7-D1; `TestBridgeTokenMaterialization`; the three
`test_042_edge_cases.py` B8 classes; UNPORTED-probe retirement at the LAST flip).

Ground state verified 2026-08-16: Python `ts-port/phase2-contract-support` @
`f5f1dde` lineage (corpus pin `70c904dc`); TS `main` @ `9fb09ef` (B7 gate closed:
**3,244 PASS / 0 FAIL / 7 UNPORTED** — the 7 = `oauth_flow.refresh_tokens`, the LAST
pending corpus api). `packages/node` is the Phase-1 skeleton (`src/index.ts` exports
`NODE_PACKAGE_NAME` only). **This gate closes the ENTIRE corpus.**

**Standing rules restated**: NO mutation testing `[SA1]`. R10.13 incremental protocol
on every agent. Python is the behavior arbiter. `analytics` READ-ONLY. LOCAL COMMITS
ONLY, both repos. B8 is fable-tier → bindings land INLINE in the module task (P3-2 b′)
and the R10.9 harness runs in the same task. **DOUBLED review** (P3-3): two independent
pairs + arbiter per shard — protocol in §6. R9.2 is the batch's backbone: TOML config
(same schema), token files atomic + `chmod 0600`, **keep symlink refusal, drop POSIX
fd-flag hardening** (plan §4.2 table row "POSIX atomic 0o600 writes"), callback ports
19284–19287, bridge file, env resolution; resolver precedence stays
env > param > target > bridge > config — **the B7 core already enforces the order; B8
only supplies real sources** through the seams defined in
`packages/core/src/auth/resolver.ts` (`ResolverEnv` / `ResolverConfigSource` /
`BridgeView` / `ResolverSources`) and
`packages/core/src/accounts/auth-effects.ts` (`AuthEffects`, `UNPORTED_AUTH_SEAMS`).
Core signatures DO NOT change (the two sanctioned core touches are enumerated in §0.3).

## §0 Shard map, dispatch order, and the playbook mapping

### §0.1 Shard table (DISPATCH-ORDER RULE honored: N1 first, N2 second, N3 third)

| Shard | Contents | Vectors | Runs |
|---|---|---|---|
| **B8-N1** | `ConfigManager` (TOML, `_internal/config.py`) + `io_utils.py` (atomic writes, symlink refusal, credential reads, stdin cap) + node env wiring (`ResolverEnv & {get}`) + W7-D1 `readFile` node impl + **the ratified org-ordering Map fix (core touch)** | 0 | **FIRST** |
| **B8-N2** | `auth/storage.py` + **`flow.py` refresh half** (`get_valid_token` / `refresh_tokens` / `_post_token_request` + `OAUTH_BASE_URLS` constants home) + `token_resolver.py` (`OnDiskTokenResolver`) + `bridge.py` + on-disk `MeCacheStore` (`me.py:413-607`) + `TokenStore` incl. `accountDirExists` — **the 7 `oauth_flow.refresh_tokens` vectors + binding land here** | **7** | second |
| **B8-N3** | `pkce.py` + `client_registration.py` (DCR + `~/.mp/oauth/client_{region}.json` persistence) + `callback_server.py` + `flow.py` interactive-login half (`login` / `_parse_pasted_redirect` / `_build_authorize_url` / `_find_available_port`) + `oauthFlow.login` effect + **node effects-bag assembly** (`createNodeAuthEffects()`, `persistActive`, `narrate`, ready-made `accounts`/`session`/`targets`/`login_unified` exports, default `ResolverSources` wiring) | 0 | third |

Σ vectors = **7** — the complete `oauth_flow.` budget (P3-1 `:104`), all carrying api
`oauth_flow.refresh_tokens` (`conformance-runner/corpus/auth/test_auth_flow.jsonl`,
`$bundle.count: 7`). All 7 ids enumerated in §3.4. No other B8 api name exists in the
corpus or the api-index.

### §0.2 Mapping vs the playbook P3-6 sketch (recorded, no scope change)

The playbook row (`:769-772`) bins the WHOLE of `flow.py` under N3 ("N3 flow + pkce +
client_registration + callback_server (the `oauth_flow.` vectors land here…)").
**This packet moves the refresh half of `flow.py` — and therefore the 7 vectors + the
binding + the `token.ts` `expires_at` TODO closure — into N2.** Reason (dependency
analysis, the B7 lesson): `OnDiskTokenResolver._refresh_and_persist`
(`token_resolver.py:174-243`) constructs `OAuthFlow` and calls `refresh_tokens`
directly (`:228-234`); leaving refresh in N3 would give N2 a BACKWARD dependency on a
later shard. With the move, the dependency chain is strictly forward:
N1 (io_utils/config) → N2 (storage/bridge/resolver/refresh, imports N1's
`atomic_write_bytes`/`reject_if_symlink`/credential reads) → N3 (login flow, imports
N2's storage + the shared OAuth constants). Shard names stay N1/N2/N3 in dispatch
order — the rule is honored; only the CONTENT of N2/N3 differs from the sketch, as
recorded here. `flow.ts` is a shared file across N2/N3: N2 creates the `OAuthFlow`
class (constructor + region validation + refresh surface); N3 extends the same file
with the login surface. Dispatch is sequential (playbook P3-6 step 2 "sequential
across groups that share files"), so there is no merge point.

### §0.3 Core touches (exactly two, both justified)

1. **Org-ordering Map fix** (N1) — USER RATIFICATION 2026-08-16
   (`user-ratifications.md:14-22`): `MeResponse.organizations` parses into an
   insertion-order-preserving container sourced from the lossless JSON layer so
   `defaultAccountName`'s first-org pick matches Python dict insertion order exactly.
   Supersedes the B7-ARB-A R2 exclusion; the naming fuzz-domain exclusion is removed
   once the fix lands. Files: `packages/core/src/client/lossless-json.ts` (ordered-
   entries capability), `packages/core/src/client/me.ts:390` (organizations — and
   decide/record whether `projects`/`workspaces` get the same treatment; the ruling
   names the FIRST-ORG PICK as the result-affecting site, the other two #13 sites are
   message/tie-order only — fixing all three with one mechanism is preferred if the
   type change is uniform, R4.8 ReadonlyMap), `packages/core/src/accounts/naming.ts`
   (`defaultAccountName` first-org pick) + every consumer `tsc` surfaces. Lock with a
   NEW Layer-3 test: out-of-ascending-id `/me` payload → derived account name equals
   Python's insertion-order pick (header cites the ratification). Gate duty §5.6
   updates playbook Discrepancy #13 with the closure.
2. **`token.ts` `expires_at` ISO-rendering TODO closure** (N2) —
   `packages/core/src/auth/token.ts:174-179` (`TODO(port)`): `fromTokenResponse`
   currently renders `Date.toISOString()` (`Z`, milliseconds) and reads the ambient
   clock. The 7 wire vectors LOCK Python `datetime.isoformat()` rendering
   (`+00:00`, no fractional digits when the microsecond field is 0 — the recorded
   result is `"2026-01-15T13:00:00+00:00"` = recordEpoch + `expires_in` 3600s) and
   force an injectable clock: `fromTokenResponse(data, {now})` (optional seam,
   default ambient — existing callers unchanged; the flow twin and the binding pass
   the frozen `now`). Rendering helper ports Python semantics: seconds precision when
   whole, else 6-digit microseconds; offset always `+00:00` (never `Z`). `isExpired`
   gains the same optional `now` seam (`token.ts:163-166` currently hardwires
   `Date.now()`) — needed by N2's `get_valid_token` twin under the frozen clock.

### §0.4 R9 posture

`packages/node` MAY import `node:*` (the eslint boundary restricts `packages/core`
only — verified `eslint.config.js:47-75`). `packages/core` still may NOT: both core
touches in §0.3 are pure. Node modules read `process.env` AT CALL TIME (never at
module load — Python reads `os.environ` per call, `storage.py:53-91`,
`config.py` `MP_CONFIG_PATH`, `bridge.py` `MP_AUTH_FILE`; call-time reads keep test
isolation semantics identical). Cross-package imports follow the repo's existing
relative-path precedent (the rig imports `../../packages/core/src/...js`,
`wire-auth.ts:21`); node imports core as `../../core/src/...js`. No build-system
change; root vitest picks up `packages/node/test/**` already (skeleton
`index.test.ts` proves it); `packages/node/package.json` gains no new scripts
(root `npm run check` covers typecheck/lint/fmt/test).

**New runtime dependency decision (N1 records it)**: Python uses
`tomllib`/`tomli_w` (`config.py:23-31`). TS needs a TOML 1.0 parse+serialize library
for `packages/node` — requirement: spec-compliant parse, table/array-of-scalars
round-trip of the config schema, no datetime handling needed. Indicative pick:
`smol-toml` (TS-native, MIT, zero-dep); N1 pins the exact version in
`packages/node/package.json` + the root lockfile and records the choice in the shard
notes. Serialization FORMATTING (whitespace, key order on disk) is out of contract —
each side reads its own writes and both read the same schema; Layer-3 locks are
read-side (`TestFixtureLoad`, `test_config.py:625` — carry the fixture file verbatim
into `packages/node/test/fixtures/`).

### §0.5 Env-var surface B8 wires (call-time `process.env` reads)

| Var | Consumer (Python cite) | Shard |
|---|---|---|
| `MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION` / `MP_OAUTH_TOKEN` / `MP_WORKSPACE_ID` | `ResolverEnv` bag (resolver core reads, B7 `resolver.py`) — B8 supplies the live bag | N1 |
| generic `env.get(name)` | `token_env` indirection + login-type detection (`accounts.py:1409`, `region_probe.py:252`) | N1 |
| `MP_CONFIG_PATH` | `ConfigManager` path override (`config.py:141-160`) | N1 |
| `MP_OAUTH_STORAGE_DIR` | storage root override (`storage.py:53-91`; honored by `account_dir` → `_account_tokens_path`, `token_resolver.py:40-54`) | N2 |
| `MP_AUTH_FILE` | bridge path override (`bridge.py:137-196` resolution order: explicit `path` > `MP_AUTH_FILE` > default search paths `bridge.py:119-134`) | N2 |
| `MP_CUSTOM_HEADER_NAME` / `MP_CUSTOM_HEADER_VALUE` | already wired at B0 (`client/headers.ts`) — NOT B8 scope; do not re-read | — |

---

## §1 Vector budget and gate arithmetic

Corpus pin `70c904dc` (`conformance-runner/corpus.config.json`), bundle
`conformance-runner/corpus/auth/test_auth_flow.jsonl` (`$bundle.count: 7`,
`source_file: tests/unit/test_auth_flow.py`). Baseline at B7 gate: **3,244 PASS /
0 FAIL / 7 UNPORTED**. B8 gate flips `oauth_flow.` → `done`; expected checkpoint:
**3,251 PASS / 0 FAIL / 0 UNPORTED — THE FULL CORPUS** (delta exactly +7; no
cross-batch setup carry-over: none of the 7 vectors carries `call.setup[]`,
`call.session`, or callbacks — verified by jq scan 2026-08-16; inputs are pure
`$type: OAuthTokens` + strings, expectations are `interactions` + `result` (3) or
`interactions` + `error` (4)). After this gate the ONLY remaining Phase-3 batch is
B9 (0 vectors, spike-scoped) — the P3-1 `:107` B9-gate expectation
(3,179+N = 3,251 with N=72) is REACHED at the B8 gate and must merely hold at B9.

---

## §2 Packet B8-N1 — config + io_utils + env wiring + readFile + org-ordering fix (fable; runs FIRST)

### §2.1 Modules, Python line ranges at HEAD, TS homes

| Python source (range @ HEAD) | What | TS home |
|---|---|---|
| `_internal/io_utils.py:1-545` (whole file) | `atomic_write_bytes` :83-163 (tmp `<name>.tmp.<pid>.<tid>`, `O_EXCL`, tmp always created 0o600, `fchmod` to requested mode, short-write loop, `os.replace`, cleanup-on-failure; `mode & 0o077` → ValueError) · `CredentialPathError(OSError)` :165-181 · `reject_if_symlink` :182-235 (lstat probe) · `_open_credential_fd` :236-348 + `_open_leaf_only` :349-378 + `_enforce_credential_file_invariants` :379-435 (**fd-flag hardening layer — DROPPED per R9.2/plan §4.2; the node port substitutes lstat-based symlink refusal + stat-based regular-file/size checks, document the substitution in the module header**) · `read_credential_bytes` :436-496 · `read_credential_text` :497-516 · `read_capped_secret_from_stdin` :517-545 | `packages/node/src/io-utils.ts` |
| `_internal/config.py:1-1061` (whole file) | `_DEFAULT_CONFIG_PATH` :59 (`~/.mp/config.toml`) · `_account_from_block` :70-91 · `_account_to_block` :92-125 (**`reveal()` site — CRED-F3**) · `ConfigManager` :126-1042 (`__init__`/`config_path` :141-161 with `MP_CONFIG_PATH` > ctor kwarg > default · `_read_raw` :162-191 · `_write_raw` :192-207 via `atomic_write_bytes` 0o600 · `_mutate` :208-236 · `_validate_raw` :237-256 · `_apply_set_active` :257-288 · `_apply_clear_active` :289-312 · `_apply_update_account` :313-405 · `_apply_add_account` :406-493 (duplicate name → PLAIN `ConfigError`, :446 region — B7-ARB-B B-E2E-F1) · `list_accounts` :494-532 · `get_account` :533-551 · `add_account` :552-606 · `update_account` :607-651 · `remove_account` :652-693 · `get_active` :694-712 · `set_active` :713-744 · `clear_active` :745-763 · `apply_session` :764-836 · `list_targets` :837-861 · `get_target` :862-886 · `add_target` :887-935 (Target model errors WRAPPED in ConfigError, :915-920) · `remove_target` :936-950 · `apply_target` :951-1003 ([active] replaced WHOLESALE — a target with no workspace clears any prior pin) · `get_custom_header` :1004-1029 · `set_custom_header` :1030-1043 · `_validate_workspace_id` :1044-1057) | `packages/node/src/config.ts` (ConfigManager twin) + `packages/node/src/config-writes.ts` (the `ResolverConfigSource & ConfigWrites` adapter) |
| env wiring (no single Python file — `os.environ` reads) | `createNodeEnv(): ResolverEnv & {get}` — call-time `process.env` reads; empty string handling stays THE CALLER'S job (the resolver core owns falsiness, `resolver.ts`; the env bag returns raw values, `undefined` for unset) | `packages/node/src/env.ts` |
| W7-D1 `readFile` seam (`b6-packets.md` outbound; `workspace.ts:1155`, `governance-data.ts:57-64`) | `nodeReadFile(path: string): Promise<Uint8Array>` over `node:fs/promises` — the `Path(...).read_bytes()` twin (`workspace.py:8044`); plain read, NO credential hardening (a user-supplied CSV, not a credential file) | `packages/node/src/fs-seams.ts` |
| org-ordering Map fix (core touch §0.3.1) | ordered `organizations` + `defaultAccountName` pick | `packages/core/src/client/{lossless-json,me}.ts`, `packages/core/src/accounts/naming.ts` |

### §2.2 Behavior locks (branch-level; each line = a review-pair assertion)

- **Atomic write protocol** (`io_utils.py:83-163`): tmp sibling named
  `<name>.tmp.<pid>.<tid>` — TS twin uses `process.pid` + a monotonically increasing
  per-process counter (document: JS has no OS thread id in the main thread;
  `worker_threads.threadId` is 0 — counter preserves the collision-avoidance intent;
  header-cite this substitution). `O_EXCL` create at literal 0o600; `fchmodSync(fd,
  mode)` BEFORE writing; full-write loop (`fs.writeSync` may short-write — loop);
  `fs.renameSync` (POSIX-atomic replace); on ANY failure unlink tmp
  (`missing_ok` semantics) and rethrow with the ORIGINAL error. `mode & 0o077` →
  coded error (Python raises bare `ValueError`; TS uses the existing
  `ParamValidationError`/`VALIDATION_ERROR` twin — R5 codes-not-messages; do NOT
  mint a code). Parent dirs NOT created. Windows: chmod is a no-op — tests are
  POSIX-gated exactly like Python's (`sys.platform` guards translate to
  `process.platform`).
- **Symlink refusal** (`io_utils.py:182-235`): `lstatSync` probe; symlink →
  `CredentialPathError` twin (a coded `MixpanelHeadlessError` subclass mirroring
  the OSError lineage in `details`; N1 defines it ONCE in `io-utils.ts`, N2 imports —
  R10.8). Probe order: symlink check BEFORE existence check (the `bridge.py:219`
  comment pattern) — a dangling symlink must refuse, not ENOENT.
- **Credential reads** (`io_utils.py:436-516`): refuse symlink; refuse non-regular
  file (stat `isFile()`); enforce the size cap (port the constant from
  `io_utils.py` — re-read at HEAD); read bytes then decode UTF-8 for the text
  variant. The DROPPED layer is exactly `_open_credential_fd`'s
  `O_NOFOLLOW`/`O_CLOEXEC`/dirfd-walk machinery (:236-435) — behavior visible to
  callers (refusals + successful reads) is preserved via lstat/stat; the TOCTOU
  window this reopens is the sanctioned R9.2 deviation, module-header documented.
- **stdin secret** (`io_utils.py:517-545`): `read_capped_secret_from_stdin` twin
  over an injectable `Readable` (default `process.stdin`) — cap + strip semantics
  verbatim (`pythonStrip`, R11.7).
- **ConfigManager transactions**: every public mutator is ONE
  `_read_raw → mutate → _write_raw` transaction (`config.py:208-236`); `_write_raw`
  routes through `atomic_write_bytes(path, toml_bytes, mode=0o600)` (:192-207).
  Config file symlink → refuse via the shared helper (`test_config.py::
  TestSymlinkRejection` :780 is the lock).
- **FR-045 promotion layering** (B7-ARB-B B-E2E-N1, `auth-effects.ts:140-150`
  doc): `ConfigManager.add_account` does NOT promote the first account to
  `[active]`; the promotion happens exactly ONCE, in the N1 `ConfigWrites.addAccount`
  ADAPTER transaction (`accounts.py:472-489` composes `_apply_add_account` +
  first-account `_apply_set_active` under one `_mutate()`). `test_config.py`'s
  non-promoting `add_account` asserts lock the manager layer; the namespace-level
  promotion is already locked by the B7 `accounts-namespace.test.ts` suites running
  over the (then-fake) `ConfigWrites` — they must pass UNCHANGED over the real one
  (§2.6 swap-in run).
- **Duplicate-name error class** (B7-ARB-B B-E2E-F1): `add_account` duplicate →
  PLAIN `ConfigError`/`CONFIG_ERROR` (`config.py:446`), never `AccountExistsError`
  (reserved for `login_unified`'s collision path, `accounts.py:1689`).
- **`apply_session` semantics** (`config.py:764-836`): all axes ONE transaction;
  `project` writes to explicit `account` else persisted active account, coded
  `ConfigError` when neither resolves; `workspace` XOR `clear_workspace`.
- **`apply_target`** (`config.py:951-1003`): `[active]` replaced wholesale + the
  target account's `default_project` updated, one transaction; unknown target OR
  deleted referenced account → `ConfigError`.
- **`_validate_workspace_id`** (`config.py:1044-1057`): runtime
  positive-integer check — TS: `Number.isInteger(w) && w > 0` (watchlist #6: never
  `!w`); this is a VALUE check, not a string parse — `pythonInt` does not apply
  here (contrast §7 caution 1).
- **Custom header** (`config.py:1004-1043`): `get_custom_header` returns the
  `[settings]` pair or `null`; feeds `ResolverConfigSource.getCustomHeader`.
- **Secrets in TOML** (CRED-F3): `_account_to_block` (:92-125) writes
  `secret.get_secret_value()` — the TS adapter calls `Secret.reveal()` at exactly
  this site; grep-audited at review (§6 pair-B lens). N1 adds the round-trip lock
  test: add SA account (Secret secret) + OT account (Secret token) → re-read via
  `getAccount` → revealed values equal the originals, and the on-disk TOML contains
  the REAL values, not `**********`.
- **Org-ordering fix** (§0.3.1): parse-order capture must survive BOTH entry paths
  into `MeResponse` — the wire parse (lossless layer) and the me.json cache
  re-hydration (N2's on-disk store re-parses through the same ordered path; N2
  consumes N1's mechanism — sequencing reason #2 for N1-first).

### §2.3 Layer-3 translation scope (N1) — per-file dispositions

| Python source (tests) | Disposition per class | TS test file |
|---|---|---|
| `tests/unit/test_io_utils.py` (803 lines, 48 tests) | TRANSLATE: `TestAtomicWriteBytes` :89, `TestAtomicWriteResilience` :210 (crash-window probes — induced failure between tmp-write and rename via injected `fs` fault or unwritable rename target; assert original intact + tmp cleaned), `TestCredentialPathError` :324 (re-expressed against the coded twin, header-cited), `TestReadCredentialBytes` :346, `TestReadCredentialText` :477, `TestRejectIfSymlink` :504, `TestSizeCap` :647, `TestReadCappedSecretFromStdin` :769 (injectable stream). **PYTHON-ONLY POSIX (plan §2.2 non-portable remainder + R9.2 drop; file-header exclusion with THIS cite)**: `TestOpenCredentialFdFlags` :546 (`O_CLOEXEC`/`O_NOFOLLOW` fd flags), `TestDirfdWalk` :674 (dirfd-walk hardening). SPLIT: `TestNonRegularFileRejection` :587 — translate the directory-as-path + stat-based refusal cases; FIFO/device-node cases Python-only (header-cited) | `packages/node/test/io-utils.test.ts` |
| `tests/unit/test_config.py` (821 lines, 51 tests) | TRANSLATE ALL 12 classes: `TestLoadEmptyOrMissing` :51, `TestAddAccount` :72 (incl. the NON-promoting asserts — B-E2E-N1 lock), `TestUpdateAccount` :199, `TestSetActive` :234, `TestApplySession` :299, `TestTargets` :373, `TestListAccounts` :475, `TestRemoveAccount` :526, `TestFixtureLoad` :625 (fixture TOML carried verbatim), `TestSettingsCustomHeader` :661, `TestMutateTransaction` :676, `TestSymlinkRejection` :780. tmp-dir `config_path` fixtures translate to `fs.mkdtempSync` dirs (NEVER `~/.mp` — §7 caution 3) | `packages/node/test/config.test.ts` |
| `tests/unit/test_settings_headers.py` (236 lines) | TRANSLATE: `TestSettingsHeaderAttachment` :52 (custom header from config reaches `_request_headers`) + `TestNoEnvMutation` :71 (env reads never mutate `process.env`). `TestBridgeHeaderAttachment` :97 → **N2** (bridge). `TestSessionHeadersOnOutboundRequests` :156 — translated at B0, NOT re-translated (playbook `:244-246`) | `packages/node/test/settings-headers.test.ts` |
| `tests/unit/test_042_edge_cases.py::TestConfigManagerEdgeCases` :459 (inbound `b7-packets.md` §7 / `b6-packets.md:1032`) | TRANSLATE against the real node ConfigManager | same file as config tests, cited section |
| NEW: org-ordering lock (§0.3.1) | out-of-ascending `/me` orgs → Python-order first pick; header cites `user-ratifications.md:14-22` | `packages/core/test/accounts/naming-order.test.ts` |
| NEW: CRED-F3 round-trip lock (§2.2) | SA secret + OT token write→read reveal equality + on-disk plaintext presence + no-mask assert | `packages/node/test/secret-roundtrip.test.ts` |

### §2.4 R10.10 consumers (signatures pasted)

- `ResolverConfigSource` (`packages/core/src/auth/resolver.ts`, B7 §2.2 —
  pasted): `getAccount(name): Account` (throws coded ConfigError on unknown) ·
  `getActive(): ActiveSession` · `getTarget(name): Target` (throws) ·
  `getCustomHeader(): readonly [string, string] | null`. N1's
  `createNodeConfigSource(options?: {configPath?: string})` returns
  `ResolverConfigSource & ConfigWrites`.
- `ConfigWrites` (`auth-effects.ts:152-…`, pasted members): `addAccount(name,
  AddAccountParams)` · `updateAccount(name, UpdateAccountFields)` ·
  `removeAccount(name, {force?}) : string[]` · `listAccounts(): AccountSummary[]` ·
  `setActive(SetActiveUpdate)` · `applySession(ApplySessionUpdate)` ·
  `applyTarget(name)` · `addTarget(name, AddTargetOptions): Target` ·
  `removeTarget(name)` · `listTargets(): Target[]`.
- `env: ResolverEnv & { get(name: string): string | undefined }`
  (`auth-effects.ts` AuthEffects.env).
- `WorkspaceOptions.readFile: (path: string) => Promise<Uint8Array>`
  (`workspace.ts:1155`, default throws `UNPORTED_FILE_READ_SEAM`).
- Downstream shards: N2 imports `atomic_write_bytes`/`reject_if_symlink`/
  credential-read twins BY NAME (R10.8 — re-implementation is a per-se finding);
  N3's bag assembly consumes `createNodeConfigSource` + `createNodeEnv`.
- `AuthEffects.readSecretStdin` (`auth-effects.ts:405-…`, `readSecretStdin` member) ← `io-utils.ts`
  stdin twin.

### §2.5 R10.9 harness spec — `throwaway/b8-n1/`

No oracle surface (auth posture, playbook Risk 7) — edge set + exhaustive local
branch enumeration + fast-check vs mini-models, ≥500 examples per surface
(P2-9 budget), seeds + counts + zero-divergence table → RUN record in
`context/phase3/notes/B8-N1-notes.md`. Mandatory rows:

1. **Atomic-write crash-window probes**: fault injection at each step (tmp create
   fails EEXIST; fchmod fails; write fails mid-loop; rename fails) → original file
   byte-identical, tmp absent (except the EEXIST case where the PRE-EXISTING tmp
   survives — Python leaves it, port verbatim: only OUR tmp is cleaned), error
   propagated. Post-success: content equal, mode 0o600 (and 0o400 when requested).
2. **0600 assertion**: stat mode after every write path (config, and via N2 reuse
   later); `mode & 0o077` guard rows (0o644, 0o640, 0o601 → coded error).
3. **Symlink refusal**: symlinked target file, symlinked PARENT dir cases as
   Python covers them, dangling symlink; both read and write entry points.
4. **ConfigManager**: every error branch enumerated from the ranges in §2.1
   (unknown account/target, duplicate add, remove-active/force, apply_session
   no-account, workspace XOR clear_workspace, invalid workspace id 0/-1/1.5/2^53,
   malformed TOML file → coded parse error, non-dict top level, unknown account
   type in block); fast-check ≥500 op-sequences vs an in-memory model
   (add/update/remove/set_active/apply_target invariants: active always references
   an existing account or is absent; target list sorted; transaction atomicity —
   a failing op leaves the file byte-identical).
5. **Edge set** (`18.0`, `1.5`, `true`, `null`, `[]`, `""`, `"𝒳"`) through every
   annotation-admitting param (account names, project strings, header values,
   TOML string round-trip of `"𝒳"` + NFC/NFD distinct strings preserved verbatim).
6. **Org-ordering**: fast-check over org-map key orders (integer-like +
   non-integer-like mixes) → first-pick equals mini-model insertion-order pick
   (the exclusion REMOVED per the ratification — this row is the proof).

### §2.6 Done-criteria (N1)

Files on disk (`io-utils.ts`, `config.ts`, `config-writes.ts`, `env.ts`,
`fs-seams.ts`, core §0.3.1 edits, tests §2.3) + `tsc --strict` clean +
translated Layer-3 green + **the B7 fake-backed suites still green with the real
`ConfigWrites` swapped in** (one representative run recorded in notes:
`accounts-namespace.test.ts` over `createNodeConfigSource` in a tmp dir) + harness
RUN record + JSDoc complete + lint boundary green (core untouched by node imports;
the two core-touch files import nothing new from `node:*`) + `npm run check` green +
one local TS commit; notes committed in the Python repo. NO vectors (0 owned).

---

## §3 Packet B8-N2 — storage + refresh flow + OnDiskTokenResolver + bridge + MeCache (fable; after N1; owns the 7 vectors)

### §3.1 Modules, Python line ranges at HEAD, TS homes

| Python source (range @ HEAD) | What | TS home |
|---|---|---|
| `_internal/auth/storage.py:1-635` (whole file) | `_storage_root` :53-76 (`MP_OAUTH_STORAGE_DIR` else `~/.mp`) · `accounts_root` :77-90 · `account_dir` :91-115 (name validation) · `ensure_account_dir` :116-142 (0o700) · `_fchmod_no_follow` :143-192 · `OAuthStorage` :193-635 (`_default_storage_dir` :213-224 (`~/.mp/oauth/`) · `__init__`/`storage_dir` :225-253 · `_validate_region` :254-276 · `_ensure_dir` :277-288 · `_check_and_fix_permissions` :289-365 · `_write_file` :366-381 · `_read_file` :382-428 · `_tokens_path` :429-439 (`tokens_{region}.json`) · `_client_path` :440-450 (`client_{region}.json` — THE DCR persistence path) · `save_tokens` :451-478 · `load_tokens` :479-525 · `save_client_info` :526-543 · `load_client_info` :544-574 · `delete_tokens` :575-593 · `delete_all` :594-611 · `clear_me_cache` :612-635) | `packages/node/src/auth/storage.ts` |
| `_internal/auth/flow.py` REFRESH HALF: module ctor + region validation :118-179 · `get_valid_token` :180-226 · `refresh_tokens` :442-499 · `_post_token_request` :500-605 (+ `OAUTH_BASE_URLS` re-export home — the constant lives in `client_registration.py:39-44`; N2 ports the CONSTANT into `packages/node/src/auth/oauth-constants.ts` so N2 does not depend on N3's module; N3 imports it from there) | `packages/node/src/auth/flow.ts` (created here; N3 extends) + `oauth-constants.ts` |
| `_internal/auth/token_resolver.py:1-288` (whole file) | `_account_tokens_path` :40-56 · `OnDiskTokenResolver` :57-288 (`get_browser_token` :74-173 · `_refresh_and_persist` :174-243 (refresh-token ROTATION KEEP :236-241; atomic rewrite via `token_payload_bytes`) · `get_static_token` :244-288) | `packages/node/src/auth/token-resolver.ts` |
| `_internal/auth/bridge.py:1-409` (whole file) | `BridgeFile` v2 model :61-118 (`version: Literal[2]`, `account` union with secrets inline, `tokens` required iff `oauth_browser` :104-117, `project` `^\d+$`, `workspace` PositiveInt, `headers` map) · `default_bridge_search_paths` :119-136 (`~/.claude/mixpanel/auth.json`, `./mixpanel_auth.json`; `MP_AUTH_FILE` consulted BEFORE defaults by callers) · `load_bridge` :137-196 · `_read_browser_tokens` :197-277 (symlink probe BEFORE existence, :219) · `_serialize_bridge` :278-313 (**reveal() site — CRED-F3**) · `export_bridge` :314-371 (0o600 atomic) · `remove_bridge` :372-409 | `packages/node/src/auth/bridge.ts` |
| `_internal/me.py:413-607` (MeCache half ONLY — models/`select_workspace_id`/`MeService` already core) | `MeCache` (`~/.mp/accounts/{name}/me.json`, dir 0o700 + PII chmod-failure raise, file 0o600, TTL default 86400, `cached_at` stamping, `get` :470-545 with expiry + corrupt-file handling, `put` :546-596, `invalidate` :597-607) | `packages/node/src/me-cache.ts` (implements core `MeCacheStore`, `services/me.ts:41-66`) |
| `TokenStore` real impl (`auth-effects.ts:305-362`) | `readTokens`/`writeTokens` (returns path)/`removeTokens`/`removeAccountDir` (`_safe_rmtree_warn` twin, `accounts.py:278-303` — warn, never raise)/`clientInfoPath` (`_client_info_path`, `accounts.py:894-915`)/`accountDirExists` (**`account_dir(name).exists()` — the B7-ARB-A SEM-F2 seam, `b7-reviewA-resolution.md:239-241`**) | `packages/node/src/auth/token-store.ts` |
| core touch §0.3.2 | `token.ts` `expires_at` Python-isoformat rendering + injectable `now` | `packages/core/src/auth/token.ts` |

### §3.2 Behavior locks — refresh path (the vector-locked heart of the batch)

Each line = a review-pair assertion; source re-read mandatory:

1. **Request shape** (`flow.py:442-499`, `:500-540`): POST
   `{OAUTH_BASE_URLS[region]}token/` — string concatenation (R2.13), recorded
   `scheme_host: "https://mixpanel.com"`, `path: "/oauth/token/"`. Body is
   form-encoded IN INSERTION ORDER:
   `grant_type=refresh_token&refresh_token=<reveal>&client_id=<id>` — vector
   `test_refresh_posts_correct_params` locks the EXACT `body_text`; TS uses
   `URLSearchParams` appended in the Python dict order (grant_type,
   refresh_token, client_id); header `content-type:
   application/x-www-form-urlencoded` (vector `headers_contain`).
2. **No refresh token** (`flow.py:476-487`): `refresh_token === null` →
   `OAuthError` `OAUTH_REFRESH_ERROR` BEFORE any request; `details` =
   `{account_name}` when supplied else `{}` — two shapes, port verbatim.
3. **Transport failure** (`flow.py:535-540`): fetch failure (normalized
   `MixpanelHttpError` via the R2.10 adapter path) → `OAuthError` with the
   OPERATION's `error_code` and `details: {url: tokenUrl}` — vector
   `test_refresh_tokens_timeout` locks `details_contain.url:
   "https://mixpanel.com/oauth/token/"` on a `transport_error` interaction.
4. **Non-200 classification** (`flow.py:542-585`): `invalid_grant` probe runs
   ONLY for status 400/401 (:547-556) — body parsed via `parseLossless`
   (GATE-R5: never `response.json()`), guard `isPlainRecord` (watchlist #13
   canonical helper, §7 caution 8) and `payload.error === "invalid_grant"`;
   parse failure → `invalid_grant = false`. The REVOKED mapping additionally
   requires `operation === "Token refresh"` (:557; exchange keeps the generic
   code). Revoked (:557-575) → `OAUTH_REFRESH_REVOKED`, details ALWAYS carry
   `{status_code, response_body: <raw text>, account_name}` — `account_name`
   present-and-null when not supplied (vector
   `test_raises_revoked_if_refresh_fails_invalid_grant` locks
   `account_name: null`; `test_refresh_invalid_grant_raises_revoked` locks
   `"personal"`). Generic non-200 → operation `error_code`, details
   `{status_code, response_body}` + `account_name` ONLY when supplied (spread
   shape, `flow.py:583-589`) — vector
   `test_refresh_transient_5xx_raises_generic_error` (503, body
   `"Service Unavailable"`); generic raise + spread at :576-585.
5. **200 parse** (`flow.py:586-605`): non-JSON body → `OAuthError`
   (`error_code`) with `details: {response_body}` and the content-type in the
   message (out of contract); `OAuthTokens.fromTokenResponse(data, {now})`
   failure → `OAuthError` with `details: {response_data: pythonStr(data)}`.
6. **`expires_at` computation + rendering** (§0.3.2): `now() + expires_in *
   1000` ms → Python-isoformat text. Vectors lock
   `"2026-01-15T13:00:00+00:00"` from `expires_in: 3600` under
   `now: () => recordEpoch` (`2026-01-15T12:00:00Z`, D1.4).
7. **`get_valid_token`** (`flow.py:180-226`): load tokens (storage) → none →
   `OAUTH_TOKEN_ERROR`; not expired (30s buffer over injected now) → reveal
   access token; expired → `load_client_info` → none → `OAUTH_REFRESH_ERROR`;
   refresh → `save_tokens` (the LEGACY v2 region path
   `~/.mp/oauth/tokens_{region}.json`, `storage.py:429-478`) → reveal. NOTE the
   two persistence worlds: `get_valid_token` persists via `OAuthStorage` v2
   paths; `OnDiskTokenResolver` persists via the per-account
   `tokens.json` (`token_resolver.py:40-56`). Both port verbatim — do not
   unify (they are different callers' contracts).
8. **`OnDiskTokenResolver`** (`token_resolver.py:74-288`): browser path —
   symlink-refuse + read per-account tokens; malformed JSON / model-invalid →
   coded `OAuthError` branches exactly as source; not-expired short-circuit;
   expired + no refresh token → `OAUTH_REFRESH_ERROR` (:78-91); refresh via
   `OAuthFlow.refresh_tokens(tokens, client_id, account_name=name)` with client
   info from the SHARED per-region DCR store (`OAuthStorage.load_client_info`;
   missing → `OAUTH_REFRESH_ERROR` :213-227); **rotation keep** :236-241 (IdP
   returns no refresh token → keep the old one via copy); atomic rewrite
   `token_payload_bytes` 0o600; return bare token (no `Bearer` prefix). Static
   path (:244-288): inline token wins; `token_env` unset/empty → coded error
   (`if not bearer` — R11.7 falsiness on strings, empty = absent). TS
   `OnDiskTokenResolver` implements the core `TokenResolver` interface
   (`auth/account.ts:74-91`: `getBrowserToken(name, region): Promise<string>`,
   `getStaticToken(account): Promise<string>`) — async where Python is sync;
   R2.9 per-request resolution semantics already enforced by core call sites.
9. **Bridge** (`bridge.py`): load resolution order explicit `path` >
   `MP_AUTH_FILE` > `default_bridge_search_paths()` (:119-196); symlink probe
   before existence at EVERY read (:219 pattern); v2 schema validation errors →
   coded errors as source (unknown version, extra fields — `extra="forbid"`);
   `export_bridge` embeds the full Account WITH secrets (reveal at
   `_serialize_bridge` :278-313 ONLY — CRED-F3) + `oauth_browser` requires
   tokens read from the per-account path (`_read_browser_tokens` :197-277, no
   refresh attempt — snapshot semantics); write atomic 0o600; `remove_bridge`
   (:372-409) explicit-path vs default-chain, returns whether a file was
   deleted. Implements `BridgeEffects` (`auth-effects.ts:259-303`) AND
   `BridgeView` production for `ResolverSources.bridge` (headers map, project,
   workspace, account).
10. **MeCache** (`me.py:413-607`): dir 0o700 with the PII chmod-failure RAISE
    (`put` :563-575, `ConfigError` at :569 — a filesystem that cannot restrict
    perms must not hold the cache; port the raise, not a warn); file 0o600
    atomic; TTL expiry in
    `get` (injected now); corrupt/missing file → `null` (never throw on read);
    `cached_at`/`cached_region` stamping; `invalidate` missing-file no-op.
    Implements core `MeCacheStore` + `MeCacheEffects.put`
    (`_persist_me_cache`, `accounts.py:1338-1356`). Re-hydration parses
    through N1's ordered-organizations path (§2.2 last bullet).
11. **OAuthStorage hardening** (`storage.py:289-365`): permission
    check-and-fix on read (chmod to 0o600 with warning) — port the observable
    behavior (fix + warn via injected logger seam per R9.5, never `console`);
    `_validate_region` (:254-276) rejects non-`us|eu|in` with the coded error;
    path traversal refusals per `account_dir` name validation (:91-115) —
    `test_storage.py::TestAccountDirNameValidation` + `test_auth_storage.py::
    TestOAuthStoragePathTraversal` are the locks.

### §3.3 Layer-3 translation scope (N2) — per-file dispositions

| Python source | Disposition | TS test file |
|---|---|---|
| `tests/unit/test_auth_storage.py` (855 lines, 48 tests) | TRANSLATE all 12 classes: `TestOAuthStorageSecurityHardening` :87 (the lstat/stat-expressible subset; any `O_*`-flag-specific assert → Python-only, header-cited per §2.1 drop), `TestOAuthStorageTokenRoundTrip` :196, `TestOAuthStorageClientInfoRoundTrip` :249, `TestOAuthStorageFilePermissions` :285, `TestOAuthStorageEnvOverride` :335 (`MP_OAUTH_STORAGE_DIR` call-time), `TestOAuthStorageRegionNaming` :377, `TestOAuthStorageMissingFile` :424, `TestOAuthStorageDelete` :453, `TestOAuthStorageCorruptedFiles` :513, `TestOAuthStoragePathTraversal` :609, `TestOAuthStorageUnicode` :700, `TestOAuthStorageConcurrency` :748 (threads → concurrent async writers over the pid+counter tmp scheme) | `packages/node/test/auth-storage.test.ts` |
| `tests/unit/test_storage.py` (327 lines, 15 tests) | TRANSLATE all 5 classes: `TestAccountDirNameValidation` :26, `TestStorageRoot` :76, `TestAccountDirHonorsStorageRoot` :107, `TestEnsureAccountDir` :126, `TestOAuthStorageSymlinkRejection` :158 | `packages/node/test/storage-paths.test.ts` |
| `tests/unit/test_token_resolver.py` (560 lines, 18 tests) | TRANSLATE all 6 classes: `TestStaticToken` :79, `TestBrowserToken` :123, `TestBrowserTokenRefresh` :214, `TestPathLayout` :368, `TestConcurrentRefresh` :390, `TestSymlinkRejection` :509 | `packages/node/test/token-resolver.test.ts` |
| `tests/unit/test_bridge_export.py` (395 lines, 19 tests) | TRANSLATE all 4 classes: `TestExportBridgeFunctional` :72, `TestRemoveBridgeFunctional` :210, `TestAccountsNamespaceWiring` :236 (over the REAL node namespaces once N3 lands the bag — N2 translates against `BridgeEffects` directly and N3's swap-in run re-covers the wiring; header-cite the split), `TestBridgeSymlinkRejection` :303 | `packages/node/test/bridge.test.ts` |
| `tests/unit/test_auth_flow.py` REFRESH classes | TRANSLATE: `TestOAuthFlowRefresh` :490, `TestOAuthFlowGetValidToken` :610, `TestOAuthFlowNetworkErrors` :802 (refresh/timeout members; exchange-op members → N3), `TestOAuthFlowRegionValidation` :984 (constructor — lands with the N2 class skeleton) | `packages/node/test/oauth-flow-refresh.test.ts` |
| `tests/unit/test_me.py` MeCache classes | TRANSLATE: `TestMeCache` :228, `TestMeCacheConcurrency` :331, `TestMeCacheSymlinkRejection` :685. Models :38-227 → done (`core/test/client/me.test.ts`); `TestMeService` :458 → done (`core/test/services/me-service.test.ts`) — NOT re-translated | `packages/node/test/me-cache.test.ts` |
| `tests/unit/test_settings_headers.py::TestBridgeHeaderAttachment` :97 | TRANSLATE (bridge headers reach `_request_headers` through `BridgeView.headers`) | `packages/node/test/settings-headers.test.ts` (extends N1's file) |
| `tests/unit/test_workspace_init.py::TestBridgeTokenMaterialization` :167 (inbound, `b7-packets.md` §7) | TRANSLATE — Workspace built over node effects with a bridge-sourced oauth_browser account materializes the bearer through the REAL resolver chain | extend `packages/core/test/workspace/workspace-init.test.ts` (drop its B8 deferral-header row — the header must end with ZERO deferrals) |
| `tests/unit/test_042_edge_cases.py::{TestTokenResolverMalformed :240, TestBridgeEdgeCases :394}` (inbound) | TRANSLATE against the real `OnDiskTokenResolver` / bridge | `token-resolver.test.ts` / `bridge.test.ts`, cited sections |
| `test_042_edge_cases.py::test_session_to_credentials_oauth_browser_missing_tokens_raises` :655 (named re-take, B7-ARB-A ASR-F4c) | RE-TAKE with the real `OnDiskTokenResolver` (the B7 translation ran over the injected fake; header cites ASR-F4c) | `token-resolver.test.ts` |

### §3.4 Binding plan (inline, fable — P3-2 b′; closes the corpus)

- **Registry name**: `oauth_flow.refresh_tokens` — Python recorder entry
  `conformance/record/registry.py:569-574` (`KIND_WIRE_API`, capability `auth`,
  target `flow:OAuthFlow.refresh_tokens`). Per the registry doc (:555-563),
  `login`/`exchange_code` are layer3_deferred (design D2 item 3 — interactive
  PKCE stays Layer-3/4) and `get_valid_token` is a convenience over refresh —
  refresh_tokens is THE registered surface and the ONLY B8 corpus api.
- **TS home**: extend `conformance-runner/src/wire-auth.ts` (created at B7-A2).
  **The runner executes in a node context, so the node package is directly
  importable by the rig** — the binding imports the REAL
  `packages/node/src/auth/flow.ts` `OAuthFlow` exactly as wire bindings import
  core (relative path, `wire-auth.ts:21` precedent). Rig code = fable —
  satisfied (module task is fable).
- **Construction**: `new OAuthFlow({region: "us", fetchImpl:
  context.harness.fetch, now: () => RECORD_EPOCH_MS, storage: <in-memory or
  tmp-dir stub — NOT consulted by refresh_tokens, which takes tokens/client_id
  as arguments>})`. No sleep/random seams exist in the refresh path. The
  recorded scheme_host is `https://mixpanel.com` = `OAUTH_BASE_URLS.us` — no
  base-URL override needed; `VectorFetch` keys interactions by scheme_host+path.
- **Input mapping**: `tokens` decodes via the existing `$type: "OAuthTokens"`
  codec (`types/vector-codecs.ts:184-…` → `parseOAuthTokens`); `client_id` /
  `account_name` map per the standard `naming.ts` snake→camel rules; absent
  `account_name` → omit (library default).
- **Result encoding**: return the real `OAuthTokens`; the codec sweep encodes
  `$type: OAuthTokens` with `expires_at` as `$type: datetime` carrying the
  library's rendered ISO TEXT — the §0.3.2 rendering fix is what makes the
  recorded `+00:00` text match byte-for-byte.
- **Error path**: throw the real `OAuthError`; runner encodes
  `{class, code, details_contain}` — the four error vectors' `details_contain`
  bags (§3.2 items 3–4) must be subset-satisfied by the real details.
- **Binding honesty (P3-5 rule 3)**: the binding calls the REAL exported
  `refreshTokens` — it never POSTs itself, never classifies statuses, never
  builds form bodies. Arbiter checks explicitly.
- **NO batch-status flip in the module commit** — vectors replay green while
  `oauth_flow.` is `pending` (the designed bound-while-pending pattern); the
  flip is the gate's (§5).

**The 7 vector ids** (bundle `auth/test_auth_flow.jsonl`, prefix
`auth/oauth_flow.refresh_tokens/test_auth_flow-`):

```
testoauthflowgetvalidtoken-test_auto_refreshes_expired_token
testoauthflowgetvalidtoken-test_persists_refreshed_tokens
testoauthflowgetvalidtoken-test_raises_revoked_if_refresh_fails_invalid_grant
testoauthflownetworkerrors-test_refresh_tokens_timeout
testoauthflowrefresh-test_refresh_invalid_grant_raises_revoked
testoauthflowrefresh-test_refresh_posts_correct_params
testoauthflowrefresh-test_refresh_transient_5xx_raises_generic_error
```

(3 result vectors + 4 error vectors; the `getvalidtoken`-named ones were
recorded through the wrapped refresh call inside `get_valid_token` tests —
the binding still drives `refreshTokens` directly with the recorded inputs.)

### §3.5 R10.10 consumers (signatures pasted)

- Core `TokenResolver` (`auth/account.ts:74-91`):
  `getBrowserToken(name: string, region: Region): Promise<string>` ·
  `getStaticToken(account: OAuthTokenAccount): Promise<string>` — consumed
  per-request by `sessionAuthHeader` (`auth/session.ts:378`, R2.9).
- Core `MeCacheStore` (`services/me.ts:41-66`): `accountName` ·
  `get(): MeResponse | null | Promise<…>` · `put(response): void | Promise<void>` ·
  `invalidate(): void | Promise<void>`.
- `TokenStore` (`auth-effects.ts:305-362`, pasted): `readTokens(name):
  OAuthTokens | null` · `writeTokens(name, tokens): string` ·
  `removeTokens(name)` · `removeAccountDir(name)` · `clientInfoPath(region):
  string` · `accountDirExists(name): boolean`.
- `BridgeEffects` (`auth-effects.ts:259-303`): `load(): BridgeView | null` ·
  `export({account, to, project, workspace, headers, tokenResolver}): string |
  Promise<string>` · `remove(at: string | null): boolean`.
- `BridgeView` (`resolver.ts`, B7 §2.2): `{account, project, workspace,
  headers}` — the resolver's bridge rung reads THIS view.
- N3 consumes `OAuthStorage` (DCR client persistence + login token writes) and
  `oauth-constants.ts` BY NAME.

### §3.6 R10.9 harness spec — `throwaway/b8-n2/`

1. **Refresh-token exact-body probe**: byte-diff the form body across the edge
   set in token values (URL-encodable chars, `"𝒳"`, `+`/space/`&`/`=`
   characters — URLSearchParams vs Python urlencode MUST agree; any divergence
   is a finding, not a disclosure), plus every §3.2 branch: no-refresh-token,
   transport error, 400/401 invalid_grant (refresh AND exchange-op control),
   400/401 non-invalid_grant, 400 unparseable body, 403/404/500/503, 200
   non-JSON, 200 missing-field matrix (each required key), rotation-keep
   (response without refresh_token), `expires_at` rendering table (whole
   seconds; fractional `expires_in` if annotation admits — it is `int`-typed,
   so fractional goes through `coerceInt` rejection verbatim).
2. **0600 + symlink + atomicity** on EVERY N2 write path (save_tokens,
   save_client_info, per-account tokens.json rewrite, bridge export, me.json)
   and refusal on every read path (each file symlinked, parent symlinked,
   dangling).
3. **`get_valid_token` truth table**: {no tokens, fresh, expired+no-client,
   expired+refresh-ok, expired+refresh-revoked, expired+refresh-transient} ×
   the 30s-buffer boundary (now = expiry−31s/−30s/−29s).
4. **OnDiskTokenResolver sweep**: static (inline / env set / env empty / env
   unset / wrong account type), browser (missing file, malformed JSON, model-
   invalid, fresh, expired→refresh→rotation-keep→persisted-bytes check,
   concurrent refreshers over the atomic scheme).
5. **Bridge v2 round-trip**: export → load → deep-equal INCLUDING revealed
   secrets for all three account types; oauth_browser without on-disk tokens →
   coded error; v1/unknown-version/extra-key/naive-datetime payloads → coded
   refusals; `MP_AUTH_FILE` precedence rows; remove default-chain vs explicit.
6. **MeCache**: TTL boundary (now = cached_at+ttl±1), corrupt file, chmod-
   failure raise (simulated via injected chmod fault), ordered-organizations
   re-hydration (consumes §2.5 row 6's mechanism).
7. **Secret-redaction sweep** (pair-B feed): sentinel secrets through every
   error branch above — sentinel appears in NO thrown message, NO details JSON,
   NO RUN-record line; on-disk appearances ONLY at the designated reveal sites
   (tokens.json, client info, bridge file, TOML — enumerate each in the notes;
   the allowlist is the CRED-F3 header list, `auth-effects.ts:15-27`).
8. fast-check ≥500/surface vs mini-models (refresh classifier, storage path
   layout, bridge resolution order, TTL); seeds + counts + zero-divergence →
   `context/phase3/notes/B8-N2-notes.md`.

### §3.7 Done-criteria (N2)

Files on disk (§3.1 homes + `wire-auth.ts` extension + tests §3.3) +
`tsc --strict` clean + translated Layer-3 green (incl. the de-deferred
`workspace-init` class; header rows zeroed) + **all 7 vectors PASS** via
`npm run conformance` (report: 3,244 PASS + 7 passing-while-pending, 0 FAIL) +
`token.ts` TODO(port) marker REMOVED (closed, not re-scoped) + harness RUN
record + CRED-F3 reveal-site enumeration in notes + JSDoc + `npm run check`
green + one local TS commit; notes committed in the Python repo.

---

## §4 Packet B8-N3 — PKCE + DCR + callback server + interactive login + node effects-bag assembly (fable; after N2)

### §4.1 Modules, Python line ranges at HEAD, TS homes

| Python source (range @ HEAD) | What | TS home |
|---|---|---|
| `_internal/auth/pkce.py:1-73` (whole file) | `PkceChallenge` :26-46 · `generate` :47-73 (RFC 7636: 32-byte urlsafe verifier, S256 challenge = base64url(sha256(verifier)) unpadded) | `packages/node/src/auth/pkce.ts` (`node:crypto` — sync `createHash`, matching Python's sync `generate()`; B9 builds its OWN WebCrypto async twin — do not pre-abstract) |
| `_internal/auth/client_registration.py:1-170` (whole file) | `OAUTH_BASE_URLS` :39-44 (**constant HOME moved to N2's `oauth-constants.ts` — N3 imports, §3.1**) · `_DEFAULT_SCOPE` :46-52 · `ensure_client_registered` :54-170 (region validate; cached-client fast path via `OAuthStorage.load_client_info`; RFC 7591 DCR POST; persist via `save_client_info` → `~/.mp/oauth/client_{region}.json` 0o600 — THE DCR persistence duty) | `packages/node/src/auth/client-registration.ts` |
| `_internal/auth/callback_server.py:1-299` (whole file) | `CALLBACK_PORTS` :32 (`[19284, 19285, 19286, 19287]`) · `_SUCCESS_HTML`/`_ERROR_HTML` :34-52 · `CallbackResult` :55-78 · `start_callback_server` :79-179 (bind loop over the ports, :133-146 — all busy → `OAuthError` `details: {ports}`) · `_create_server` :180-195 · `_CallbackHandler.do_GET` :196-276 (query parse, state mismatch, error param, missing code; HTML responses) · `_send_html` :277-290 · `log_message` suppression :291-299 | `packages/node/src/auth/callback-server.ts` (`node:http`) |
| `_internal/auth/flow.py` LOGIN HALF: `_parse_pasted_redirect` :51-117 · `login` :227-394 (PKCE + state, port probe, DCR, authorize URL, the two racing completers — callback server + stdin paste reader when `open_browser=False`, exchange, optional persist) · `exchange_code` :395-441 · `_build_authorize_url` :606-637 (urlencode param order locked) · `_find_available_port` :638-654 (bind-and-release probe on 127.0.0.1, in port order) | extend `packages/node/src/auth/flow.ts` (N2's file) |
| Effects-bag assembly (no Python twin — the B7 outbound wiring rows) | `createNodeAuthEffects(options?): AuthEffects` composing N1+N2+N3 members; `persistActive(session)` = the `ConfigManager.apply_session` twin routing (`workspace.py:696-722` semantics via N1's `applySession`); `narrate` = `process.stderr.write(msg + "\n")`; `readSecretStdin` = N1's io-utils twin; ready-made `accounts` / `session` / `targets` namespace exports + `login_unified` (core factories `createAccountsNamespace(effects)` etc. over the real bag) + default `ResolverSources` (env + config + `bridge.load()`) — closes the four Phase-2 `__all__` deferrals at node level | `packages/node/src/auth-effects.ts`, `packages/node/src/index.ts` |

### §4.2 Behavior locks (branch-level)

- **PKCE** (`pkce.py:47-73`): verifier = `secrets.token_urlsafe(32)` twin
  (`crypto.randomBytes(32)` → base64url unpadded); challenge =
  base64url(sha256(ascii(verifier))) with `=` stripped; method `S256`. RFC 7636
  Appendix-B test vector locked in Layer-3 (runtime-independent).
- **DCR** (`client_registration.py:54-170`): cached client short-circuits (NO
  network — assert zero fetches); registration POST body/headers verbatim from
  source (re-read at HEAD); non-2xx / malformed responses → coded `OAuthError`
  branches as source; success persists BEFORE returning (crash between
  register and persist re-registers next time — port, don't "improve");
  `redirect_uri` threaded from the caller's bound port.
- **Callback server** (`callback_server.py`): port loop IN ORDER 19284→19287;
  each bind failure falls through; all busy → `OAuthError` with
  `details: {ports: CALLBACK_PORTS}`. `do_GET`: non-`/callback` paths,
  state mismatch (CSRF), `error=` param, missing `code` — each returns the
  ERROR HTML with the source's status and NEVER resolves the result; success
  returns `_SUCCESS_HTML` and resolves `{code, state}`.
  **HTML escaping** (`TestCallbackHtmlSecurity` :281): the `{message}`
  interpolation into `_ERROR_HTML` must escape as Python does — re-read the
  source's escaping mechanism at HEAD and port exactly (XSS surface; pair-B
  lens item).
- **`_find_available_port`** (`flow.py:638-654`): bind-AND-RELEASE probe on
  `127.0.0.1` per port, first success returned, `None` when none — then
  `login` raises `OAUTH_PORT_ERROR` (`flow.py:274-277`). Keep the two-phase
  probe-then-bind shape verbatim (TOCTOU window is Python's too — R10.7).
- **`_parse_pasted_redirect`** (`flow.py:51-117`): full URL / bare query /
  `code=`-fragment tolerance, state check, error param — every branch; pure
  function, translate its whole test class.
- **`login` orchestration** (`flow.py:227-394`): step order locked (PKCE →
  port → DCR → authorize URL → completers race → exchange → optional
  persist); `open_browser=False` prints the URL to stderr (narrate seam) and
  ADDS the stdin paste completer — the callback server listens EITHER WAY;
  browser opening is an injected `openBrowser(url)` effect (no `child_process`
  `open` at module scope). `persist=False` default semantics: tokens returned
  in memory; the ONLY persist=True writer is the legacy v2 path
  (`storage.save_tokens`). `OAuthFlowEffects.login(region, {openBrowser})`
  (`auth-effects.ts:369-388`) is implemented over this with
  `persist: false` ALWAYS (the orchestrator persists via
  `TokenStore.writeTokens` — B7 contract).
- **Bag assembly**: `defaultNodeAuthEffects` members must satisfy every
  `UNPORTED_AUTH_SEAMS` name (§4.4 checklist) — after N3, calling ANY member of
  the node bag never throws `UNPORTED_AUTH_SEAM`, and a `Workspace` built with
  `resolverSeamsFromEffects(createNodeAuthEffects())` in a tmp-dir HOME passes
  the B7-deferred persistence tests (`test_workspace_use.py::TestPersist`
  twins).

### §4.3 Layer-3 translation scope (N3)

| Python source | Disposition | TS test file |
|---|---|---|
| `tests/unit/test_auth_pkce.py` (141 lines, 9 tests) | TRANSLATE `TestPkceChallenge` :25 whole (incl. RFC vectors; B9 re-uses the RFC rows against WebCrypto later — playbook `:254-256`; no conflict, different package) | `packages/node/test/pkce.test.ts` |
| `tests/unit/test_auth_registration.py` (461 lines, 13 tests) | TRANSLATE all 3 classes: `TestEnsureClientRegistered` :68, `TestEnsureClientRegisteredRobustness` :371, `TestEnsureClientRegisteredRegionValidation` :441 | `packages/node/test/client-registration.test.ts` |
| `tests/unit/test_auth_callback.py` (341 lines, 12 tests) | TRANSLATE all 3 classes: `TestCallbackResult` :33, `TestStartCallbackServer` :49 (real 127.0.0.1 binds on the fixed ports, exactly as Python does — port-conflict cases occupy 19284 first and assert fallback), `TestCallbackHtmlSecurity` :281 | `packages/node/test/callback-server.test.ts` |
| `tests/unit/test_auth_flow.py` LOGIN classes | TRANSLATE: `TestOAuthFlowLogin` :88, `TestParsePastedRedirect` :215, `TestOAuthFlowPasteFallback` :286, `TestOAuthFlowTokenExchange` :385, `TestOAuthFlowRegionUrls` :759, + the exchange-op members of `TestOAuthFlowNetworkErrors` :802 (refresh members were N2's, header-cite the split) | `packages/node/test/oauth-flow-login.test.ts` |
| Bag swap-in runs | The B7 fake-backed namespace suites re-run over `createNodeAuthEffects()` with tmp-dir storage (representative subset, recorded in notes — full duplication not required; the suites remain fake-backed as their primary form) | notes record only |

### §4.4 Seam-closure checklist (the whole point of B8 — every name accounted)

`UNPORTED_AUTH_SEAMS` (`auth-effects.ts:477-487`, committed constant) + the
adjacent named stubs — owner map, NONE may remain stubbed after B8:

| Seam name | Real node implementation | Owner |
|---|---|---|
| `config.*` (ResolverConfigSource & ConfigWrites, on-disk TOML) | `createNodeConfigSource` | **N1** |
| `env` (process.env wiring incl. `get`) | `createNodeEnv` | **N1** |
| `readSecretStdin` | io-utils stdin twin | **N1** |
| `UNPORTED_FILE_READ_SEAM` (`WorkspaceOptions.readFile`, W7-D1 — B6 outbound row; not in the auth constant but same duty) | `nodeReadFile` | **N1** |
| `tokenStore.*` (incl. `accountDirExists` — B7-ARB-A SEM-F2, `writeTokens`-returns-path, `clientInfoPath`, `removeTokens`) | `token-store.ts` | **N2** |
| `tokenResolver` (on-disk twin) | `OnDiskTokenResolver` | **N2** |
| `bridge.*` (load/export/remove) | `bridge.ts` | **N2** |
| `meCache` (on-disk MeCacheStore + effects.put) | `me-cache.ts` | **N2** |
| `oauthFlow.login` (PKCE dance) | `flow.ts` login half via `OAuthFlowEffects` | **N3** |
| `persistActive` (via `config.applySession` — routing shipped by B7 `resolver-seams.ts`) | bag member over N1's `applySession` | **N3** (impl dep: N1) |
| (`narrate` — NOT in the constant; core default is silent no-op) | `process.stderr` write | **N3** |
| `UNPORTED_RESOLVER_SEAM` residue (exactly one after B7: `persistActive` routing when B8 absent, `lifecycle.ts:111-143`) | closed by the same bag member | **N3** |

N3's done-criteria include a mechanical sweep: instantiate
`createNodeAuthEffects()` and invoke every seam name from the constant against
tmp-dir state — zero `UNPORTED_AUTH_SEAM` / `UNPORTED_RESOLVER_SEAM` /
`UNPORTED_FILE_READ_SEAM` throws remain (the harness records the sweep). The
`unportedAuthSeam` helper and the constant STAY in core (they document the
core-alone posture — core without a bag still throws correctly); what B8
removes is every DEFAULT-ONLY gap in the node package.

### §4.5 R10.9 harness spec — `throwaway/b8-n3/`

1. **Callback-server port-conflict fallback**: occupy 19284 → server lands
   19285; occupy all four → coded error `{ports}`; occupy 19284+19286 →
   19285. Race: two concurrent `start` calls land distinct ports. GET matrix:
   success, wrong state, `error=access_denied`, missing code, wrong path,
   double-hit after resolve.
2. **PKCE**: RFC 7636 vector; 500 random verifiers → challenge matches an
   independent sha256/base64url mini-model; charset/length invariants.
3. **DCR**: cached fast-path zero-fetch; every non-2xx/malformed branch;
   persist-then-return ordering (fault between → next call re-registers);
   region validation triple.
4. **login state machine**: openBrowser true/false × callback-vs-paste
   completer × exchange success/failure × persist true/false — over injected
   fetch/openBrowser/stdin fakes; authorize-URL param order + S256 +
   state echo asserted; `_parse_pasted_redirect` branch table.
5. **Bag sweep** (§4.4) + end-to-end: `login_unified` browser path over the
   REAL bag with fake fetch + tmp HOME — account dir created 0o700, tokens
   0o600, config updated, me.json written, orphan-dir guard
   (`accountDirExists`) trips on a pre-seeded directory.
6. **Secret-redaction sweep** re-run over the login/DCR branches (pair-B
   feed). fast-check ≥500/surface; seeds + counts →
   `context/phase3/notes/B8-N3-notes.md`.

### §4.6 Done-criteria (N3)

Files on disk + `tsc --strict` clean + Layer-3 green + §4.4 sweep clean +
ready-made exports (`accounts`/`session`/`targets`/`login_unified`/
`createNodeAuthEffects`) in `packages/node/src/index.ts` with JSDoc +
`npm run check` green + one local TS commit; notes committed in the Python
repo. NO vectors (0 owned).

---

## §5 Gate flip spec (P3-2e — one fable task after all three shards + doubled reviews; CLOSES THE CORPUS)

1. **Flip**: `batch-status.ts` flips `["oauth_flow.", "pending"]` → `"done"`
   (playbook P3-5 §4 B8 row `:663`; the table then contains ZERO pending
   entries). Standing collision assertion: scan all corpus api names — the only
   name matching the flipped prefix is `oauth_flow.refresh_tokens` (7);
   NOTHING remains pending. Record the scan in the gate notes. Update the
   `batch-status.ts` header comment (`:57-72`) to the terminal state.
2. **Report checkpoint**: `npm run conformance` → **3,251 PASS / 0 FAIL /
   0 UNPORTED — the full corpus** (UNPORTED drops by exactly 7; no †
   adjustment, §1). Archive JSON →
   `context/phase3/reports/2026-08-XX-b8-gate.json` (Python repo, support
   branch, docs commit). This satisfies the P3-1 `:107` end-state
   (3,179+N, N=72) one batch early — note it in the gate notes for the B9
   packet author.
3. **UNPORTED-probe terminal re-anchor (SPEC'D DECISION — the
   `b6-packets.md:1033` retirement duty)**: `runner.test.ts:136-157` and
   `batch-status.test.ts:84-87,239-256` currently use
   `oauth_flow.refresh_tokens` as the pending-name exemplar. With no pending
   corpus name left, the pattern RETIRES: (a) the runner's UNPORTED/skip code
   path keeps coverage via a SYNTHETIC batch table + synthetic vector injected
   through the existing test seams (the logic test detaches from corpus
   names — `batch-status.test.ts:86` already uses the NON-CORPUS name
   `oauth_flow.build_authorize_url`, proving the seam takes arbitrary names;
   keep a fictional-prefix fixture table pinned to `pending` INSIDE THE TEST,
   never in the shipped table); (b) the shipped-table tests re-anchor to the
   terminal assertions: `pendingEntries == []`, full-corpus prefix coverage
   still total, and every corpus api name resolves `done`; (c) the
   "UNPORTED must FAIL after flip" Risk-8 assert flips to: NO vector may
   report UNPORTED at all — assert the report's `unported == 0` in the gate
   checkpoint test. Land (a)–(c) in the SAME commit as the flip.
4. **Oracle probe + differential regression**: `oauth_flow.refresh_tokens` is
   a WIRE api — exempt from the mechanical oracle probe (P3-2e item 3). No new
   oracle families (auth has no oracle surface). The differential full-suite
   regression still runs over the EXISTING registered surface, fresh seeds,
   ≥500/family; RUN appended to `differential/oracle/RUN.md`.
5. **Checks**: `npm run check` green (TS); `just check` green if any Python
   file changed (docs/notes-only commits expected → not triggered). No
   referees (B8 touches no bookmarks).
6. **Playbook + ratification follow-through**: append the Discrepancy #13
   closure note (org-ordering FIXED at B8-N1 per the 2026-08-16 ratification;
   fuzz exclusion removed; the optional order-insensitive-comparison
   HUMAN-CALL is MOOT for the first-org site) to the playbook discrepancy log
   in the same docs commit as the report.
7. **Cleanup + notes**: remove `throwaway/b8-n1/`, `throwaway/b8-n2/`,
   `throwaway/b8-n3/` after arbiter sign-off; finalize
   `context/phase3/notes/B8-notes.md` (RUN records, findings, disclosure
   decisions, escalations, the §0.2 mapping, the CRED-F3 reveal-site
   allowlist); gate commit on TS `main`, docs/report commit on the Python
   support branch.

---

## §6 DOUBLED-REVIEW protocol (P3-3 auth doubling — binding for all three shards)

Per SHARD: **two independent review pairs (4 reviewers) + 1 arbiter**, all
fable. Every reviewer runs the standard P3-2(d) items 1–5 (R10.2
assertion-weakening diff, rulebook pass, GATE-R5 lossless grep on `flow.ts`/
`client-registration.ts`, `TODO(port)` triage — the batch must END with zero
unowned markers in `packages/node` and the `token.ts` marker gone, harness
re-run from recorded seeds). Lenses:

- **Pair A (primary)** — A-lens-1 *FS/wire semantics*: line-by-line diff of
  each shard's TS against the §2.1/§3.1/§4.1 ranges — transaction atomicity,
  tmp-file protocol, mode bits, symlink probe placement, refresh classifier
  branch order, rotation-keep, TTL boundaries, port-loop order, DCR
  persist-before-return, promotion layering (B-E2E-N1), duplicate-name class
  (B-E2E-F1). A-lens-2 *assertion fidelity + coverage*: R10.2 diff over every
  translated file; header-exclusion audit — every Python-only POSIX class
  carries the §2.3/§3.3 citation (plan §2.2 + R9.2); test-count
  reconciliation vs Python `def test_` counts (config 51, io_utils 48,
  auth_storage 48, storage 15, token_resolver 18, bridge_export 19,
  auth_flow 37, pkce 9, registration 13, callback 12, me-cache subset of 44,
  settings_headers subset of 7); harness RUN reproduction.
- **Pair B (BLIND)** — B-lens-1 *credential-safety*: the CRED-F3 rule
  (`auth-effects.ts:15-27`) — grep every new file + test + RUN record for
  `reveal(` sites and diff against the notes allowlist; `JSON.stringify` /
  serializer audit on every write path (a persisted `**********` mask is a
  BLOCKING finding); round-trip locks present (§2.3, §3.6-5); 0600/0700
  discipline; symlink refusal at every credential touch; no secret in error
  `details`, messages, or logs. B-lens-2 *adversarial FS + e2e auth*: hostile
  inputs through the REAL surfaces — path-traversal account names, symlink
  swaps between probe and open (document the sanctioned TOCTOU residue vs
  Python's fd-hardened version — the R9.2 drop must WIDEN nothing beyond the
  documented window), oversized/corrupt TOML + tokens + me.json + bridge
  files, port squatting during login, `invalid_grant` spoofing on the
  exchange op (must stay generic), unicode + Nd-digit region/env values,
  replay of the 7 vectors from scratch, the §4.4 sweep re-run.

**Independence rule (file-access, NAMED)**: pair B receives ONLY the Python
sources + the TS diff (playbook `:383-385`). Pair-B agents MUST NOT read
`b8-review-pairA-*.md`, the shard notes' review sections, or any arbiter
draft; their packets omit those paths and state the prohibition. Output
files: pair A → `b8-review-pairA-{semantics,fidelity}.md`; pair B →
`b8-review-pairB-{credsafety,adversarial}.md`; the ARBITER is the only reader
of all four (`b8-review-resolution.md`). A pair-B output citing a pair-A file
is void — re-run fresh. Launch pair B first or concurrently.

---

## §7 Cautions (file:line cited)

1. **Two-parser rule carried from B7 (§6.4 / caution 4)**: `str.isdigit()`
   guards and `int()` parses are DIFFERENT parsers and must not be unified —
   the B7 exemplars are `resolver.py:207` (`isdigit` → `/^\d+$/`) vs
   `resolver.py:242` (`int()` → `pythonInt`, R11.7). B8's own sites:
   `bridge.py` `project` field pattern `^\d+$` (regex, NOT pythonInt);
   `config.py:1044-1057` workspace check (VALUE typecheck
   `Number.isInteger && > 0`, no parse at all); `token.py` `expires_in`
   (already `coerceInt` in core). Any new `parseInt`/`Number()`/bare
   `trim()`/`\s`-regex in ported code is a per-se finding (R11.7).
2. **CRED-F3 lock** (`b7-reviewB-resolution.md:245-252`;
   `auth-effects.ts:15-27`): `Secret.toJSON()` returns the MASK — every
   on-disk writer (`ConfigWrites` account writers, `TokenStore.writeTokens`,
   `BridgeEffects.export`, DCR client info if Secret-bearing) calls
   `reveal()` at its designated site; round-trip Layer-3 locks are MANDATORY
   deliverables (§2.3, §3.6-5), not optional hardening.
3. **Real-home guard discipline**: the Python suite's conftest scrubs `MP_*`
   env and guards real-`~/.mp` writes (plan §2.2 "Key mechanics"); TS FS
   tests mirror it — every test builds under `fs.mkdtempSync(os.tmpdir())`,
   points the module there via `MP_CONFIG_PATH`/`MP_OAUTH_STORAGE_DIR`/
   `MP_AUTH_FILE`/explicit ctor paths, and a shared test helper asserts no
   resolved path is under `os.homedir()` before any write. `~/.mp` is NEVER
   touched by tests (`b7-packets.md` §6.19 precedent).
4. **`expires_at` rendering is now CONTRACT** (`token.ts:174-179` TODO; the 7
   vectors): Python `datetime.isoformat()` — offset `+00:00` (never `Z`), no
   fractional digits when microsecond == 0, else exactly 6. The clock is a
   SEAM (`now`), frozen to recordEpoch in the binding (D1.4).
5. **Refresh error-detail shapes differ per branch** (`flow.py:476-487`
   `{account_name}`-or-`{}`; `:570-575` revoked ALWAYS carries
   `account_name` even when null; `:579-584` generic spreads it only when
   set) — three shapes, port each verbatim; the vectors assert two of them.
6. **`invalid_grant` is refresh-op-only AND 400/401-only**
   (`flow.py:548-557`): exchange gets the generic code; 403/500 with an
   invalid_grant body stay generic. Body probe via `parseLossless` + the
   canonical dict guard — GATE-R5 grep covers `flow.ts` (Python's
   `response.json()` here is stdlib-strict; `parseLossless` with
   `pythonConstants` is the sanctioned superset per B0-1 F1).
7. **Rotation keep** (`token_resolver.py:236-241`): refresh response without
   a `refresh_token` keeps the OLD one before persisting — dropping it
   bricks future refreshes; harness row §3.6-4 locks it.
8. **Watchlist #13**: every `isinstance(x, dict)` in these ranges
   (`flow.py:552` payload guard; `_read_file` JSON shapes,
   `storage.py:382-428`; bridge payload reads) ports via the ONE canonical
   guard (`isPythonDict`/`isPlainRecord`) — a new local helper is a per-se
   finding (B6-ARB standing rule).
9. **Two persistence worlds, do not unify** (§3.2-7): legacy v2 region paths
   `~/.mp/oauth/{tokens,client}_{region}.json` (`storage.py:429-450`) vs
   per-account `~/.mp/accounts/{name}/{tokens.json,me.json}`
   (`token_resolver.py:40-56`, `me.py:462-469`). DCR client info is
   REGION-shared across accounts (`token_resolver.py:213-227`) — the packet's
   B7-era spelling `clientInfoExists(region)` already evolved to
   `clientInfoPath(region)` (`auth-effects.ts:294-304` shape note).
10. **Atomic-write tmp naming**: Python embeds `<pid>.<tid>`
    (`io_utils.py:136`); TS substitutes pid+counter (§2.2) — header-cite; the
    EEXIST stale-tmp branch leaves the FOREIGN tmp in place (only our own
    cleanup path unlinks, `:160-162`).
11. **`mode & 0o077` guard raises BEFORE any FS touch**
    (`io_utils.py:131-135`) — assert no tmp file exists after the reject.
12. **MeCache chmod failure RAISES a coded ConfigError** (`me.py:563-575` —
    PII rationale; the raise is `ConfigError`, :569);
    contrast `OAuthStorage._check_and_fix_permissions` which FIXES + WARNS
    (`storage.py:289-365`) and `_safe_rmtree_warn` which WARNS only
    (`accounts.py:278-303`). Three different failure postures three modules
    apart — do not cross-pollinate.
13. **Callback HTML escaping** (`callback_server.py:196-290` +
    `test_auth_callback.py::TestCallbackHtmlSecurity` :281): the error
    `{message}` interpolation is an XSS surface — port the escaping exactly;
    pair-B item.
14. **Port probing is two-phase by design** (`flow.py:638-654` probe, then
    `callback_server.py:133-146` binds again) — the TOCTOU between them is
    Python's own (R10.7); port verbatim, do not collapse into bind-once.
15. **FR-045 promotion exactly once** (B-E2E-N1, `auth-effects.ts:140-150`):
    adapter promotes, manager twin does not; `test_config.py::TestAddAccount`
    non-promoting asserts are the layer lock.
16. **Env reads at call time** (§0.4): module-load `process.env` capture
    breaks the monkeypatch-equivalent test isolation AND the
    `TestNoEnvMutation` lock (`test_settings_headers.py:71`).
17. **No real network anywhere** (Phase-4 owns live auth); callback tests
    bind real LOCALHOST sockets on the fixed ports exactly as Python does —
    that is a local bind, not network; everything else runs injected fetch.
18. **Deferral headers must zero out**: `workspace-init.test.ts`
    (`TestBridgeTokenMaterialization` row), `client-workspace.test.ts`
    MeCache-related notes, and any remaining "→ B8" rows across
    `packages/core/test` — after B8, a repo-wide grep for `B8` in test
    headers returns only historical citations, no open deferrals.
19. **No mutation testing** `[SA1]`; effort ≤ high; skeleton-first + small
    frequent edits + notes file (harness kills silent agents >3 min).

## §8 Deferral ledger

### Inbound (all placed)

| Inbound deferral (source) | Placed |
|---|---|
| `UNPORTED_AUTH_SEAMS` implementations (`b7-packets.md` §7 outbound row 1) | §4.4 owner map (N1/N2/N3) |
| Node-level default wiring: ready namespaces + `ResolverSources` (`b7-packets.md` §7 row 2) | N3 §4.1/§4.2 |
| `TokenStore.accountDirExists` (B7-ARB-A SEM-F2, `b7-reviewA-resolution.md:239-241`) | N2 §3.1 |
| CRED-F3 serialization rule + round-trip lock (B7-ARB-B, `b7-reviewB-resolution.md:245-252`) | N1 §2.3 + N2 §3.6-5 + §6 pair-B lens |
| FR-045 promotion layering (B-E2E-N1) | N1 §2.2 |
| Duplicate-name error class (B-E2E-F1) | N1 §2.2 |
| ASR-F4c named re-take (`test_session_to_credentials_oauth_browser_missing_tokens_raises`, `test_042_edge_cases.py:655`) | N2 §3.3 |
| `test_workspace_init.py::TestBridgeTokenMaterialization` :167 (`b7-packets.md` §7) | N2 §3.3 |
| `test_042_edge_cases.py::{TestTokenResolverMalformed :240, TestBridgeEdgeCases :394, TestConfigManagerEdgeCases :459}` (`b6-packets.md:1032`) | N2 §3.3 ×2 + N1 §2.3 |
| `readFile` seam W7-D1 → `node:fs` (`b6-packets.md` outbound) | N1 §2.1 |
| `MeCacheStore` on-disk twin (`b6-packets.md:1027`, `me.py:413-607`) | N2 §3.1 |
| UNPORTED-probe pattern retirement at the LAST flip (`b6-packets.md:1033`) | Gate §5.3 (terminal re-anchor spec) |
| `token.ts` `expires_at` TODO(port) (phase2-audit A7; playbook `:240-242`) | N2 §0.3.2 |
| Org-ordering ruling (user ratification 2026-08-16; supersedes B7-ARB-A R2) | N1 §0.3.1 + Gate §5.6 |
| Playbook B8 Layer-3 row files (`:240-246`) | §2.3 + §3.3 + §4.3 (every file placed; per-class dispositions incl. the Python-only POSIX exclusions per plan §2.2) |

### Outbound (created by B8, for the B9 packet author / Phase 4)

| Outbound deferral | Owner |
|---|---|
| PKCE RFC 7636 vector rows re-translate against WebCrypto (async) for the browser package (playbook `:254-256`) | B9 |
| Browser `CredentialStore` + redirect PKCE + R9.3 SA refusal — no B8 dependency, but B9 SHOULD reuse `oauth-constants.ts` values by copy-with-cite (core may not import node) | B9 |
| Sanctioned TOCTOU residue of the R9.2 fd-hardening drop (documented in `io-utils.ts` header + N1 notes) — re-examine only if Phase-4 burn-in surfaces a practical exploit path | Phase 4 (burn-in review) |
| Live auth scenarios (real IdP refresh, real browser login, real DCR) | Phase 4 (plan §6 burn-in) |
| B9-gate expectation already satisfied at B8 (3,251/0/0) — B9 gate must merely HOLD the count while adding tests only | B9 gate |

---

**Done for this packet (task B8-DL)**: 7/7 vectors accounted (§1, §3.4);
every `UNPORTED_AUTH_SEAMS` entry + `accountDirExists` + `readFile` +
`persistActive`/`UNPORTED_RESOLVER_SEAM` residue assigned an owner shard with
none left stubbed (§4.4); dispatch-order rule honored — N1/N2/N3 named in
dispatch order with the playbook-sketch content mapping recorded (§0.2);
binding plan (§3.4, node-context note included) and gate flip spec with the
terminal UNPORTED-probe re-anchor decision (§5); doubled blind review protocol
(§6); cautions cited (§7); Layer-3 per-file dispositions incl. Python-only
POSIX exclusions (§2.3, §3.3, §4.3).
