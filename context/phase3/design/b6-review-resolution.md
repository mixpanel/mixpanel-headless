# B6 arbiter resolution (P3-2d) — review pair `b6-review-fidelity.md` × `b6-review-assertions.md`

**Status**: COMPLETE · 2026-08-16 · Arbiter (fable tier).
**Inputs**: fidelity review (GO conditional on 1 MAJOR, + 3 minors: F1–F4 —
found ON DISK but UNCOMMITTED by its author; committed alongside this
resolution, a process nit charged to the fidelity reviewer) · assertions
review (GO with 2 MAJOR + 3 minors: A–E, commit `cc30b7c`).
The two lenses overlap on exactly one finding (fidelity F1 ≡ assertions A — the
crud-edge todos); seven distinct findings total. Every verdict below was
re-verified against source by the arbiter before ruling — nothing accepted on
reviewer authority alone.

**Outcome: ALL SEVEN FINDINGS CONFIRMED AND APPLIED (library fixes red-first
where a red is constructible; every test-side fix strengthens, none weakens; one
rulebook amendment filed under R10.4; two reviewer sub-claims corrected on the
record). Post-fix verdict: GO for the B6 gate.**

Post-fix state (TS repo `main`): workspace suites **1,436 passed / 0 todo**
(pre-fix 1,402 + 26 todo); full `npm run check` green; conformance replay
**3,251 vectors — 3,230 PASS / 0 FAIL / 21 UNPORTED @ 70c904dc** (unchanged —
every fix is either test-side or confined to a zero-vector member's error
details).

---

## Findings ledger

| # | Finding (reviewer) | Verdict | Disposition |
|---|---|---|---|
| A ≡ FID-F1 | `crud-edge.test.ts` `TestCodedResponseValidationCodes` todos never converted by W4–W8 (both reviewers, MAJOR) | **CONFIRMED** — with a count correction: the true count is **26**, not fidelity's 27 (stub census: W4 ×4, W5 ×6, W6 ×4, W7 ×8, W8 ×4; Python class total 30 = 4 translated + 26 stubbed; vitest pre-fix reported exactly 26 todo; `B6-W3-notes.md` says 26) | FIXED — all 26 converted to real bodies over the existing `makeResultsWorkspace`/`assertCoded` helpers; `makeResultsWorkspace` gained the Python helper's `workspace_id=` twin (`{workspaceId}` → `client.setWorkspaceId`) for the two flags cases (:461/:468 pin 777). All 26 pass — **no latent wrap bug surfaced in any W4–W8 member** (the risk assertions §4 flagged did not materialize). File header rewritten from "the shard converts its todo" to the resolved record. Charge: per P3-3, the miss is booked against W4–W8 (4/6/4/8/4) as a dropped cross-shard hand-off, with a process note below (§Process) |
| B | `workspace-facade.test.ts` drops 8/11 `TestLiveQueries` + 9/11 `TestDiscovery` behind a header claiming the classes whole (assertions, MAJOR) | **CONFIRMED** — drop census re-verified against `test_workspace.py:118-705`; all claimed B5/B6 twins independently located (`discovery-facade.test.ts:99/:112/:127/:137/:147/:191/:210/:224/:233/:255`; `workspace-bookmarks.test.ts:220` `TestQuerySavedReport`, 8 tests) | FIXED per the reviewer's split recommendation: the **7 live-query delegation tests with no Layer-3 twin anywhere** (event_counts :210, property_counts :239, activity_feed :270, frequency :318, segmentation_numeric :343, segmentation_sum :373, segmentation_average :403) are TRANSLATED (delegation-stub pattern already in the file); the 10 with equal-or-stronger twins (`query_saved_report` + the 9 Discovery cases) got a per-test file:line exclusion citation block in the header (R10.2 form). File now 31 tests (24 + 7) |
| C | 6 `pytest.raises(Class, match=…)` sites translated message-regex-only; 4 uncompensated (assertions, minor) | **CONFIRMED** at all 6 sites; the 2 `workspace-facade` limit sites verified compensated by the `TestCodedWorkspaceGuardCodes` class+code twins (:347-390 pre-edit) | FIXED — `rejects.toBeInstanceOf(MixpanelHeadlessError)` added at the 4 uncompensated sites (`governance-data.test.ts` upload timeout/failure; `business-context.test.ts` org_context/project_context), same-promise double-assert pattern. The 2 compensated sites left as-is per the reviewer's own scoping. **R10.4 tally**: B5 (~55 sites) + B6 (6 sites) = two batch recurrences; per the assertions reviewer's note, ONE more batch recurrence triggers a translation-prompt amendment — logged here as the standing tally, no amendment yet |
| D | BIND's `isPlainRecordValue` re-derives `isPythonDict`; dict-guard duplication family hits R10.4 ≥3 (assertions, minor) | **CONFIRMED** — bodies semantically identical; family history verified (B2 F1 blocker, B5 ASR-F3 `isPlainDict`, B6-BIND). Arbiter addendum: the reviewer's "swap for an import" is NOT directly executable — `query/validation-shared.ts` imports `types/index.js` → entities → `model-base.ts`, so the naive import creates a real evaluation cycle (entities `extends EntityModel` at module-eval time). This is very likely WHY the BIND author wrote a local twin instead of importing | FIXED structurally — `isPythonDict` MOVED to the leaf `compat/python-dict.ts` (compat imports nothing above itself, so any layer may import it); `validation-shared.ts` re-exports (every existing consumer path unchanged); `model-base.ts` imports it and the local twin is deleted. **R10.4 amendment FILED**: rulebook watchlist #13 extended (B6-ARB extension — canonical home `compat/python-dict.ts`; standing rule "one named guard per discrimination semantics, import-only"; `isPythonDict` vs `isPlainRecord` semantics named). No regeneration needed — greps confirm zero other local twins remain |
| E | BIND `dumpValue` identity-passthrough fix landed with no red-first unit lock (assertions, minor) | **CONFIRMED** — no test referenced the behavior | FIXED — 2 tests added to `model-base.test.ts` (`model_dump identity passthrough` describe): custom-class member of a `dict[str, Any]` field dumps BY REFERENCE (`toBe`, with and without excludeNone) + `Uint8Array` non-decomposition regression. Red-check executed: with the pre-fix clone-anything walk temporarily re-applied as a mutation, both tests fail; reverted, both pass |
| FID-F2 | `uploadLookupTable` drops Python's two `isinstance(raw, dict)` guards on the register response (fidelity, minor) | **CONFIRMED, with a reachability correction**: through the REAL composed client the non-dict arm is dead code in BOTH languages — `register_lookup_table` itself raises `expected dict, got X` (`api_client.py:7741-7746` = `services/entities/lookup-tables.ts:294-299`) and `_poll_lookup_upload` returns dict-or-raises (`workspace.py:8106-8114`), so the facade-level red test the arbiter first wrote produced the IDENTICAL client error on both sides. The divergence IS reachable at the member seam (`uploadLookupTable(client, …)` takes an injected client — a legitimate library surface, and the exact seam Python's `MagicMock` tests exercise) | FIXED red-first at that seam — new member-level test (`governance-data.test.ts` `hands a non-dict register payload to validation untouched`): injected client returns `["oops"]`; pre-fix the spread mangled it to `{0: …, name: …}` and the error read `missing`/`id`; post-fix the raw list reaches `validateResponseModel` untouched and fails `model_type` with `input: ["oops"]`, exactly as pydantic does. Both guards ported via `isPlainRecord` per packet Caution #10 (`governance-data.ts` uploadId read + name-inject) |
| FID-F3 | R6.2 facade test asserts wrapper identity one level shallower than Python's `id(client._http)` (fidelity, minor) | **CONFIRMED** — `test_workspace_use.py:132-166` asserts the inner pool; pool identity was only locked at the B4 client tests (`client-core.test.ts:283-299`), not through the facade path | FIXED — `ws.client.httpHandle()` captured before and `toBe`-asserted after each of the three `use()` swaps in `workspace-use.test.ts` (wrapper asserts retained) |
| FID-F4 | `set_flag_test_users` maps bare `model_dump()` to `toJSON()` though the exact `modelDump()` twin now exists (fidelity, minor/nit) | **CONFIRMED** — provably equivalent TODAY for `SetTestUsersParams` (one required alias-free field, `extra='ignore'`; verified both sides), so **no red test is constructible**: there is no observable divergence to go red on | FIXED without a red (documented exception to red-first — a pure future-proofing harmonization): `params.modelDump()` + JSDoc updated to cite W8's "toJSON is NOT a substitute" rationale and this ruling |

Nothing was REJECTED outright. Two reviewer sub-claims corrected on the record:
fidelity F1's "the real count is 27" (it is 26) and fidelity F2's implied
reachability through the real client (dead code there; live at the
injected-client member seam — severity unchanged, minor, zero vectors).

---

## Ripples chased

- **Finding D relocation**: `compat/index.ts` exports the new module;
  `validation-shared.ts` keeps `isPythonDict` in its export surface (re-export),
  so all 10+ existing importers (`workspace-query-params`, `bookmarks/*`,
  `query/*`, `replays/rrweb-analyzer`, `client/response-validation`, …) are
  untouched; grep for `isPlainRecordValue` in sources: only the tombstone
  comment remains (`conformance-runner/dist/` is build output, regenerated).
  `model-base.ts`'s OTHER guard `isPlainObject` (:250) is intentionally NOT
  unified: it is the JSON-shape variant used for nested-model payload
  candidacy where Python runs pydantic's mapping check, not
  `isinstance(x, dict)` — distinct semantics, per the amendment's own rule.
- **Finding A helper change**: `makeResultsWorkspace` signature gained an
  optional options bag only; the 4 pre-existing call sites are unchanged.
- **FID-F2 type ripple**: `uploadLookupTable`'s `raw` local widened
  `Record<string, unknown>` → `unknown` (matches Python's untyped flow);
  `uploadStub`'s `registerResult` widened to `unknown` in the test helper.
  `tsc --strict` clean across the workspace.
- **FID-F4**: flags suites re-run green — no dump-shape assert depended on
  `toJSON` semantics (expected: the dumps coincide for this model).
- **Conformance**: full replay re-run post-fix — 3,230/0/21 @ 70c904dc,
  byte-identical counts to the BIND claim (no fix touched a vector-observable
  path).

## Process note (for the gate task and the B7 packet author)

Finding A's root cause is a SEQUENCING inversion, not a shard defect: the
packet ordered W3 last precisely so the cross-entity suites would land against
a complete facade; the orchestrator ran W3 first and the compensating hand-off
protocol (file-header + notes checklist) had no enforcement point — five
shards and the BIND task all missed it. Recommendation recorded for P3-6:
when a packet's sequencing note is inverted at dispatch time, the orchestrator
MUST add the displaced duties as explicit done-criteria lines to the affected
downstream packets (a header protocol alone does not survive shard turnover).
B7/B8 have no cross-shard suite of this shape (doubled review instead), so no
packet change is required there; the B6 gate task should verify 0 todos in
`packages/core/test/workspace` as part of its checklist.

## Gate hand-off (unchanged duties, still gate-owned)

Per both reviews (verified, not re-litigated here): the
`workspace.list_bookmarks_v2` pending-override removal + the B5 exact-name
collapse to the `workspace.` prefix (P3-5 flip rules), the referees (a)+(b)
re-run (P3-7), the differential full-suite regression, `throwaway/` cleanup,
and the §12.5 comment/convention remainder of the UNPORTED-probe re-anchor.

## Commits

- TS repo `main`: `4ae898f` — all seven fixes + tests (12 files,
  +545/−113).
- Python repo `ts-port/phase2-contract-support`: this commit — the
  resolution, the rulebook watchlist #13 amendment, and the fidelity
  review file its author left uncommitted.
