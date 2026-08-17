# B8 pair-A arbiter resolution (task B8-ARB-A)

**Status**: COMPLETE · 2026-08-16 · arbiter: fable (≤ high).
Inputs: `b8-reviewA-semantics.md` (lens 1, storage/protocol semantics — 1 major + 5 minor)
and `b8-reviewA-assertions.md` (lens 2, assertion fidelity — 1 major + 2 minor).
Scope: all four B8 TS commits (`597ef7d` MAPFIX, `44fc912` N1, `53a134e` N2, `8017fc4` N3).
Pair B (blind) is arbitrated separately (B8-ARB-B); nothing here reads pair-B output.

Every fix below was applied RED-FIRST: the lock test was written and run failing
against the pre-fix source (recorded per finding), then the source fix landed, then the
full suites re-ran green. Verification after all fixes:
`npm run conformance` → **3,251 / 0 / 0 @ 70c904dc** (unchanged);
`npm run check` → green (typecheck, eslint, prettier, **9,771 tests / 232 files**, browser
smoke); core purity untouched (all fixes in `packages/node` except comment-only core edits
and one core TEST addition).

TS fix commit: `B8-ARB-A fixes` on `main` (see `git log`). Python repo: this file +
playbook Discrepancy #14 + rulebook R11.8 (one docs commit).

---

## Verdicts — pair-A semantics lens

### SEM-F1 (MAJOR) — bridge startup materialization unreachable from any default node composition → **CONFIRMED, FIXED (option a)**

Verified: `loadBridgeForStartup` (bridge.ts:612) had ZERO `src/` callers (grep);
`createNodeResolverSources` routes `resolverSourcesFromEffects` → pure
`effects.bridge.load()`; the bridge.ts:602-611 JSDoc claim ("B8-N3's default
ResolverSources wiring calls THIS") was false as shipped; the N2-notes disclosure #1
obligation on N3 went unfulfilled and conflicted with packet §4.1 row 5's pure-`load()`
spelling. Failure scenario reproduced by the red run: fresh tmp HOME + `MP_AUTH_FILE`
bridge with oauth_browser tokens, no per-account `tokens.json` → resolver-sourced
Workspace resolves but `OnDiskTokenResolver.getBrowserToken` throws OAUTH_TOKEN_ERROR
where Python `Workspace()` succeeds (`workspace.py:476-513`).

**Fix (reviewer option a)** — a SHIPPED node-level startup composition:

- `packages/node/src/auth-effects.ts` — new export `createNodeWorkspaceSources(options?)`:
  `createNodeAuthEffects(options)` + `loadBridgeForStartup()` + `bridgeViewFromFile`,
  the exact `workspace.py:476-513` sequence. `createNodeResolverSources` stays PURE
  (N2 disclosure #1: `use()` re-resolution must never clobber mid-session-refreshed
  tokens with a stale bridge payload — Python re-resolves through plain `load_bridge()`,
  `resolver.py:407-408`).
- Exported from `packages/node/src/index.ts` (module JSDoc updated with the
  pure-vs-startup split).
- bridge.ts:602-611 JSDoc corrected to cite `createNodeWorkspaceSources` as the shipped
  caller.
- core `workspace.ts` sessionless-construction comment + error message now point at
  `createNodeWorkspaceSources()` (see ASR-F2 below — the stale TODO there is retired by
  the same edit).

**Arbiter ruling on the packet conflict**: packet §4.1 row 5's "default `ResolverSources`
(env + config + `bridge.load()`)" remains CORRECT for the resolver/namespace surfaces
(`createNodeResolverSources`); the N2-notes N3 obligation applied to FACADE CONSTRUCTION
only. Both compositions now ship; the obligation is CLOSED here (recorded closure of
`B8-N2-notes.md` §7 disclosure #1).

**Locks** (`packages/node/test/workspace-bridge-materialization.test.ts`, new describe
"B8-ARB-A SEM-F1"): (1) fresh-VM courier path end-to-end over
`new Workspace({ sources: createNodeWorkspaceSources(...) })` — per-account file written
+ REAL resolver serves the bridge bearer; (2) `createNodeResolverSources()` purity
(bridge visible to the rung, NOTHING materialized). RED RUN: 1 failed / 3 passed pre-fix
(the purity lock passed pre-fix, as expected — it pins current behavior); 4/4 green
post-fix. File header rewritten (it repeated the false JSDoc claim).

### SEM-F2 (minor) — undisclosed I/O-error-CLASS divergences on degrade-to-null read paths → **CONFIRMED, ALIGNED (not just disclosed)**

All three cited sites verified against source AND live CPython probes (recorded here):
`load_tokens` on an unreadable (0o000) file → **PermissionError propagates**;
invalid-UTF-8 bridge file (0600) → **raw UnicodeDecodeError**;
invalid-UTF-8 `me.json` (0600) → **raw UnicodeDecodeError**.

Chose alignment over disclosure (Python is the behavior arbiter; the EACCES-as-"no
tokens" case masks a real permission problem, exactly as the reviewer argued):

- **F2a** `storage.ts` `#readFile`: degrade only on `SyntaxError`/`TypeError` (the
  ValueError-family twins, `storage.py:415-419`); errno errors rethrow.
  Lock: `packages/node/test/io-error-classes.test.ts` (new file) — the reachable Python
  fixture (root-owned 0600 file) cannot be built unprivileged and the permission fixer
  repairs any mode we could set, so EACCES is injected at the module seam via a partial
  `vi.mock` of io-utils (the `monkeypatch.setattr` twin; header-cited mechanism
  substitution). RED: 2 failed pre-fix.
- **F2b** `bridge.ts` `loadBridge` read-catch: wrap only
  `CredentialPathError | SyntaxError | errno` (the `(OSError, json.JSONDecodeError)`
  clause list, `bridge.py:181`); the decode `TypeError` propagates RAW.
  Lock in `bridge.test.ts`. RED: failed pre-fix (ConfigError).
- **F2c** `me-cache.ts` `get`: decode `TypeError` rethrows before the corrupt-debug
  path (`me.py:514` clause list). Lock in `me-cache.test.ts`. RED: failed pre-fix (null).

**Predicate hardening (arbiter-caught during F2)**: node stamps string `code`s on
NON-system errors — the TextDecoder fatal `TypeError` carries
`ERR_ENCODING_INVALID_ENCODED_DATA` — so the pre-existing code-only `isErrnoError` in
`config.ts` would have classified decode errors as OSError (its own comment claimed
otherwise). `isErrnoError` now requires string `code` AND numeric `errno`, and is
hoisted to `packages/node/src/io-utils.ts` as the ONE shared OSError-twin (R10.8);
`config.ts` imports it. New lock in `config.test.ts`: invalid-UTF-8 config file (0600)
→ raw TypeError, not ConfigError (live CPython probe: `list_accounts` over an
invalid-UTF-8 `config.toml` raises **raw UnicodeDecodeError**).

**Ripples chased (same clause family, arbiter-found beyond the finding)**:
- `bridge.ts` `readBrowserTokens` — read catch `(OSError, JSONDecodeError)`-narrowed
  (decode TypeError now RAW) and probe catch errno-wrapped (`bridge.py:221-242`).
  Locks in `bridge.test.ts` ("B8-ARB-A readBrowserTokens error-class locks");
  RED: 2 failed pre-fix.
- `token-resolver.ts` `getBrowserToken` probe catch errno-wrapped
  (`token_resolver.py:104-111` `except OSError`). Lock in `token-resolver.test.ts`;
  RED: 1 failed pre-fix. (Its read/model catches were audited and already
  clause-faithful: `read_credential_bytes` has no decode step, and pydantic
  `model_validate_json` on invalid UTF-8 raises ValidationError → wrapped both sides.)
- Full audit of the remaining 43 `catch` sites in `packages/node/src`: every other
  clause-mapped site matches its Python list (`MeCache.get` probe = CredentialPathError
  only, matching `me.py:497`; `MeCache` model-drift branch rethrows non-library errors;
  `token-store.readTokens` has no Python twin — N2 disclosure #4 stands).

**R10.4 amendment filed**: the fix pattern recurred 8× in this one pass (> threshold 3)
→ rulebook **R11.8** (except-clause class mapping + the errno/decode twin table +
the single shared `isErrnoError`). Affected modules regenerated = the fixes above;
no earlier-batch module has FS-read `except` boundaries (core is FS-free; wire error
paths are transport-adapter-normalized and vector-locked).

### SEM-F3 (minor) — `exportBridge` wraps invalid pins in ConfigError where Python propagates the validation error raw → **CONFIRMED, FIXED**

Verified by live probe: `BridgeFile(project="abc")` and `workspace=0` raise pydantic
`ValidationError` raw (no wrap anywhere in `bridge.py:357-364` / `accounts.py:963-1010`;
the Python docstring's ConfigError claim is wrong in Python itself). Aligned to the
established pydantic-ValidationError → `ParamValidationError`-raw convention: the
try/catch wrap in `exportBridge` is REMOVED; JSDoc `@throws` corrected. Locks in
`bridge.test.ts` (project="abc", workspace=0 → ParamValidationError, and no partial
file left behind). RED: 2 failed pre-fix. Grep confirmed no other test pinned the old
ConfigError wrap (the reviewer was right that no Layer-3 lock existed on either class).

### SEM-F4 (minor) — `serializeBridge` sortKeys uses UTF-16 code-unit order at a `sort_keys=True` port site → **CONFIRMED, FIXED**

One-line fix: `Object.keys(value).sort()` → `sortedByCodepoint(Object.keys(value))`
(R11.5, `packages/core/src/compat/codepoint.ts`) + JSDoc note. CPython control:
`json.dumps({"😀":1,"｡":2}, sort_keys=True)` → `{"｡": 2, "😀": 1}` (probe recorded).
Lock in `bridge.test.ts` (on-disk text index order of "｡" vs "😀" in headers).
RED: failed pre-fix (reversed order).

### SEM-F5 (minor) — undisclosed `\d` ASCII-vs-Nd narrowing at the digit-gate sites → **CONFIRMED, DISCLOSED AS A CLASS (no code change)**

Probes recorded: CPython `re.fullmatch(r'^\d+$', "٤٢")` matches; pydantic
`BridgeFile(project="٤٢")` ACCEPTED; JS `/^\d+$/` rejects. Behavioral alignment would
contradict packet §7 caution 1 (the mandated regex spelling / two-parser rule), and
every affected TS input is REJECTED with a coded error (never wrongly accepted).
Recorded as **playbook Discrepancy #14** (covers ALL `\d`/isdigit gate sites, B7+B8);
the batch-gate task must carry the entry into `B8-notes.md` (gate §5.7 duty noted
below).

### SEM-F6 (minor) — config `readRaw` wraps only CredentialPathError from the probe; Python wraps ANY OSError → **CONFIRMED, FIXED**

`config.ts` probe catch now wraps `CredentialPathError || isErrnoError` into ConfigError
(`config.py:180-183`). Lock in `config.test.ts` (unreadable parent dir → ConfigError;
POSIX, non-root-gated). RED: failed pre-fix (raw errno escaped). The same probe-wrap
family at `load_bridge`/`_read_browser_tokens`/`get_browser_token` was fixed under the
SEM-F2 ripple sweep above (each of those Python probes is `except OSError` too;
`storage._read_file` and `MeCache.get` probes are `except CredentialPathError` ONLY and
were verified to already propagate errno raw — matching Python, no change).

## Verdicts — pair-A assertions lens

### ASR-F1 (MAJOR) — the settings-custom-header → bridge.headers COMPOSITION lock fell through the N2 translation split → **CONFIRMED, FIXED**

Verified: `packages/node/test/bridge.test.ts` locks only the effect-level verbatim-headers
half; grep confirmed zero tests set a non-null `customHeader` on the exportBridge path at
any layer (fake default null; `auth-effects-bag.test.ts` asserts it IS null).

Fix: new describe in `packages/core/test/accounts/accounts-namespace.test.ts`
("B8-ARB-A ASR-F1 custom-header export composition lock, test_bridge_export.py:274") —
fake-backed: `config.state.customHeader = ["X-Mixpanel-Cluster", "cell-3"]` →
`accounts.exportBridge` → exported headers bag equals `{"X-Mixpanel-Cluster": "cell-3"}`,
plus an anti-vacuity companion (no header configured → bag stays `null`).
**Anti-vacuity RED demonstrated by mutation**: temporarily swapping name/value at
`accounts-ops.ts:848` (`{[header[1]]: header[0]}`) made the new test FAIL (1 failed /
1 passed / 48 skipped), then reverted — the exact regression class the reviewer named is
now caught. Suite green at HEAD (50/50).

### ASR-F2 (minor) — stale future-tense TODO(port) markers pointing at completed batches → **CONFIRMED, FIXED NOW (not deferred to the gate)**

The reviewer proposed folding into the gate commit; applied here instead (the arbiter
commit is the natural home for the retirement it cites). All five sites rewritten to
cite the §4.4 core-alone posture ("real implementation lives in packages/node") instead
of future work, keeping every CODE unchanged and the default-throwing seams in place:

- `packages/core/src/accounts/auth-effects.ts` (`unportedAuthSeam` body + message),
- `packages/core/src/workspace-members/lifecycle.ts:113` (`unportedSeam` body + message),
- `packages/core/src/workspace-members/governance-data.ts:62` (W7-D1 doc) and `:219`
  (`unportedReadFile` doc + message → cites `nodeReadFile`),
- `packages/core/src/workspace.ts:1182` (sessionless-construction guard → cites
  `createNodeWorkspaceSources()`, joining the SEM-F1 fix).

Messages are out of contract (R5.4); grep confirmed no test pinned the old texts (only
built `dist/` artifacts). `grep -rn "TODO(port)" packages/core/src` now returns only the
legitimately-standing disclosure markers (query-engine/discovery/transforms/pagination/
replays/py-dates/schemas/login-unified/response-validation + closed-marker citations),
none of which reads as open B7/B8 work. `packages/node` remains TODO(port)-free.

### ASR-F3 (minor) — storage-paths.test.ts header self-contradiction → **CONFIRMED, FIXED**

Header now reads "all 5 classes covered — 13/15 members translated, 2 Python-only
members cited below" with the two exclusions itemized under the same plan §4.2 / R9.2
citations. No behavior change.

---

## Cross-cutting arbiter duties

- **Binding honesty (P3-5 rule 3)**: re-verified for the shard — `wire-auth.ts`'s
  `oauth_flow.refresh_tokens` binding drives the real `OAuthFlow.refreshTokens` (kwarg
  plumbing + codec walk only); post-fix conformance replay 3,251/0/0 @ 70c904dc.
- **R10.4**: rulebook **R11.8** filed (except-clause mapping; 8 recurrences — see SEM-F2).
- **Playbook**: Discrepancy **#14** appended (SEM-F5 class).
- **Formatting**: prettier normalized the touched test files plus the reviewer's
  untracked `throwaway/b8-reviewA-semantics-probes.ts` (format-only; `npm run check`'s
  fmt gate covers `throwaway/`).

## Duties handed to the B8 gate task

1. Carry the Discrepancy #14 (SEM-F5) class disclosure into `B8-notes.md` alongside the
   §5.6 org-ordering closure note.
2. The §5.7 `throwaway/` cleanup now also covers `throwaway/b8-reviewA-semantics-probes.ts`
   (pair-A reviewer probes) after both arbiters sign off.
3. Caution 18's "repo-wide grep for B8 in test headers" is unaffected: the new
   arbiter-cited describes reference `b8-reviewA-resolution.md` as historical citations.

## GO/NO-GO

**GO.** Both majors and all six minors resolved (7 fixed red-first, 1 disclosed as a
ratified-pattern class entry); ripples chased across all sibling clause sites; no
HUMAN-CALLs required (SEM-F1 resolved via reviewer option (a) inside existing rules;
SEM-F5 handled per the Discrepancy #8 annotation-boundary spirit the reviewer invoked).
Post-fix state: `npm run check` green (9,771 tests), conformance 3,251/0/0, core purity
green, zero TODO(port) in `packages/node`, zero open deferral headers.
