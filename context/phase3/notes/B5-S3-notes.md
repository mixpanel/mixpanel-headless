# B5-S3 notes — ReplaysService + rrweb analyzer + aggregators + replay_labels + 10 replay members

Status: DONE (2026-08-16). Packet: `context/phase3/design/b5-packets.md` §5.

## §0 Inventory (start of task)

- TS repo `main` @ `62dc07c` (B5-S2 R10.9 harness). S1 + S2 both landed.
- `packages/core/src/replays/` holds only the Phase-1 placeholder `index.ts`.
- `packages/core/test/replays/` does not exist.
- `packages/core/src/workspace.ts` (1875 LOC) already carries the §2 skeleton
  and the `// === B5-S3 session-replay members (append-only; S3 owns) ===`
  marker at :1860. S2 left an explicit TODO in its own section instructing S3
  to add the `#replays` accessor there (packet §2 assigns it to S2 but
  `ReplaysService` did not exist yet).
- No prior S3 partial work.

## §1 Work log

1. `compat/python-int.ts` — NEW export `pythonIntCoerce` (the CPython
   `int(value)` LADDER, as opposed to the existing `pythonInt(str)`
   grammar). Packet §9 Caution #3 requires it at two sites
   (`replays.py:392`, `rrweb_analyzer.py:586,913`); R10.8 says import,
   never re-implement, so it lands in the shared `pythonCompat` module.
2. `replays/replay-labels.ts` + `test/replays/replay-labels.test.ts`
   (8 tests) — closes the three phase2-audit A1 deferrals.
3. `replays/rrweb-analyzer.ts` + `test/replays/rrweb-analyzer.test.ts`
   (50 tests: all 9 classes of `test_rrweb_analyzer.py`).
4. Golden suite: `conformance/goldens/rrweb/generate.py` (Python repo,
   inside the allowed write surface) freezes
   `{actions, markdown, page_visits, console_errors}` for 3 fixtures →
   `test/replays/rrweb-analyzer.golden.test.ts` (4 tests). Fixtures:
   `sample-replay-001` (copied from `tests/fixtures/rrweb/`),
   `synthetic-mixed-001` (generator-defined; selection over a non-BMP
   text node, ancestor-context descriptions, the `(×N)` run collapse,
   mutation add/remove/text/attribute, checkbox input, scroll, console
   plugin, and the two no-op branches), `empty-stream`. The READ-ONLY
   `analytics` repo's `iron/replay-embed/__test__/fixtures.ts` was
   inspected per packet §5 — its builders yield strictly simpler
   streams than the two fixtures above, so nothing was extracted
   (recorded in the TS suite header).
5. `replays/aggregators.ts` — pandas frames → row arrays + paired
   `*RowColumns()` (the C6 `toRows()` precedent).

## §S3-D1 — `ReplayBundle.sample` decision: CPython PARITY (ported)

The packet recommended porting CPython parity rather than substituting
a PRNG, and escalating if disproportionate. It was NOT disproportionate:
`packages/core/src/compat/python-random.ts` (~280 LOC incl. docs)
implements MT19937 (`init_genrand` / `init_by_array` / `genrand_uint32`),
`getrandbits(k)` (both the `k<=32` fast path and the little-endian word
loop), `_randbelow_with_getrandbits`, and `Random.sample`'s two-branch
selection algorithm verbatim.

**Scope**: INTEGER and `null` seeds. The `str`/`bytes` seeding paths hash
through CPython's SipHash and are unreachable from
`ReplayBundle.sample(n, seed: number | null)`; `null` requires an
explicit entropy array (no `os.urandom` seam in `core`, R9.5) and raises
`PY_RANDOM_SEED_UNSUPPORTED` otherwise — the facade supplies it.

**Evidence**: `conformance/goldens/rrweb/python-random-probe.json` — 168
pinned CPython 3.14.6 cases (getrandbits at k∈{5,32,64,128} × 7 seeds
incl. `0`, negative, and `2**40+7`; `sample` across seed∈{0,1,42,999,-7}
× n∈{1,2,3,5,10,25,40} × k∈{0,1,2,5,min(n,8)} — covering BOTH the
`n <= setsize` pool branch and the `n > setsize` selected-set branch).
Regenerate with the snippet below, then copy the JSON to
`packages/core/test/compat/python-random-probe.json`.

```bash
uv run python - <<'PY'
import json, random, sys
out = {"python_version": sys.version.split()[0], "cases": []}
for seed in (0, 1, 42, 12345, 2**31, 2**40 + 7, -42):
    r = random.Random(seed)
    out["cases"].append({"kind": "getrandbits", "seed": seed, "k": 32,
                         "values": [str(r.getrandbits(32)) for _ in range(8)]})
for seed in (42, 7):
    r = random.Random(seed)
    out["cases"].append({"kind": "getrandbits", "seed": seed, "k": 64,
                         "values": [str(r.getrandbits(64)) for _ in range(4)]})
for seed in (42, 3):
    r = random.Random(seed)
    out["cases"].append({"kind": "getrandbits", "seed": seed, "k": 5,
                         "values": [str(r.getrandbits(5)) for _ in range(10)]})
for seed in (42, 11):
    r = random.Random(seed)
    out["cases"].append({"kind": "getrandbits", "seed": seed, "k": 128,
                         "values": [str(r.getrandbits(128)) for _ in range(3)]})
for seed in (0, 1, 42, 999, -7):
    for n in (1, 2, 3, 5, 10, 25, 40):
        for k in (0, 1, 2, 5, min(n, 8)):
            if k > n:
                continue
            pop = [f"r-{i}" for i in range(n)]
            out["cases"].append({"kind": "sample", "seed": seed, "n": n, "k": k,
                                 "result": random.Random(seed).sample(pop, k=k)})
with open("conformance/goldens/rrweb/python-random-probe.json", "w") as f:
    json.dump(out, f, indent=2, sort_keys=True); f.write("\n")
PY
```

NOTE the probe stores every `getrandbits` value as a STRING: `k=64` /
`k=128` draws exceed 2^53 and `JSON.parse` would silently round them
(caught on the first run — the initial numeric probe produced four
false failures at `k=64`).


## §2 Deliberate deviations + decisions (arbiter-visible)

1. **`ReplaysService.discover` / `eventsFor` "no query_fn"** — Python
   raises a bare `RuntimeError` (`replays.py:547`, `:721`) with no
   registry code. The port raises `MixpanelHeadlessError` code
   `REPLAYS_QUERY_FN_REQUIRED`, keeping the Python message verbatim so
   the `match="query_fn"` assertion survives (R5.4: a code is stronger
   than a message, and the taxonomy has no `RuntimeError` twin).
2. **`fetch_replays` all-fail error selection** — Python raises
   `failures[0][1]`, and `failures` is appended in `as_completed`
   (COMPLETION) order, so which error surfaces is nondeterministic
   under a thread pool. The port appends in INPUT order, which is the
   deterministic reading of the same rule. No vector or Layer-3 assert
   distinguishes them (`test_all_failures_raise_first_underlying_error`
   makes every replay fail with the same error).
3. **`fetch_replays` outer parallelism** — Python's `ThreadPoolExecutor`
   exists purely so each replay's `asyncio.run` owns its own event loop
   (`workspace.py:11160`). The port needs no such isolation, so the
   outer level is bounded-concurrency promise scheduling with the SAME
   worker cap (`max(1, concurrency)`), the same input-ordered output,
   and the same per-replay failure isolation.
4. **`stream_replay` event-loop plumbing** — Python's
   `asyncio.new_event_loop()` + `run_until_complete(gen.__anext__())` +
   `finally: gen.aclose()` (`workspace.py:11025-11043`) has no TS twin:
   `yield*` over the service generator composes directly, and
   `AsyncGenerator.return()` already guarantees the `aclose()` contract
   (proved in the R10.9 harness).
5. **`_to_unix_ms` pandas branch** — Python's final fallback is
   `pd.Timestamp(value)`, whose grammar is far wider than ISO-8601. The
   REACHABLE domain is the Insights `$time` group key (always a
   second-precision ISO-8601 string), so the port implements ISO-8601
   only and returns Python's unparseable fallback (`0`) otherwise —
   recorded as a cited `TODO(port)` in `services/replays.ts`. NOTE the
   port does NOT use `Date.parse`: per ES2016 a date-TIME form without
   an offset reads as LOCAL time, which would shift every naive
   Insights key by the host's zone; pandas treats it as UTC.
6. **`_CDN_TIMEOUT`** — httpx's four-way per-operation timeout
   (`connect=10, read=30, write=10, pool=30`) becomes ONE 30s clock,
   the already-sanctioned D-B4ARB-1 scope (`b4-review-resolution.md`
   §W-F2) the B4 client uses for its own requests.
7. **`ReplaysService.logger`** — Python assigns `self._logger` at
   `replays.py:171` and never emits to it. The port keeps it as a
   public readonly field (a `#private` would trip
   `no-unused-private-class-members`); it is documented DI surface, not
   a live call site.
8. **`Workspace.replaysService` is a getter/setter pair** — the getter
   is Python's `@property _replays_service` (lazy, `query`-bound); the
   setter is Python's plain `self._replays_svc = …` attribute write,
   which the Layer-3 suites and the conformance bindings substitute a
   stub through.
9. **`ReplayBundle.summaryMarkdown`'s `except NotImplementedError`**
   (`types.py:13876-13878`) is a Phase-2-era holdover from the unported
   `Replay.summary_markdown`; the member is implemented now and cannot
   raise it, so the fallback branch is unreachable in BOTH runtimes and
   is not ported (comment cited in place).
10. **`compat/python-int.ts` gains `pythonIntCoerce`** — the CPython
    `int(value)` LADDER (bool → 0/1, float → trunc-toward-zero, str →
    the existing `pythonInt` grammar, else `TypeError`). R10.8 says
    import, never re-implement, so the two S3 sites (`replays.py:392`,
    `rrweb_analyzer.py:586,913`) share one helper in `pythonCompat`.
11. **`compat/python-random.ts` is new** — see §S3-D1. Scope: integer
    and `null` seeds; `str`/`bytes` seeding is unreachable from
    `ReplayBundle.sample(n, seed: number | null)`.
12. **Import cycle `types/results/replays.ts` ⇄ `replays/rrweb-analyzer.ts`**
    — safe under ESM (every cross-edge is consumed inside a function
    body, never at module-eval time) and mirrors Python's deferred
    function-local imports at exactly the same call sites
    (`types.py:13199`, `:13529`, `:13585`, `:13738`, `:13777`).

## §3 Files landed

TS (`mixpanel-headless-ts`, branch `main`):

- `packages/core/src/compat/python-int.ts` (+`pythonIntCoerce`),
  `compat/index.ts` (re-export)
- `packages/core/src/compat/python-random.ts` (NEW — MT19937 + `sample`)
- `packages/core/src/replays/{replay-labels,rrweb-analyzer,aggregators,index}.ts`
- `packages/core/src/services/replays.ts`
- `packages/core/src/types/results/replays.ts` (TODO block CLOSED)
- `packages/core/src/workspace.ts` (the S3 member section + the
  `#replays` accessor S2 deferred)
- `packages/core/src/index.ts` (the three `replay_labels` public exports)
- tests: `test/compat/python-random.test.ts` (+ probe JSON),
  `test/replays/{replay-labels,rrweb-analyzer,rrweb-analyzer.golden,aggregators}.test.ts`
  (+ `fixtures/`, `goldens/`),
  `test/services/replays-service.test.ts`,
  `test/workspace/workspace-replays.test.ts`
- `throwaway/b5-s3/` (deleted at the batch gate, §7.5)

Python (`mixpanel-headless`, branch `ts-port/phase2-contract-support`):

- `conformance/goldens/rrweb/generate.py` + `*.golden.json` +
  `synthetic-mixed-001.input.json` + `python-random-probe.json`
- `context/phase3/notes/B5-S3-notes.md` (this file)

## §4 Test counts (all green)

| suite | tests |
| --- | ---: |
| `test/replays/replay-labels.test.ts` | 13 |
| `test/replays/rrweb-analyzer.test.ts` | 50 |
| `test/replays/rrweb-analyzer.golden.test.ts` | 4 |
| `test/replays/aggregators.test.ts` | 12 |
| `test/services/replays-service.test.ts` | 27 |
| `test/workspace/workspace-replays.test.ts` | 39 |
| `test/compat/python-random.test.ts` | 170 |
| **S3 total** | **315** |

`npm run check` green end-to-end: 173 files / 7,592 passed / 881 skipped
(the UNPORTED vectors), browser smoke OK.

## §R10.9 — harness RUN record (mirrored; `throwaway/b5-s3/` is deleted at the gate)


Throwaway. Packet §7.5 deletes `throwaway/b5-s3/` at the batch gate; this
record is mirrored into `context/phase3/notes/B5-S3-notes.md` §R10.9
(which survives).

## Part 1 — differential (Python arbiter vs TS port)

| file         | role                                                                            |
| ------------ | ------------------------------------------------------------------------------- |
| `py-side.py` | seeded recipe generation + Python arbiter outputs (`cases.json`, `py-out.json`) |
| `ts-side.ts` | the same recipes rebuilt as TS objects, through the port (`ts-out.json`)        |
| `compare.ts` | canonical-JSON comparator (sorted object keys, `-0` preserved)                  |

Run:

```
uv run python <ts-repo>/throwaway/b5-s3/py-side.py   # from the PYTHON repo
npx vite-node throwaway/b5-s3/ts-side.ts             # from the TS repo
npx vite-node throwaway/b5-s3/compare.ts
```

Seed `20260816`, `PER_FAMILY = 520` (packet §5 requires ≥500 per family).

### Counts

| family                   |     cases |  raised | diverged |
| ------------------------ | --------: | ------: | -------: |
| `url_normalizer`         |       520 |       0 |        0 |
| `default_label_fn`       |       520 |       0 |        0 |
| `selector_label_fn`      |       520 |       0 |   **14** |
| `rrweb_analyzer.analyze` |       520 |     109 |    **6** |
| **total**                | **2,080** | **109** |   **20** |

The 109 raises are all `ParamValidationError` /
`UA1_TIMESTAMP_NOT_POSITIVE` — the analyzer's downstream `UserAction`
constructor guard, reached when a drawn stream carries a `timestamp` of
`0` or `-1.9` (the mandated edge set puts both in the domain). Class and
code are identical on both sides for all 109.

### Divergences — all 20 are the documented int/float narrowing

`cases.json` is JSON, so a Python `18.0` arrives in JS as `18`: the two
runtimes then render `str(18.0) == "18.0"` vs `String(18) === "18"`. This
is the SAME narrowing `compare.ts`'s header documents and `toNativeJson`
erases by contract (`json-value.ts:108-112`). Verified mechanically —
stripping the CPython integral-float spelling from the PY side makes all
20 byte-identical, and **0 divergences of any other class remain**:

```
divergences 20   int/float-narrowing 20   other 0
```

Both affected surfaces are f-string interpolations of a `dict[str, Any]`
value (`selector_label_fn`'s `{candidate}` and the analyzer's
`" ".join(str(m) …)` console-message join); no vector reaches a float
there.

### Defect found and fixed: `selectorLabelFn` used `String()`

The first differential run reported **29** divergences, 9 of which were a
REAL fork: Python's f-string is `str(candidate)`, so a boolean metadata
value renders `True` while `String(true)` renders `true` (and `None` vs
`null`, `[1, 2]` vs `1,2`). Fixed by routing the interpolation through
`pythonStr` (`packages/core/src/replays/replay-labels.ts`), which dropped
the count to the 20 transport-narrowing cases above.

## Part 2 — CDN-walker wire edges (`wire-edges.ts`)

```
npx vite-node throwaway/b5-s3/wire-edges.ts
→ 70 checks / 0 failures
```

Every scenario the packet §5 harness spec names, plus every owned error
branch:

**404 sentinel** — 404 at absolute file 0 → `REPLAY_NOT_FOUND` (+ all
three `details` fields); mid-batch 404 with survivors AFTER it in the
SAME batch (pre-sentinel files yield, post-sentinel files are dropped,
and the whole batch was still ISSUED — the `asyncio.gather` twin); 404
exactly at a batch boundary (clean terminate, batch 0 preserved).

**403 re-sign** — 403-then-success (exactly ONE re-sign, whole batch
refetched); 403-re-sign-then-403 → `SIGNED_URL_EXPIRED` whose details
carry the ORIGINAL `signed_at` / `expired_at` (packet §9 Caution #4) and
`statusCode` 403; `reSignOnExpiry=false` → raise with ZERO sign calls.

**Bounds + concurrency** — `maxFiles` CLAMPS the batch (3 requests
issued, not 50-then-truncate); `concurrency: 1` vs `50` produce
byte-identical output on an identical interaction set, with the observed
in-flight peak 1 vs >1 proving the two paths really differ.

**Body handling / mandated edge set** — 200 `[]` continues the walk (not
a terminator); 200 non-list bodies (`42`, `"text"`, `{}`, `null`,
`true`, `NaN`) are EMPTY files, not errors (Caution #5); `NaN` inside a
200 body parses (`parseLossless` + `pythonConstants`); float / string /
bool timestamps order through the CPython `int()` LADDER — `18.9`
truncates to `18`, NOT `19` (Caution #3); non-BMP body content survives
byte-for-byte.

**Mobile detection** — non-rrweb first event →
`UNSUPPORTED_REPLAY_FORMAT` with `details.format`; the check skips
leading EMPTY files (fires on the first YIELDED file); it is once-only
(a later non-rrweb event does not re-fire it).

**Transport + status** — transport failure → `CDN_FETCH_ERROR` with the
credential scrubbed from both the message and the serialized details
(`<redacted>` present, `Signature=SECRET` absent); non-JSON 200 →
`CDN_INVALID_RESPONSE`; 500 / 502 / 429 / 301 / 418 →
`CDN_UNEXPECTED_STATUS`.

**Workspace guards** — all 10 `WR1` / `WR4` / `WR5` sites
(`TestCodedReplayGuardCodes` plus the `fetchReplay` / `fetchReplays` /
`replaysForUser` WR1 seams the Python file does not reach), each PAIRED
with a "makes no wire call" assertion; exactly-5 properties is allowed
(inclusive cap). Plus `fetchReplay`'s own zero-event `REPLAY_NOT_FOUND`
(distinct from the walker's first-file branch) and an R6.6 proof that
`streamReplay` yields its first event before the walk is exhausted and
closes cleanly on early `return()`.

## Error-code coverage (S3-owned branches)

| code                            | exercised in                                     |
| ------------------------------- | ------------------------------------------------ |
| `REPLAY_NOT_FOUND`              | walker first-file 404; `fetchReplay` zero events |
| `SIGNED_URL_EXPIRED`            | 403×2; `reSignOnExpiry=false`                    |
| `UNSUPPORTED_REPLAY_FORMAT`     | 3 mobile-detection scenarios                     |
| `CDN_FETCH_ERROR`               | transport failure (+ redaction)                  |
| `CDN_INVALID_RESPONSE`          | non-JSON 200                                     |
| `CDN_UNEXPECTED_STATUS`         | 5 statuses                                       |
| `WR1_TOO_MANY_EVENT_PROPERTIES` | 5 facade seams                                   |
| `WR4_REPLAY_SELECTOR_REQUIRED`  | 3 selector shapes                                |
| `WR5_DATE_RANGE_REQUIRED`       | 2 window shapes                                  |
| `UA1_TIMESTAMP_NOT_POSITIVE`    | 109 differential cases                           |
| `PY_RANDOM_SAMPLE_RANGE`        | `test/compat/python-random.test.ts`              |
