# Phase-2 Design Review — Arbiter Resolution Log

**Date**: 2026-08-15
**Arbiter pass**: independent verification of review-fidelity.md + review-verifiability.md,
then direct edits to `context/phase2/design/phase2-design.md`.
**Branches verified**: Python `ts-port/phase1-addendum` (confirmed via
`git branch --show-current`); TS `mixpanel-headless-ts` main, corpus snapshot
`source_commit d5627564`.

Every finding was independently re-verified against the live repos before action
(runtime introspection via `uv run python`, JSON-aware corpus scans, source reads).
Verdicts: **APPLIED** (design edited), **REJECTED** (with reason), **MERGED**
(duplicate handled under another entry). No lock or gate was weakened; several were
strengthened (anti-vacuity probes, entity goldens, vector-coverage closure).

## Fidelity findings

### F1 (blocker) — ActiveSession `project` field — APPLIED
Verified: `_internal/auth/session.py:309+` — `ActiveSession` has ONLY `account` and
`workspace`, `model_config = ConfigDict(extra="forbid")`, docstring explicitly says
unknown keys including `project` are rejected. Edit: C4 sketch drops `project`,
adds an inline normative comment requiring `parseActiveSession` to reject a
`project` key (extra-forbid parity) and porting the docstring rationale
(project lives on `Account.default_project`).

### F2 (blocker) — ValidationError field list — APPLIED
Verified: `exceptions.py:1255+` — dataclass fields are
`path/message/code/severity/suggestion/fix` (no `field` attribute);
`to_dict()` always emits `{path, message, code, severity}` and conditionally adds
`suggestion` (tuple → list) and `fix` when non-None. Edit: C3 respecs the TS class
with the exact six fields, defaults, and the omit-when-None `toDict()` behavior.

### F3 (blocker) — universal `.df` row contract false; multi-frame surfaces missing — APPLIED
Verified in `types.py`: `SavedReportResult.df` (~1105) non-insights branch returns a
single-row frame with a nested `series` cell; `FlowsResult.df` (~1180) has NO empty
column list; `QueryResult.df` (~9765) picks among 4 column layouts with explicit
`columns=cols`; `UserQueryResult.df` (~11953) has 5 branches + post-frame reorder
(distinct_id, last_seen, alphabetical, ~12059); `FlowQueryResult` exposes
`nodes_df`/`edges_df` (+ `trees_df`) with caches `_df_cache/_nodes_df_cache/
_edges_df_cache/_graph_cache/_trees_df_cache/_anytree_cache`; `SchemaGraphResult`
exposes `events_df`/`properties_df`/`relationships_df` with
`_df_cache/_events_df_cache/_properties_df_cache/_relationships_df_cache/_graph_cache`.
Edit: C6 row contract rewritten — uniform pattern restricted to the classes it holds
for; per-class row specs mandated for the 4 divergent classes; `rowColumns` changed
from static to instance method `rowColumns()` (data-dependent columns); auxiliary
frames get dedicated `to*Rows()` methods with translated tests per frame; full
codec-visible private-cache field surface enumerated. Risk #6 mitigation updated to
cover per-frame test suites.

### F4 (major) — CohortDefinition decode rule misstated — APPLIED
Verified: `conformance/record/codecs.py:477-508` — `'or'` → `any_of`, `'and'` →
`all_of`, anything else raises `UndecodableValueError` (and reconstruction failures
wrap into it). Edit: C7 bullet rewritten with the literal `'or'`/`'and'`/raise
mapping and an explicit note that there is no `'any'` literal and no else-fallback.

### F5 (major) — types.* entry counts wrong; FunnelStep/RetentionEvent phantom coverage — APPLIED
Verified: api-index has **39** `types.*` keys (not 22); recorder registry has **40**
(includes `types.CohortCriteria.did_not_do_event`, which has zero vectors); NO
`types.FunnelStep`/`types.RetentionEvent` anywhere (0 corpus vectors) despite real
`__post_init__` guards (types.py ~9992/~10324); `property_is_set`/
`property_is_not_set` factories unregistered. Decision: **close the holes rather
than downgrade the lock** (the design's own C8(a) anticipates requesting authored
vectors; Risk #3 already budgets support-branch vector work; downgrading would
weaken C3 lock #2). Edits: ground-truth inventory corrected (39/40 + named holes);
P2-1 gains recorder-registry entries + recorded vectors (incl. guard-failure cases)
for the 5 entry points, re-extract + re-pin; C3 lock #2 caveated until P2-1 lands;
C7 binding count 39→44; C9 oracle list corrected (40 registered + 4 starred P2-1
additions, `did_not_do_event` added, FunnelStep/RetentionEvent moved to the
additions line); P2-5a/P2-5b/P2-5c/P2-9 counts corrected (159 / 110+additions /
66+additions / 44 apis); Discrepancy Log #10 records the pre-fix phantom-lock claim.

### F6 (major) — C3 registry-exclusion bullet wrong about CF/CB/B* — APPLIED
Verified at runtime: `CODED_GUARD_REGISTRY` contains BB1–BB8, CA1/CA2, CB1/CB2,
CF1/CF2, UA1/UA2; only V*/U*/UP* rule codes are absent. Edit: bullet rewritten —
V*/U*/UP* absent (Phase-3 B2); CF/CB/CA/UA are Phase-2 constructor-guard codes and
BB1–BB8 Phase-3 builder codes, ALL in the artifact and required in the TS mirror.

### F7 (major) — alias/export counts double-count `__all__` duplicates — APPLIED
Verified at runtime: `len(__all__)=284`, distinct=274; 10 Literal-alias names
duplicated; distinct Literal aliases=37; `BookmarkTypeLiteral` NOT in `__all__`;
functions=5. Edits: ground-truth partition restated as 284 entries / 274 distinct
with the corrected per-kind partition (sums to 274); C1 public-surface and
literals.ts counts 47→37/274; C2 table fixed (types.py contributes 3 public
aliases; BookmarkTypeLiteral dropped from the public table), artifact sketch "47
entries"→"37 entries (distinct names)"; P2-10 coverage map keyed on 274 distinct
names; Discrepancy Log #9 records the duplicate-strings latent nit (do not fix
mid-phase); Discrepancy Log #1 updated.

### F8 (minor) — tag split 6+79 → 5-present+80; grep pseudo-tag — APPLIED
Verified by JSON-aware scan of all 3,322 corpus lines: 85 distinct tags, `date`
absent (0 occurrences), datetime 68 / SecretStr 20 / bytes 18 / callback 17 /
float 2, rich tags=80. Edits: inventory bullet rewritten (5 present built-ins +
80 rich; `date` registered-but-unexercised; JSON-aware counting mandated with the
escaped-`\"$type\"` pseudo-tag warning); C7 "ALL 79 rich tags"→80; P2-7 criterion
made artifact-driven ("the full tag-universe.json rich set — 80 in the current
corpus — registered; no hard-coded count") per the verifiability suggestion; P2-1
done-criterion switched from "matches a corpus grep" to independent JSON-aware
scan.

### F9 (minor) — CA guard family missing from C7 list — APPLIED
Verified: `types.py` ~8717 raises CA1_AGGREGATION_PAIR /
CA2_EMPTY_AGGREGATION_PROPERTY inside `CohortCriteria.did_event`; both in registry.
Edit: CA added to the C7 family list with a note that the C9 error-branch set is
derived from raise-site introspection / the generator artifact, not the prose list.

### F10 (minor) — assorted transcription nits — APPLIED (all sub-items)
Verified each: functions are 5 (list printed); `ResultWithDataFrame` NOT in
`__all__` and `ValidationError` IS (the correct 59th-subtraction); `Session.headers`
is required `Mapping[str, str] = Field(default_factory=dict)` (session.py:145);
ALL 8 `Filter` fields are `_`-prefixed; cache-field surfaces as listed under F3;
`did_not_do_event` in the recorder registry. Edits: inventory partition names the 5
functions; C6 scope sentence names `ValidationError` as the subtraction and notes
RWDF is unexported; C4 `Session.headers` made required with the Python citation;
C7 enumerates all 8 underscore Filter fields as codec-visible; C6 enumerates every
`_*_cache` field for both multi-frame classes; C9 list includes `did_not_do_event`.

## Verifiability findings

### V1 (blocker) — 69/125 entity models with zero runtime verification, deferral unnamed — APPLIED
Verified: 56/125 exported Pydantic models occur as corpus `$type` tags; 69 do not
(incl. Dashboard, Cohort, Bookmark, Annotation, FeatureFlag, Experiment,
ProjectWebhook, EventDefinition, PaginatedResponse, auth/session models); entity
wire vectors DO carry plain `expect.result` payloads (measured 535/608 in
`corpus/entities/` alone), so the suggested golden extension is feasible offline.
Decision: extend the lock rather than name a deferral (naming a 69-model deferral
would hollow out C8's "every type locked" gate — instruction: do not weaken).
Edits: C5 gains item 5 (runtime lock: entity goldens + `model-coverage.json`
artifact emitted by P2-1: model → corpus-tag | golden vector ids | authored
fixture | named deferral row with owner; a model with none is a P2-7 failure);
C8(b) retitled "Result-shape + entity-model golden tests" with the scope-extension
bullet; ground-truth inventory records the 56/69 split; P2-7 and P2-10
done-criteria reference `model-coverage.json`.

### V2 (major) — phantom locks + entry arithmetic — MERGED into F5
Same defects verified once; all edits listed under F5 (39/40/44 counts, P2-5a=159,
P2-5c=66, `did_not_do_event` added, P2-1 closure work, Discrepancy Log #10).

### V3 (major) — vacuous-pass admissibility of sweep + goldens — APPLIED
Verified by reading the design's own C8 text: sweep asserted diff-equality only;
goldens compare `toJSON()` against the very payload `fromDict` consumed; the ~50
model tags carry no error vectors, so decode-to-plain-object round-trips cleanly.
Edits: C8(a) gains a mandatory anti-vacuity bullet (decoded product must be
`instanceof` the registered core class; SecretStr round-trip must preserve the
revealed value); C8(b) gains a mandatory per-golden mutation probe (unknown-key
strict-decode error for strict/forbid classes, or `Object.keys(toJSON())` equality
against a statically declared field list for lax models); P2-8 gains the
raw-payload-retention audit grep over `packages/core/src/types/`.

### V4 (major) — SecretStr migration incompatible with runner codecs.ts — APPLIED
Verified in `conformance-runner/src/codecs.ts`: `register()` throws on built-in
shadowing (SecretStr is a built-in), the built-in decode arm constructs
`SecretValue` in place (~line 342), the encoder branches on
`value instanceof SecretValue` and reads the public `.value` (~line 425) — core
`Secret` hides the value behind `reveal()`/`#value` and its `toJSON()` masks.
Also verified the 42 compat/wirestub vectors carry no SecretStr tags. Edits: C7
step 2 respecced as explicit codecs.ts edits (decode arm constructs core
`new Secret(...)`; encode branch uses `instanceof Secret` + `value.reveal()`,
never `toJSON()`; `SecretValue` survives only as `type SecretValue = Secret`),
with the gate-honesty note that the behavioral lock is the sweep over the 20
extracted SecretStr occurrences (plus the new revealed-value assertion), not the
42 gate.

### V5 (minor) — 79 vs 80 rich tags in P2-7 criterion — MERGED into F8
Same off-by-one; P2-7 criterion made artifact-driven, no hard-coded count.

### V6 (minor) — runner batch table does not exist — APPLIED
Verified: `runner.ts` returns UNPORTED purely on missing implementation
(~340-359); "declared done" only in comments (runner.ts:21, verdicts.ts:16); no
batch-table module or data shape anywhere. Edits: C7 item 4 rewritten to state the
table does NOT exist and spec the new module
(`conformance-runner/src/batch-status.ts`: declarative api-prefix →
pending/done map, verdict-path wiring so done-prefix + no implementation = FAIL,
unit test for both semantics); P2-8 file list names the module explicitly.

### V7 (minor) — dead strategy-file citation — APPLIED
Verified: `tests/test_query_types*.py` matches nothing; real files are
`tests/test_types_{funnel,retention,flow,flow_tree}_pbt.py`,
`tests/test_cohort_definition_pbt.py`, `tests/test_cohort_behaviors_pbt.py`,
`tests/test_custom_property_pbt.py`, `tests/test_user_query_pbt.py`, plus
`tests/pbt/*` (account/session/resolver/config strategies). Edit: C9 fuzz-strategy
paragraph cites the real list and flags the dead glob.

## Rejections

None. Every claim in both reviews reproduced under independent verification;
no finding was rejected, and the two overlapping findings (V2, V5) were merged
into their fidelity twins rather than double-applied.

## Cross-cutting ripple check

- All occurrences of the stale counts (47 aliases, 22 entries, 79 tags, 6
  functions, 284-name maps, ~200/~85 vector estimates, static `rowColumns`)
  were grepped for after editing; none remain outside the Discrepancy Log's
  historical notes.
- New P2-1 scope (5 recorder entries + vectors, `model-coverage.json`) ripples
  into: C3 lock #2, C7 binding counts (44), C9 oracle list, P2-5b/P2-5c/P2-7/
  P2-8/P2-9/P2-10 done-criteria, Risk #3 (already budgeted this workflow),
  Discrepancy Log #10. All updated.
- No gate weakened: the 42-PASS gate, sweep, goldens, registry equality, and
  differential budget all survive; anti-vacuity and entity-golden requirements
  are additive.

## Human calls needed

None. All resolutions were decidable from the rulebook + plan + repo evidence:
the two judgment calls (close the FunnelStep/RetentionEvent/factory recorder
holes on the support branch rather than downgrade the lock; extend goldens to
entity models rather than name a 69-model deferral) both follow directly from
the standing instruction that locks and gates must not be weakened, and both
reuse mechanisms the design already budgets (Risk #3 support-branch vector
workflow; C8(b) golden machinery).
