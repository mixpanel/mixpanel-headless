# B5 adversarial review — ASSERTION FIDELITY + BINDING HONESTY lens (P3-2d, fable)

**Reviewer**: assertion-fidelity/binding-honesty half of the B5 pair.
**Date**: 2026-08-16. **Scope**: all B5 commits since B5-DL — TS `2981570`
(S1), `2458df3..62dc07c` (S2, 26 commits), `0f441bd` (S3), `952a2cf`
(B5-BIND); Python `73631c5..28cc207` (packets, shard notes, goldens,
oracle strategies). Spec: `b5-packets.md` v1.0 + playbook v1.1.
**Verdict: GO with findings** — 2 MAJOR (both fixable at/before the gate,
neither blocks vector or test greenness), 4 MINOR. No blocker: every
inbound deferral-ledger item verifiably landed, the 506-vector replay
reproduces exactly, and all three shard harness RUN records reproduce
from their recorded seeds.

---

## 1. Independent verification performed (evidence)

### 1.1 The 506-vector replay (confirmed myself)

- Full corpus: `npm run conformance` @ pin `70c904dc598d` →
  **3,251 — 2,876 PASS / 0 FAIL / 375 UNPORTED** (B4 baseline 2,370/881
  → +506/−506, the exact packet §1 gate delta; batch-status table
  verified UNTOUCHED — flip correctly left to the gate task).
- Per-family filtered runs (trailing-slash filter list): build_params/
  143, build_funnel_params/ 95, build_user_params/ 80,
  build_retention_params/ 55, build_flow_params/ 53, query_saved_report/
  37, query_saved_flows/ 6, retention/ 3, funnel/ 3, replays.fetch_files/
  8, `replay_labels.` 16, `rrweb_analyzer.` 2 — all N/N PASS, matching
  the packet §1 table cell-for-cell.

### 1.2 Binding honesty (P3-5 rule 3) — per binding

- `wire-workspace.ts`: all **44** `workspace.<member>` names registered
  (counted; matches the §7.1 generated list). Sampled bindings
  (`query_saved_report`, `query`, `build_params`, `query_funnel`,
  `build_funnel_params`, `stream_replay`) all call the REAL facade
  member (`ws.querySavedReport(...)` etc.); no request assembly, no
  re-derived transforms. `stream_replay` drains the real
  `AsyncGenerator` item-by-item (the Python runner's Iterator branch
  twin) — no shim generator.
- `workspaceFromSession`: memoized under the single `"workspace"` state
  key; client shared via `CLIENT_STATE_KEY`/`clientFromSession` (setup
  entries mutate the same instances — P3-5 mandate). Builder-kind
  vectors: synthetic `_DEFAULT_SESSION_VALUES` session + EMPTY
  `VectorFetch` (network attempts fail loudly). Facade session
  precedence `workspace_session ?? session ?? synthetic` matches
  `execute.py`.
- `replays-bindings.ts`: all 9 replays-family names; wire names bound to
  a REAL `ReplaysService` over `clientForContext` + `harness.fetch` as
  the CDN seam (`targets.py:331-346` mirror); no unordered_group
  special-casing (packet R6.4 bullet).
- Sanctioned adaptations only: kwarg plumbing, the U8 `today` seam
  (library-level `TodayFn` option, not a rig-only backdoor), recorder
  float-token twins (each cites its Python-float-typed field).
- §6.5 `toExpectError` `errors[]` extension for `BookmarkValidationError`
  — landed (`bindings.ts:539-553`). §6.7 UNPORTED-probe re-anchor →
  `workspace.me` in `oracle-protocol.test.ts` ×2; `runner.test.ts` was
  already anchored on B6 names (verified — no change needed). §6.8
  `workspace.me` NOT bound (checked the registration list).
- Oracle strategies: `PHASE3_B5_TARGETS` present in
  `conformance/differential/strategies.py` (9 servable families).

### 1.3 R10.9 harness re-runs (review item 5)

- **S1** (`throwaway/b5-s1`): fully re-ran py-side (seed 20260816) +
  ts-side + compare → **5,522 compared / 0 divergences** — reproduces
  RUN.md exactly. This matters most for S1: zero corpus vectors, so the
  harness + Layer-3 are its only locks.
- **S2** (`throwaway/b5-s2`): fully re-ran all three stages →
  **2,678 compared / 12 divergences** (2 flow-operand + 10 engage-where),
  exactly the RUN record's residual F1 class (integral-float spelling
  through JSON transport); 966 raises across 36 registry codes
  class-and-code identical. T1/T2 AttributeError fixes verified fixed at
  the owning layer with class-typed regression tests
  (`transform-funnel.test.ts` R10.9 describe, minted `AttributeError`
  twin).
- **S3** (`throwaway/b5-s3`): re-ran compare over the committed outputs →
  **2,080 compared / 20 divergences**, all the documented int/float
  narrowing — reproduces RUN.md exactly.
- Repo left clean afterward (regenerated artifacts removed; committed
  s3 outputs restored byte-identical).

### 1.4 R10.2 mechanical diff — every translated file

Per-file `def test_` vs `it(` counts (parametrize/`it.each`/loop-generated
cases resolved by per-class inspection where static counts diverged):

- Exact matches: live_query (41→40+1 header-cited), live_query_pbt 10,
  phase008 31, flow 19, bookmarks 19, transform_retention 40,
  validation_bypass 20, bypass_r2 16, query_params 82, workspace_flow 49,
  build_cohort_params 76, workspace_funnel 18, workspace_retention 11,
  workspace_cohort 19, build_user_params 68, query_user 47, aggregate 45,
  integration 36, parallel 48, edge_cases 28, discovery_pbt 14,
  discovery_bookmarks 10, workspace_replays 39, replays_service 27,
  rrweb_analyzer 41 (it.each covers both parametrized classes).
- Reconciled partials, all header-cited with correct arithmetic:
  query_validation 76 = 45 here + 8 direct-validator cases + 23
  (TestValidateTimeArgs 12 + TestValidateGroupByArgs 11) — all 31
  verified PRESENT in the B2 `query/query-validation.test.ts`;
  custom_property_types 40 = 37 + TestImmutability 3 (R4.6 no-freeze);
  lexicon_schemas 37 = 33 + 4 frozen cases; discovery 62 = 60 + the
  stacklevel case (cited) + parametrize artifact; schema_graph 38 = 22 +
  TestSchemaGraphResult Phase-2 half (6 to_graph cases re-homed
  verbatim) + 2 CLI cases; query_user_structural 13 = 8 + 5 in the four
  B3-K3/K4-translated classes (citations verified);
  replay_bundle 34 = labels 8 + analyzer 2 + aggregators 8 + Phase-2 16,
  with the four Phase-2-excluded asserts (`test_elements_df`,
  `..._normalizes_urls`, `test_error_sessions`, `test_sample_determinism`)
  verified alive in `aggregators.test.ts`.
- Additive-only surpluses, correctly labeled non-substitutive:
  transform_funnel +4 (the R10.9 regression describe),
  query_integration +1, `discovery-facade.test.ts` (18 additive
  zero-vector facade locks, Caution #13, header disclaims substitution).
- All 43 B5 test files re-run: **1,513/1,513 green**.
- Zero `.skip`/`.todo` in any B5 test file.

### 1.5 Deferral-ledger closure (blocker check — all inbound items landed)

Every §8 inbound row verified on disk: bypass WHOLE ×2 ✓;
query_validation facade classes ✓ (reconciled above); query_user_edge_cases ✓;
**transform_funnel/transform_retention (B3-K3) ✓** (40/44 + 40/40,
spot-diffed TestTransformRetentionErrors statement-for-statement);
structural 8-classes ✓; TestMeasurementPropertyBuilder appended (4 tests) ✓;
bookmark_builders_pbt 3 equivalence classes ✓; build_cohort/query_params ✓;
`response_validation` correctly NOT re-ported (its only consumers are B6
CRUD members — verified in Python source); 3 label fns exported from
`index.ts` ✓; Phase-2 TODO closures (replays.ts:15, query-engine.ts
831/1170, discovery.ts:1083) all closed ✓; toExpectError ✓; re-anchor ✓.
S3-D1: CPython MT19937 parity PORTED (`compat/python-random.ts` + 168-row
pinned probe) — the packet-recommended path, no silent PRNG substitution.
S1 sequencing deviation (S1 built the skeleton, not S2) disclosed in the
commit + `B5-S1-notes.md` §0 — accepted, section markers intact.

### 1.6 Rulebook greps (R4.8 / R11.7 / watchlist-13 / GATE-R5 / R6.6)

- R11.7: zero `.trim(`/`parseInt`/`\s`-regex in B5 src. `Number()` hits
  audited individually: all are regex-anchored ASCII-digit groups,
  post-`isPyInt` numeric narrowing, or BigInt→number — none is a Python
  `int(str)`/`float(str)` twin. (One PRE-EXISTING Phase-2 site noted in
  finding F6.)
- GATE-R5: no `response.json()`/bare `JSON.parse` in B5 src (comment
  hits only); CDN 200 path uses parseLossless+pythonConstants.
- watchlist-13: `isPythonDict` imported in discovery/transforms/replays/
  rrweb — but ONE local re-derivation found (finding F3).
- R4.8: membership via `Object.hasOwn` throughout except three
  fixed-literal `"text" in obj` sites in rrweb-analyzer (finding F4).
- R6.6: `workspace.streamReplay` is `async *` with item-level `yield*`
  over `walkCdnAsync`; `walkCdnAsync` is a true `async function*`
  yielding per-event — no array-collect shim anywhere in the facade
  streaming path. Walker fidelity spot-verified: batch loop, 403
  re-sign-once + whole-batch refetch, `buildExpiredError(signed)` with
  the ORIGINAL handle (Caution #4), file-0 404 → not-found, mid-walk 404
  sentinel with survivors-first, mobile check on first non-empty file,
  per-file stable sort by `pythonIntCoerce(timestamp)` (Caution #3).
- Transform math: division guards transcribed statement-for-statement
  (`steps[0].count > 0`, `prev_count > 0`, step-0 literal `1.0`,
  empty-cohort `0.0`) — Caution #1 satisfied; the 6 authored transform
  vectors PASS.

---

## 2. Findings (ranked)

### F1 — MAJOR (R10.2 assertion weakening, systematic): exception-CLASS
### asserts dropped from ~55 `pytest.raises(<Class>, match=...)` translations

Python asserts BOTH the exception class and a message substring; the TS
translation asserts the message substring only (`.rejects.toThrow(/…/)`
matches ANY error whose message matches). Quantified (Python class-typed
raises → TS class asserts in file):

| file | py class-raises | TS class asserts |
|---|---|---|
| `workspace/validation-bypass.test.ts` | 8 × BookmarkValidationError | **0** |
| `workspace/validation-bypass-r2.test.ts` | 12 × BookmarkValidationError | **0** |
| `workspace/query-validation-facade.test.ts` | 18 × BookmarkValidationError (+ParamValidationError ctor raises) | **0** (31 message-only throws) |
| `workspace/custom-property-types.test.ts` | 14 × BookmarkValidationError | **0** on those sites |
| `workspace/query-user-edge-cases.test.ts` | 2 | 0 (5 other tests assert codes) |
| `services/transform-retention.test.ts` | partial (2 of 7 raise-sites message-only) | class asserted on the other 5 |

Aggravating evidence: the `validation-bypass.test.ts` header (line 16-18)
CLAIMS "`pytest.raises(BookmarkValidationError, match=…)` translates to a
class + message-substring assertion" — the class half was not actually
written. Contrast: sibling S2/S3 files do it right
(`query-user-parallel.test.ts:483` `toBeInstanceOf(BookmarkValidationError)`
+ code assert; `rrweb-analyzer.test.ts:257-258` class AND message;
`build-cohort-params.test.ts:473`). So the correct pattern was in-shard;
these files just didn't use it.

Failure mode locked out by Python but not by TS: a regression that
throws a different class (plain `Error`, `ParamValidationError`,
a `TypeError` from a broken guard) carrying the same wording passes
these suites where the Python originals fail. Codes-not-messages note:
none of these sites asserts `.code`/`errors[]` either, so the message
substring is currently the ONLY discriminator — strictly weaker than
Python on both axes available.

**Ask**: add the class assert (`.rejects.toBeInstanceOf(...)` or the
try/catch `toBeInstanceOf` + match pattern already used elsewhere) at
each site, and correct the bypass header. Mechanical, test-only fix;
pre-gate.

### F2 — MAJOR (deferral-ledger integrity): two NEW outbound deferrals
### exist only in TS test-file headers — absent from every notes file

1. `TestWorkspaceFacadeScoping` (:379) — packet §3/§8 assigned it to S2's
   `facade-scoping.test.ts`; the shard correctly discovered it depends on
   `ws.use(workspace=4242)` (a B6-W1 stub) and deferred it to B6-W1
   (header, `facade-scoping.test.ts:1-25` — verified against the Python
   source: the case does call `use()`; the packet's routing was wrong).
2. `TestListCustomPropertiesErrorHandling` (:260) — packet said
   "translate against the B4 client method"; the shard verified the
   contract under test is the FACADE re-raise wrapper
   (`workspace.py:7742-7790`, `list_custom_properties` = api-map batch
   B6) which the B4 client does NOT perform, and deferred to B6
   (header, `custom-property-query.test.ts:9-22` — reasoning verified
   correct).

Both deferrals are legitimate and well-reasoned, BUT: `grep` of
`context/phase3/notes/B5-*.md` finds NEITHER (no mention of
`FacadeScoping` or `list_custom_properties` in any notes file), and the
packet §8 outbound list predates them (it names only
`TestDiscoveryCacheAcrossUse`). The B6 design-lite author works from the
P3-1 row + notes + the b5 outbound list — a header-only deferral is
exactly the shape that gets silently dropped, losing the only Python
lock on `use()`-workspace-scoping threading and on the displayFormula
re-raise. **Ask**: the gate task's `B5-notes.md` finalization MUST carry
an outbound-deferrals section listing all FOUR B6-bound items
(TestDiscoveryCacheAcrossUse, TestWorkspaceFacadeScoping,
TestListCustomPropertiesErrorHandling, list_bookmarks_v2-override
removal), and the B6 packet author should be pointed at it.

### F3 — MINOR (watchlist #13 / R10.4 amendment): local `isinstance(x, dict)`
### re-derivation

`workspace-query-params.ts:2160-2168` defines a private `isPlainDict`
for the `in_cohort` payload walk — semantically identical to
`isPythonDict` (`validation-shared.ts:323-329`) but the amendment says
"import `isPythonDict` … never re-derive" precisely because this pattern
already recurred 4× at B2. No behavioral divergence today (the logic is
byte-equivalent); replace with the import.

### F4 — MINOR (R4.8 letter): three `"text" in obj` prototype-membership
### tests in `rrweb-analyzer.ts` (:398, :473, :1127)

Fixed literal key `"text"` on plain-literal `TrackedNode` records —
`Object.prototype` has no `text`, so no divergence is reachable; but
R4.8 mandates `Object.hasOwn` for object-literal membership and the rest
of the shard complies. Cheap consistency fix.

### F5 — MINOR (TODO(port) triage, review item 4): stale marker
`workspace.ts:757-769` still says the `_replays_service` accessor is
missing and "**S3 must add it here**" — S3 landed it (as
`replaysService` get/set at :2003-2026, in the S3 section rather than
the S2 section the packet §2 assigned). Behavior fine; the marker is now
false and should be removed (or rewritten as a placement note) so the
gate's TODO triage doesn't re-litigate it.

### F6 — MINOR (observation for the arbiter, two parts)

(a) The residual integral-float-spelling divergence class the S2/S3
harnesses disclose (flow `filter.operand` "18.0"→"18"; engage `where`
"… <= 18.0"→"18"; rrweb console-message join "18.0 None"→"18 None") is
real library-output divergence for Python callers passing `18.0`, argued
under R10.11/`toNativeJson`-contract in RUN records and shard notes
only. Precedent (#6/#7/#9-#11) puts sanctioned deviation CLASSES in the
playbook Discrepancy log — recommend the arbiter either logs it or
records why R10.11 already covers all three surfaces.
(b) Pre-existing Phase-2 site `types/results/query-engine.ts:425-433`
(`overall_conversion_rate`): `Number(value)` on a string ports Python
`float(str)` — R11.7 (amended AFTER Phase 2) would require
`pythonFloat` (`Number("")` → 0 where Python raises; `"inf"` casings
diverge). Not B5-authored (blame: P2-6 commit `2ee9f59`) but it sits on
a B5-touched file and the B0-gate remediation missed it — worth a
straggler ticket rather than silence.

---

## 3. Positive attestations (for the arbiter's GO/NO-GO)

- Binding honesty: PASS for all 53 registered names (44 workspace + 9
  replays-family).
- 506-vector replay: PASS, reproduced independently, per-family counts
  exact, batch-status untouched.
- R6.6 streaming: PASS (no array-collect shims in facade streaming).
- Inbound deferral ledger: COMPLETE — nothing missing (the blocker
  condition does not fire).
- Harness RUN records: all three reproduce from recorded seeds; the two
  in-flight fidelity fixes (AttributeError twins, ValueError/RuntimeError
  catch-arm widening in `user-validators.ts`) verified faithful to
  Python at the owning layer with regression tests.
- 1,513/1,513 translated tests green; zero skips; header exclusions all
  carry design citations with arithmetic that reconciles.
