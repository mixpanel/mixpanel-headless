# Phase-2 Design Review — Lens: VERIFIABILITY

**Reviewer**: adversarial review agent (verifiability lens)
**Target**: `context/phase2/design/phase2-design.md` (801 lines, dated 2026-08-15)
**Repos checked**: Python `ts-port/phase1-addendum` (confirmed current branch), TS `main`.
All numbers below re-measured from disk; scripts run via `uv run python` against the
committed corpus snapshot (`conformance-runner/corpus/`, manifest `source_commit d5627564`).

## Verification log (measurements)

| Design claim | Measured | Verdict |
|---|---|---|
| 284 exports; 47 Literal aliases; 8 Enums; 59 dataclasses; 125 Pydantic models | 284 / 47 / 8 / 59 / 125 (introspection) | ✓ |
| 28 exception classes + `ValidationError` dataclass | 29 `class` defs in `exceptions.py` | ✓ |
| `CODED_GUARD_REGISTRY` 120; twins 9 | 120 / 9 | ✓ |
| `types.py` 13,938 LOC; 39 `def to_dict`; 24 `.df` | 13,938 / 39 / 24 | ✓ |
| Corpus: 3,322 JSONL lines; manifest total 3,007; 395 `types.*` vectors | 3,322 / 3,007 / 395 | ✓ |
| 85 distinct `$type` tags; all reachable via `call.input` sweep | 85 distinct; **all 85 occur in `call.input`**; only `SecretStr`/`datetime`/`bytes` also occur under `expect` | ✓ (sweep domain is adequate) |
| "6 built-ins + **79** rich tags" | `date` has **0** corpus occurrences → 5 built-ins present + **80** rich tags (the 80th being `OAuthTokens`, the only rich tag not in `__all__`) | ✗ off-by-one |
| api-index: 396 = 60 builder + 10 validator + 323 wire_api + 3 wire_state | matches | ✓ |
| "**22** of the builder entries are `types.*` names" | **39** `types.*` entries in `api-index.json` (each `Filter.*`/`CohortCriteria.*`/`CohortDefinition.*` static is its own entry); 22 is the count of distinct *class families* | ✗ |
| C9: `types.FunnelStep`, `types.RetentionEvent` "already in the D4 builder registry, hence callable through oracle-py" | **Neither is in `conformance/record/registry.py`** (grep: only `codecs.py` docstring hits) and **neither has a single corpus vector** (`grep '"api":"types\.'` shows 39 api values, no FunnelStep/RetentionEvent) | ✗ |
| P2-5a "~200" vectors / P2-5c "~85" / P2-5b "~110" / P2-6 replays "~60" | 159 / 66 / 110 / 60 (per-family counts; total 395 ✓) | ✗ for 5a, 5c |
| `bookmark_enums.json` snapshot, 34 constants | exists at `corpus/enums/bookmark_enums.json`, 34 constants | ✓ |
| Discrepancy log #4 (codecs.py docstring lists `CohortDefinition`, tuple special-cases it) | confirmed (`codecs.py:19` vs `:609`) | ✓ |
| `CodecRegistry.register` throws on duplicates | confirmed (`codecs.ts:238-249`) — **and it also throws on built-in shadowing, incl. `SecretStr`** | ✓ / see F4 |
| oracle-py real (`oracle.info/call/shutdown`), `oracle-protocol.md` exists | confirmed (`conformance/oracle_py/server.py`, `conformance/schema/oracle-protocol.md`) | ✓ |
| C9 strategy source "tests/test_query_types*.py" | glob matches nothing; actual strategy files are `tests/test_types_{funnel,retention,flow}_pbt.py`, `tests/test_cohort_definition_pbt.py`, `tests/pbt/*` | ✗ path |
| Runner "batch table" (C7 step 4, P2-8) | `runner.ts` has no batch table — `UNPORTED` = implementation-absence only (`gateApis`, runner.ts:340-359); "declared done" appears only in comments | ✗ (does not exist yet) |
| Guard-code corpus coverage | 90 of 120 registry codes appear in `types.*` vector `expect.error.code`; the 30 uncovered are B2/B3-family (`ES*/SG*/BB*/AC*/WR*/WS*` + `RESPONSE_VALIDATION_ERROR`) — consistent with the design's phase split | ✓ (with F2 caveat) |
| Entity-model tag coverage | **69 of 125 Pydantic models have NO corpus `$type` tag at all** (incl. `Dashboard`, `Cohort`, `Bookmark`, `CustomAlert`, `Annotation`, `FeatureFlag`, `Experiment`, `ProjectWebhook`, `EventDefinition`, `PropertyDefinition`, `Session`, `Project`, `WorkspaceRef`, all three Account variants, `PaginatedResponse`, `CursorPagination`, …); 36 of 59 dataclasses likewise (all the result classes — expected, they're C8(b)'s domain) | → F1 |

## Findings (severity-ordered)

### F1 — BLOCKER — 69 of the 125 entity models (and the auth/session models) have NO runtime verification in Phase 2, yet C8 claims "every type locked"

C8's preamble (design ln 579-583) says Phase 2 implements "every type locked before
anything consumes it" via four offline checks. Measured against the corpus, the four
checks reach:

- codec round-trip sweep (C8a): only the 80 rich tags that occur in `call.input` —
  i.e. 56/125 Pydantic models + 23/59 dataclasses + `OAuthTokens`;
- goldens (C8b): result classes only ("`packages/core/src/types/results/*.golden.test.ts`",
  ~40-row api→result table — design ln 601-609);
- error locks (C8c): registry equality + `types.*` guard vectors (C7/C6-d families only);
- enum locks (C8d): literals/enums/bookmark tables.

That leaves **69 named Pydantic models with zero runtime exercise**: no tag → invisible
to the sweep (the sweep's own coverage accounting only counts *registered* tags, and
only tags in `tag-universe.json`); not result classes → no goldens; no guard vectors.
Their only Phase-2 check is the compile-time vendored cross-check (C5 step 2), which
the design itself documents as full of holes (cohorts: none; webhooks iron-only;
alerts advisory per E4). `fromDict` alias acceptance, `toDict` alias emission,
drop-null behavior, `extra` behavior, `default_factory`-on-absent — all runtime
semantics, all unverified for these 69 until Phase 3.

Worse, C5's rationale (ln 399-403) *justifies* hand-writing these models by saying
"the Python models are what the vectors lock — 700+ `entities`/`data-governance` wire
vectors record the Python field names, alias behavior, and drop-null serialization" —
but Phase 2 never replays a single wire vector (no client), so this locking is
deferred rhetoric presented as a present-tense guarantee. The C8 deferral table
(ln 627-639) defers "wire serialization of entity *Params models*" and "result parsing
from raw response bodies" but never names the 69 response/entity models whose *shape
itself* leaves Phase 2 unlocked. The lens rule is: each deferral must be named and
justified. This one is neither.

**Concrete failure scenario**: P2-7 implementer types `Dashboard.layout` wrong, or
ports an `AliasChoices` set incompletely. Every P2-7 done-criterion passes (sweep
allowlist empty — Dashboard has no tag; contract test-d compiles — schema4api's
dashboard type is the server view, not the Python subset). Phase 3 B6 then builds
`create_dashboard` against the wrong shape and the 810 `api_client.*` vectors fail en
masse, in the expensive phase.

**Fix**: the material for a cheap offline lock is already in the snapshot — entity
wire vectors carry plain `expect.result` dicts (verified: e.g.
`corpus/entities/test_api_client_crud.jsonl`, `api_client.create_dashboard` →
`{id, title}` result payloads). Extend the C8(b) golden mechanism to entity models
(`fromDict(expect.result) → toDict() → canonical-diff`), driven by a generated
per-model coverage table; for models with no vector occurrence anywhere (compute the
list mechanically in P2-1's generator), require either an authored golden fixture or
an explicit named deferral row with owner. Add "every exported model name appears in
the coverage table with a non-empty lock or a named deferral" as a P2-7/P2-8
done-criterion.

### F2 — MAJOR — Phantom locks and phantom oracle entry points for `FunnelStep` and `RetentionEvent`; entry-point arithmetic wrong throughout C9/C10

Measured: `types.FunnelStep` and `types.RetentionEvent` (a) have **zero** corpus
vectors, (b) are **not** in the D4 builder registry
(`conformance/record/registry.py` — grep confirms), so oracle-py cannot call them.
Yet the design:

- C9 (ln 649-657) lists both inside "The 22 `types.*` builder entries" and asserts
  "all already in the D4 builder registry, hence callable through `oracle-py`'s
  `oracle.call` today" — false for these two;
- P2-5c's done-criterion "their `types.*` vectors (~85) PASS" implies vector locks for
  FunnelStep/RetentionEvent that cannot exist (actual P2-5c family count: 66 —
  Exclusion 19, FlowStep 9, FrequencyBreakdown 15, FrequencyFilter 18, HoldingConstant 5);
- P2-9's gate "green over all 22 `types.*` apis" is unsatisfiable as written for two
  of the named apis;
- Ground-truth inventory (ln 34-36) says "22 of the builder entries are `types.*`
  names"; the real number is **39** (statics are separate entries), and C7 step 3's
  "22 entries" for `bindings.ts` adapters repeats the error — under-registration
  would be caught by the ≥395 count check, but the packet spec hands the implementer
  a wrong list. C9 also omits `types.CohortCriteria.did_not_do_event`, which IS in
  the Python builder registry (registry.py:385) — oracle-ts "registers the same 22"
  would diverge from oracle-py's callable surface.

Both classes have real coded guards (`_validate_event_name` → `EV1/EV2`; see
`types.py:9992` FunnelStep `__post_init__`, `types.py:10324` RetentionEvent). Code-level
coverage of EV1/EV2 via `Exclusion` vectors does NOT verify that FunnelStep/
RetentionEvent *wire the guard at all* — a TS port that forgets the `__post_init__`
call passes every Phase-2 gate.

**Fix**: correct all counts to the measured 39-entry list; then either (preferred)
add `types.FunnelStep` / `types.RetentionEvent` registry entries on
`ts-port/phase2-contract-support` and record/author vectors for them (the design
already budgets Python-side vector work in Risk #3), or list both classes in the C8
deferral table with an owner and strike them from the C9 oracle list.

### F3 — MAJOR — The C8(b) golden tests and C8(a) sweep can pass vacuously; no mechanical anti-vacuity criterion exists

C8(b) (ln 601-612): "`fromDict(expect.result)` → `toJSON()` → canonical-diff against
the original payload (identity through the class proves field coverage…)". It proves
that only if `fromDict` actually destructures into declared fields and `toJSON`
re-emits from them. A lazy implementation — `fromDict(raw) { this.#raw = raw }` /
`toJSON() { return this.#raw }` — passes every golden byte-for-byte while porting
nothing. Nothing in the packet done-criteria (C10) or the P2-10 audit list ("no
weakened/dropped assertions in *translated* tests" — goldens aren't translated tests)
mechanically forbids this.

Same class of hole in the sweep: C8(a) decode is specified as "through the real
constructor/factory (guards FIRE on decode)", but for the ~50 Pydantic-model tags
there are **no error vectors** (all 90 covered guard codes are C7/C6-d dataclass
codes), so a codec that decodes a `CreateBookmarkParams` payload into a plain object
and re-emits the same fields round-trips perfectly. The sweep asserts diff-equality,
never `instanceof`.

**Failure scenario**: P2-7 registers passthrough codecs for entity tags; sweep green,
allowlist empty, P2-8 checkpoint green. Phase-3 B6 calls
`new CreateBookmarkParams(...).toDict()` and discovers the class has no real field
mapping — the "contract layer" was a JSON echo.

**Fix** (all mechanically checkable): (i) sweep asserts the decode product of every
rich tag is `instanceof` the registered core class (the registry entry can carry the
constructor); (ii) each golden adds a mutation probe — inject an unknown key into the
payload and assert the strict-decode error (dataclass results: `ResponseValidationError`;
Pydantic models: per-class `extra` behavior), or assert
`Object.keys(instance.toJSON())` equals a statically declared field list rather than
the input's keys; (iii) forbid any class from retaining the raw payload (audit grep:
no `#raw`/`this.raw = raw` in `types/`).

### F4 — MAJOR — The SecretStr/`SecretValue` migration as specified is incompatible with the current runner code; the described "alias" cannot work

C7 step 2 (ln 557-563) claims migration safety via "SecretValue is kept as a
deprecated alias re-exporting core's `Secret` (constructor-compatible: both wrap a
revealed string)". Measured against `conformance-runner/src/codecs.ts`:

- `SecretStr` is a **built-in** tag: `CodecRegistry.register` throws on built-in
  shadowing (codecs.ts:239-243), so `registerContractCodecs` cannot swap the decoder;
  the built-in decode site (`codecs.ts:342`, `new SecretValue(...)`) must be edited
  in-place — this is runner-internal surgery, not a registration;
- the encoder reads the **public field** `value.value` (`codecs.ts:425`,
  `SecretValue.value` is `readonly value: string`, codecs.ts:53-65). Core `Secret`
  (C4, ln 339-354) hides the string in an ECMAScript `#value` with only `reveal()`.
  Aliasing `SecretValue = Secret` breaks both the encoder and any wirestub binding
  that reads `.value` — "constructor-compatible" is not the compatibility that
  matters here;
- `Secret.toJSON()` returns the 10-asterisk mask. If any comparison path serializes
  a decoded input via `JSON.stringify` instead of `encodeExpectValue`, a masked value
  diffs against a masked value — vacuously equal for *any* two secrets, silently
  destroying the round-trip's discriminating power for exactly the tag being migrated.

The same-commit "42 PASSes green" gate would catch a hard breakage but not the
vacuous-mask case, and the design's description sends the P2-4 implementer down a
path (alias + registration) that the code forbids. Note also the 42 PASS vectors
carry no `SecretStr` tags at all (authored bundles' tags: `datetime`, `bytes`,
`float`, `Filter`, `CustomPropertyRef`, `Formula`), so the *real* regression surface
is the 20 `SecretStr` occurrences in extracted (currently-UNPORTED) vectors — the
gate protecting the swap is the sweep, not the 42.

**Fix**: respec the migration as explicit `codecs.ts` edits: decode built-in
constructs `new Secret(...)`; encode branch becomes
`value instanceof Secret → { $type: 'SecretStr', value: rejectBadString(value.reveal()) }`;
keep `SecretValue` only as a type alias; add a sweep-level assertion that a
round-tripped `SecretStr` payload preserves the *revealed* value (mask appearing in
an encoded vector = FAIL).

### F5 — MINOR — Rich-tag arithmetic off by one: 80 rich tags, not 79; P2-7's done-criterion hard-codes the wrong constant

Measured: the `date` built-in has **zero** corpus occurrences, so the 85 distinct
tags = 5 built-ins present + **80** rich tags (design ln 30-33 says 6 + 79; the
missed rich tag count includes `OAuthTokens` as claimed, so one dataclass/model tag
was dropped in the count). P2-7 (ln 729) says "codec-sweep allowlist EMPTY (all 79
rich tags registered)" — the mechanical check would trip on the 80th. Also
`codecs.ts`'s built-in docstring lists 5 built-ins (no `float`); `float` is a
decode-only authored tag per `codecs.py` — the C3 `tag-universe.json` generator spec
should classify built-ins from the codec table, not from a hand count. **Fix**: strike
hard-coded tag counts from done-criteria; phrase as "tag-universe rich set fully
registered" (the artifact already carries the truth).

### F6 — MINOR — The "runner batch table" referenced by C7 step 4 and P2-8 does not exist; the flip mechanism is unspecified

`runner.ts` treats `UNPORTED` purely as implementation-absence (`gateApis`,
runner.ts:340-359); "until the module's batch is declared done" exists only in
comments. C7 step 4 says "the runner's **batch table** marks `types.*` as ported so
any remaining `UNPORTED` verdict for those apis becomes FAIL" as if flipping an
existing switch. It's new infrastructure with no file, shape, owner, or test named —
a straggler api would otherwise sit at UNPORTED silently until the P2-8 count
checkpoint (which does compensate: 395+42 expected PASS is mechanical). **Fix**: add
the batch-table design (module, data shape, verdict change, unit test) to the P2-8
file list explicitly.

### F7 — MINOR — C9 strategy-source citation is a dead path

"reuse/vendor the suite's composite strategies per D14 (`tests/test_query_types*.py`,
`tests/pbt/*` filter/cohort strategies)": the glob `tests/test_query_types*.py`
matches nothing on `ts-port/phase1-addendum`; the composite strategies live in
`tests/test_types_{funnel,retention,flow,flow_tree}_pbt.py`,
`tests/test_cohort_definition_pbt.py`, `tests/test_custom_property_pbt.py`, and
`tests/pbt/*` has no filter/cohort strategy modules (it covers account/session/
resolver/naming/etc.). A P2-9 implementer following the citation finds nothing.
**Fix**: name the real files.

## What survived the attack (for the orchestrator's calibration)

- The sweep's domain choice (`call.input` only) is sound: measured, all 85 tags occur
  under `call.input`; only `SecretStr`/`datetime`/`bytes` appear under `expect`, and
  those are built-ins. No tag is expect-only.
- Core inventory numbers check out: 284/47/8/59/125 exports, 28+1 exception classes,
  120/9 code registry, 395 `types.*` vectors, 3,322 lines, 3,007 manifest total,
  bookmark_enums snapshot (34 constants), discrepancy-log items #2/#4/#6/#7 all
  reproduce.
- The 30 registry codes without `types.*` vector coverage are all B2/B3-family
  (`ES*/SG*/BB*/AC*/WR*/WS*`, `RESPONSE_VALIDATION_ERROR`) — the design's claim that
  Phase 2 locks exactly the code universe Phase-2 code can raise holds, modulo F2.
- oracle-py, `oracle-protocol.md`, `CodecRegistry` duplicate-throw, and the D9-style
  authored bundles all exist as described; `codec.roundtrip` as a protocol addendum
  is a genuinely strong verifiability addition.
- No mutation-testing residue found anywhere in the design ([SA1] clean — C10 restates
  "No mutation testing anywhere [SA1]").
