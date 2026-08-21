# Python corpus runner (design D7)

Re-executes library code from every committed conformance vector — it never
replays recordings against themselves. Served responses are canned; requests
and results are live library behavior, so mutations in URL building, param
serialization, retry counting, pagination, and parsing all surface as diffs
(design D9 proves it via the deliberate-break smoke test).

## Running

```bash
# pytest harness — one test per vector, id = vector id (part of `just check`
# via the `conformance` recipe):
uv run pytest conformance/runner -o addopts="" -q

# pytest-free CLI (worktree smoke runs, design D9.2):
uv run python -m conformance.runner --vectors conformance/vectors --report json
uv run python -m conformance.runner --vectors conformance/vectors \
    --filter 'segmentation/*'
```

The CLI is NOT dependency-free: it needs `mixpanel_headless`, `httpx`, and
`freezegun` (dev extras) — bootstrap with `uv sync --all-extras` first. A
missing `freezegun` fails fast with a `runner_crashed` report.

## Exit codes / report (design D9.3 — a crash is NEVER a catch)

| Exit | `status` | Meaning |
|------|----------|---------|
| 0 | `ok` | every selected vector passed |
| 1 | `vector_failed` | ≥1 vector executed and diffed red |
| 2 | `runner_crashed` | failure before/outside vector execution (missing dep, corpus load error, harness bug) |

`--report json` emits `{status, total, passed, failed, failures: [{id, kind,
reasons}], error, runtime_seconds}`.

## Measured runtime (PR-6 done-criterion: ≤ 5 minutes)

Measured 2026-08-14 on the committed corpus (2,530 vectors, Apple Silicon
dev machine, `/usr/bin/time -p`):

| Harness | Wall time |
|---------|-----------|
| `python -m conformance.runner` (CLI) | **1.2 s** |
| `uv run pytest conformance/runner -o addopts=""` | **2.4 s** (1.8 s in-test) |

Two orders of magnitude inside the 5-minute budget; collection cost is one
`json.loads` per JSONL line (design D7 lever, unexercised).

## Execution model (module map)

- `loading.py` — walks `conformance/vectors/**/*.jsonl`, skips `$bundle`
  headers, rejects duplicate ids, applies the `--filter` glob.
- `transport.py` — `VectorTransport`: ordered interactions serve
  positionally (mismatches surface as diffs, not serving errors);
  `unordered_group` members serve KEYED by canonical
  `(method, path, params)`, each consumable once (design D2/D7);
  `transport_error` interactions re-raise the recorded httpx class WITH the
  recorded message (library details embed it — `probe_region`); recorded
  `body_stream` chunks rebuild with boundaries preserved.
- `targets.py` — rebuilds `Session` from `call.session` (D5.1) and the
  replay object per `call.api` prefix: `api_client.*`, `workspace.*`
  (two-session pattern via `workspace_session`), `replays.*` (async seam),
  `oauth_flow.*` (region reverse-looked-up from the recorded scheme_host in
  the fixed OAUTH_BASE_URLS table; storage sandboxed to a temp dir),
  `region_probe.*` (real recording client factory over the vector
  transport; the recorded factory was test infrastructure), `pagination.*`
  (client prepended), `wirestub.*` (D13 gate stub).
- `execute.py` — kind dispatch (`builder`/`validation-error`/`wire`/`parse`),
  `call.setup[]` execution (setup raises are tolerated: setup returns are
  NOT diffed per design D2 — their request sides diff via
  `interactions[]`), result/error/interaction/callback-log diffing through
  `canonical.py` (design D6), callback stub injection
  (`$type: callback` → recording stubs diffed against
  `expect.callback_calls`), and a per-vector `$HOME` + `MP_*` sandbox so
  library cache writes (`MeService`) can neither touch the real `~/.mp`
  nor leak between vectors.
- `test_corpus.py` — `pytest_generate_tests` parametrization, id = vector
  id; session-scoped replay clock.
- `__main__.py` — the pytest-free CLI.

Replay determinism: both harnesses install the same `RECORD_EPOCH` freeze,
deterministic-UUID stream, and VIRTUAL sleep as record mode
(`conformance/record/clock.py`, design D1.4/D7), reset per vector, so
backoff vectors replay instantly and date-defaulted payloads are bit-stable.
