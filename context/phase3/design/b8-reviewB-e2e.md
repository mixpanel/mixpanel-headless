# B8 review — Pair B (BLIND), Lens 2: adversarial end-to-end differential

Status: COMPLETE · 2026-08-16 · reviewer: pair-B e2e (fable).
Scope: ALL B8 commits at batch level per the orchestrator ruling — TS
`597ef7d` (B8-MAPFIX), `44fc912` (B8-N1), `53a134e` (B8-N2), `8017fc4`
(B8-N3), `92a5f8a` (pair-A arbiter fixes; reviewed as HEAD code only).
Blindness: NO `b8-reviewA-*` file was read at any point (findings
blindness; the fixed code at HEAD is in scope per the orchestrator
ruling). Python arbiter source: support branch @ `8a84d24` lineage,
corpus pin 70c904dc.

## Method

46 end-to-end scenario cases across the full stack, each executed against
BOTH implementations in isolated temp homes (never `~/.mp` — every run
under `/tmp/b8e2e/work/{py,ts}/<sid>/home` with `HOME` +
`MP_CONFIG_PATH`/`MP_OAUTH_STORAGE_DIR`/`MP_AUTH_FILE` scoped per
scenario), outcomes normalized to canonical JSON and diffed
field-by-field. Cross-implementation ARTIFACT reads (Python-written
files read by TS and vice versa) exercise the on-disk interchange
contract directly — 8 cross-read comparisons.

Drivers (scratch, not committed to either package):
- Python: `/tmp/b8e2e/py_driver.py`, `py_r2.py`, `py_r3.py`, `py_r4.py`
  (run `uv run python … {main,cross}` from the Python repo). Real
  library end-to-end; network faked with `httpx.MockTransport`; the
  OnDiskTokenResolver refresh path exercised via the same
  module-attribute patch the Python suite uses.
- TS: `throwaway/b8-reviewB-e2e/ts_driver.ts`, `ts_r2.ts`, `ts_r3.ts`,
  `ts_r4.ts` (run `npx vite-node …`). Real node package end-to-end;
  network faked via the `fetchImpl` seams.
- Diff: `/tmp/b8e2e/diff.py`, `diff_r2.py` (recursive field-by-field;
  raw class names + normalized class + code + sorted details keys +
  picked detail values; `expires_at` normalized to format flags +
  delta-window because Python has no clock seam on the resolver path).

## Scenario matrix

| # | Scenario | Result |
|---|---|---|
| S01 | config.toml SA account + [active] + [settings] header → resolve_session → Basic header, 0600 config | MATCH |
| S02 | config oauth_token account → resolve → Bearer via OnDiskTokenResolver static path | MATCH |
| S03 | env SA quad (+MP_WORKSPACE_ID) overrides config on all three axes | MATCH |
| S04 | MP_OAUTH_TOKEN vs full SA quad (SA wins); token+project+region alone (token account) | MATCH |
| S05 | empty-string env vars all treated as unset (fall back to config); MP_REGION=usa → ConfigError {env_var,value} | MATCH |
| S06 | target axis resolution; target+axis kwarg mutex; unknown target | MATCH (mutex: py bare ValueError ↔ ts `ParamValidationError`/`WS1_TARGET_MUTUALLY_EXCLUSIVE` — the established R5 coded-twin convention, cls_norm equal) |
| S07 | bridge via MP_AUTH_FILE as account/project/workspace source; bridge headers WIN over [settings] on collision; MP_PROJECT_ID overrides bridge project only | MATCH |
| S08 | bridge export→load round-trip, all 3 account types, secrets revealed, 0600 | MATCH own-side; cross-reads below |
| S09 | corrupted/partial bridge matrix (first pass; superseded by R4 — see note) | MATCH (all rows; but see R4 note on the 0644-mode confounder) |
| S10a | expiry → refresh → ROTATION persisted (returned token, fetch count, request URL/body/content-type, disk keys+values, `+00:00` no-Z rendering, 0600) | MATCH |
| S10b | rotation-KEEP: IdP omits refresh_token → old one persisted | MATCH |
| S10c | fresh token: zero fetches, disk untouched | MATCH |
| S10d | expired + missing DCR client info → OAUTH_REFRESH_ERROR {account_name,region,path} | MATCH |
| S10e | static token_env: unset/empty → coded error; set → token | MATCH |
| S11 | get_valid_token legacy world: expired tokens_us.json → refresh → persisted at v2 path, posted body parity | MATCH |
| S12 | refresh error classification matrix ×11 (400/401 invalid_grant→REVOKED with account_name present-and-null; 400-other/403-invalid_grant/503→generic; 200 non-JSON; 200 missing-field; network→{url}; no-refresh-token {} vs {account_name}, 0 fetches) | MATCH (all 11, field-by-field incl. details-key sets and fetch counts) |
| S13 | MeCache round-trip with OUT-OF-ORDER integer-like org keys ("999" before "12"): on-disk key order, first-org pick `zeta-org`, collision pick `zeta-org-2`, TTL expiry, corrupt→null, 0600/0700 | MATCH — the MAPFIX ordered cache WRITE path verified e2e |
| S14 | 8-writer concurrent race on one tokens.json ×20 rounds: final file valid, no tmp strays, 0600 | MATCH (invariants) |
| S15 | config with 3 account types + target + active(workspace) + custom header: own-read view | MATCH; cross-reads below |
| S16 | symlinked tokens.json / config.toml / bridge + dangling bridge symlink → refusal classes | MATCH |
| S17 | MP_OAUTH_STORAGE_DIR relocation of account dirs (relpath + 0700) | MATCH |
| X1 | TS reads Python-written bridges (sa/ot/browser) | MATCH except tokens `expires_at` TEXT — finding F2 |
| X2 | TS reads Python-written config.toml (secrets revealed, order, target, header) | MATCH |
| X3 | TS reads Python-written me.json → first-org pick + org order | MATCH (`zeta-org`, ["999","12"]) |
| X4/X5/X6 | Python reads TS-written bridges / config.toml / me.json | MATCH |
| R2A | bridge headers with integer-like keys → loaded key order + session headers | MATCH (export sorts keys on write — both sides, order converges) |
| R2B | config error matrix: malformed TOML, unknown account type (list+get), invalid [active], accounts-not-a-table | MATCH (all ConfigError/CONFIG_ERROR) |
| R2C | apply_session project-no-account; workspace XOR clear_workspace; apply_session writes default_project; apply_target WHOLESALE (clears workspace pin, updates target account default_project) | MATCH (XOR: py ValueError ↔ ts coded twin, convention) |
| R2D | duplicate add → plain ConfigError (B-E2E-F1); remove referenced → AccountInUseError/ACCOUNT_IN_USE both; force → removed targets list | MATCH |
| R2E | MP_AUTH_FILE → missing file → None; empty var → default chain → None | MATCH |
| R2F | default bridge search paths: ~/.claude/mixpanel/auth.json then <cwd>/mixpanel_auth.json | MATCH |
| R2G | refresh POST body byte parity with hostile token/client_id (`space + & = ~ * % / ? 𝒳`): quote_plus semantics (`~` literal, `*`→%2A, space→+) | MATCH (byte-identical bodies) |
| R2H | 30s expiry buffer boundary (now+25s → refresh; now+40s → fresh) | MATCH |
| R2I | MP_PROJECT_ID = Nd digits "٤٢" → ACCEPTED by BOTH (py `str.isdigit`; ts `/^\p{Nd}+$/u`, resolver.ts:364) — see F4 note on Discrepancy #14's wording | MATCH |
| R2J | MP_WORKSPACE_ID grammar: "abc"/"0"/"-1"/"1.5" → ConfigError {env_var,value}; "+5"→5; "1_0"→10 (CPython int() grammar honored via pythonInt) | MATCH |
| R2K | TWO concurrent refreshers on one expired account: 2 IdP calls, both callers served, final file valid+0600 (once-per-caller contract) | MATCH |
| R2L | STARTUP bridge materialization (py: real `Workspace()` ctor; ts: `loadBridgeForStartup()`): tokens.json written 0600, empty scope → "read" default | MATCH |
| R2M | remove_bridge explicit/default-chain + idempotent second call | MATCH |
| R2N | unicode config (NFD secret, non-BMP header) own-read + BOTH cross-reads verbatim | MATCH (own-side py/ts values differ only by driver-side NFD construction; cross-reads byte-faithful) |
| R3A | bridge with 0644 mode → BOTH refuse (group/world-bit credential-read guard) — accidental but valuable parity row | MATCH |
| R3B | corrupt per-account tokens.json matrix ×6 | 5 MATCH; `epoch_expires` DIVERGES — finding F1 |
| R3C | chain: py-written browser bridge ("Z" text) → TS startup materialization → tokens.json ("Z" preserved) → BOTH resolvers serve at-br | MATCH (Z spelling propagates but parses everywhere) |
| R4 | bridge schema matrix ×12 at correct 0600 (truncated/version 1/"2"/extra key top+account/browser-no-tokens/project "12a"/project Nd/workspace 0/empty/naive-datetime/epoch tokens) | 10 MATCH; `project_nd_digits` = sanctioned #14 divergence (py accepts, ts ConfigError); `epoch_tokens` DIVERGES — finding F1 |

Totals: 46 scenario cases + 8 cross-read comparisons; 2 genuine
undisclosed behavioral divergences (one class — F1), 1 interchange-shape
divergence (F2), 1 module-load-capture timing divergence (F3), 1
discrepancy-log wording inaccuracy (F4), 1 sanctioned-divergence
confirmation (#14 bridge project), everything else field-identical.

## Findings

### F1 (MAJOR, CONFIRMED) — numeric-epoch `expires_at` accepted by Python, rejected by TS at the per-account resolver read AND the bridge-file parse; TS is also internally inconsistent with its own legacy-storage lax mirror

- Python: `OnDiskTokenResolver.get_browser_token` parses via
  `OAuthTokens.model_validate_json` (`token_resolver.py:134-148`) —
  pydantic lax converts a numeric epoch-seconds `expires_at` to an
  aware datetime. Probe: `OAuthTokens.model_validate({... "expires_at":
  1893456000 ...})` → `2030-01-01T00:00:00+00:00`. A per-account
  `tokens.json` carrying `"expires_at": 1893456000` SERVES the token
  (repro R3B `epoch_expires`: py `{"kind":"ok","returned":"at-epoch"}`).
  Same for `BridgeFile.tokens` (pydantic model): a v2 bridge with epoch
  tokens LOADS (repro R4 `epoch_tokens`: py ok).
- TS: `token-resolver.ts:208` parses via core
  `parseOAuthTokens(parsed, {boundary:"param"})`, whose
  `requireString(payload, "OAuthTokens", "expires_at")`
  (`packages/core/src/auth/token.ts:344-347`) REJECTS any non-string →
  `OAuthError OAUTH_TOKEN_ERROR` ("malformed or missing required
  fields"). `parseBridgeFile` rejects the same bridge with
  `ConfigError`. Meanwhile `packages/node/src/auth/storage.ts:573-595`
  DOES implement the pydantic-lax mirror ("numeric epoch SECONDS
  convert to aware UTC") — verified: `OAuthStorage.loadTokens` over the
  same payload returns `expires_at: "2030-01-01T00:00:00+00:00"`. So
  the three TS read paths disagree with each other, and two of them
  disagree with Python.
- `B8-N2-notes.md` §7 decision 3 explicitly claims the lax mirror
  covers "**resolver** + storage read paths" — the shipped resolver
  path does not implement it. This is a recorded-decision/code
  mismatch, not just an undisclosed deviation.
- Failure scenario: any foreign writer of the interchange surfaces (the
  bridge file is BY DESIGN written by third-party tools — the Cowork
  courier contract) emitting epoch expiry: Python library authenticates
  fine; TS library refuses with "re-run mp account login". Divergent
  success-vs-error outcome. TS fails CLOSED (never wrongly accepts), so
  not a security issue — a parity/availability one.
- Suggested fix: route the resolver-path and bridge-path `expires_at`
  through the same lax acceptance `storage.ts` already has (single
  helper, R10.8), or have the arbiter rule epoch inputs out of the file
  contract AND correct B8-N2-notes decision 3 + add the row as a
  documented rejection. Either way the three TS read paths must agree.
- Repro:
  `uv run python /tmp/b8e2e/py_r3.py main` (R3B `epoch_expires`) vs
  `npx vite-node throwaway/b8-reviewB-e2e/ts_r3.ts`; R4 `epoch_tokens`
  in `py_r4.py`/`ts_r4.ts`; storage probe `/tmp/b8e2e/epoch_legacy.ts`.

### F2 (MINOR, CONFIRMED) — bridge-file writer emits `expires_at` as `+00:00` text where Python's writer emits pydantic's `Z` form

- Python `_serialize_bridge` (`bridge.py:292` `model_dump(mode="json")`)
  renders the tokens' expiry as `"2030-01-01T00:00:00Z"` on disk
  (pydantic v2 JSON rendering). TS `serializeBridge`
  (`bridge.ts:381-405`) writes the model's stored ISO TEXT verbatim,
  which for library-written tokens is the `pythonUtcIsoformat` form
  `"2030-01-01T00:00:00+00:00"`. Observed: py-written
  `bridges/browser.json` carries `Z`; TS-written carries `+00:00`
  (S08/X1 diff — the ONLY field that differed across all 8 cross-read
  comparisons).
- Both parsers accept both spellings (verified: X1/X4 round-trips and
  the R3C chain, where the `Z` text survives TS materialization into
  `tokens.json` and Python then serves the token). So interop is safe;
  this is a writer-shape divergence on an interchange artifact whose
  docstring claims `_serialize_bridge` parity (sort_keys + indent — both
  hold; the datetime rendering does not).
- Suggested fix: render bridge `tokens.expires_at` through a
  pydantic-JSON-shaped formatter (Z form) in `serializeBridge`, or
  disclose the spelling difference in the bridge.ts header + N2 notes
  (strict byte-consumers of the bridge are the only parties affected).

### F3 (MINOR, CONFIRMED) — default config path captured at module import in Python, at construction in TS

- Python: `_DEFAULT_CONFIG_PATH = Path.home() / ".mp" / "config.toml"`
  (`config.py:59`) — evaluated ONCE at import. TS:
  `defaultConfigPath()` evaluated per `ConfigManager` construction
  (`config.ts:306-314`). With `MP_CONFIG_PATH` unset and `HOME` changed
  mid-process (exactly what test harnesses and long-lived agent
  processes do), Python managers keep pointing at the import-time home
  while TS managers follow the new one. My round-1 driver hit this
  live: sequential scenarios under fresh `HOME`s saw Python
  `ConfigManager()` keep writing the FIRST scenario's config
  ("Account 'alpha' already exists" crashes) while the TS mirror
  followed each scenario's `HOME`.
- Note the asymmetry inside Python itself: bridge default search paths
  are call-time (`default_bridge_search_paths()` function), storage
  roots are call-time — only the config default is import-frozen. The
  TS port made everything call-time (packet §0.4's call-time rule),
  which silently "fixed" Python's frozen default; R10.7 would keep the
  quirk or disclose it.
- Suggested fix: disclosure note in `config.ts` (recommended — matching
  an import-time freeze in ESM is ugly and no real workflow depends on
  it), or arbiter blessing as a sanctioned call-time-env deviation row.

### F4 (MINOR, docs) — playbook Discrepancy #14's first example does not match shipped code: the resolver env-project gate is Unicode-Nd on BOTH sides

- #14 claims every ported `isdigit`/`^\d+$` gate site — naming "the B7
  `resolver.py:207` twin" first — "accepts Nd in Python but rejects
  them in TS". The shipped TS resolver gate is `/^\p{Nd}+$/u`
  (`packages/core/src/auth/resolver.ts:364`, with a comment explicitly
  porting `str.isdigit()` as Nd) and my R2I e2e run confirms BOTH
  implementations accept `MP_PROJECT_ID="٤٢"` end-to-end (session
  project `"٤٢"` on both sides). The #14 class is real ONLY at the
  bridge gate sites (`parseBridgeFile`/`validatedProject` `/^\d+$/` —
  confirmed diverging in R4 `project_nd_digits`, py accepts / ts
  ConfigError, exactly as sanctioned). The discrepancy-log entry's
  example list should be corrected at the gate so future readers don't
  "fix" the resolver gate to ASCII and CREATE a real divergence.

### Expected-divergence confirmations (no action)

- R4 `project_nd_digits`: the sanctioned #14 divergence reproduces
  exactly as disclosed (py pydantic accepts `"٤٢"`; ts coded refusal —
  fails closed). My independent pydantic probe also confirms the
  arbiter's `BridgeFile(project="٤٢") ACCEPTED` claim.
- S06/R2C error-class rows: Python bare `ValueError` ↔ TS coded
  `ParamValidationError` twins (R5 convention; cls_norm equal).

## Positive verifications worth recording (batch-level per-shard coverage)

- MAPFIX (`597ef7d`): S13 + X3/X6 prove the ordered org map end-to-end
  INCLUDING the cache-write flag from B8-MAPFIX-notes decision 3 — the
  TS me.json writer preserves out-of-order integer-like org keys on
  disk (`["999","12"]`), Python and TS read each other's cache files
  and derive the identical account name (`zeta-org`) and collision
  suffix (`zeta-org-2`).
- N1 (`44fc912`): S01–S07, S14–S16, R2A–R2F, R2N — config transactions,
  FR-045 layering (via namespaces at S15/R2C-D), duplicate-add class,
  atomic-write race invariants, TOML cross-reads with NFC/NFD + non-BMP
  preserved verbatim, symlink + group/world-bit read refusals.
- N2 (`53a134e`): S08–S13, R2G–R2M, R3B/R3C — rotation + rotation-keep
  + 30s buffer + classifier matrix byte-parity (incl. `account_name`
  present-and-null on REVOKED), quote_plus body byte-parity, both
  persistence worlds, startup materialization with the `""→"read"`
  scope default, no secret material in any error surface (sentinel scan
  clean on both sides).
- N3 (`8017fc4`): exercised here only via the bag wiring
  (`createNodeResolverSources` used by every TS scenario) — login/PKCE
  interactive surfaces are pair-B lens-1/Layer-3 territory, out of this
  lens's cross-language reach (no Python-vs-TS diffable network-free
  path); the packet's compensating controls (Layer-3 + harness rows)
  stand.
- The 7 `oauth_flow.refresh_tokens` corpus vectors: `npm run
  conformance` at HEAD reports 3,251 PASS / 0 FAIL / 0 UNPORTED
  (bound-while-pending), and S10-S12 replicate the vector behaviors
  from scratch in fresh temp homes (independent re-derivation, not a
  corpus replay).

## RUN record

```
# Python side (from /Users/jaredmcfarland/Developer/mixpanel-headless)
uv run python /tmp/b8e2e/py_driver.py main  > /tmp/b8e2e/out/py-main.json   # 17 scenarios, 0 crashes
uv run python /tmp/b8e2e/py_r2.py main      > /tmp/b8e2e/out/py-r2.json     # 14 scenarios, 0 crashes
uv run python /tmp/b8e2e/py_r3.py main      > /tmp/b8e2e/out/py-r3.json
uv run python /tmp/b8e2e/py_r4.py           > /tmp/b8e2e/out/py-r4.json
uv run python /tmp/b8e2e/py_driver.py cross > /tmp/b8e2e/out/py-cross.json  # reads TS artifacts
uv run python /tmp/b8e2e/py_r2.py cross     > /tmp/b8e2e/out/py-r2-cross.json
uv run python /tmp/b8e2e/py_r3.py cross     > /tmp/b8e2e/out/py-r3-cross.json

# TS side (from /Users/jaredmcfarland/Developer/mixpanel-headless-ts)
npx vite-node throwaway/b8-reviewB-e2e/ts_driver.ts > /tmp/b8e2e/out/ts-main.json  # 17 + cross, 0 crashes
npx vite-node throwaway/b8-reviewB-e2e/ts_r2.ts     > /tmp/b8e2e/out/ts-r2.json
npx vite-node throwaway/b8-reviewB-e2e/ts_r3.ts     > /tmp/b8e2e/out/ts-r3.json
npx vite-node throwaway/b8-reviewB-e2e/ts_r4.ts     > /tmp/b8e2e/out/ts-r4.json
npx vite-node /tmp/b8e2e/epoch_legacy.ts            # storage lax-mirror probe

# Diffs
uv run python /tmp/b8e2e/diff.py     # round 1: 4 raw diffs (3 = coded-twin convention, 1 = F2)
uv run python /tmp/b8e2e/diff_r2.py  # round 2: 5 raw diffs (3 = coded-twin convention, 2 = driver NFD noise; cross-reads clean)
# round 3/4 compared inline: R3B epoch_expires + R4 epoch_tokens (F1), R4 project_nd_digits (#14, sanctioned)
```

Driver-noise notes (for reproducibility honesty): (i) round-1 S09 wrote
bridge files at default 0644, so both sides refused on the
group/world-bit guard before schema validation — the matrix was redone
at 0600 in R4 (S09's MATCH rows stand but classify the permission
refusal, not schema errors); (ii) R2N own-side "diff" is the TS driver
using NFC `é` where the Python driver built NFD — the cross-reads (the
actual contract) are byte-faithful in both directions; (iii) the
round-1 Python driver crashes that forced explicit `config_path=`
arguments are themselves finding F3's evidence.

## Verdict

GO with findings. The B8 node package is, on this lens's evidence, an
unusually faithful port: 46 adversarial cross-language scenario cases
and 8 cross-implementation artifact reads produced exactly one
undisclosed behavioral divergence class (F1 — epoch `expires_at` at the
resolver/bridge read paths, contradicting the shard's own recorded
decision), one interchange-artifact spelling divergence (F2), one
env-capture timing divergence (F3), and one discrepancy-log wording
error (F4). Nothing found is a security regression — every TS-side
divergence fails closed.
