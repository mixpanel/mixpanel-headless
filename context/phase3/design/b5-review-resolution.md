# B5 arbiter resolution (P3-2d) — review pair `b5-review-fidelity.md` × `b5-review-assertions.md`

**Status**: COMPLETE · 2026-08-16 · Arbiter (fable tier).
**Inputs**: fidelity review (GO w/ findings: 3 MAJOR F1–F3 + 2 minor F4–F5, commit
`7320d35`) · assertions review (GO w/ findings: 2 MAJOR F1–F2 + 4 minor F3–F6,
commit `884d460`). Eleven distinct findings total (no overlap between the two
lenses' numbered findings; the fidelity ledger's "promote the float-spelling class
to a numbered discrepancy" recommendation ≡ assertions F6(a)). Every verdict below
was re-verified against source and live-CPython probes by the arbiter before
ruling — nothing accepted on reviewer authority alone. Probe transcripts:
arbiter session 2026-08-16 (`/tmp/b5arb/`, transient; the durable copies are the
CPython-reference comments inside the new regression test files).

**Outcome: ALL ELEVEN FINDINGS CONFIRMED AND APPLIED (library + test fixes
red-first; no assertion weakened; no comparison logic relaxed; one new playbook
Discrepancy #12 filed; one straggler ledgered to the B6 gate). Post-fix verdict:
GO for the B5 gate.**

---

## Findings ledger

| # | Finding (reviewer) | Verdict | Disposition |
|---|---|---|---|
| FID-F1 | Eager `pyNumber` coercion in `transformFunnel`/`transformRetention` raises where CPython succeeds (fidelity F1, MAJOR) | **CONFIRMED** (arbiter CPython probes: funnel zero/None → `[('A',0,1.0),('B',None,0.0)]` overall `0.0`; retention `('5',[])`; str+str CONCATENATES at the `+` aggregation; bools flow raw) | FIXED red-first — raw storage + operator-site twins `pyAdd`/`pyGtZero`/`pyDiv` (§FID-F1) |
| FID-F2 | In-annotation CPython `AttributeError`/`TypeError` raise-emulation missing at most transform read sites — wrong SUCCESS incl. a wrong computed number (fidelity F2, MAJOR) | **CONFIRMED** (arbiter probe table reproduced: seg list-data/list-segvals/str-values, extract str/int/list, `_get_val` non-dict metric, null `date_range`, activity-feed dict/int/str events + non-dict props, flow non-dict root/tree/step + child-before-step order, numeric-bucket, saved-report funnels truthy-non-dict `keys` vs falsy short-circuit, `dataValues`) | FIXED red-first — mechanical sweep of `live-query-transforms.ts` + `live-query.ts` (§FID-F2). The alternative (narrowing the Discrepancy #8 in-annotation contract) REJECTED: #8 is ratified/settled, Python is the behavior arbiter, and the shard itself had already treated the class as in-contract (T1/T2) |
| FID-F3 | `?? 0` conflates explicit JSON `null` timestamps with absent keys at 3 sites; fuzz domain omits `None` undocumented (fidelity F3, MAJOR) | **CONFIRMED** (CPython: `int(None)` TypeError incl. SINGLE-element lists — `sorted(key=…)` computes every key; absent key → 0 OK) | FIXED red-first — `Object.hasOwn` absent-key ternary at all 3 sites PLUS decorate-sort-undecorate (the bare JS comparator would never run for 1-element lists — an arbiter-found extension of the finding); `None` ADDED to `_B5_RRWEB_TIMESTAMPS` with the FID-F3 domain note (§FID-F3) |
| FID-F4 | `STEP_PREFIX_RE` bare `(.+)`: JS `.` excludes `\r`/U+2028/U+2029, Python `.` only `\n` (fidelity F4, minor) | **CONFIRMED** (CPython match `"1. a\rb"` → `'a\rb'`, U+2028 case too) | FIXED red-first — `([^\n]+)` + doc note (§FID-F4) |
| FID-F5 | `fetchReplay` window derivation: missing `timestamp` key → TypeError vs Python `KeyError` (fidelity F5, minor) | **CONFIRMED** (`workspace.py:10946` is a SUBSCRIPT `int(ev["timestamp"])`) | FIXED red-first — `Object.hasOwn` guard + the `python-builtins.ts` `KeyError` twin (§FID-F5) |
| ASR-F1 | Exception-CLASS half of ~55 `pytest.raises(<Class>, match=…)` translations dropped across 6 files; bypass header falsely claims the pair (assertions F1, MAJOR) | **CONFIRMED** (arbiter counts: bypass 9 `toThrow`/0 class, r2 12/0, facade 40/0, custom-property-types 14 message-only, edge-cases 3 message-only, transform-retention 8 message-only) | FIXED — **86 class asserts added** (every message-only raise site in the six files, a superset of the review's ~55): async sites get a duplicated `.rejects.toBeInstanceOf(<Class>)`, sync sites `.toThrow(<Class>)`; classes mapped per site from the Python source (BookmarkValidationError for facade validation raises; ParamValidationError for the ctor/builder ValueError twins; QueryError for the retention transform raises). Bypass header corrected. All 193 tests in the six files green — the implementations DO throw the asserted classes (§ASR-F1) |
| ASR-F2 | Two NEW outbound deferrals to B6 exist only in TS test headers — absent from every notes ledger (assertions F2, MAJOR) | **CONFIRMED** (`grep -rl 'FacadeScoping\|list_custom_properties' context/phase3/notes/B5-*` → nothing; both headers re-read and their deferral reasoning verified: the scoping case does call `ws.use(workspace=4242)` — a B6-W1 stub; `list_custom_properties` is api-map batch B6 and the B4 client does no `displayFormula` re-raise) | FIXED — `context/phase3/notes/B5-notes.md` CREATED with a BINDING outbound-deferrals ledger of **five** B6-bound items (the review's four + the ASR-F6b straggler); the B5 gate task finalizes the rest of the file; the B6 design-lite packet MUST cite the ledger (§ASR-F2) |
| ASR-F3 | Local `isPlainDict` re-derivation of `isPythonDict` (watchlist #13 5th recurrence; assertions F3, minor) | **CONFIRMED** (body byte-equivalent to `validation-shared.ts` `isPythonDict`) | FIXED — helper deleted, `isPythonDict` imported (`workspace-query-params.ts`) |
| ASR-F4 | Three `"text" in obj` prototype-membership tests in `rrweb-analyzer.ts` (R4.8 letter; assertions F4, minor) | **CONFIRMED** (`:398`, `:473`, `:1132`; fixed literal key, no reachable divergence) | FIXED — `Object.hasOwn` at all three sites |
| ASR-F5 | Stale S2 `TODO(port)` claiming the `_replays_service` accessor is missing (assertions F5, minor) | **CONFIRMED** (`replaysService` get/set landed at `workspace.ts:2003-2026`; `#replays` field live) | FIXED — marker rewritten as a placement note citing this resolution |
| ASR-F6 | (a) integral-float-spelling divergence class argued only in RUN records, not the Discrepancy log; (b) Phase-2 `Number(str)` R11.7 straggler at `query-engine.ts` `overall_conversion_rate` (assertions F6, minor; fidelity ledger concurs on (a)) | **CONFIRMED** ((a) class spans flow-operand render, engage `where` render, rrweb console/label renders, `GroupBy.bucket_max`; (b) `git blame` pins the line to P2-6 `2ee9f59`, pre-amendment; `Number("")` → 0 where CPython `float("")` raises) | (a) RULED — playbook **Discrepancy #12** filed (arbiter-promotion per the #10/#11 precedent). (b) SPLIT: the STRING arm fixed red-first via the existing `pythonFloat` (the reviewers' exact ask); the NON-STRING ladder (`floatValue(value) ?? 0.0` vs CPython `float(None)` TypeError) needs a new `pythonFloatCoerce` compat twin mirrored in both repos + oracle strategy — a B0-style packet change, LEDGERED to the B6 gate in `B5-notes.md` item 5 rather than patched here (§ASR-F6) |

Nothing was REJECTED outright; the only narrowing is ASR-F6(b)'s non-string arm
(deferred with a named owner, not silenced). No reviewer split existed — the two
lenses were disjoint and complementary.

---

## FID-F1 — lazy operator-site coercion (MAJOR, fixed)

Python stores RAW count/size values and coerces only at the `+` (aggregation on
repeated step index), `>` (division guards), and `/` (rate math) operator sites
(`live_query.py:126-147`, `:196`). The pre-fix TS coerced with `pyNumber` at
READ time, raising `TypeError` where CPython returns results.

**Fix (TS, red-first)** in `packages/core/src/services/live-query-transforms.ts`:

- New CPython operator twins, all JSON-domain complete and message-exact
  (`pythonTypeNameOf` spellings, operand order preserved):
  `pyAdd` (number/bool add, str CONCAT, list CONCAT, else
  `unsupported operand type(s) for +: 'X' and 'Y'`), `pyGtZero`
  (`'>' not supported between instances of 'X' and 'int'`), `pyDiv`
  (`unsupported operand type(s) for /: 'X' and 'Y'`).
- `transformFunnel`: `aggregatedCounts` holds `[unknown, unknown]`; first
  insertion stores RAW; repeats go through `pyAdd`; `conv_rate`/overall use
  `pyGtZero`/`pyDiv` on the raw values; `FunnelResultStep.count` receives the
  raw value via the existing `passthrough` convention (exactly what Python's
  unenforced dataclass annotation does).
- `transformRetention`: `size` stored raw; the guard+division run PER COUNT
  inside the comprehension twin, so empty `counts` never touches `size`;
  iteration is Python `for` via the new `pyIter` (dict → keys, str → chars).
- `pyNumber` (still used by `pySum`) message corrected to CPython type names.

**Locks**: `packages/core/test/services/transform-raise-fidelity.test.ts`
(43 tests, every expectation a recorded CPython probe result;
**39 red pre-fix / 43 green post-fix** — the 4 pre-fix passes are the
already-correct edges). The 78-case transforms harness corpus stays 78/78
byte-identical (S2 harness re-run below), so the S10/S11 conversion math is
untouched.

## FID-F2 — AttributeError raise-emulation sweep (MAJOR, fixed)

Ruling first: the fidelity review offered two paths — extend the `pyMapping`
guard everywhere, or narrow the Discrepancy #8 in-annotation contract for
response-body interiors. **The sweep was chosen.** #8 is a ratified, settled
class ruling ("every value inside `dict[str, Any]`/`Any` interiors" is
IN-annotation); narrowing it retroactively would also have had to un-fix the
shard's own T1/T2 remediation, and Python is the behavior arbiter.

**Fix (TS, red-first)**, mechanical sweep of `live-query-transforms.ts` +
`live-query.ts` against the Python source's attribute reads, with three new
CPython twins (`pyIn` — str key membership: dict/`Object.hasOwn`, str/substring,
list/element-equality, else the CPython-3.14 `argument of type 'X' is not a
container or iterable`; `pyIter` — list/str/dict-keys, else
`'X' object is not iterable`; `segmentationCounts` — a LAZY generator so the
`sum` interleaving of `+`-TypeErrors and `.values()`-AttributeErrors matches
Python's generator order, probe-verified):

- `extractStepsFromDateData(unknown)`: `pyIn` before each `pyMapping` read
  (order matters: a str containing `"steps"` passes membership THEN raises at
  `.get`).
- `transformFunnel`: T1's `pyMapping` attr corrected `items` → `values`
  (Python raises at `data.values()`; the existing regression tests assert class
  only, so no test churn); per-step `pyMapping(stepRaw, "get")`.
- `transformSegmentation`: `data`/`values`/per-segment `.values()` guards +
  the lazy sum (kills the wrong-computed-number case: `{data:{values:{seg:[1,2]}}}`
  now raises `AttributeError` instead of returning `total=3`).
- `dictGetRecord` REDEFINED over `pyMapping` (its JSDoc lie about
  `Object.hasOwn` raising "the same way Python's attribute lookup does" —
  called out by the review — is gone with it); this fixes every `date_range`
  consumer (JSON-null → `AttributeError 'NoneType'`), `transformActivityFeed`
  `results`/`properties`, and `transformNumericBucket` in one move.
- `transformActivityFeed`: `pyIter(rawEvents)` (dict iterates KEYS then raises
  at the str `.get`; int raises the iteration TypeError) + per-event
  `pyMapping`.
- `transformFlowResult`/`parseTreeNode`: `pyIter` over `trees`/`children`;
  `parseTreeNode(unknown)` guards `raw` at `.get`, keeps `step` RAW until after
  the children recursion (CPython statement order, probe-verified:
  child error beats step error).
- `transformSavedReport` funnels branch: truthiness FIRST, then
  `pyMapping(data, "keys")` — a falsy non-dict `data` short-circuits exactly
  like Python (`{'data': 0}` → `('', series=0)` probe).
- `live-query.ts` `dataValues`: nested read now `pyMapping` (JSDoc corrected).

`extractStepsFromDateData` and `parseTreeNode` signatures widened to `unknown`
(their exported callers all pass through; typecheck clean).

**Locks**: the FID-F2 describes of `transform-raise-fidelity.test.ts` (22 cases
incl. both service-level `dataValues` locks through `createMockClient`).

## FID-F3 — null-timestamp `?? 0` conflation (MAJOR, fixed)

Three sites fixed with the `Object.hasOwn` absent-key ternary AND
decorate-sort-undecorate (arbiter extension: CPython's `sorted(key=…)` computes
the key for EVERY element, so a 1-element list with `timestamp: null` raises in
Python while a bare JS comparator never runs — probe-verified):

- `replays/rrweb-analyzer.ts` `processEvent` (`:854`) — hasOwn ternary;
- `replays/rrweb-analyzer.ts` `analyze` sort — decorated;
- `services/replays.ts` walker per-file sort (`:465`) — decorated.

**Fuzz-domain remediation**: `None` ADDED to
`conformance/differential/strategies.py::_B5_RRWEB_TIMESTAMPS` with a
documented-omission-style note citing this resolution (the review's finding that
the omission was undocumented is thereby moot — the value is now IN the domain
and locks the fix).

**Locks**: `packages/core/test/replays/null-timestamp-fidelity.test.ts` (4) +
the FID-F3 describe appended to `replays-service.test.ts` (2) — **4 red
pre-fix**, all green post-fix. Both-bridge fuzz re-run below draws the new value
cleanly.

## FID-F4 / FID-F5 — minors (fixed)

- `STEP_PREFIX_RE` capture group → `([^\n]+)` + doc note; locked by the FID-F4
  describe (`\r` and U+2028 match with numeric sort keys; `\n` still refused).
- `workspace.ts` `fetchReplay` window derivation: `Object.hasOwn` guard +
  `KeyError` twin; locked by the FID-F5 describe appended to
  `workspace-replays.test.ts` (red pre-fix).

## ASR-F1 — class asserts (MAJOR, fixed)

86 sites across the six files (see ledger row). Insertion is a duplicated
statement (class assert BEFORE the message assert) — the paired style the shard
itself used correctly in `query-user-parallel.test.ts:483` /
`rrweb-analyzer.test.ts` / `build-cohort-params.test.ts`. Double invocation of
the awaited expression is safe at every site (pure validation raises against
stub clients; no state mutation before the raise). The
`validation-bypass.test.ts` header now states the pair form AND discloses that
the class half was added at B5-ARB. All 193 tests in the six files green.

## ASR-F2 — outbound-deferrals ledger (MAJOR, fixed)

`context/phase3/notes/B5-notes.md` created (OPEN status — gate task finalizes)
with the BINDING five-item outbound table:
`TestDiscoveryCacheAcrossUse` → B6-W1; `TestWorkspaceFacadeScoping` → B6-W1;
`TestListCustomPropertiesErrorHandling` → B6; `workspace.list_bookmarks_v2`
override removal → B6 gate; `overall_conversion_rate` non-string R11.7
straggler (`pythonFloatCoerce`) → B6 gate. The B6 design-lite packet must cite
this section — carried as a note-for-next to the orchestrator.

## ASR-F6 — Discrepancy #12 + the straggler split

Playbook **Discrepancy #12** filed (integral-float string-spelling narrowing as
a sanctioned CLASS — full entry in `phase3-playbook.md` §P3-8, rationale: JS
cannot express `18.0` vs `18`; #7's R4.5 reasoning; float-token twins cover the
vector-observable cases; residual S2 12/2,678 + S3 20/2,080 divergences are the
documented remainder). The `overall_conversion_rate` STRING arm now routes
through `pythonFloat` (red tests: `"inf"` → `Infinity`, `""` → raise, `"0.25"`
unchanged); the non-string ladder is ledgered (B5-notes item 5) — an arbiter
patch would have required minting a new shared compat function without its
both-repo mirror and oracle strategy, which is packet-scale work.

---

## Post-fix verification (all re-run by the arbiter, this session)

| check | result |
|---|---|
| New regression locks | `transform-raise-fidelity.test.ts` 43/43 (39 red pre-fix) · `null-timestamp-fidelity.test.ts` 4/4 · appended describes in `replays-service` / `workspace-replays` (red pre-fix) |
| S2 R10.9 harness, recorded seed 20260816 / PER_FAMILY 520 (full 3-stage re-run) | **2,678 compared / 12 divergences** — identical to the RUN record; all 12 are the Discrepancy #12 class (2 flow-operand + 10 engage-where); transforms family **78/78 byte-identical** (conversion math untouched by the FID-F1/F2 rework) |
| S3 R10.9 harness, full 3-stage re-run | **2,080 compared / 20 divergences** — identical to the RUN record; spot-checked all-#12 class (`18.0`→`18` renders); committed `throwaway/b5-s3` artifacts restored byte-identical afterwards |
| S2/S3 wire-edge matrices | **119/0** and **70/0** — match the RUN records |
| B5-BIND oracle fuzz, recorded seed **789657390**, 9 families, EXTENDED domain (`None` timestamp) | **4,555 examples / 0 skips / 0 divergences** — oracle-ts now raises `int(None)`'s TypeError exactly like oracle-py |
| `npm run conformance` @ pin `70c904dc598d` | **3,251 — 2,876 PASS / 0 FAIL / 375 UNPORTED** (unchanged; batch-status untouched — flip stays with the gate task) |
| `npm run check` (typecheck + lint + fmt + vitest 8,15x + browser smoke) | green (full suite 175 files, 8,199+ tests incl. the new locks) |
| `just check` (Python repo — `strategies.py` touched) | green |
| Residual-pattern greps | zero `?? 0`-timestamp, zero `"text" in`, zero `isPlainDict` in `packages/core/src` |

S1's harness was not re-run here: no S1 (discovery) surface was touched by any
fix, and the assertions reviewer independently re-ran it from its recorded seed
two commits ago (5,522/0).

## Notes for the B5 gate task

1. `batch-status` flip (44 exact names + `replays.`/`replay_labels.`/
   `rrweb_analyzer.` + the `workspace.list_bookmarks_v2` pending override) is
   still pending — unchanged by this resolution.
2. `throwaway/` cleanup happens at the gate per P3-2(c); the arbiter left all
   four directories in place with committed artifacts byte-identical.
3. `B5-notes.md` finalization must PRESERVE the outbound-deferrals section
   (ASR-F2) — it is the binding input to the B6 design-lite packet.
4. The regenerated rrweb goldens were verified byte-identical by the fidelity
   review; no golden regeneration was needed for these fixes (the analyzer
   changes touch only null/absent-timestamp and membership-test paths, and the
   golden suite stayed green).
