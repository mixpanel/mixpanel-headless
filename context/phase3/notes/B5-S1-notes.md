# B5-S1 notes — DiscoveryService + lexicon schemas + schema graph + the 12 facade members

Packet: `context/phase3/design/b5-packets.md` §4 (v1.0). Python arbiter branch
`ts-port/phase2-contract-support`; TS branch `main`. Corpus pin `70c904dc`.
Vectors owned: **0** (measured; §4 "Vectors: 0") — the Layer-3 suites and the
R10.9 harness are the only behaviour locks (packet Caution #13).

Status: **DONE**. `npm run check` green (136 files / 6,248 passed / 881
corpus-skipped — the B4-gate UNPORTED baseline, unchanged: S1 adds no vectors).

## 0. Sequencing deviation (RECORDED — arbiter-visible)

Packet §2 says **S2 runs FIRST and creates `packages/core/src/workspace.ts`**.
The orchestrator dispatched **S1 first** ("S1 lands before S2, S2 before S3"),
and at dispatch time `packages/core/src/workspace.ts` was still the Phase-1
placeholder (`export {}`). To avoid blocking on an absent seam, **S1 created
the §2 skeleton to the packet's contract, verbatim**, including all four
append-only section markers in the packet's file order, and filled only the
`=== B5-S1 discovery/lexicon members ===` section.

Built per the §2 skeleton contract:

- `class Workspace` with `new Workspace({session, client?, clientOptions?, warn?,
  logger?})` — `client` is the injected replay/test seam; absent, the ctor
  builds one via `createMixpanelClient({session, …})`. The Python ctor kwargs
  `account/project/workspace/target` carry a cited `TODO(port)` (B7).
- `use()` / `close()` / `[Symbol.asyncDispose]` as **B6-owned stubs** throwing
  `MixpanelHeadlessError` code `UNPORTED_MEMBER` with `// TODO(port): B6-W1`.
- The lazy `discoveryService` accessor (`workspace.py:1005-1010`).

NOT built (left to their owners): the `_live_query_service` accessor + the 22
S2 query members; the `_replays_service` accessor (it wires `query_fn` to the
bound `query` member, which is S2's). **S2 must EXTEND this file** — its marker
is already in place — not recreate it.

## 1. Files

TS (repo `mixpanel-headless-ts`), all under `packages/core`:

| Path | Content |
|---|---|
| `src/services/discovery.ts` (NEW, 1,050 LOC) | whole-file port of `_internal/services/discovery.py` (920) — 5 parsers, subproperty inference, `DiscoveryService` |
| `src/workspace.ts` (REPLACED placeholder) | §2 skeleton + the 12 S1 members |
| `src/types/results/discovery.ts` | `SchemaGraphResult.toGraph()` + `SchemaGraph`/`SchemaGraphNode`/`SchemaGraphEdge` (closes the `:1083` TODO(port)) |
| `src/compat/codepoint.ts` + `compat/index.ts` | `compareCodepoints` promoted to an export (R10.8 — non-string-keyed `sorted()` sites need the comparator) |
| `src/query/python-builtins.ts` | `KeyError` twin added (the discovery parsers subscript required API keys) |
| `src/services/index.ts` | discovery exports |
| `test/services/discovery.test.ts` | `tests/unit/test_discovery.py`, ALL 10 classes (60 tests) |
| `test/services/discovery.pbt.test.ts` | `tests/unit/test_discovery_pbt.py`, ALL 5 classes (14 properties) |
| `test/services/discovery-bookmarks.test.ts` | `tests/unit/test_discovery_bookmarks.py` (10) |
| `test/services/lexicon-schemas.test.ts` | `tests/unit/test_lexicon_schemas.py`, ALL 13 classes (33) |
| `test/services/schema-graph.test.ts` | `tests/unit/test_schema_graph.py` — the 4 packet-owned classes + the 6 Phase-2-deferred `to_graph` cases (29) |
| `test/workspace/discovery-facade.test.ts` | ADDITIVE facade coverage for the 12 zero-vector members (18) |
| `throwaway/b5-s1/` | R10.9 harness + `RUN.md` (removed at the batch gate) |

Python repo: this notes file only (no `src/` or `tests/` change; nothing in the
Python source needed fixing).

## 2. Translation decisions

1. **Wire calls are B4 client methods, imported by name** (R10.8): `getEvents`,
   `getEventProperties`, `getPropertyValues`, `listFunnels`, `listCohorts`,
   `listBookmarks`, `getTopEvents`, `getSchemas`, `getSchema`,
   `listEventDefinitions`, `listPropertyDefinitions`. Nothing re-assembled.
   Their `JsonValue` products convert through `toNativeJson` at the service
   boundary — the documented point where the TS wire layer equals
   `json.loads` (int/float spelling erased, `json-value.ts:108-112`).
2. **`warnings.warn` → an injected `WarningSink`** (R9.5: `core` has no
   stderr); `_logger.debug` → an injected `DiscoveryLogger`. Both default to
   no-ops and are threaded from the `Workspace` ctor. The `UserWarning` texts
   are reproduced verbatim (including the `{name!r}` CPython `repr` spelling)
   because three Layer-3 cases match on their substrings.
3. **`_is_valid_iso`** — `datetime.fromisoformat` has no JS twin, so the
   calendar rules were PROBED against the arbiter interpreter (CPython 3.14.6,
   2026-08-16) and ported as explicit checks: year 1..9999 (`0000-01-01`
   raises), month/day with the proleptic-Gregorian leap rule, hour 0..23 or
   exactly 24 when minute/second/microsecond are all zero, minute/second
   0..59, fractional seconds TRUNCATED (not rounded) to 6 digits, and a UTC
   offset whose total `±(hh*60+mm)` is strictly inside ±24h (`+00:60` is
   legal). 507 harness cases over these boundaries: 0 divergences.
4. **`re.split(r"[\s_\-]+")`** in `_find_similar_events` ports via
   `PYTHON_STR_WHITESPACE` + `_` + `-`, never a JS `\s` regex (R11.7; the two
   whitespace sets diverge in both directions — probe-verified that Python
   `re`'s `\s` for `str` patterns equals `str.isspace()`, 29 code points).
   The empty-string members Python's `re.split` emits at a leading/trailing
   separator are KEPT — they participate in the overlap count.
5. **Every `sorted()` is code-point ordered** (R11.5): `sortedByCodepoint` for
   plain string lists, a small stable `key=`-comparator (`compareCodepoints`
   for string members, numeric for `len()`/tuple members) for
   `sorted(key=lambda x: x.name)`, `key=len`, and the `(entity_type, name)`
   tuple key. A bare JS `.sort()` inverts e.g. `["ｱa", "𝒳"]`.
6. **Caches are `Map`s keyed by the JSON encoding of Python's tuple key**
   (R4.8 — no bare-object lookup table). Copy-on-return and copy-on-store are
   preserved (`list(...)` in the source).
7. **`KeyError` twin** for the required-key subscripts (`f["funnel_id"]`,
   `c["id"]`, `e["amount"]`, `data["entityType"]`, the six `_parse_bookmark_info`
   fields) — minted in the shared `query/python-builtins.ts` (R10.8). NOTE for
   R10.4: `types/query-params/cohort.ts:62` carries an older module-local
   `KeyError`; that is 2 occurrences, below the rulebook threshold, and is
   flagged in the new class's docstring rather than refactored inside this
   shard.
8. **The parsers stay unvalidated passthroughs.** Python never type-checks the
   API values it forwards into the result dataclasses, so a `passthrough<T>()`
   re-type is used rather than a Phase-2 `expect*` guard — running a guard
   would raise where Python does not (R10.2).
9. **`toGraph()`** returns the plain adjacency object the packet specifies
   (`{nodes, edges}`), with the `networkx` iteration semantics reproduced
   exactly (see §3 findings 2 and 3). Python caches the graph; the TS build is
   pure and deterministic, so the codec-visible `_graph_cache` slot stays
   `null` and the Phase-2 "caching ⇒ repeated-call equality" convention
   applies.
10. **`computed_at`** comes from the client's injected clock seam
    (`client.core.now()`, packet §0.4) and renders CPython's
    `datetime.now(timezone.utc).isoformat()` shape (`+00:00`, never `Z`;
    microseconds omitted when zero).

### Header-cited exclusions (all recorded in the test files' headers)

- `test_discovery.py::TestListSubproperties::test_mixed_warning_stacklevel_points_at_user_frame`
  (:1410) — `warnings.warn(stacklevel=N)` attributes a warning to a CALLER
  FRAME; the TS side channel is an injected sink with no frame attribution.
  The behaviour it pins (the mixed-type warning reaching the caller through
  Workspace → service → inference) is asserted by
  `test_mixed_types_collapse_to_string_with_warning` and by the facade
  sink-threading case.
- `test_lexicon_schemas.py` — the four `test_frozen` cases (`:244`, `:284`,
  `:310`, `:336`): no TS runtime analog (`readonly` is compile-time), same
  exclusion and reason as `test/types/results/types.test.ts:12-13`.
- `test_schema_graph.py::TestFacadeAndCli` — the two CLI cases (`:518`,
  `:530`): the CLI is out of Phase-3 scope (api-map preamble).
- `test_schema_graph.py::TestSchemaGraphResult` — translated in Phase 2
  (`test/types/results/schema-graph.test.ts:1-11`) except its `to_graph()`
  assertions, which come alive here (6 cases, re-homed verbatim).

### Outbound deferrals created by S1

- `TODO(port)` on `SchemaGraphResult`'s derived maps: `event_to_properties` /
  `property_to_events` are plain objects, so an event or property NAMED WITH
  DIGITS reorders under `Object.keys()` (watchlist #10). No vector sees it
  (the conformance canonicalizer sorts object keys, `canonical.ts:13`) and
  `toGraph()` no longer depends on that order, but a `Map`-valued surface is
  the complete fix — a Phase-2 field-shape decision, escalated rather than
  changed unilaterally.
- `Workspace` is NOT re-exported from `packages/core/src/index.ts` yet (the
  class is a third built): the conformance bindings import deep `src/` paths,
  and the barrel export belongs with the last shard that completes the facade.

## 3. R10.9 RUN record

Full record + reproduce steps: `throwaway/b5-s1/RUN.md` (TS repo). Two parts.

**Part 1 — differential (Python arbiter vs TS), seed 20260816, ≥500
examples/family, 11 families, FINAL: 5,522 compared / 0 divergences.**

```
infer_subproperties 503 · infer_scalar_type 510 · is_valid_iso 507 ·
iter_dict_rows 501 · parse_lexicon_metadata 500 · parse_lexicon_property 500 ·
parse_lexicon_definition 500 · parse_lexicon_schema 500 ·
parse_bookmark_info 500 · find_similar_events 501 · schema_graph 500
```

Edge set present verbatim: `18.0`, `1.5`, `True`, `None`, `[]`, `""`, `"𝒳"`
(U+1D4B3) — plus `-0.0`, `False`, `0`, integer-like keys, the empty key, the
ISO-boundary strings, and unparseable/non-dict raw values. The only comparison
normalization is the documented int/float spelling erasure; negative zero is
compared, not normalized.

Three real divergences found and fixed red → green:

1. **`sample_values` de-duplication used JS `Set` semantics** (5/503).
   CPython hashes numerically and `bool` is a subclass of `int`, so `{0}`
   already contains `False` and `{1}` contains `True`: Python samples `[0]`
   where the port sampled `[0, false]`. Fixed with `pySetKey` (folds
   `false`/`0`/`-0` and `true`/`1`; each parsed `NaN` stays distinct, matching
   CPython's identity check inside `set`).
2. **`toGraph()` edge order** (88/500). `networkx` stores edges per source in
   an adjacency dict, so `G.edges` yields them grouped by SOURCE NODE in
   node-insertion order — not global edge-insertion order. Fixed with a
   two-level adjacency map flattened in node order.
3. **`toGraph()` node order** (67/500 after fix 2). Python's first loop walks
   `event_to_properties`; `Object.keys()` on the TS twin hoists integer-like
   keys (`"1"`) to the front (watchlist #10). Fixed by rebuilding the same key
   sequence from `events`/`properties` directly; the underlying field-order
   gap is the `TODO(port)` above.

(Two harness-only artifacts were corrected first: `JSON.stringify(-0)` erasing
negative zero on the TS side, and a PBT assertion using `[...names].sort()`
instead of `sortedByCodepoint` — the second is itself an R11.5 trap caught by
the suite.)

**Part 2 — wire edge set: 47 checks / 0 failures.** Empty collections through
all nine list members; non-BMP code-point sorting; integral floats through
`parseLossless` (`TopEvent.count`, `FunnelInfo.funnel_id`, `sample_values`
incl. the `18.0`/`18` dedupe); cache hit/miss/clear, per-triple keys,
copy-on-return, uncached `list_top_events`/`list_bookmarks`; schema-graph call
count (3 vs 2), `includeDensity`, `force_refresh`, `params` echo; the three
`list_bookmarks` response shapes; `KeyError` on three missing-key paths; and
every error branch — 401 `AuthenticationError`, 403 `QueryError`, 429
`RateLimitError`, 500/503 `ServerError`, 400 → `EventNotFoundError` on
`list_properties` (with the suggestion fetch asserted) and 400 → `QueryError`
elsewhere; non-JSON 200 and transport failure both surface the B4 layer's
`MixpanelHeadlessError` (code passthrough, never re-handled).

## 4. Done-criteria (packet §4)

| Criterion | Status |
|---|---|
| `tsc --strict` clean | ✅ (all five workspaces) |
| all 5 suites green | ✅ 60 + 14 + 10 + 33 + 29 = 146 translated tests (+18 additive facade) |
| `toGraph()` TODO closed | ✅ `types/results/discovery.ts` |
| member section appended without touching S2/S3 sections | ✅ (S1 also had to CREATE the skeleton — §0) |
| RUN record | ✅ `throwaway/b5-s1/RUN.md` + §3 |
| commit | ✅ one TS commit, one Python commit (this file) |
