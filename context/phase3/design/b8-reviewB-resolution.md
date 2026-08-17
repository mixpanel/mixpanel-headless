# B8 pair-B arbiter resolution (task B8-ARB-B)

**Status**: COMPLETE · 2026-08-16 · arbiter: fable (≤ high).
Inputs: `b8-reviewB-atrest.md` (lens 1, credential-at-rest safety — ZERO findings,
GO, 4 non-blocking observations) and `b8-reviewB-e2e.md` (lens 2, adversarial
end-to-end differential — 1 major + 3 minor, GO with findings).
Scope: all five B8 TS commits (`597ef7d` MAPFIX, `44fc912` N1, `53a134e` N2,
`8017fc4` N3, `92a5f8a` pair-A arbiter fixes) at HEAD. Pair A was arbitrated
separately (`b8-reviewA-resolution.md`); the two-pair convergence note is §"Two-pair
convergence" below.

Every code fix was applied RED-FIRST: 13 new locks written and run FAILING against
the pre-fix source (1 companion lock passes pre-fix by design — it pins the
post-fix rejection boundary), then the fixes landed, then everything re-ran green.
Verification after all fixes:
`npm run conformance` → **3,251 / 0 / 0 @ 70c904dc** (unchanged);
`npm run check` → green (typecheck, eslint, prettier, **9,831 tests / 233 files**,
browser smoke); pair-B atrest probe suite re-run post-fix → **62 checks / 0
failures**; the e2e reviewer's OWN divergence repros re-run post-fix → both former
DIVERGES rows now MATCH Python field-for-field (see F1). `just check` green on the
Python side (docs-only changes there; run with the color env cleared — the
arbiter's harness shell exports `FORCE_COLOR=3`, which makes Rich embed ANSI
codes in captured CLI output and false-fails 14 rendering asserts; verified
env-only by re-running the failing subset both ways).

TS fix commit: `e44bea2` (`B8-ARB-B fixes`) on `main`; conformance re-verified
3,251/0/0 at that HEAD. Python repo: this file + playbook
Discrepancy #14 correction + new Discrepancy #15 + rulebook R11.9 + the
`B8-N2-notes.md` decision-3 correction (one docs commit).

---

## Verdicts — pair-B lens 1 (credential-at-rest, `b8-reviewB-atrest.md`)

**GO, zero blocking/major findings — ACCEPTED.** Arbiter re-ran the committed
probe suite from the review's RUN record
(`throwaway/b8-reviewB-atrest/probes.ts`, `npx vite-node`): **62 checks, 0
failures**, both BEFORE and AFTER the F1/F2 fixes below (the fixes touch three
CRED-F3-adjacent files — `bridge.ts`, `storage.ts`, `token-payload.ts` — so the
post-fix re-run is the ripple check; the reveal-site allowlist is UNCHANGED at
exactly the four designated sites, and no new datetime formatter touches secret
material).

Dispositions for the four non-blocking observations:

- **O1** (flow.ts:898 `response_data` carries the full 200 token payload into
  refresh-error details — verbatim `flow.py:596-605` parity): ACCEPTED as
  Python-parity, no change. The suggested Phase-4 burn-in ledger line is handed
  to the B8 gate task (gate duty 3 below) for `B8-notes.md` — same vehicle as
  N2's TOCTOU Phase-4 row.
- **O2** (TS malformed-tokens `validation_error` names fields only vs Python's
  pydantic `str(exc)` — equal-or-safer): ACCEPTED, no change (message text out of
  contract, R5.4; safe direction).
- **O3** (MeCache parent-dir transient mode identical to `me.py:563`): parity
  confirmation, no action.
- **O4** (untracked `.DS_Store` noise): left to the gate's worktree hygiene.

Blindness verified: the review file cites no pair-A artifact; the probe file
reads only shipped sources.

## Verdicts — pair-B lens 2 (e2e differential, `b8-reviewB-e2e.md`)

### F1 (MAJOR) — numeric-epoch `expires_at` accepted by Python (pydantic lax) at the resolver read + bridge tokens parse, rejected by TS; TS internally inconsistent with its own legacy-storage lax mirror → **CONFIRMED, FIXED (reviewer option 1: one shared lax helper, R10.8)**

Verified three ways: (i) arbiter probe (`throwaway/b8-arb-b/f1-repro.ts`) —
pre-fix: resolver REJECT (`OAUTH_TOKEN_ERROR`), `parseBridgeFile` REJECT
(`ParamValidationError`), `OAuthStorage.loadTokens` ACCEPT; (ii) live CPython:
`OAuthTokens.model_validate({... "expires_at": 1893456000})` →
`2030-01-01T00:00:00+00:00` (probe table below); (iii) the reviewer's own R3B
`epoch_expires` / R4 `epoch_tokens` drivers. The `B8-N2-notes.md` §7 decision-3
claim ("resolver + storage read paths") did NOT match shipped code — the notes
file now carries a bracketed correction.

**Arbiter probes went beyond the finding and pinned the FULL speedate lax
surface** (every row live-probed against pydantic v2 on the support branch):

| input | pydantic result |
|---|---|
| `1893456000` | `2030-01-01T00:00:00+00:00` |
| `1893456000.5` | `2030-01-01T00:00:00.500000+00:00` |
| `"1893456000"` / `"+1893456000"` / `".5"` / `"5."` | ACCEPTED (digit-string epoch grammar) |
| `" 1893456000"` / `"1_0"` / `"0x10"` / `"1e10"` / `True` | REJECTED |
| `19_999_999_999` / `20_000_000_000` | seconds (2603-10-11) |
| `20_000_000_001` / `1_893_456_000_000` | **milliseconds** (watershed `|v| > 2e10`) |
| `253_402_300_799_999` (ms) | `9999-12-31T23:59:59.999000+00:00` (max) |
| `253_402_300_800_000` (ms) / `-62_135_596_800_001` | REJECTED ("dates after 9999" / year 0) |

**Fix**: new `packages/node/src/auth/pydantic-datetime.ts` exporting
`coerceLaxExpiresAt` — the ONE pydantic-lax mirror (numeric epochs with the 2e10
watershed, numeric-string grammar `[+-]?(\d+(\.\d*)?|\.\d+)`, year-1..9999 range,
ISO text passthrough with the `Date.parse` NaN gate). Routed by ALL credential
datetime readers:

- `token-resolver.ts` `getBrowserToken` (pre-normalization before
  `parseOAuthTokens` — the `token_resolver.py:134-148` twin),
- `bridge.ts` `parseBridgeFile` tokens (the `BridgeFile` pydantic twin),
- `token-store.ts` `readTokens` (no Python twin — N2 disclosure 4 — but it reads
  the SAME file as the resolver; blanket consistency, disclosed),
- `storage.ts` `loadTokens` (absorbs the former private `coerceStoredExpiresAt`,
  which lacked the string-epoch grammar and the ms watershed),
- `storage.ts` `loadClientInfo` `created_at` (arbiter-found sibling:
  `storage.py:566` is `OAuthClientInfo.model_validate` — pydantic-lax too).

**Deliberately NOT laxed** (per-path fidelity): `readBrowserTokens` /
`_read_browser_tokens` (`bridge.py:243-244` requires `isinstance(expires_raw,
str)` — BOTH sides reject epoch there; verified in source) — the finding
correctly excluded it.

**Arbiter-found sibling gate closed in the same pass**: pre-fix,
`parseBridgeFile` accepted a tz-suffixed NON-instant (`"2030-99-99T00:00:00+00:00"`
— passes the tz-suffix regex, `Date.parse` NaN) that pydantic REJECTS; the shared
helper's NaN gate now rejects it (locked).

**Locks (RED runs recorded)**: `token-resolver.test.ts` "B8-ARB-B F1" (epoch
int + numeric-string serve the token — both RED pre-fix; year-9999-overflow
rejection — pre-passing pin), `bridge.test.ts` "B8-ARB-B F1/F2" (epoch +
string-epoch parse, month-99 rejection — all RED), `token-store.test.ts` (epoch
readTokens — RED), `auth-storage.test.ts` (string-epoch + ms-watershed +
epoch created_at — RED), plus the 43-row unit probe table in the new
`packages/node/test/pydantic-datetime.test.ts`. Aggregate red run: **13 failed /
114 passed** across the four suites pre-fix; **127/127** post-fix.

**Post-fix reviewer-repro re-run**: R3B `epoch_expires` — TS now
`{"kind":"ok","returned":"at-epoch"}` = Python; R4 `epoch_tokens` — TS now
`tokens_expires "2030-01-01T00:00:00+00:00"` = Python. Both former DIVERGES rows
MATCH.

### F2 (minor) — TS bridge writer emits `+00:00` where Python's pydantic writer emits `Z` → **CONFIRMED, FIXED AS A CLASS (alignment, not disclosure) — two additional writer sites found**

Verified: live probe `model_dump(mode="json")` renders
`2030-01-01T00:00:00Z` / `...00.500000Z` / `...00.000120Z` / `...00+05:30`. Root
cause is structural: Python stores a parsed `datetime` and RE-RENDERS per writer;
TS stores ISO TEXT and echoed it. That made the class BIGGER than the finding —
arbiter ripple-chase found every writer:

| writer | Python rendering | TS pre-fix |
|---|---|---|
| bridge `_serialize_bridge` (`bridge.py:292`) | pydantic JSON → `Z` | echoed `+00:00` (the finding) |
| `token_payload_bytes` (`token.py:206`) — tokens.json incl. **bridge materialization** | `isoformat()` → `+00:00` | echoed source text (a py-written `Z` bridge leaked `Z` into tokens.json — the reviewer's R3C chain observed exactly this text but byte-compared nothing) |
| legacy `save_tokens` (`storage.py:471`) | `isoformat()` → `+00:00` | echoed |
| `save_client_info` (`storage.py:541`) | pydantic JSON → `Z` | echoed `+00:00` |

**Fix**: two formatters in `pydantic-datetime.ts` — `pydanticJsonDatetimeText`
(`Z` canonical) and `pythonIsoformatDatetimeText` (`+00:00` canonical), both
canonicalizing fractions to pydantic/isoformat's 0-or-6 digits and non-zero
offsets to `±HH:MM`; out-of-grammar text passes through verbatim (disclosed
corner — unreachable from validated models). Applied at all four writer sites.
Plus one byte-level ripple: `tokenPayloadBytes` now renders through the existing
core `pythonJsonDumps` (R10.8 — `json.dumps` default `", "`/`": "` separators),
closing the last whitespace gap.

**Byte-parity goldens** (`/tmp/b8arbb/py_writers.py` — REAL Python library
writers — vs `throwaway/b8-arb-b/f2-parity.ts`, identical inputs): bridge,
`tokens_us.json`, `client_us.json`, and the tokens.json payload are now ALL
**BYTE-IDENTICAL** across the two implementations (pre-fix: bridge differed on
`Z`, payload differed on separators). Locks in `bridge.test.ts` (exported bridge
carries `"2030-01-01T00:00:00Z"`; materialization from a `Z`-text bridge writes
`"expires_at": "2030-01-01T00:00:00+00:00"` — both RED pre-fix) and
`auth-storage.test.ts` (saveTokens `+00:00` from a `Z` model; saveClientInfo `Z`
from a `+00:00` model — both RED), plus the formatter rows of the unit table.

### F3 (minor) — Python freezes the default config path at module import; TS resolves per construction → **CONFIRMED, BLESSED AS SANCTIONED DEVIATION (reviewer's recommended option)**

Verified in source: `config.py:59` module-level `_DEFAULT_CONFIG_PATH =
Path.home() / ...` vs `config.ts` call-time `defaultConfigPath()`; the reviewer's
live evidence (round-1 Python driver crashes under sequential fresh `HOME`s)
stands. Matching an import-time freeze in ESM would pin module-evaluation-order
trivia; Python's own bridge/storage defaults are already call-time; no real
workflow depends on the frozen quirk. Resolution: **playbook Discrepancy #15**
(sanctioned call-time deviation, R10.7 disclose option) + the upgraded disclosure
JSDoc at `config.ts` `defaultConfigPath` (the prior comment understated the
observable difference). No code change; no HUMAN-CALL needed (class-only,
not result-affecting on any real workflow — the #6/#7 blessing pattern).

### F4 (minor, docs) — Discrepancy #14's first example contradicts shipped code → **CONFIRMED, PLAYBOOK CORRECTED**

Verified: `resolver.ts:364` gates `MP_PROJECT_ID` with `/^\p{Nd}+$/u` (comment
explicitly ports `str.isdigit()` as Nd, per B7 packet Caution #4) and carries the
B7-ARB-A R1 message-only disclosure; Python `resolver.py:207` `isdigit()`. Both
sides accept `"٤٢"` — the reviewer's R2I row is right and #14's "resolver.py:207
twin" example was wrong (the class is real only at the B8 bridge `/^\d+$/`
sites). **Playbook #14 rewritten** to scope the class to the bridge gates and to
carry an explicit "do NOT align the resolver gate to ASCII" warning. No code
change.

---

## Cross-cutting arbiter duties

- **Harness re-run (P3-2d item 5)**: atrest probes 62/0 reproduced (pre- and
  post-fix); e2e R3/R4 TS drivers re-run post-fix against the reviewer's recorded
  Python outputs (`/tmp/b8e2e/out/`) — epoch rows converged, everything else
  unchanged. The reviewer throwaway drivers stay in
  `throwaway/b8-reviewB-{atrest,e2e}/` (plus the arbiter's
  `throwaway/b8-arb-b/`) for the gate's §5.7 cleanup; the arbiter's lint/prettier
  normalization touched four throwaway files (unused imports / `any` casts —
  mechanical, no probe-logic change; pair-A precedent).
- **Binding honesty (P3-5 rule 3)**: unchanged by these fixes —
  `wire-auth.ts` untouched; post-fix conformance replay 3,251/0/0 @ 70c904dc.
- **R10.4**: rulebook **R11.9** filed (pydantic-lax datetime twins + writer
  formatter table; the pattern recurred 8× in this pass, threshold 3; binds B9's
  browser CredentialStore too).
- **Playbook**: Discrepancy #14 corrected (F4); Discrepancy **#15** appended (F3).
- **N2 notes**: §7 decision 3 carries the bracketed B8-ARB-B correction.

## Duties handed to the B8 gate task

1. Carry into `B8-notes.md`: the R11.9 filing, Discrepancy #15, the #14
   correction, and lens-1 O1 as a Phase-4 burn-in ledger line
   (flow.ts:898 `response_data` full-payload parity — re-examine only if a live
   IdP ever returns secrets the error surface shouldn't carry; Python-verbatim
   today).
2. §5.7 `throwaway/` cleanup now also covers `throwaway/b8-reviewB-atrest/`,
   `throwaway/b8-reviewB-e2e/`, and `throwaway/b8-arb-b/` after gate sign-off
   (the `/tmp/b8e2e/`, `/tmp/b8arbb/` scratch dirs are ephemeral, nothing to do).
3. O4: drop the untracked `.DS_Store` noise from both repos' worktrees at the
   gate (do not commit).

## Human calls

**None required.** F1/F2 resolved by ALIGNMENT (Python is the behavior arbiter;
byte parity achieved); F3 blessed inside the established arbiter
sanctioned-deviation pattern (#6/#7 class — not result-affecting for any real
workflow, unlike the org-ordering case the user ruled on); F4 is a docs
correction. For completeness: no new evidence arrived on B7's still-open optional
HUMAN-CALL (order-insensitive comparison ratification) — status unchanged,
non-blocking.

## Two-pair convergence note (B8)

Coverage was complementary, overlap was consistent, and neither pair's majors
were visible to the other's lens — the doubling earned its cost:

- **Disjoint majors**: pair A's SEM-F1 (startup materialization unreachable from
  any shipped composition) is a WIRING defect no cross-language differential
  could see pre-fix (pair B's R2L/R3C scenarios exercise
  `loadBridgeForStartup()` directly — and in fact only compile because the
  pair-A fix had already landed at HEAD); pair B's F1 (pydantic-lax epoch
  acceptance) is a VALUE-DOMAIN defect invisible to pair A's
  source-vs-source assertion/semantics lenses (no Layer-3 Python test feeds an
  epoch `expires_at`, so there was no assertion to weaken). Single-pair review
  would have shipped one of the two.
- **Independent convergence** on the error-class discipline: pair A forced the
  clause-mapping alignment (R11.8); pair B's matrices (R3B ×6, R4 ×12,
  S12 ×11) then reproduced the ALIGNED classes field-for-field blind —
  a genuine cross-check of pair A's fixes, not a duplicate finding.
- **Convergence on the #14 class from opposite directions**: pair A disclosed
  the `\d` narrowing class (probing the bridge gates); pair B blind-probed BOTH
  gate families end-to-end and caught that the class statement over-claimed the
  resolver site (F4) — the corrected entry is now exactly the intersection both
  pairs measured.
- **Lens-1 twins agree**: pair A's assertions lens and pair B's at-rest lens
  independently signed off on the CRED-F3 allowlist (4 reveal sites), the 0600
  atomic protocol, and the sentinel-free error surfaces; pair B added the
  62-check adversarial probe suite as a standing artifact the arbiter could
  re-run (and did, post-fix).
- **Residue for the record**: pair B's byte-parity goldens (all four credential
  writers byte-identical to Python post-fix) close the last writer-shape gap the
  program had never measured; pair A's R11.8 + pair B's R11.9 are sibling
  rulebook amendments — together they now pin BOTH halves of the on-disk
  contract (error classes on the way in, byte shapes on the way out).

## GO/NO-GO

**GO.** All four e2e findings resolved (2 fixed red-first as classes with byte
parity verified, 1 sanctioned-deviation row, 1 docs correction); lens-1 GO
accepted with observations dispositioned; ripples chased across every sibling
datetime read/write site; pair-A locks re-run green post-fix. Post-fix state:
`npm run check` green (9,831 tests / 233 files), conformance 3,251/0/0 @
70c904dc, atrest probes 62/0, core purity untouched (all fixes in
`packages/node`), zero TODO(port) in `packages/node`. Combined two-pair posture:
**GO — nothing in either resolution blocks the B8 gate**; the flip spec
(`oauth_flow.` → done) is unchanged; the gate inherits three duties from this
file plus the two standing from pair A.
