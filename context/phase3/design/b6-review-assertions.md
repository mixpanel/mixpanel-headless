# B6 adversarial review — ASSERTION FIDELITY + COVERAGE lens (P3-2d, fable)

**Status**: v1.0 · 2026-08-16 · Reviewer B of the B6 pair. Scope: the 8 W-shard
commits (`b093180` W1, `5dd445e` W2, `1338e93` W3, `3cfe49a` W4, `e5679e8` W5,
`2015275` W6, `69f3b91` W7, `3a25703` W8) + the fable BIND commit (`7a851f0`),
TS repo `main`; Python-repo notes commits `624a036..cfe9b93` read as claims
under test. Spec of record: `phase3-playbook.md` v1.1 + `b6-packets.md` v1.0.
**Verdict: GO with 2 MAJOR findings that must be resolved before the gate
flip** (both are test-side; zero library-behavior defects found under this
lens) **+ 3 minors.**

---

## 1. Independent verification record (what I re-ran / re-derived myself)

1. **Conformance replay (independently re-run)**: `npm run conformance` →
   **3,251 vectors — 3,230 PASS / 0 FAIL / 21 UNPORTED** @ corpus `70c904dc598d`
   (run 2026-08-16, this review). Matches the BIND commit claim exactly.
   Arithmetic: 2,876 (B5 gate) + 354 (353 B6-member vectors + the P3-1 †
   dagger) = 3,230; 21 UNPORTED = 14 `region_probe.` + 7 `oauth_flow.` — the
   dagger holdback (`api_client.resolve_workspace_id` w/ `workspace.me` setup)
   is therefore CLOSED pre-flip, as §11.2 predicted.
2. **158-member surface check (mechanical)**: extracted
   `jq -r '.workspace_members[] | select(.batch=="B6") | .name'` (158 names)
   and probed each camelCase twin against `packages/core/src/workspace.ts`
   (5,756 lines): **0 missing**. Spot-verified the four read-only getters
   (`account` :3101, `project` :3109, `workspace` :3117, `session` — B5-era
   :1155), `use` :1226, `close` :1309, `[Symbol.asyncDispose]` :1319,
   `me` :3192, `get api()` :3126, `streamEvents` :3263 / `streamProfiles`
   :3279 (both `async *` with `yield*` bodies — R6.6). **Zero
   `UNPORTED_MEMBER` markers remain** in `workspace.ts`.
3. **Binding completeness + honesty (mechanical)**: the union of
   `"workspace.<name>"` registrations in `wire-workspace.ts` (55) and
   `wire-workspace-entities.ts` (143) minus the 44 B5 names = exactly the 154
   registry-covered B6 names; the 4 absentees are exactly the 4 properties
   (`account`/`project`/`workspace`/`session`), matching §11.1 and
   `registry.py:117-158`. Grep for `ws.client`/direct client calls in both
   binding modules: **zero hits**; all 143 entity bindings are
   `bindFacade(...)` → `ws.<realMember>(...)` over the memoized
   `workspaceFromSession` twin; `use`/`close` bind wire_state with null
   returns per the `clear_discovery_cache` precedent
   (`wire-workspace.ts:993-1011`). HONEST.
4. **Layer-3 suite run**: `npx vitest run packages/core/test/workspace` →
   **1,402 passed / 26 todo** (the 26 todos are Finding A below, and are the
   ONLY todos in the workspace suites).
5. **R2.13 / codes-not-messages greps**: `new URL(` in `packages/core/src`:
   only a prohibition comment (`client/url.ts:9`). Error-message asserts in
   B6 test files all trace to Python originals that assert the same text
   (`test_workspace_data_governance.py:1142-1143`, `test_me.py:542/569/587`,
   `workspace.py:7770-7773` displayFormula rewrap — the B5 part-17
   `list_custom_properties` deferral, landed at
   `governance-data.test.ts:959-975` with `toBeInstanceOf(QueryError)` +
   status/method/params/cause asserts). No invented message contracts.
6. **Test-count reconciliation, ALL 8 shards** (Python `ast` class/def counts
   vs TS `it(` counts, every B6 file — this exceeds the 6-file/shard sampling
   floor because no shard has 6 files; W1 has 6, others 1–4, all reviewed):

   | Shard | File | Py (assigned classes) | TS | Verdict |
   |---|---|---|---|---|
   | W1 | workspace-facade.test.ts | 40 (−3 header-cited B7) | 24 | **Finding B** |
   | W1 | workspace-use.test.ts | 15 assigned (+5 classes header-deferred B7, +3 seam-bound cases header-cited) | 22 (12 translated + seam/additive) | clean; R6.2 identity `toBe` locks faithful (:121-160) |
   | W1 | workspace-init.test.ts | 4 | 6 | clean (headers cite B7/B8 splits) |
   | W1 | workspace-streaming.test.ts | 20 (WHOLE) | 21 | clean; datetime→ISO mapping documented (:15-19) |
   | W1 | business-context.test.ts | 21 (WHOLE) | 21 | clean (2 class-assert nits, Finding C) |
   | W1 | facade-scoping.test.ts (+`TestDiscoveryCacheAcrossUse`) | 1 | +1 (:86) | clean — B5 §8 deferral landed |
   | W1 | services/me-service.test.ts | additive (test_me.py MeService classes, early) | 27 | clean |
   | W2 | crud-dashboards.test.ts | 24 | 41 + it.each | clean — 1:1 name-matched + clearly-headed ADDITIVE sections for all 10 zero-vector members; several asserts STRONGER than Python (e.g. `ids=1,2` param spelling) |
   | W3 | workspace-bookmarks.test.ts | 17 (WHOLE) | 17 | clean |
   | W3 | crud-bookmarks-cohorts.test.ts | 64 | 64 | clean |
   | W3 | crud-edge.test.ts | 42 (WHOLE) | 16 + **26 it.todo** | **Finding A** |
   | W3 | delegation-equivalence.pbt.test.ts | 6 | 6 | clean (W6's later edit is an R11.7 trim→pythonStrip FIX, disclosed in `B6-W6-notes.md` §4) |
   | W4 | workspace-flags.test.ts | 20 | 23 + each | clean, 1:1 name-matched |
   | W4 | workspace-experiments.test.ts | 16 | 18 + each | clean; conclude/duplicate body-capture asserts byte-faithful |
   | W5 | workspace-annotations.test.ts | 13 | 18 | clean (ADDITIVE headed) |
   | W5 | workspace-webhooks.test.ts | 9 | 13 | clean (`result.message` at :237 is a DATA field, not an error message) |
   | W5 | workspace-alerts.test.ts | 15 | 22 | clean |
   | W6 | lexicon-tracking.test.ts | 23 | 39 | clean — 1:1 + line-cited additive dump-shape contracts |
   | W7 | governance-data.test.ts | 39 | 62 | clean except 2 class-assert drops (Finding C); `TestUploadLookupTable` 4/4 incl. timeout/failure via injected `readFile` + virtual clock (W7-D1 honored, seconds kept under Python names) |
   | W8 | workspace-schemas.test.ts | 26 | 33 | clean |
   | W8 | workspace-governance.test.ts | 22 | 32 | clean (`run_audit` composite branches additive-locked w/ `toBeInstanceOf` + `/got str/` twins) |

7. **B5 §8 outbound-deferral ledger — every item verified landed** (file:line):
   - `use()`/`close()`/`[Symbol.asyncDispose]` stubs replaced →
     `workspace.ts:1226/:1309/:1319`; idempotent-close + `await using` locks at
     `workspace-facade.test.ts:182-214`. ✓
   - `workspace.me` + B4 dagger → `workspace.ts:3192` + `services/me.ts` +
     `setWorkspaceResolver` wiring; dagger PASS confirmed by my replay
     (item 1). ✓
   - `stream_events`/`stream_profiles`/`api` veneer decision → W1-D3 CLOSED:
     `workspace.ts:3263/:3279` (`yield*` veneers, project-scoped, no workspace
     threading) + `get api()` :3126. ✓
   - `TestDiscoveryCacheAcrossUse` → `facade-scoping.test.ts:86`, header cite
     at :13. ✓
   - `workspace.list_bookmarks_v2` pending-override removal → GATE-owned
     (§12.1); correctly still present at `batch-status.ts:53-54/:111-region`
     pre-gate. PENDING BY DESIGN — gate task must do the collapse + collision
     scan. ✓ (placement verified, not yet executed)
   - UNPORTED-probe re-anchor → done EARLY at BIND (disclosed):
     `conformance-runner/test/runner.test.ts:135-139` and
     `differential/test/oracle-protocol.test.ts:299-317`, both on
     `region_probe.probe_region`. ✓
   - `response-validation.ts:22-27` TODO triage (W3 review duty) → marker
     re-scoped in place with an R10.3 disclosure and a corpus-lock cite
     (`response-validation.ts:18-26`); W3 additionally FIXED the alias-blind
     `collectModelErrors` bug there (red-first, disclosed in the commit). ✓
   - Discrepancy #10 re-examination at W3 → recorded in the W3 commit +
     `B6-W3-notes.md` (ordering exposed via `BookmarkValidationError.errors`,
     measured `zz,2,10,1` → `1,2,10,zz`, ruling stands, fuzz exclusion kept). ✓
   - Referees (a)+(b) → GATE-owned (§12.4), not yet run — correctly pending.

---

## 2. Findings

### Finding A — MAJOR (coverage / R10.2): 26 `TestCodedResponseValidationCodes` cases still `it.todo`; the header's own conversion protocol was never executed

`packages/core/test/workspace/crud-edge.test.ts:386-413`. W3 (dispatched
BEFORE W4–W8, against the packet's W3-LAST sequencing) carried the 26
W4–W8-owned cases of `test_workspace_crud_edge.py::TestCodedResponseValidationCodes`
(:459-:642) as `it.todo(...)` with an explicit contract in the file header
(:11-19): "the shard that lands the member converts its todo". **None of
W4–W8 touched `crud-edge.test.ts`** (verified per-commit file lists), and the
BIND task didn't either. Result: 26 of the Python file's 42 assertions
(the coded `RESPONSE_VALIDATION_ERROR` wrap for every W4–W8 entity family)
are not executing — confirmed live: the workspace suite reports
**1,402 passed / 26 todo**. The translated cases are two-liners over the
existing `makeResultsWorkspace` helper (:369-384 shows the exact pattern), so
conversion is mechanical. Playbook Risk #3 realized in its mildest form —
the assertions were carried visibly rather than dropped silently, but the
batch cannot close its gate with them outstanding (R10.2: a `TODO(port)`
gets an owner or a fix; the owners have all already exited).
**Required action**: one task converts all 26 todos (charge per P3-3 to the
owning shards' escalation lane or fold into the arbiter-fix task); expected
result 1,428 passed / 0 todo.

### Finding B — MAJOR (R10.2 header misclaim + dropped translations): `workspace-facade.test.ts` silently drops 8/11 `TestLiveQueries` and 9/11 `TestDiscovery` tests

`packages/core/test/workspace/workspace-facade.test.ts:1-21` claims the
packet's seven `test_workspace.py` classes are translated, with only the
three constructor-guard cases + empty `TestCredentialResolution` deferred
(both citations verified correct). But `TestLiveQueries` (:118, 11 tests)
is translated as only 3 (`segmentation`/`funnel`/`retention`; :72-150) —
`test_event_counts_delegation` (:210), `test_property_counts_delegation`
(:239), `test_activity_feed_delegation` (:270),
`test_query_saved_report_delegation` (:293), `test_frequency_delegation`
(:318), `test_segmentation_numeric_delegation` (:343),
`test_segmentation_sum_delegation` (:373),
`test_segmentation_average_delegation` (:403) are absent with **no header
citation** — and `TestDiscovery` (:439, 11 tests) is translated as only 2
(:152-180). Mitigations found (which is why this is not a blocker):
(i) all 9 dropped Discovery asserts have equal-or-stronger twins in the B5
`discovery-facade.test.ts` (:62-266 — events/properties/propertyValues/
subproperties/funnels/cohorts/topEvents/clearDiscoveryCache/lexiconSchema*);
(ii) `query_saved_report` delegation is locked by
`workspace-bookmarks.test.ts` (`TestQuerySavedReport`, 8 tests); (iii) the
7 remaining live-query members are B5 members whose corpus vectors replay
through the REAL facade bindings, locking delegation end-to-end at Layer-2.
But R10.2 is explicit: a dropped assertion needs a file-header design
citation, and a header that names a class as translated while carrying 27%
of it is a misclaim (the exact finding class the B5 review flagged).
**Required action**: either translate the 17 missing tests (mechanical — the
delegation-stub pattern is already in the file) or add the header exclusion
block citing the B5 twins per file:line for each dropped test; the 7
live-query facade delegation tests with no Layer-3 twin anywhere
(eventCounts, propertyCounts, activityFeed, frequency, segmentationNumeric,
segmentationSum, segmentationAverage) should be translated, not cited away.

### Finding C — MINOR (R10.2 class-assert drop, B5-recurrent pattern, 6 sites): `pytest.raises(<Class>, match=...)` translated as message-regex-only

Python asserts BOTH the exception class and the message; these TS twins
assert only the regex:
- `governance-data.test.ts:785` (`/timed out/`) and `:805` (`/failed/`) vs
  `test_workspace_data_governance.py:1594/:1644`
  (`pytest.raises(MixpanelHeadlessError, match=...)`);
- `business-context.test.ts:450/:458` vs the
  `TestGetBusinessContextChain` raises (`test_workspace_business_context.py`,
  `pytest.raises(MixpanelHeadlessError)` + str-contains);
- `workspace-facade.test.ts:227/:241` drop `ParamValidationError` — but the
  same scenarios re-assert class+code in the `TestCodedWorkspaceGuardCodes`
  describe (:347-390), so these two are compensated.
Every other error-path translation reviewed pairs `rejects.toBeInstanceOf` +
regex (e.g. `workspace-governance.test.ts:633-640`,
`workspace-schemas.test.ts:600-606`, `crud-bookmarks-cohorts.test.ts:336-343`)
— the B5-ARB fix pattern was internalized; these 6 are stragglers. Fix is a
one-line `rejects.toBeInstanceOf(MixpanelHeadlessError)` at the 4
uncompensated sites. **R10.4 tally note**: this pattern has now recurred
across B5 (~55 sites, arbiter-fixed) and B6 (6 sites) — one more batch
recurrence and the translation prompt itself should be amended.

### Finding D — MINOR (watchlist #13 re-derivation, third family recurrence): BIND's `isPlainRecordValue` duplicates `isPythonDict`

`packages/core/src/types/entities/model-base.ts` (BIND commit `7a851f0`)
adds `isPlainRecordValue` — prototype-based dict discrimination
**semantically identical** to `isPythonDict`
(`query/validation-shared.ts:323-329`, the B2-arbiter-unified guard).
Watchlist #13 / packet §0.4 says reuse, never re-derive (the packet names
`isPlainRecord` from `services/entities/shared.ts`, itself a re-export of the
JSON-shape variant — note the two existing guards differ: `isPlainRecord`
admits class instances, `isPythonDict` does not; the BIND fix needed the
`isPythonDict` semantics and should import it). Third recurrence of the
dict-guard duplication family (B2 F1 blocker; B5 minor `isPlainDict`
re-derivation; now B6-BIND) — **R10.4's ≥3 threshold is met**: arbiter
should file the rulebook amendment (one named guard per discrimination
semantics, import-only) and fold the import swap into the fix task.

### Finding E — MINOR (test-coverage gap on a library fix): the BIND `dumpValue` identity-passthrough fix has no red-first lock

Same commit: `dumpValue` now passes non-plain instances through by
reference (pydantic v2 identity-passthrough parity — "measured live",
disclosed in `B6-BIND-notes.md` §"Library fidelity fix", with the
`Uint8Array`-decomposition failure mode named). The fix is correct-by-
disclosure and vector-covered indirectly (`download_lookup_table` bytes),
but unlike the B3/B5 arbiter fixes it landed with **no dedicated unit test**
(no test in `packages/core/test` references the identity behavior).
One `modelDumpExcludeNone` test asserting `out.d.k === instance` (and the
`Uint8Array` non-decomposition regression) closes it.

---

## 3. Explicitly verified non-findings (so the arbiter doesn't re-litigate)

- **`WireRawFloat` request-side input twin** (`wire-workspace-entities.ts:149-293`):
  rig-only, mutates decoded kwargs to restore recorded integral-float
  spellings via `JSON.rawJSON` before the REAL member call; the library still
  performs its own flatten/serialize. Sanctioned mechanics under Discrepancy
  #12 (the recorder-side float-token twins' runner-side complement), fully
  disclosed in the BIND commit + notes. Honest.
- **W3 editing W2's `dashboards.ts`**: the diff is the `requireResponse`/
  `native` lift into new `workspace-members/shared.ts` (single copy for
  W3–W8) — R10.8 consolidation, disclosed, not a section violation.
- **Shard-order deviation** (W3 ran 3rd, not last): disclosed in the W3
  header/commit; its only residue is Finding A.
- **`upload_lookup_table` seconds-vs-ms**: `poll_interval`/`max_poll_seconds`
  stay seconds under Python names in the options bag; conversion at the sleep
  seam (W7-D1/R2.12) — verified in `governance-data.ts` + tests.
- **Zero-vector members (20)**: every one carries clearly-headed ADDITIVE
  delegation tests in its owning shard's file (W2's 10 at
  `crud-dashboards.test.ts:513-660`, W7's `upload_lookup_table` 4-test class,
  W1's 9 across facade/init/use/me-service files). Caution-#13 pattern
  followed.
- **`test_042_edge_cases.py` non-translation**: packet §14.1 misassignment
  ruling honored; ledger §13 carries the 9 classes to B7/B8. Nothing dropped
  silently.
- **BIND early re-anchor of the UNPORTED probes** (packet said gate §12.5):
  benign scheduling pull-forward, disclosed in the BIND commit; the gate's
  remaining §12.5 duty is only the comment/convention part.

## 4. Gate-blocking summary for the arbiter

Findings A and B are pre-gate work (test-side only; no library behavior
change expected — though A's 26 conversions could in principle surface real
wrap bugs in W4–W8 members, which is exactly why they must run). C/D/E fold
into the same fix task. Replay (3,230/0/21), member surface (158/158),
binding surface (154/154, honest), and the B5 §8 ledger are all
independently verified clean.
