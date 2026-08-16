# B5 adversarial review — SEMANTIC FIDELITY lens (P3-2d, fable)

**Status**: COMPLETE · 2026-08-16 · fidelity reviewer of the B5 pair.
**Scope**: TS `2981570..952a2cf` (S1, S2 incl. Layer-3 parts 1-24 + R10.9, S3,
B5-BIND) + Python notes commits `73631c5..28cc207`, verified against Python
source at `ts-port/phase2-contract-support` HEAD, corpus pin `70c904dc`.
**Verdict**: GO with findings — 3 MAJOR (F1-F3, all mechanically confirmed,
none vector-visible at this pin) + 2 MINOR. No binding-dishonesty, no
assertion-relevant drift found on this lens. All RUN records reproduce.

## Verification ledger (everything re-run, this review)

| check | result |
|---|---|
| rrweb goldens regenerated from Python (`conformance/goldens/rrweb/generate.py`) and byte-diffed | 3/3 goldens byte-IDENTICAL (committed-py = regenerated-py = TS copies); fixture copies differ only by prettier whitespace, `jq -S` semantically identical |
| TS golden suite | `rrweb-analyzer.golden.test.ts` 4/4 green |
| S2 R10.9 harness re-run (seed 20260816, PER_FAMILY 520) | reproduces exactly: 2,678 compared / 12 divergences — all the documented F1 integral-float narrowing class (`B5-S2-notes.md` §4.2); transforms family 78/78 byte-identical |
| S3 R10.9 harness re-run (seed 20260816) | reproduces exactly: 2,080 / 20 — all the documented `str(18.0)` narrowing class |
| wire-edge matrices re-run | S1 47/0 · S2 119/0 · S3 70/0 (matches RUN records) |
| B5-BIND oracle fuzz re-run (recorded seed 789657390, 9 families) | reproduces exactly: 4,555 examples / 0 skips / 0 divergences |
| `npm run conformance` | 3,251 — 2,876 PASS / 0 FAIL / 375 UNPORTED @ 70c904dc (the packet §1 pre-flip expectation; † holdback UNPORTED as designed) |
| B5 Layer-3 suites (`test/services` + `test/workspace` + `test/replays`) | 1,343/1,343 green |
| Adversarial oracle spot-runs (this review, 24 cases: 12 S2 builders, 12 S3 replay/rrweb; non-BMP, `\r`, `\x1c`, U+2028 property names, empty strings, `-0.0`, percent-encoded/uuid/hex URLs, float timestamps) | 23 ok · 1 divergence = out-of-annotation dict flow-step (`event: str \| FlowStep \| Sequence[...]` — dict is NOT in the annotation; Discrepancy #8 sanctions; NOT a finding) |
| CDN walker line diff vs `replays.py:277-505` | faithful: batch `[n, min(n+concurrency, max_files))`, eager `Promise.all` in file order (gather twin), 403 re-sign ONCE + whole-batch refetch, expired error from the ORIGINAL handle (`:349/:355` parity), first-file-404 → `REPLAY_NOT_FOUND`, mid-walk 404 sentinel yields survivors then returns, mobile check on first non-empty file, `zfill` 04d naming, redaction via `replaceAll` (matches CPython `str.replace` incl. the empty-query-string interleave quirk), 200-non-list → `[]` via parseLossless+pythonConstants, `CDN_UNEXPECTED_STATUS`/`CDN_INVALID_RESPONSE`/`CDN_FETCH_ERROR` branch-for-branch, no-details + `ErrorOptions.cause` (B5-BIND fix verified in source) |
| Discovery cache semantics vs `discovery.py:359-920` | faithful: lifetime in-memory, tuple keys as `JSON.stringify` (collision-free over the `str\|int\|None` domain), shallow-copy on hit AND store, `list_top_events` uncached, `clear_cache` drops both maps, `get_schema` `[schema]`-wrapping + truthiness guard, `_find_similar_events` strategy with `cpLength` sort keys and stable sorts |
| Facade kwargs→options vs api-map (R3.3/R3.8) | all 44 rows spot-checked: positional params match `params` lists (retention/query_user/frequency all-kwonly → single options bag), option keys keep Python spelling, S3 bags carry `retention_by_id`/`distinct_id_by_id`/`re_sign_on_expiry`/`cdn_concurrency` exactly; `workspace.me` NOT bound (§6.8 verified in `wire-workspace.ts:482`); `stream_replay` is a true `yield*` generator (R6.6) with Python's resolve-retention → sign → walk order |
| R4.3 rrweb IntEnums | const objects byte-equal to `rrweb_analyzer.py:52-93` |
| query-user parallel engine vs `workspace.py:10069-10207` | faithful: worker cap 5, page-0 metadata, `pages_needed` math incl. `total>0` guard, single-page shortcut, >48-page warning, abort on the four wire error classes vs warn-and-continue otherwise, sorted page merge, `[:limit]` slice semantics (null/0/negative) |

## Findings

### F1 (MAJOR · correctness · smoke surface) — eager `pyNumber` coercion in `transformFunnel`/`transformRetention` raises where CPython succeeds

`packages/core/src/services/live-query-transforms.ts` coerces counts/sizes at
READ time; Python stores raw values and raises only lazily at `+`/`>`/`/`
sites — so shapes that never reach those operators SUCCEED in Python.
CONFIRMED both sides (CPython probe + vitest probe):

- `_transform_funnel({"data":{"d":{"steps":[{count:0},{count:null}]}}})` —
  Python returns `[('A',0,1.0),('B',None,0.0)]`, overall `0.0`
  (`live_query.py:126-147`: first insertion stores raw; `prev_count > 0` is
  `0 > 0` False → no division; overall guard False). TS `transformFunnel`
  (pyNumber at aggregation, `live-query-transforms.ts` ~`:314`) throws
  `TypeError`.
- `_transform_retention({"d":{"first":"5","counts":[]}})` — Python returns
  `CohortInfo(size="5", retention=[])` (`live_query.py:196` compares `size`
  only inside the per-count comprehension; empty `counts` → no comparison,
  raw store). TS (`pyNumber(dictGet(cohortData,"first",0))`) throws
  `TypeError`. Same for `first: null`.

Wrong-ERROR (never wrong math), in-annotation (`Any` interiors, Discrepancy
#8 boundary), reachable only through wire bodies (no corpus vector carries
these shapes). The lazy-raise structure should be transcribed: keep the raw
value; apply the CPython coercion exactly at the `+` / `>` / `/` operator
sites Python has.

### F2 (MAJOR · correctness) — in-annotation CPython `AttributeError`s silently swallowed at most transform read sites (wrong success)

The S2 R10.9 harness fixed exactly two rows (T1/T2 → `pyMapping` in
`transformFunnel`/`transformRetention`) but the same class — ratified as
IN-annotation by the Discrepancy #8 boundary ("every value inside
`dict[str, Any]`/`Any` interiors"; requireHashable precedent) — is unguarded
everywhere else in `live-query-transforms.ts` / `live-query.ts`. CONFIRMED
(CPython vs vitest probes, identical inputs):

| input | Python | TS |
|---|---|---|
| `_transform_segmentation({"data": [1,2]})` | `AttributeError 'list'…'get'` | SUCCESS `total=0` |
| `_transform_segmentation({"data":{"values":{"seg":[1,2]}}})` | `AttributeError 'list'…'values'` | SUCCESS `total=3` — a wrong COMPUTED number |
| `_extract_steps_from_date_data("my steps here")` (`"steps" in <str>` is a SUBSTRING test in Python) | `AttributeError 'str'…'get'` | `[]` |
| `_extract_funnel_steps_from_series({"F":{"count":{…},"avg_time":3}})` (non-dict metric) | `AttributeError 'int'…'get'` | SUCCESS `avg_time: 0` |

Further unguarded sites by inspection (same class): `dataValues` in
`live-query.ts` (event_counts/property_counts `raw.get("data").get("values")`),
`dictGetRecord(raw,"date_range")` consumers (a JSON-`null` `date_range`
throws JS `TypeError` where Python raises `AttributeError`),
`transformActivityFeed` (`results`/`props` reads; dict `raw_events`
iteration: Python iterates keys → `AttributeError`, TS `for…of` on a
non-iterable throws `TypeError`), `transformFlowResult` trees/`root`
(truthy non-dict root: Python `AttributeError`, TS builds a default node),
`transformNumericBucket` `data.values`. The `dictGetRecord` JSDoc claim that
"`Object.hasOwn` raises the same way Python's attribute lookup does" is
factually wrong for str/list/number receivers (it just returns `false`).
Recommend either extending `pyMapping` to every `.get()`-on-`Any` site
(mechanical sweep of the file against the Python source's attribute reads)
or an arbiter ruling explicitly narrowing the #8 in-annotation raise-emulation
contract for response-body interiors (which would also retroactively cover
T1/T2 — the shard itself treated the class as in-contract).

### F3 (MAJOR · correctness · oracle-reachable) — `?? 0` conflates explicit `null` timestamps with absent keys; TS wrong-success where CPython raises

Python `int(e.get("timestamp", 0))` defaults only when the KEY IS ABSENT; a
JSON `"timestamp": null` reaches `int(None)` → `TypeError`. The TS twins
spell `pythonIntCoerce(x["timestamp"] ?? 0)`, and `null ?? 0` → `0`. Sites:

- `replays/rrweb-analyzer.ts:854` and `:1314-1315` (`analyze` — an
  ORACLE-SERVABLE family);
- `services/replays.ts:465` (CDN walker per-file sort key);

CONFIRMED through BOTH oracle bridges:
`rrweb_analyzer.analyze([{type:3, data:{source:3,…}, timestamp:null}])` →
oracle-py `{ok:false, error:{class:TypeError}}`, oracle-ts
`{ok:true, output:{actions:[], …}}`. The ≥500-example fuzz missed it because
`strategies.py::_B5_RRWEB_TIMESTAMPS` (`:7699`) omits `None` with NO
documented-omission comment — unlike the family's other exclusions. Fix the
port (`Object.hasOwn` ternary, the `dictGet` pattern) or document + exclude
by arbiter ruling; either way the strategy site needs the standard
domain-note treatment (Discrepancy #8 documentation convention), and if the
port is fixed, `None` should ENTER the timestamp domain to lock it.

### F4 (MINOR · correctness) — `STEP_PREFIX_RE`: JS `.` excludes `\r`/U+2028/U+2029; Python `.` excludes only `\n`

`live-query-transforms.ts` `STEP_PREFIX_RE` transcribes `\d`→`\p{Nd}` and
`\s`→`PYTHON_STR_WHITESPACE` correctly, but keeps a bare `(.+)`. Step names
like `"1. a\rb"` / `"1. a b"`: Python matches (`event="a\rb"`, sort key
`(1, …)`); TS fails the match → event = the WHOLE name, sort key `(2^31, …)`.
CONFIRMED both sides. Reachable only via adversarial step keys in insights
funnel wire bodies. Fix: `[^\n]` in place of `.` (both occurrences of the
semantics; one group here).

### F5 (MINOR · error-class parity) — `fetch_replay` window derivation: missing `timestamp` key raises `TypeError('undefined')` vs Python `KeyError`

`workspace.ts:2223` `pythonIntCoerce(ev["timestamp"])` for
`workspace.py:10946` `int(ev["timestamp"])`: an rrweb event WITHOUT a
`timestamp` key gives JS `undefined` → `TypeError` mentioning `'undefined'`;
Python raises `KeyError`. Class-only divergence on a corrupt-stream edge; no
vector or Layer-3 assert reaches it. Note-and-fix-cheaply (a `KeyError` twin
exists in `query/python-builtins.ts`).

## Items reviewed and explicitly ACCEPTED (no finding)

1. **Transform conversion math** (the S10/S11 mandate): step-0 literal
   `1.0`, `count/prev_count` guarded `prev_count > 0`, overall
   `last/first` guarded `first > 0`, empty-steps/empty-cohort `0.0`,
   retention `count/size` guarded `size > 0` — statement-for-statement
   IEEE division, no rounding, no epsilon. Locked by the 78-case
   byte-identical transforms corpus + the 6 authored wire vectors + my
   probes (incl. `size=0, counts="abc"` → `[0.0,0.0,0.0]` parity, where
   the string-iteration quirk matches on both sides).
2. **S2/S3/BIND F1 integral-float narrowing, option (b)** (12 + 20 recorded
   divergences + the `GroupBy.bucket_max` site): a JS caller cannot express
   `18.0` vs `18`; consistent with Discrepancy #7's R4.5 reasoning; domains
   documented at the strategy sites. This lens CONCURS with option (b) and
   recommends the arbiter promote the class to a numbered playbook
   discrepancy (it now spans three surfaces: flow operand render, engage
   `where` render, `selector_label_fn`/console-join renders).
3. **B5-BIND float twins** (decision 3) — checked against the recorder's
   Python-`float` typed fields; encoding-side only, binding honesty holds
   (bindings call `Workspace`/`ReplaysService` members; spot-audited
   `wire-workspace.ts`/`replays-bindings.ts`).
4. **Out-of-annotation dict flow-step** divergence from my spot-run —
   sanctioned by the ratified Discrepancy #8 boundary.
5. **CDN walker, discovery cache, parallel engine, facade mapping, R4.3
   enums, R6.6 generators** — verification ledger above.

## Handoff

- F1+F2+F3 are library changes on the S2/S3 surfaces; per P3-3 the fixes are
  fable-tier arbiter-directed remediation (B2/B3 arbiter-fix precedent),
  red-first with CPython-probe reference tests, then re-run: the S2/S3
  harness seeds, the BIND fuzz seed 789657390 (with `None` added to the
  timestamp domain if F3 is fixed in the library), and the 506-vector replay.
- No batch-status flip has landed (correct — gate task owns it).
- Probe artifacts for this review live under `/tmp/b5rev/` (transient);
  nothing in either repo was modified by this review (goldens regenerated
  byte-identically in place; `git status` clean both repos).
