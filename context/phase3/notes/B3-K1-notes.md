# B3-K1 notes — `bookmark_enums` parity + the `bookmark_schema` remaining slice

**Task**: b3-packets.md §"Packet K1". **Vectors: 0** (oracle/Layer-3-locked).
**Date**: 2026-08-15. **Model**: opus.
**Python source of record**: `src/mixpanel_headless/_internal/bookmark_schema.py`
ranges `:38-59`, `:333-379`, `:695-1553` and
`src/mixpanel_headless/_internal/bookmark_enums.py` (whole file), at
`ts-port/phase2-contract-support` HEAD.
**TS homes**: `packages/core/src/bookmarks/schema.ts` (NEW),
`packages/core/src/bookmarks/schema-sorting.ts` (GROWN, R10.8),
`packages/core/src/bookmarks/index.ts` (barrel).

---

## 1. `bookmark_enums.py` parity audit — ZERO diffs

Mechanical, member-for-member, no ordering claims (per the packet):
`throwaway/b3-k1/dump-enums.py` dumps every Python `frozenset` / `dict` /
`int` constant as sorted JSON; `harness.mjs enums` does the same for
`enums.ts`; `diff-enums.py` diffs.

```
py-only names: []
ts-only names: ['BOOKMARK_ENUM_TABLES']
total diffs: 0
```

36 Python constants (34 tables + `_MAX_FUNNEL_STEPS` + `_MAX_HOLDING_CONSTANT`)
all present and member-identical. `BOOKMARK_ENUM_TABLES` is the TS-only
registry-of-tables convenience added at P2-3 for the C8(d) snapshot lock — not a
divergence. **No enums.ts changes were needed.** The missing lock —
`tests/unit/test_bookmark_enums.py` (270 LOC, 6 classes) — is now translated in
`packages/core/test/bookmarks/enums.test.ts` (39 tests).

---

## 2. Mandatory CPython pydantic probe (V1b precedent)

Scripts (all under `throwaway/b3-k1/`, all `uv run python`, all against the
support-branch pydantic pin, run 2026-08-15):

| script | what it pins |
|---|---|
| `probe-schema.py` | 389-case transcript: error TYPE / LOC / ORDER / MULTIPLICITY over all four non-sorting root models |
| `probe-grammar.py` | the lax `str -> int` / `str -> float` / `str -> bool` grammars |
| `probe-detail.py` | int-literals, aliases, tuples, nested dict-unions, emission order |
| `probe-order.py` | `model_fields` declaration order for all 28 models + required-model-null shapes |
| `probe-bool.py`, `probe-bool2.py` | the numeric → bool boundary and its i64 ceiling |

Transcripts: `probe-transcript.json`, `grammar-transcript.json`,
`detail-transcript.json`, `order-transcript.json` (regenerate with
`bash throwaway/b3-k1/run.sh`).

### Load-bearing findings (each is encoded in the twin and locked by a test)

1. **Emission order** = declared fields in class-body order, THEN
   `extra_forbidden` for unexpected keys in INPUT insertion order. Re-confirmed
   at B3 (`order/do-multiple`: `chartType`, `plotStyle`, `analysis`, then
   `zzz`, `aaa` — despite `zzz` preceding `plotStyle` in the input).
2. **`Ignore[T]` is NOT "accept anything"** — it is `T | None` with a default.
   `Ignore[JsonValue]` tolerates junk, but `icon: Ignore[str]` → `string_type`
   on `12345`, `id: Ignore[int]` → `int_parsing` on `"notanint"` /
   `int_from_float` on `1.5`, `isNewQBEnabled: Ignore[bool]` → `bool_parsing`
   on `2`. **This contradicts the packet's "accept anything incl. explicit
   null, never error" characterisation of `Ignore[T]`** — the packet line is
   correct only for the `Ignore[JsonValue]` majority. Recorded here as a packet
   correction; the twin follows the probe.
3. **Non-Optional fields that merely carry a DEFAULT reject explicit `null`**:
   `forward: int = 0` → `int_type`, `collapse_repeated: bool = False` →
   `bool_type`, `conv_first_step: bool = False` → `bool_type`,
   `flows_merge_type: str = "graph"` → `string_type`,
   `date_range: dict[str, Any]` (required) → `dict_type`,
   `show: list[ShowClause]` (required) → `list_type`,
   `chartType: ChartTypeLiteral` (required) → `literal_error`,
   `steps: StepRange` (required) → `model_type`. The twin models this with a
   `nullable` flag distinct from `required` (defaulting to `!required`, which is
   right for every `X | None = None`).
4. **`_show_clause_discriminator` can never fail.** It is a plain callable that
   always returns one of two Tags, so `union_tag_invalid` /
   `union_tag_not_found` — and therefore **`B7_INVALID_BEHAVIOR_TYPE`** — are
   UNREACHABLE through the K1 models. A non-dict `show` element surfaces as
   `model_type` at `show.0.BehaviorShowClause` instead
   (`sections/show-element-not-dict`). Same for the sorting discriminators
   (B2-M2 probe finding 5). `enum` and `value_error` are likewise unreachable
   (no `Enum` types, no custom validators in this module). Every OTHER
   `_DEFAULT_CODE_MAP` row is reached by the edge set (§4).
5. **Plain (non-discriminated) unions** — `MultiAttribution` and
   `dict[str, int | dict[str, int]]` — short-circuit on the first member that
   validates, and otherwise emit EVERY member's errors in declaration order,
   each tagged with the member's rendered type name in `loc`
   (`…multiAttribution.PredefinedMultiAttribution.type`,
   `…exposures.a.dict[str,int].b`). Those names are NOT in
   `_DISCRIMINATOR_TAGS`, so they survive into the JSONPath.
6. **`Literal[0..8]` uses Python equality**: `True`/`False` match `1`/`0`,
   `1.0` matches `1`, `"1"` does not, `9`/`-1`/`[]` do not.
7. **Alias vs Python-name collision** (`populate_by_name=True`): the ALIAS
   wins and the Python-name key falls through to the extras pass
   (`{"conv-first-step": true, "conv_first_step": false}` →
   `extra_forbidden` at `conv_first_step`; same for `_idx`/`idx` and
   `from`/`from_step`).
8. **Lax scalar grammars** (`probe-grammar.py`):
   - `str -> int`: unchanged from B2 (`pydanticTrim` + the
     `[+-]?digits(_digits)*(\.0+)?` grammar). NBSP-led `"\xa05"` accepted,
     FEFF-led `"﻿5"` rejected.
   - `str -> float`: same trim, then signed `inf`/`infinity`/`nan` (ASCII
     case-insensitive) OR a decimal literal with optional fraction and
     exponent, single underscores between digits. Accepts `"5."`, `".5"`,
     `"1e3"`, `"1_000.0"`, `"1.0_0"`; rejects `"0x5"`, `"1,000"`, `""`,
     `"1__0"`, non-ASCII digits.
   - `str -> bool`: ASCII case-insensitive membership in
     `{0,off,f,false,n,no,1,on,t,true,y,yes}` and — unlike the numeric
     parsers — **no trimming** (`" true "` is rejected).
9. **The i64 window** (`probe-bool2.py`) — a B3-K1 R10.9 FUZZ FINDING, not
   something the hand-written probe set predicted. pydantic-core converts a
   float through Rust `i64`:
   - `int` field: integral float `4.611686018427388e18` → OK, but
     `9.223372036854776e18` (2**63) and `1e300` → **`int_parsing_size`** (a new,
     unmapped error type → generic `VALIDATION_ERROR`). A Python `int` of any
     size (`2**70`) → OK.
   - `bool` field: `0`/`1`/`0.0`/`1.0`/`-0.0` → OK; other integral values
     inside the window → `bool_parsing`; fractional, `inf`, `nan`, and
     **anything at or past 2**63 (int OR float)** → `bool_type`.
   The twin keys the `int` branch on FLOAT-NESS (PyFloat carrier, or a
   non-integral bare number), never on magnitude alone, because a bare JS
   number stands for a Python `int` under the P2 codec convention.
10. `tuple[str, float]` (`Goal.checkpoints`): non-list element → `tuple_type`;
    short element → one `missing` per absent index; long element → a single
    `too_long` at the tuple's own loc. `too_long` / `tuple_type` /
    `int_from_float` / `finite_number` / `int_parsing_size` are all
    unmapped → `VALIDATION_ERROR`.

---

## 3. What landed

### `schema-sorting.ts` (GROWN, never re-implemented — R10.8)

The model-description machinery is now exported and generalised:
`FieldType` gains `float` / `bool` / `json` / `literalInt` / generic `list` /
`dict` / `tuple` / thunked `model` / `plainUnion`; `ModelSpec` gains
`extra: "allow"`; `FieldSpec` gains `nullable`. The old `optionalStr` /
`optionalInt` / `ignore` kinds folded into `str` / `int` / `json` + `nullable`
with identical semantics, and the five sorting specs were rewritten onto them
(all 690 B2 vectors and the whole B2 test suite stay green — see §5). New
exports: `RootModelHandle`, `modelHandle()`, one handle per sorting model,
`SORT_ORDER_LITERAL`, `INSIGHTS_BOOKMARK_SORT_CONFIG`.

### `schema.ts` (NEW)

All 28 non-sorting models as `ModelSpec`s in Python declaration order, the 22
literal aliases as exported value tuples (the `TestEnumParity` twin needs
them — `typing.get_args` has no TS analogue), `showClauseDiscriminator`
(watchlist #13: `isPythonDict`, `Object.hasOwn`),
`getRootModelForBookmarkType` (`ReadonlyMap` + `?? null`, so unknown types and
the explicit `"user" -> None` entry are indistinguishable, exactly as
`dict.get()` leaves them), `PARTIAL_UPDATE_SUB_MODELS` (`ReadonlyMap`, R4.8,
`sorting` deliberately absent) and `BOOKMARK_MODEL_HANDLES` — the name→handle
map the (b′) adapter mirrors.

### Layer-3 translations (R10.2, 114 tests)

| Python file | TS file | tests |
|---|---|---|
| `tests/unit/test_bookmark_enums.py` (6 classes) | `test/bookmarks/enums.test.ts` | 39 |
| `tests/unit/test_bookmark_schema.py` (9 classes) | `test/bookmarks/schema.test.ts` | 58 |
| `tests/unit/test_bookmark_schema_pbt.py` (7 classes) | `test/bookmarks/schema.pbt.test.ts` | 17 |

Two documented, header-cited weakenings — both structural, neither an
assertion strength loss on any `pytest.raises`:

- The twin has **validators, not parsers**. `m = Model.model_validate(raw);
  assert m.sortBy == "column"` becomes "validating `raw` yields zero errors".
  There is no `m`; the package's only consumer
  (`Workspace._validate_bookmark_params_schema`) reads the error stream and
  discards the object. Same for `assert "sortOrder" not in m.model_dump()` and
  the PBT `model_dump` round-trips (which become the statelessness half of the
  property).
- `TestBookmarkTypeLiteral` asserts pydantic's `literal_error` on
  `CreateBookmarkParams`; the TS twin of that PUBLIC type is the Phase-2
  `EntityModel` port, whose `oneOf` check raises `ResponseValidationError`. The
  assertion keeps its strength against the twin's own contract surface.

`schema.test.ts` also adds a `probe-pinned pydantic-core shapes` block: 12
tests that lock findings 1, 4, 5, 7, 9 and the reachable/unreachable
`_DEFAULT_CODE_MAP` partition directly (additions, not weakenings).

---

## 4. R10.9 harness — RUN record

Location `throwaway/b3-k1/` (TS repo; the batch gate deletes it). Re-run
everything from the recorded seeds with:

```bash
bash throwaway/b3-k1/run.sh                 # the recorded sweep below
bash throwaway/b3-k1/run.sh 4242 600        # one seed / N per model
```

Arbiter = the REAL CPython `bookmark_schema.validate_with_pydantic` (Python
half writes a JSON oracle); subject = the REAL
`packages/core/src/bookmarks/schema.ts` reached only through
`throwaway/b3-k1/entry.ts` → esbuild → `.build/entry.mjs`. Python floats cross
as PyFloat CARRIERS (`{"__pyfloat__": repr}`), exactly as the Phase-2 codec
transports them; a bare JSON number stands for a Python `int`. Diff is
position-by-position on the full `[type, loc]` sequence — order and
multiplicity included, not just membership.

### Recorded run, 2026-08-15

```
== enums parity audit ==            py-only []  ts-only [BOOKMARK_ENUM_TABLES]  diffs 0
== root-model dispatch probe ==     insights/funnels/retention -> InsightsBookmarkParams,
                                    flows -> FlowsBookmarkParams,
                                    user/""/insightz/USER/𝒳/sorting/displayOptions -> null
== probe-transcript replay ==       compared=389  divergences=1  skipped=0
== fuzz seed 20260815 (600/model) == compared=3000 divergences=0
== fuzz seed 4242     (600/model) == compared=3000 divergences=0
== fuzz seed 99991    (600/model) == compared=3000 divergences=0
== fuzz seed 20260816 (600/model) == compared=3000 divergences=0
== fuzz seed 7        (600/model) == compared=3000 divergences=0
```

**Totals: 15,389 compared, 1 divergence (the disclosed one in §6), 0 skips.**
Per-model budget 600 ≥ the packet's 500. The verbatim mandatory edge set
(`18.0`, `1.5`, `True`, `None`, `[]`, `""`, `"𝒳"`) appears both as the raw
value against all five models and as a leaf inside an otherwise-valid params
dict, in both the probe transcript and every fuzz corpus (`_B3_MANDATORY_EDGES`
in the strategy tables; `EDGE_SCALARS` in `fuzz-cases.py`). Every reachable
`_DEFAULT_CODE_MAP` row plus every unmapped-but-reachable type is exercised —
verified by replaying the strategy edge set through the real Python function:

```
codes covered by edge set: ['B0_INVALID_LITERAL', 'B0_MISSING_FIELD',
                            'B0_WRONG_TYPE', 'S3_UNKNOWN_FIELD',
                            'VALIDATION_ERROR']   (missing: [])
```

Two harness-fidelity bugs found and fixed during the run (recorded so the
review pair does not re-find them as twin bugs): the mutator could write an
INT dict key (not JSON-transportable — `json.dumps` stringifies it, so the two
sides saw different values), and the shared `[]`/`{}` literals in the edge
table could be grafted into themselves (infinite recursion in the encoder).
Both are guarded in `fuzz-cases.py` now.

### Oracle-family declarations (Python side)

`conformance/differential/strategies.py` gains `bookmark_schema_family`
(90 edge calls, mutation-driven strategy over all five models, optional
`path_prefix`) and `get_root_model_family` (10 edge calls, sampled-plus-junk),
exported as `PHASE3_B3_TARGETS` and appended to `ALL_TARGETS`;
`conformance/tests/test_fuzz_harness.py` learns the two names.

**Deferral (packet-sanctioned)**: they are declared but NOT SERVED through
`oracle-py` yet. `validate_with_pydantic(model_cls, …)` takes a model CLASS,
which is not JSON-transportable, and the name-resolving adapter in
`conformance/record/adapters.py` plus the registry retarget are explicitly the
(b′) task's (b3-packets §"validate_with_pydantic — adapter retarget"). The
strategies address models BY NAME so (b′) can wire them with no strategy
changes. Until then the K1 differential runs through the throwaway harness
above, which drives the same five models by name against the same CPython
reference — so the coverage is not deferred, only the transport.

---

## 5. No-regression evidence

- `npm run check` green: 93 files, **3,738 passed / 2,022 corpus-skipped**.
- `npm run conformance`: **3,251 vectors — 1,229 passed, 0 failed, 2,022
  unported** @ corpus `b5c136982405` — the entering baseline, unchanged (K1
  adds zero vectors and flips nothing; the batch-status flip is the gate's).
- `just check` green in the Python repo (ruff + ruff format + mypy --strict +
  3,251 conformance tests + build), with `strategies.py` and
  `test_fuzz_harness.py` touched.

---

## 6. Known divergence — ONE, disclosed, arbiter item

`ibp/integer-like-extra-keys`: an `extra="forbid"` model whose UNKNOWN keys mix
integer-like and non-integer-like spellings emits `extra_forbidden` in a
different ORDER on the two sides.

```
input: {…valid…, "2": 1, "b": 2, "1": 3}
py: extra_forbidden@2, extra_forbidden@b, extra_forbidden@1
ts: extra_forbidden@1, extra_forbidden@2, extra_forbidden@b
```

Cause: `JSON.parse` produces a plain object, and JS object key iteration puts
array-index-like keys first, so the Python insertion order is **destroyed at
decode time**, not at validation time — the validator cannot recover it. Note
the CONTENT is identical; only the order differs.

This is the same JS-engine limitation as ratified **Discrepancy #9**, but at a
DIFFERENT site: #9 is scoped to the B2 S4 chart-type warning pair, and
Caution §17 says "do not extend it". So this is escalated as its OWN item
rather than absorbed:

> **Arbiter item K1-D1.** Extend the order-insensitive comparison to
> `extra_forbidden` emission order on integer-like unknown keys of an
> `extra="forbid"` model, or accept it as a permanently-disclosed divergence?
> Reachability: needs a bookmark params dict carrying ≥2 unknown top-level
> keys with mixed integer-like/non-integer-like spellings. ZERO corpus
> vectors carry a `bookmark_schema.*` api, so this cannot fail the B3 gate;
> it CAN surface in the (b′) differential fuzz once the adapter lands, so the
> K1 fuzz generator excludes such inputs explicitly and counts the
> exclusions (`has_int_like_extra`, 0 skipped at every recorded seed — the
> mutator never produced one).

The pre-existing note on `validateInsightsBookmarkSortConfig` documents the
same limitation for the sorting path, where `validate_sorting_block`'s
chart-type pre-filter makes it unreachable.

---

## 7. Consumer / handoff notes

- **B6-W3** (`Workspace._validate_bookmark_params_schema`,
  `workspace.py:5186-5243`): call
  `validateWithPydantic(root.validate, rawNoSorting)` where
  `root = getRootModelForBookmarkType(bookmarkType)` (null → skip), then
  iterate `PARTIAL_UPDATE_SUB_MODELS` and call
  `validateWithPydantic(model.validate, raw[key], { path_prefix: key })`.
  The handle's `.name` is the `model_name` codec's payload.
- **(b′)**: `BOOKMARK_MODEL_HANDLES` (in `schema.ts`) is the TS mirror of the
  adapter's fixed name→class map — five entries, same spellings. Output codec
  is the existing `validation_errors` encoder (`[{code, path, severity}]`,
  emission order preserved).
- **No `// TODO(port)` markers were left in the K1 code.** The one
  deliberately-reproduced upstream TODO is the `extra="allow"` corpus-parity
  note quoted verbatim into the `FLOWS_BOOKMARK_PARAMS` docblock, mirroring
  `bookmark_schema.py:1511-1513` so the twin and its source drift together.
- **Repo hygiene** (re-added, and REVERTED BY THE BATCH GATE with
  `throwaway/`, B0/B2 precedent): the eslint `throwaway/*/.build/**` ignore +
  `throwaway/**/*.mjs` Node-globals glob, `.prettierignore throwaway/`,
  `.gitignore throwaway/*/.build/`.
