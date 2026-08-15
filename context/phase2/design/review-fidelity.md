# Phase-2 Design Review — Lens: CONTRACT FIDELITY

**Reviewer**: adversarial fidelity lens (independent agent)
**Target**: `context/phase2/design/phase2-design.md`
**Repos verified**: Python `ts-port/phase1-addendum` (confirmed via `git branch --show-current`), TS `mixpanel-headless-ts` corpus snapshot @ `source_commit d5627564`.
**Method**: every claim below was re-measured against live source / corpus; findings cite file:line or a reproducible command result.

---

## Findings (ranked)

### F1 — BLOCKER — C4 `ActiveSession` sketch adds a `project` field Python explicitly forbids

Design C4 sketch:

```ts
export interface ActiveSession { readonly account?: AccountName | null; readonly project?: ProjectId | null;
                             readonly workspace?: WorkspaceId | null; }
```

Reality (`src/mixpanel_headless/_internal/auth/session.py:309-327`): `ActiveSession`
has ONLY `account` and `workspace`, with `model_config = ConfigDict(extra="forbid")`
and a docstring that says verbatim: *"Only `account` and `workspace` live in
`[active]`. Project lives on the account itself as `Account.default_project` …
Unknown keys (including `project`) are rejected by `extra='forbid'`."*

Failure scenario: a TS `ActiveSession` with a `project` member locks a wrong auth
shape — a TS-serialized `[active]` block with `project` set is REJECTED by the
Python model, and a TS parse factory that accepts `project` silently diverges from
Python's extra-key rejection. Phase-3 B7/B8 (config/bridge round-trip) inherits the
divergence. Nothing in the Phase-2 gates catches it: `ActiveSession` has no `$type`
corpus tag, so the codec sweep never sees it.

Fix: drop `project` from the interface; port the docstring note.

### F2 — BLOCKER — C3 `ValidationError` field list is wrong (wrong name, two fields missing)

Design C3: *"`ValidationError` (the dataclass) ports as a plain class in `errors.ts`
with `field`/`code`/`message`/`severity` fields exactly as Python defines it."*

Reality (`src/mixpanel_headless/exceptions.py:1255-1319`): the dataclass fields are
`path`, `message`, `code` (default `"VALIDATION_ERROR"`), `severity`
(`Literal["error","warning"]`, default `"error"`), `suggestion: tuple[str,...] | None`,
`fix: dict[str, Any] | None`. There is no field named `field`. `to_dict()` emits
`{path, message, code, severity}` and conditionally adds `suggestion` (as a list) and
`fix` when non-None.

Failure scenario: a TS class built to the design's spec serializes
`BookmarkValidationError.errors` entries with a `field` key and no
`path`/`suggestion`/`fix` — every future B2/B3 validation-error vector (680 of them)
that carries serialized ValidationErrors diffs against Python, and the Phase-2
"error-shape unit tests" would be written against the wrong key set. The design
labels this "exactly as Python defines it," so an implementer has no reason to
re-check the source.

Fix: correct the field list to `path/message/code/severity/suggestion/fix` and spec
`toDict()`'s conditional-omission behavior (which incidentally is a per-field case of
the design's own R4.11 rule).

### F3 — BLOCKER — C6 row contract falsely claims "every Python `.df` follows one pattern"; `static rowColumns` is unimplementable for several classes

Design C6 (generalizing from 3 representatives): *"every Python `.df` follows one
pattern: build `rows: list[dict]` with hand-named lowercase keys, then
`pd.DataFrame(rows)` (empty input → empty frame with a fixed column list)"*, plus
*"Each class also exposes `static readonly rowColumns: readonly string[]` = the
Python empty-frame column list."* Measured counter-examples (all in
`src/mixpanel_headless/types.py`):

- **`SavedReportResult.df`** (1074-1113): only the `insights` branch builds rows;
  the retention/funnel/flows branch returns
  `pd.DataFrame([{"series": self.series}])` — a single-row frame whose one cell is
  the raw nested dict. No rows list, no fixed columns; the shape depends on
  `report_type` (a derived property).
- **`FlowsResult.df`** (1170-1183): `pd.DataFrame(self.steps) if self.steps else
  pd.DataFrame()` — columns come from arbitrary step-dict keys; the empty frame has
  NO columns, so `rowColumns` would be `[]`, which is not "the CSV-header contract".
- **`QueryResult.df`** (9765-9848): FOUR alternative column layouts
  (`["date","event","segment","count"]` / `["event","segment","count"]` /
  `["date","event","count"]` / `["event","count"]`) selected by data shape, and the
  non-empty path passes `columns=cols` (column selection/order is part of the
  contract, not just the rows list). A single static `rowColumns` cannot represent
  this.
- **`UserQueryResult.df`** (11953-12065): five branches by mode/shape; profiles mode
  applies a post-frame column reorder (`distinct_id`, `last_seen`, then remaining
  alphabetical — 12059-12065) that the "rows list before pandas" does not carry, and
  the documented NaN-fill across ragged profile rows is part of the class's contract
  (docstring 11959-11976), unlike the RetentionResult case the design carves out.
- **Multi-frame classes unaddressed**: `FlowQueryResult` (11041) exposes
  `nodes_df`/`edges_df` and per-tree frames with three dedicated cache fields
  (11085-11089); `SchemaGraphResult` (11507) exposes
  `events_df`/`properties_df`/`relationships_df` (11560-11566). C6 replaces only
  `.df` with `toRows()` and says nothing about these public DataFrame surfaces —
  they'd be silently dropped from the port or improvised per-implementer.

Why blocker rather than major: `toRows()` is the one Phase-2 contract with NO vector
or oracle lock (design's own C8(b)/risk #6 note) — a wrong shape locked here is
undetectable by every gate in the plan and surfaces only when a human consumes it in
Phase 3+.

Fix: reduce the claim to the classes it is true for (the C6-a/C6-b simple results,
verified: `SegmentationResult` rows `{date,segment,count}` 306-321, `FunnelResult`
`{step,event,count,conversion_rate}` step-from-1 397-412, `RetentionResult` ragged
`period_i` 487-501 — all accurate), and give `SavedReportResult`, `FlowsResult`,
`QueryResult`, `UserQueryResult`, `FlowQueryResult`, `SchemaGraphResult` per-class
row/column specs (including the auxiliary `*_df` surfaces), replacing the
one-size-fits-all `rowColumns` static with whatever each class actually needs
(possibly an instance method `rowColumns()` for the dynamic cases).

### F4 — MAJOR — C7 `CohortDefinition` decode rule misstates the operator mapping

Design C7: *"operator `any`→`anyOf`, else `allOf`, unknown operator →
`UndecodableValueError`"* — internally contradictory ("else allOf" vs "unknown →
error") and factually wrong on the literal. Reality
(`conformance/record/codecs.py:477-508` + runtime check): `_operator` is `"or"` →
`any_of`, `"and"` → `all_of`, anything else raises `UndecodableValueError`.
Confirmed live: `CohortDefinition.any_of(...)._operator == 'or'`,
`all_of(...)._operator == 'and'`.

Failure scenario: an implementer following the written rule decodes an
`"_operator":"or"` payload through the "else allOf" arm — every `any_of` cohort
vector (44 `CohortDefinition` tag occurrences in the corpus) rebuilds as the wrong
combinator. The round-trip sweep WOULD catch it (re-encode emits `"and"`), but the
spec as written directs the implementer into the bug and the debugging cost lands in
P2-5b.

Fix: state the mapping as `"or"→anyOf`, `"and"→allOf`, else throw.

### F5 — MAJOR — `types.*` entry counts are wrong everywhere they appear, and two C7 classes have no direct vectors at all

- Design ground-truth: *"22 of the builder entries are `types.*` names"*; C7 step 3:
  *"registers an implementation per `types.*` api-index entry (22 entries)"*; P2-9
  gate: *"green over all 22 `types.*` apis"*. Measured: `api-index.json` has **39**
  `types.*` entries (each Filter/CohortCriteria/CohortDefinition static is its own
  entry); the Python D4 builder registry (`conformance/record/*.py`) has **40**
  (adds `types.CohortCriteria.did_not_do_event`, which has zero extracted vectors).
  Even the design's own C9 enumeration counts to 24 grouped names, not 22.
- Design C9 lists `types.FunnelStep` and `types.RetentionEvent` among the oracle
  entry points *"all already in the D4 builder registry, hence callable through
  oracle-py's `oracle.call` today"*. **Neither exists** in the api-index NOR in the
  Python builder registry (grep of `conformance/record/*.py` — no
  `types.FunnelStep` / `types.RetentionEvent`), and the corpus has zero vectors with
  those `call.api` values. Consequences:
  - C3 lock #2's claim that *"the 395 `types.*` vectors include every recorded
    guard-failure test for the C7 families"* is false for `FunnelStep` (FS1 via
    `_validate_event_name`, types.py:10044-10050) and `RetentionEvent`
    (types.py:10324+) — their constructor guards get no vector replay.
  - P2-5c's done-criterion "their vectors (~85) PASS" implies vector coverage for
    FunnelStep/RetentionEvent that does not exist (their tags appear only nested
    inside other vectors, exercised by the codec sweep, which fires guards on decode
    — partial, but not the guard-failure lock the design asserts).
  - P2-9's differential gate cannot run `oracle.call` on FunnelStep/RetentionEvent
    without first ADDING registry entries on the support branch — unplanned Python
    work the design doesn't schedule.
  - `CohortCriteria.property_is_set` / `property_is_not_set` (public factories,
    confirmed via `dir(CohortCriteria)`) appear nowhere in the design, the corpus,
    or the C9 oracle list.

Fix: correct all counts to the measured 39 (index) / 40 (registry); either add
oracle registry entries + authored vectors for FunnelStep/RetentionEvent/
did_not_do_event/property_is_set/property_is_not_set, or downgrade the C3/P2-5c
claims to name the codec-sweep + translated-test lock those classes actually get.

### F6 — MAJOR — C3's registry-exclusion bullet contradicts both the generator spec and the registry contents

Design C3: *"The V*/B*/CF/CB/U*/UP* validator-rule code families are NOT in this
artifact."* Measured `CODED_GUARD_REGISTRY` (120 codes) **contains**:
`CF1_COHORT_ID_NOT_POSITIVE`, `CF2_COHORT_NAME_EMPTY` (raised by the
`Filter.in_cohort` family — Phase-2 C7 code, types.py:7686-7757),
`CB1_COHORT_ID_NOT_POSITIVE`, `CB2_COHORT_NAME_EMPTY` (CohortBreakdown, Phase-2),
`BB1`–`BB8` (bookmark_builders, Phase-3 B3), `UA1`/`UA2` (UserAction, Phase-2
C6-d). Only V*/U*/UP* rule codes are genuinely absent (V-codes appear solely as 5 of
the 9 twins). Since the generator dumps the entire frozenset (*"coded_guard_registry:
[...120 codes...]"*), no exclusion happens — the bullet is wrong about what the
artifact contains and mislabels Phase-2-raising CF/CB codes as Phase-3 validator
codes. An implementer reconciling the bullet against the artifact will burn time, or
worse, filter CF/CB out of the TS mirror and fail the equality gate.

Fix: reword to "V*/U*/UP* rule codes are absent (they live in validation.py /
user_validators.py, Phase 3); CF/CB/BB/UA ARE registry codes — CF/CB/UA fire in
Phase-2 constructors, BB in Phase-3 builders."

### F7 — MAJOR — C2 alias enumeration: 47 counts duplicate strings (37 distinct), and `BookmarkTypeLiteral` is not exported

- `len(mixpanel_headless.__all__) == 284` but only **274 distinct names** — 10 alias
  names are listed twice in `__init__.py`'s `__all__` (`MathType`,
  `PerUserAggregation`, `FunnelMathType`, `RetentionAlignment`, `RetentionMode`,
  `RetentionMathType`, `CustomPropertyType`, `FilterOperator`,
  `FilterPropertyType`, `FilterDateUnit` — e.g. `__init__.py:332` + `:573` for
  `MathType`). The "47 Literal aliases" are 47 list entries = **37 distinct
  aliases**. Any generator keyed by name emits 37 entries, so the design's
  "literal_aliases: { ... 47 entries ... }" artifact sketch and every downstream "47"
  is wrong, and P2-10's "284-export coverage map (each name)" is a 274-name map.
- The C2 table lists `BookmarkTypeLiteral` among the "4 public" types.py aliases.
  Measured: `'BookmarkTypeLiteral' in mp.__all__` → **False** (types.py defines it
  but it is not exported). The distinct-alias arithmetic that actually holds is
  32 (`_literal_types`) + 3 (`BookmarkType`, `SavedReportType`, `EntityType`) +
  2 (`Region`, `AccountType`) = 37. A hand-written `literals.ts` that includes
  `BookmarkTypeLiteral` per the design fails the set-equality snapshot gate
  (flaky-gate rework), or the export surface gains a name Python doesn't ship.

Fix: state 274 distinct / 37 aliases, note the 10 duplicate `__all__` strings
explicitly (they are also a latent Python-side cleanup candidate — record, don't
fix, per R10.7 posture), and drop `BookmarkTypeLiteral` from the public table.

### F8 — MINOR — tag-universe arithmetic off by one; no `date` tag exists in the corpus

Measured distinct real `$type` tags = **85**, but the split is **5 built-ins
(`datetime`, `SecretStr`, `bytes`, `callback`, `float`) + 80 model tags** — the
`date` built-in never occurs (design says 6 + 79). All 80 model tags are Phase-2
types (79 in `__all__` + `OAuthTokens` via `auth_types`), so the scope conclusion
stands, but P2-7's done-criterion *"all 79 rich tags registered"* is off by one —
literally applied, the sweep allowlist is non-empty at 79 and P2-8 blocks. Beware
also: a naive `grep '"$type"'` over the JSONL yields an 86th pseudo-tag from an
ESCAPED `\"$type\": \"datetime\"` inside a string value — the tag-universe
generator (P2-1) must parse JSON, not grep, or its "matches a corpus grep exactly"
done-criterion will disagree with itself.

### F9 — MINOR — C7 guard-prefix list omits the `CA` family (CohortCriteria aggregation guards)

`CA1_AGGREGATION_PAIR` / `CA2_EMPTY_AGGREGATION_PROPERTY` are registry codes raised
inside `CohortCriteria.did_event` (types.py:8717-8723) — Phase-2 C7 code — but the
C7 code-family enumeration ("the CF/CB/CM/CD/TC/MT/FM/LC/FD/LG/GB/EV/FB/FF/EX/HC/
FS/UA codes") omits `CA`. C9's mandatory error-branch edge set ("one example per
code in `CODED_GUARD_REGISTRY` that belongs to a C7/C6-d family") derived from that
list would skip both CA codes.

### F10 — MINOR — assorted count/shape nits

- Header partition says "6 functions"; distinct exported functions = **5**
  (`login_unified`, `validate_bookmark`, `default_label_fn`, `selector_label_fn`,
  `url_normalizer`). The partition as printed sums to 285 over 284 entries / 274
  distinct.
- C6 arithmetic subtracts "the base `ResultWithDataFrame`" from the 59 dataclasses,
  but `ResultWithDataFrame` is NOT in `__all__`; the actual 59th non-C6/C7 export is
  `ValidationError` (handled in C3). 37 is right by accident; the stated reasoning
  is wrong.
- C4 `Session` sketch types `headers?: ReadonlyMap<string,string>` as optional;
  Python is `headers: Mapping[str, str] = Field(default_factory=dict)` — never
  absent, never None (session.py:145). Under the design's own R3.9 rule
  (optionality only for `T | None = None` fields) it should be a required field
  defaulting to an empty map.
- C1/C7 wording singles out `Filter._list_item_filters` as if it were the odd
  underscore field; ALL EIGHT `Filter` fields are underscore-prefixed
  (`_property`, `_operator`, `_value`, `_property_type`, `_resource_type`,
  `_date_unit`, `_list_item_filters`, `_list_item_quantifier` — confirmed by both
  `dataclasses.fields(Filter)` and corpus payloads). The stated `@internal` rule
  ("every codec-visible `_`-prefixed field") therefore strips Filter's ENTIRE field
  surface from the published `.d.ts` — consistent with Python's privacy, but the
  design should say so explicitly so P2-5a doesn't "fix" it. Likewise
  `CohortCriteria` (`_selector_node`/`_behavior_key`/`_behavior`), `CohortDefinition`
  (`_criteria`/`_operator`), `GroupBy._list_item_mode`, and the extra cache fields
  `_nodes_df_cache`/`_edges_df_cache`/`_trees_df_cache` (FlowQueryResult) and
  `_events_df_cache`/`_properties_df_cache`/`_relationships_df_cache`
  (SchemaGraphResult) — all codec-visible dataclass fields the encode walk must
  emit, beyond the lone `_df_cache` the design names.
- Design C9 CohortCriteria oracle list omits `did_not_do_event` (which IS in the
  Python builder registry and callable today) — see F5.

---

## Claims verified accurate (no finding)

- Branch = `ts-port/phase1-addendum`; `len(__all__)` = 284 (as list entries).
- `exceptions.py`: 28 exception classes; hierarchy tree in C3 matches measured MRO
  edge-for-edge (incl. `SessionReplayError` under `APIError`,
  `RegionProbeNetworkError` under `RegionProbeError`); dual inheritance
  `ParamValidationError(MixpanelHeadlessError, ValueError)` /
  `ParamTypeError(..., TypeError)` correct; default codes `UNKNOWN_ERROR` /
  `VALIDATION_ERROR` ×2 / `RESPONSE_VALIDATION_ERROR` correct; `to_dict()` =
  `{code, message, details}` correct; `CODED_GUARD_REGISTRY` = 120 (frozenset),
  `CODED_GUARD_TWIN_CODES` = 9 — both correct.
- C4 Account union: `_AccountBase` `frozen` + `extra="forbid"`; `name` 1–64
  `^[a-zA-Z0-9_-]+$`; `default_project` `^\d+$`; `ServiceAccount.username`
  (min_length=1) + `secret: SecretStr`; `OAuthTokenAccount` exactly-one-of
  `token`/`token_env` (`account.py:241-257`); `TokenResolver` protocol method names.
  `Project`/`WorkspaceRef` field lists match; `OAuthTokens` =
  `access_token/refresh_token/expires_at/scope/token_type`; NewTypes live in
  `auth_types.__all__` (AccountName/ProjectId str, WorkspaceId int).
- Corpus: manifest `total: 3007`, by_kind 1744/1198/65, `source_commit d5627564`;
  3,322 JSONL lines; **395** `types.*` vectors; api-index = 396 entries
  (60 builder / 10 validator / 323 wire_api / 3 wire_state); enum vector
  `enums/bookmark_enums.json` has exactly the 34 public constants (the 2 private
  `_MAX_*` constants are excluded); `_df_cache: null` genuinely appears in tagged
  payloads (49×) and `codecs.py::_encode_common` walks ALL dataclass fields /
  all `model_fields` (computed fields expect-side only) as the design states;
  discrepancy-log items #2, #4, #7 reproduce.
- Enums: 8 classes, 7 `str`-based + `AlertFrequencyPreset` IntEnum. 125 Pydantic
  models, 59 dataclasses, 5 TypedDicts (names match C6-c), 24 `def df` + 39
  `def to_dict` in types.py (13,938 LOC).
- C6 representative row shapes (Segmentation/Funnel/Retention) and empty-frame
  column lists are transcribed correctly, including the step-from-1 and ragged
  `period_i` details.
- E4 alerts handling does NOT silently trust the vendored file: alerts wire vectors
  exist (11 `api_client.*` + 11 `workspace.*` alert apis in the corpus) so step (i)
  of the P2-7 verification is executable; PROVENANCE.json records the exact
  coverage holes the design cites (webhooks iron-only, cohorts none, alerts
  custom-only advisory).

## Verdict

Sound skeleton with genuinely measured corpus/registry numbers in most places, but
three blocker-grade shape errors (F1 phantom `ActiveSession.project`, F2 wrong
`ValidationError` fields, F3 over-generalized toRows/rowColumns contract on the one
surface no vector locks) and a cluster of count/enumeration errors (F4–F7) that sit
directly inside done-criteria and gate definitions. All are cheap to fix at design
time; none invalidates the architecture (generate-don't-transcribe, hand-written
models with vendored cross-checks, codec-binding migration are all verified
feasible against the real repos).
