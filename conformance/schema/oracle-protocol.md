# Differential-Oracle Bridge Protocol (design D14 — NORMATIVE)

Status: normative for BOTH bridges — `conformance/oracle_py/` (Python repo)
and `differential/oracle/` (TS repo, task TS-7). The fuzz harness
(`conformance/differential/fuzz_harness.py`) is the reference consumer.
Version: `protocol_version = "1.0"`.

## 1. Transport and framing

- Newline-delimited JSON-RPC 2.0 over stdin/stdout: exactly ONE request
  object per line in, exactly ONE response object per line out. LSP-style
  `Content-Length` framing is rejected as needless — payloads are
  single-line JSON and can never contain a raw newline (JSON string
  escaping guarantees it).
- **Framing encoding is ASCII-safe (D14)**: oracle-py serializes every
  response with `ensure_ascii=True`; oracle-ts MUST escape all non-ASCII
  code points equivalently. Consequence: a lone-surrogate string generated
  by a fuzz strategy can never kill the bridge mid-session via a UTF-8
  encode error on stdout. Lone surrogates are ADDITIONALLY rejected by the
  D6 rule-2 encoder on both sides — a strategy that generates one gets a
  protocol-level `error` response (§5), never a hang or crash.
- Requests are processed strictly in order; the response for request *i*
  is written before request *i+1* is read. Blank input lines are ignored
  (no response).
- `stderr` is free-form logs and MUST NEVER be parsed by any consumer.
- Session end: after serving `oracle.shutdown` the process exits 0. EOF on
  stdin also exits 0 (a harness crash must not leave zombie oracles).

## 2. Request/response shapes

Request:

```json
{"jsonrpc": "2.0", "id": 7, "method": "oracle.call", "params": {...}}
```

- `jsonrpc` MUST be `"2.0"`; `id` is echoed verbatim (int or string;
  the reference harness uses monotonically increasing ints).
- Success response: `{"jsonrpc": "2.0", "id": 7, "result": {...}}`.
- Protocol failure: `{"jsonrpc": "2.0", "id": 7, "error": {"code": <int>,
  "message": <str>}}`. For an unparseable request line, `id` is `null`.
- `error.message` is diagnostic free text — NEVER compared by the harness
  (R5.4 applies to library errors; protocol errors are harness bugs).

## 3. `oracle.info`

No params. Result:

```json
{
  "language": "python" | "typescript",
  "library_version": "<distribution version or 'unknown'>",
  "source_commit": "<40-char SHA or 'unknown'>",
  "protocol_version": "1.0"
}
```

`source_commit` resolution (oracle-py): the committed corpus manifest's
`source_commit` (`conformance/vectors/manifest.json`) when present, else
`$CONFORMANCE_RECORD_COMMIT`, else `"unknown"` — never `git rev-parse`
(mirrors the design D3 injected-stamp rule). oracle-ts reports its pinned
`corpus.config.json` `sourceCommit`.

## 4. `oracle.call`

Params:

```json
{
  "api": "<python dotted vector name>",
  "input": { ...$type-tagged kwargs (design D4.4 codec table)... },
  "session": { ... },        // optional
  "interactions": [ ... ]    // optional, wirestub.* only (§4.3)
}
```

- **`api` is the PYTHON dotted name on BOTH sides** (design D14
  language-neutral naming); oracle-ts applies the same naming map as the
  TS conformance runner (D12). Names resolve through the recorder/runner
  registry (`conformance/record/registry.py`) — an api in neither the
  builder surface nor the recognized scopes below is a protocol error
  `-32602` (fail fast: the harness only emits registry names).
- `input` values are `$type`-tagged per the shared codec table; both
  bridges decode with their codec mirror. Undecodable input → `-32602`.
- `session` is accepted for shape parity but UNUSED by the Phase-1
  builder surface (facade builders bind a synthetic session; sessions
  become meaningful when wire scope arrives in Phase 3).

### 4.1 Result payload — library outcomes are DATA (R5.4)

Success (`result`):

```json
{"ok": true, "output": <vector-JSON value>}
```

or

```json
{"ok": false, "error": {"class": "<exception class name>",
                         "code": "<domain code>",
                         "errors": [{"path": ..., "code": ..., "severity": ...}],
                         "details_contain": {...}}}
```

- `output` is the entry's output-codec encoding (design D4.4: `json`,
  `validation_errors`, `selector_str`, `model_name`, …) as a plain JSON
  value. The HARNESS canonicalizes both sides with the D6 implementation
  before diffing; each oracle MUST verify its own `output` canonicalizes
  (rejecting with `-32000` otherwise) so poison values surface at the
  producing side.
- `error` carries ONLY structural members: `class` (R5.2), `code`,
  `errors[]` as `{path, code, severity}` triples (design D4.3), and
  optional `details_contain`. **`message`, `suggestion`, and `fix` are
  stripped and MUST NOT appear** (R5.4). This keeps "Python raised V7 /
  TS raised V7" a comparable value, not an RPC failure.
- Uncoded builtin raises (`ValueError`/`TypeError` — R5.5-excluded from
  the corpus) still encode as `{"class": "<name>"}` with no `code`, so
  error-branch parity stays comparable in the differential harness.

### 4.2 Scope and skip payloads (Phase 1)

- oracle-py v1 surface = exactly the D4 BUILDER-side registry entries
  (5 facades + module-level builders/validators/serializers + pythonCompat
  reference fns incl. the D13 wirestub). `wire_api`/`wire_state` entries
  answer `{"ok": false, "error": {"class": "Unsupported", "code":
  "WIRE_OUT_OF_SCOPE"}}` (fuzzing wire calls needs a transport story —
  Phase 3 concern).
- oracle-ts Phase-1 scope = protocol conformance + the D13 compat module;
  every other api answers `{"ok": false, "error": {"class": "Unported",
  "code": "UNPORTED"}}`.
- **The harness counts a response whose `error.code` is `UNPORTED` or
  `WIRE_OUT_OF_SCOPE` (from EITHER side) as SKIP, never divergence.**

### 4.3 `wirestub.*` transport extension (Phase-1, gate stub only)

The D13 wire-stub apis are part of the v1 surface but need canned HTTP
responses. The optional `interactions` param carries vector-schema
`interactions[]` objects; the oracle builds its replay transport
(`VectorTransport` / `VectorFetch`) from them and executes the stub call
against it. This extension is DEFINED ONLY for `wirestub.*` — supplying
`interactions` to any other api is ignored (builder path) and does NOT
enable real wire apis.

## 5. Error mapping (JSON-RPC `error` codes)

Only HARNESS bugs surface as JSON-RPC `error` objects (design D14):

| Code | Meaning |
|---|---|
| `-32700` | Request line is not valid JSON |
| `-32600` | Request object malformed (`jsonrpc`/`method` invalid) |
| `-32601` | Method not one of `oracle.info` / `oracle.call` / `oracle.shutdown` |
| `-32602` | Invalid params: unknown api name, undecodable `input`, wrong member types |
| `-32000` | Internal: output unencodable or fails D6 canonicalization (incl. lone surrogates), unexpected dispatch failure |

## 6. `oracle.shutdown`

No params. Result `{"ok": true}`; the process exits 0 after writing it.

## 7. Determinism environment

Both bridges run their library calls under the frozen environment of the
corpus runners (design D1.4/D7/D12):

- clock frozen at `RECORD_EPOCH = 2026-01-15T12:00:00Z`;
- deterministic UUID stream `00000000-0000-4000-8000-{seq:012d}`;
- virtual sleep (advances the frozen clock, returns immediately);
- per-`oracle.call` reset of the UUID counter AND the frozen-clock epoch,
  so no call's output depends on earlier calls in the session;
- oracle-py additionally sandboxes `$HOME` + `MP_*` env per call (the
  corpus-runner `_isolated_home` sandbox) so ambient credentials/config
  can never leak into outputs.
