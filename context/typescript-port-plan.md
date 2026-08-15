# mixpanel-headless → TypeScript: Port & Verification Master Plan

**Status**: Phase 0 COMPLETE (2026-08-14) — ready for Phase 1 via dynamic workflow
**Scope**: A faithful, fully agentic port of `mixpanel_headless` (Python) to TypeScript
(browser + Node), using the existing Python implementation and its ~7,000-test suite as
permanent verification infrastructure.

**Phase 0 artifacts** (all in `context/`):
- `typescript-port-rulebook.md` — v1.1, stress-test-amended (32 `[ST]` amendments applied)
- `typescript-port-api-map.md` / `.json` — the mechanical queue (205 Workspace members,
  39 sections, 281 exports; JSON is machine-readable for the Phase 3 workflow)
- Spike results and stress-test findings folded into §4.3, §6 Phase 0, and the rulebook

> **SCOPE AMENDMENT `[SA1]` (2026-08-14, user directive)**: **Mutation testing is OUT OF
> SCOPE for the port.** No mutmut-based judge validation, no StrykerJS in the TS repo, no
> mutation-score gates anywhere in the pipeline. Judge validation (the "corpus must fail on
> broken code" requirement) is replaced by a lightweight **deliberate-break smoke check**:
> 8–12 hand-authored sabotage patches applied one at a time in a throwaway worktree, each of
> which the corpus runner must catch. The Python repo's own mutmut practice (CLAUDE.md)
> continues for Python development but plays no role in port verification. All struck
> mutation references below are tagged `[SA1]`.

---

## 1. Executive Summary

`mixpanel_headless` is ~71K LOC of Python whose behavior is, by measured composition,
**~48% wire plumbing** (build an HTTP request, parse a response), **~13% pure
computation** (query builders, validators, the rrweb analyzer), **~9% OS-bound state**
(config files, token storage, OAuth callback server), and **~19% CLI presentation**.
Its 138K-LOC test suite (7,057 tests, 2:1 test:src ratio) asserts almost entirely on
observable contracts: exact request URLs/params/bodies captured through
`httpx.MockTransport`, exact bookmark/param JSON from pure builders, and 503
live-credential tests against the real Mixpanel API.

This shape dictates the strategy:

1. **Do not translate the test suite. Compile it.** Instrument the Python suite once and
   run it in "record mode" to extract a language-neutral **conformance corpus** of JSON
   vectors (call → expected request; canned response → expected result). This is the
   Wycheproof / JSON-Schema-Test-Suite pattern, derived mechanically from six years of
   accumulated test-writing judgment instead of authored by hand.
2. **Keep Python as a permanent executable oracle.** A differential harness, fuzzed by
   Hypothesis, runs the same inputs through both implementations and diffs canonical
   wire output — forever, not just during the port.
3. **Recruit Mixpanel's own source of truth as extra referees.** The `analytics`
   monorepo provides the server's bookmark JSON Schema, the server-side
   `bookmark_parser`, schema4api-generated entity types, and the webapp's own TS client
   layer — assets no published porting case study has had.
4. **Run the port as an Anthropic-style migration pipeline**: rulebook → verification
   rig → dependency-ordered fan-out with adversarial review → multi-night parity
   burn-in, with a judge that is itself validated (must pass on Python, must fail on
   mutated Python).

**Locked decisions** (this document assumes them):

| # | Decision | Choice |
|---|----------|--------|
| D1 | Repo topology | Separate `mixpanel-headless-ts` repo; conformance corpus lives in the Python repo and is consumed by the TS repo |
| D2 | Browser scope | Gated on a CORS/auth spike (Phase 0) before committing browser-tier claims |
| D3 | Package layout | Split: `@mixpanel-headless/core` + `@mixpanel-headless/node` + `@mixpanel-headless/browser` |
| D4 | CLI | Deferred out of scope for v1 (Python `mp` remains the CLI story) |
| D5 | Corpus home | First-class artifact in the Python repo: `conformance/` directory + record-mode CI job on every PR |

---

## 2. Source Material Inventory

Everything below was measured directly from the repos on 2026-08-14.

### 2.1 The Python codebase (`mixpanel-headless`, 70,774 LOC src)

| Area | LOC | Port relevance |
|---|---|---|
| `types.py` | 13,671 | 118 Pydantic models + 60 result dataclasses + 24 lazy `.df` properties; result layer is dataclass-based, validation is Pydantic |
| CLI (`cli/`) | 12,357 | **Deferred (D4)** — Typer/Rich/jq confined here; zero imports elsewhere |
| `workspace.py` | 10,981 | Facade: **205 public methods** (+31 private, 9 properties) across ~25 capability sections |
| `api_client.py` | 8,834 | Region→URL table (us/eu/in × query/export/engage/app), Basic vs per-request Bearer auth, 429-only retry w/ Retry-After, cursor pagination (MAX_PAGES=10000), byte-buffered JSONL streaming, workspace_id injection |
| Auth subsystem (`_internal/auth/`) | 4,350 | PKCE flow + localhost callback (ports 19284–19287), DCR, token refresh, resolver (env > param > target > bridge > config), hardened 0o600 atomic writes |
| Services | 3,943 | live_query 2,042; replays 971 (only async code: parallel CDN walker); discovery 920 |
| `validation.py` | 3,090 | Pure two-layer rule engine (V0–V27 arg rules, B1–B26 bookmark rules); uses `difflib.get_close_matches` for suggestions |
| Bookmark builders/schema/enums/segfilter/transforms | ~3,538 | Pure request construction — three translation paths from shared `Filter`: bookmark JSON, flows segfilter, engage selector strings |
| accounts/session/targets/auth_types | 2,272 | Public account-management surface |
| `exceptions.py` | 1,478 | ~35 exception classes |
| Replays (`_internal/replays/`) | 1,141 | **rrweb_analyzer (969 LOC) is pure-stdlib JSON computation** — cleanest 1:1 port target |
| Config + io_utils | 1,606 | TOML config, POSIX-hardened atomic writes (Node-only concern) |
| me.py / query engine / pagination / misc | ~3,500 | |

- **Public API**: 281 exports; ~50 Literal aliases; discriminated `Account` union.
- **No JQL, no client-side analytics aggregation, no metaclasses, no dynamic imports.**
- **Structural constants**: sync httpx everywhere (one `AsyncClient` exception);
  generators for streaming; connection-pool preservation across `use()` switches is a
  documented invariant.

### 2.2 The test suite (138,225 LOC, ~7,057 tests, 238 files)

| Bucket | Count | Portability path |
|---|---|---|
| Pure logic (builders, validators, types, serialization, rrweb) | ~3,500–3,900 (50–55%) | → conformance vectors (builder input → output JSON) |
| Wire tests (`httpx.MockTransport`, exact paths/params/bodies) | ~1,400 (20%) | → conformance vectors (call → captured request; canned response → result) |
| CLI (Typer CliRunner, stdout assertions) | ~670 (9.5%) | Deferred with the CLI (D4) |
| Filesystem/config/auth-storage | ~500–700 (8–10%) | Hand-translate the Node-relevant subset (Layer 3) |
| Live-credential (`pytest.mark.live`, off by default) | 503 (7%) | Run against BOTH implementations (Layer 4) |
| Property-based (overlaps buckets above) | **~554 tests / 39 `*_pbt.py` files / 541 `@given` sites** | Re-express invariants in fast-check + feed generators to the differential oracle |

Key mechanics that make extraction feasible:

- **Single mock seam**: every wire test injects `httpx.MockTransport` through one
  private `_transport` kwarg on `MixpanelAPIClient`. One instrumentation point captures
  all ~1,400 wire tests.
- **Central `conftest.py`**: `make_session(...)`, `mock_client_factory`, canned
  200/401/429 handlers, autouse `MP_*` env scrub, real-`~/.mp/` write guard.
- **No fixture corpus exists today** — canned responses are inline dicts in handler
  closures. The contract lives in test code; extraction is the only scalable reuse.
- Non-portable remainder (<10%): pandas `.df` assertions (28 files), POSIX
  fd/permission tests (`O_CLOEXEC`, 0o600), subprocess tests, Pydantic
  `frozen`/`SecretStr` behavior, Python `jq` binding, mutmut/LoC-budget meta-tests.
- Quality bars to mirror: 90% coverage floor. (Mutation-score bar dropped per `[SA1]`.)

### 2.3 The `analytics` monorepo (local at `../analytics`) — first-party referees

| Asset | Path | Role in this plan |
|---|---|---|
| Canonical bookmark JSON Schema | `lib/common/mxpnl/report/bookmarks/generated/bookmark.json` | **Referee**: every TS-built bookmark payload must validate against it |
| Server-side bookmark parser | `bookmark_parser/` (insights/funnels/retention + `validate.py`) | **Referee**: TS payloads must parse server-side |
| schema4api generated types | `webapp/app_api/**/types.d.ts` (45 files) + `iron/common/types/schema4api/` | **Source of truth** for entity types (dashboards, bookmarks, flags, alerts, Lexicon, replays, webhooks) — derive, don't hand-port Pydantic |
| Internal OpenAPI → TS | `webapp/app_api/v1/generated/openapi.internal.json` → `iron/generated/platform/v1/types.gen.ts` via `@hey-api/openapi-ts` | Type-generation pipeline to copy |
| Public OpenAPI specs | `api_references/openapi/src/common/{app-api,export-api,ingestion-api}.yaml`; plus [mixpanel/docs](https://github.com/mixpanel/docs) query/export specs | Neutral contract source for Query/Export APIs |
| Webapp TS client layer | `iron/common/report/queries/{query-api,app-api,utils}` (~60 per-entity App API clients + Query API clients over `BaseClient`) | **Structural template**: mirror this decomposition so the port reads native to Mixpanel TS engineers |
| Query payload builders in TS | `iron/common/report/insights/` (clause models + `InsightsQueryManager`), `report-manager/query.ts`, `flows/query.ts`, funnels/retention models | Idiom reference for builder APIs |
| MSW mock fixtures | `iron/.storybook/mocks/api/{query,app}/...` | Seed realistic response-side vectors |
| Replay embed | `iron/replay-embed/` (+ forked `@mixpanel/rrweb-player`), `query-api/session-replay.ts` | Reference for replay fetching/merging |
| House conventions | `base-tsconfig.json` strict (incremental via `@ts-strict-ignore`), Vitest, npm workspaces, **no Zod/io-ts** — JSON Schema server-side + generated `.d.ts` client-side | Adopt: generated types + JSON-Schema boundary validation, not Zod-everywhere |

**Gap finding**: iron contains **no PKCE code** (CSRF-session + legacy implicit grant
only). The Python library is the *only* reference implementation for the auth
subsystem → budget extra adversarial review there; no second oracle exists.

---

## 3. Prior Art & Lessons Applied

Condensed from research; sources in Appendix C.

| Lesson | Source | How this plan applies it |
|---|---|---|
| One-shot translation fails at repo scale; closed translate→compile→test→repair loops work | Augment guide; repo-level studies (GPT-4: 8.1% full-project) | Everything runs as verification-gated agent loops |
| Rulebook before fan-out; dependency map; mechanical resumable queue ("done" = artifact on disk) | Anthropic migration blog (Bun Zig→Rust 1M LOC / 2 weeks; Python→TS 165K LOC / weekend) | Phases 0–1 produce the rulebook + queue before any volume porting |
| **Validate the judge**: oracle must pass on the original and fail on deliberately broken code | Anthropic | Corpus must pass 100% on Python and fail on deliberately broken Python — deliberate-break smoke check (§5, Layer 1) `[SA1]` |
| Adversarial review: two independent reviewers + arbiter; check assertions weren't weakened | Anthropic | Per-module gate in the port pipeline (Phase 3) |
| Compiler in-loop when cheap | Anthropic (tsc in-loop for the Python→TS port) | `tsc --strict` runs inside every agent loop |
| **Partial-suite green ≠ parity**; agents converge on passing the subset while diverging system-wide | ScanCode→Rust case study | Layer 2 differential fuzzing + Layer 4 whole-system live parity are mandatory exit criteria |
| Fixed tests alone can't prove semantic preservation | Berkeley EECS-2025-174; Oxidizer; Kaizen | Property-based differential oracle on top of fixed vectors |
| LLMs are measurably weaker translating *out of* Python | PolyHumanEval | Verification carries the weight, not translation skill; strongest model on rules/review |
| Language-neutral JSON vectors + thin per-language harness is the proven cross-language pattern | Wycheproof, JSON-Schema-Test-Suite, NIST ACVP, toml-test | The conformance corpus design (§5, Layer 1) |
| Fix the pipeline, not the output; cluster failures upstream into rules | Anthropic; Google Research | Failure triage protocol in Phase 3 |

---

## 4. Target Architecture (`mixpanel-headless-ts`)

### 4.1 Repo & package topology (D1, D3)

```
mixpanel-headless-ts/
├── packages/
│   ├── core/        # @mixpanel-headless/core   — isomorphic, zero Node deps
│   │   ├── src/client/        # MixpanelAPIClient: fetch-based, region table, retry,
│   │   │                      #   pagination, JSONL streaming (ReadableStream)
│   │   ├── src/query/         # builders, validators, segfilter, selector strings
│   │   ├── src/bookmarks/     # bookmark schema types + builders + enums
│   │   ├── src/types/         # result types + generated entity types
│   │   ├── src/replays/       # rrweb analyzer (pure), aggregators, replay service
│   │   ├── src/services/      # discovery, live-query, replays orchestration
│   │   ├── src/workspace.ts   # Workspace facade (async)
│   │   ├── src/auth/          # Session/Account model, resolver core, PKCE primitives
│   │   │                      #   (WebCrypto), TokenResolver interface
│   │   └── src/errors.ts      # exception hierarchy → Error classes w/ cause
│   ├── node/        # @mixpanel-headless/node    — TOML config (~/.mp), token files
│   │                #   (atomic 0o600 via fs), localhost OAuth callback server,
│   │                #   bridge file, env-var resolution
│   └── browser/     # @mixpanel-headless/browser — injectable Storage provider,
│                    #   redirect-based PKCE, oauth_token mode (scope per D2 spike)
├── conformance-runner/   # consumes vectors from the Python repo (git submodule or
│                         #   published tarball); replays via undici MockAgent / MSW
└── differential/         # TS side of the oracle bridge (stdin JSON-RPC server)
```

- **TS config**: `strict: true` from day one (no `@ts-strict-ignore` escape hatch —
  greenfield doesn't need iron's incremental migration), `exactOptionalPropertyTypes`,
  ESLint, Prettier. Vitest for tests, fast-check for PBT. (StrykerJS dropped per `[SA1]`.)
- **Transport**: `fetch` + `ReadableStream` (isomorphic); no axios. Custom JSONL line
  splitter ported from `_iter_jsonl_lines` (the gzip chunk-boundary handling is a known
  bug workaround — port the *behavior*, verify with vectors).
- **Auth abstraction**: `core` defines `TokenResolver` / `CredentialStore` interfaces;
  `node` and `browser` provide implementations. Basic (service account) and Bearer
  (oauth_token / oauth_browser) header construction lives in core.

### 4.2 API mapping conventions (rulebook seed — Phase 0 finalizes)

| Python | TypeScript |
|---|---|
| 205 sync `Workspace` methods | **All async** (`Promise`-returning). The single biggest structural change; applied uniformly, no sync escape hatches |
| kwargs | Single `options` object per method (last positional param) |
| Generators / `Iterator[...]` streaming | `AsyncIterable<T>` (async generators) |
| Context managers (`__enter__/__exit__`, `client.stream`) | `close()` + `Symbol.asyncDispose` |
| Pydantic models (validation layer) | Generated types from schema4api/OpenAPI + JSON-Schema validation at trust boundaries (house style; **not** Zod) |
| Dataclass result types + lazy `.df` | Plain classes/interfaces, identical field names/shapes; `.df` → `toRows()` / column accessors; optional Arrow adapter later. **Result JSON shape must match Python exactly** so vectors stay shared |
| Discriminated `Account` union (`Field(discriminator="type")`) | TS discriminated union on `type` |
| `Literal` aliases (~50) | String/number literal union types |
| Exceptions hierarchy (~35 classes) | `Error` subclasses preserving names, `cause`, and machine-readable `code` |
| `SecretStr` | Redacting wrapper class (`toString() → '***'`, explicit `.reveal()`) |
| `difflib.get_close_matches` suggestions | JS close-match substitute; **conformance compares error codes, not suggestion strings** |
| `IntEnum` (rrweb) | `const` objects / numeric literal unions |
| Protocols (`TokenResolver`, `WorkspaceResolver`) | Interfaces |
| `time.sleep` retry | `await delay()`; identical backoff math (429-only, exponential from 1s, honor `Retry-After`) |
| POSIX atomic 0o600 writes | Node: `fs` atomic write + chmod (drop fd-flag hardening specifics); Browser: injectable storage |
| networkx/anytree conveniences | Dropped from v1 (document as Python-only extras) |
| pandas aggregator helpers (replays) | Reimplement over row arrays (5 small functions) |

**Semantic-trap watchlist** (differential fuzzer priorities): ints beyond 2^53
(project/workspace IDs are safe, but event counts may not be — decide `bigint` policy),
float formatting in serialized params, date/timezone serialization, `None` vs
`undefined` vs absent key in JSON bodies, dict-ordering assumptions, Unicode handling in
the selector-string escaper (`properties["plan"] == "premium"` path).

### 4.3 Browser reality (D2 — SPIKE COMPLETE, 2026-08-14)

**Spike result: direct browser access is REAL.** Measured with preflight (OPTIONS) and
authenticated requests carrying an `Origin` header, per endpoint × region:

| Surface | CORS posture | Verdict |
|---|---|---|
| Query API (`/api/query/*`) — us/eu/in | Preflight 200; **echoes the request Origin**; allows `Authorization`, GET/POST; authenticated 200 confirmed with `access-control-allow-origin: <origin>` (live segmentation data returned) | **Browser-callable** |
| App API (`/api/app/*`) — us/eu/in | Preflight 200; `access-control-allow-origin: *`; allows `authorization, content-type`; GET/PATCH/POST/PUT/DELETE; `max-age 86400`; authenticated 200 confirmed (bookmarks list) | **Browser-callable** (ACAO `*` ⇒ header-based auth only, no cookies — which is our model) |
| Export API (`data.mixpanel.com`, `data-eu`) | Preflight 200 but **no CORS headers** | **Node-only** (export streaming excluded from browser tier) |

Resulting tiers for `@mixpanel-headless/browser` v1:
- **Tier A — Node/edge/SSR**: full capability (unchanged).
- **Tier C — direct browser with bearer tokens (`oauth_token` / PKCE-obtained): IN SCOPE.**
  Query + App API work cross-origin today. Service-account Basic auth remains refused in
  browser builds by policy (secret exposure), even though CORS would technically permit it.
- **Tier B — proxy pattern**: demoted to a documented fallback for export streaming,
  rate-limit pooling/caching (60 q/hr still applies per project), and SA-credential setups.

Notes for implementers: `/api/app/me` responds but is very slow (minutes) — never place it
on an interactive path; use the pinned-session flow and cached `me.json` semantics as Python
does. HTTP/2 flakes were observed once against `/api/app`; transport should tolerate
protocol fallback. **Remaining unverified**: browser-origin PKCE end-to-end (DCR client
registration + redirect-URI acceptance for third-party origins) — verify during B9; if DCR
rejects arbitrary redirect URIs, Tier C ships with `oauth_token` (server-minted, handed to
browser) and PKCE stays Node-only until resolved.

### 4.4 Explicitly out of scope for v1 (D4 + findings)

CLI (`mp`), `--jq` filtering (no good browser libjq; revisit jq-wasm later), pandas
DataFrames, networkx/anytree graph conveniences, keyring-style OS credential stores.
The Python library remains the agentic/CLI/data-science surface; TS targets embedding.

---

## 5. Verification Architecture — Five Layers + Three Referees

The port is "done" only when all layers are green. Ordered cheapest → most authoritative.

### Layer 0 — Compiler & lint as always-on judge
`tsc --strict` + ESLint inside every agent loop (seconds per check — the Anthropic
Python→TS precedent). Nothing merges red.

### Layer 1 — The extracted conformance corpus ⭐ the centerpiece

**What**: language-neutral JSON vectors, one per extracted test scenario, in the
**Python repo** at `conformance/` (D5), organized by capability
(`conformance/vectors/funnels/*.json`, `.../segmentation/`, `.../cohorts/`, ...).

**Vector schema** (per-vector; full JSON-Schema in Appendix A):

```json
{
  "id": "funnels/build_funnel_params/behavior_type_is_funnel",
  "source_test": "tests/test_build_funnel_params.py::TestDefaults::test_behavior_type_is_funnel",
  "kind": "builder | wire | parse | validation-error",
  "call": { "api": "workspace.build_funnel_params",
            "input": { "steps": ["Signup", "Purchase"], "from_date": "2025-01-01" },
            "session": { "type": "service_account", "region": "us", "project_id": "12345" } },
  "expect": {
    "output": { "...canonical builder output JSON..." },
    "request": { "method": "GET", "path": "/api/query/funnels",
                 "params": { "...": "..." }, "json_body": null,
                 "headers_contain": { "authorization": "Basic <redacted-pattern>" } },
    "given_response": { "status": 200, "body": { "...": "..." } },
    "result": { "...parsed result as canonical JSON..." },
    "error": { "code": "B12", "field": "steps" }
  }
}
```

**How vectors are produced — extraction, not authorship**:
1. A pytest plugin (`conformance/record/`) wraps the two seams the suite already uses:
   the `_transport` kwarg (captures every mocked request + canned response + parsed
   result for ~1,400 wire tests) and the public builder entry points (captures
   input kwargs → output JSON for ~1,800 pure builder tests, via a registry of
   `build_*` methods).
2. Run the suite once in record mode → emit vectors keyed by test nodeid. Manual review
   samples ~5%, an agent audits the rest for extraction artifacts.
3. Validation-rule tests extract as `validation-error` vectors comparing **error codes**
   (V*/B* rule IDs), not message strings.
4. MSW fixtures from `iron/.storybook/mocks/api/` seed additional `parse` vectors with
   realistic response bodies.

**Runners**:
- Python runner in the Python repo's CI (every PR): proves the *original* passes 100%
  of its own corpus — this validates the extractor and pins the contract against
  future Python drift.
- TS runner in `mixpanel-headless-ts` (`conformance-runner/`): replays `call.input`
  through the TS API with undici `MockAgent`/MSW intercepting fetch; canonicalizes
  (sorted keys, normalized number/date rendering) and diffs.

**Judge validation** (non-negotiable, per Anthropic + ScanCode lessons):
- Corpus passes 100% on unmodified Python.
- Corpus **fails** on deliberately broken Python `[SA1]`: 8–12 hand-authored sabotage
  patches (one per major capability area — validation rule flip, builder param drop,
  URL-path change, retry math change, pagination guard change, serializer null/absent
  flip, …) applied one at a time in a throwaway worktree; the corpus runner must produce
  ≥1 failure per sabotage. A missed sabotage → extract more vectors or add authored
  ones covering that area, then re-run.

### Layer 2 — Python as permanent differential oracle

- Two tiny bridge processes speaking JSON-RPC over stdin/stdout: `oracle-py` (imports
  `mixpanel_headless`, exposes builder/validator/serializer entry points) and
  `oracle-ts` (same surface over the TS build).
- A Hypothesis-driven harness (reusing the suite's 41 composite strategies) generates
  random inputs, runs both bridges, canonicalizes, diffs. Any divergence = bug filed
  with the shrunken repro.
- Priorities: the three Filter translation paths (bookmark JSON / segfilter / engage
  selector strings — string escaping is the riskiest), validation rule outcomes (by
  code), param serialization, slugify/naming, rrweb analyzer output on generated event
  streams, resolver precedence (Node side).
- Runs nightly forever; it is drift insurance for as long as both libraries live.

### Layer 3 — Translated tests where behavior is internal

Hand-translated (agentically, pytest→Vitest) only where the wire can't see it:
retry/backoff timing, pagination iteration semantics (MAX_PAGES guard, cursor
handling), error mapping, token refresh + expiry re-sign (replays' 403-as-expired), CDN
walker 404-sentinel logic, config-resolution precedence and file round-trips
(`@mixpanel-headless/node`), streaming chunk-boundary behavior.
- The ~554 Hypothesis properties are re-expressed in fast-check (invariants port
  conceptually; the delegation-equivalence family is redefined for async).
- rrweb analyzer: shared fixtures (`tests/fixtures/rrweb/` + new captured samples +
  `iron/replay-embed/__test__/fixtures.ts`) with Python's outputs frozen as golden
  files.
- **Adversarial review gate**: paired independent reviewers + arbiter verify no
  assertion was weakened or dropped in translation.
- ~~Mutation parity~~ `[SA1]` — dropped; assertion-fidelity is carried by the adversarial
  review gate above plus the differential oracle (Layer 2).

### Layer 4 — Live suite as whole-system parity gate

- Parameterize the 503 live tests' scenarios; run against a dedicated demo project from
  **both** implementations on a nightly schedule (rate-limit-aware: 60 q/hr budget →
  sharded across nights or across projects; responses cached and diffed after
  canonicalization).
- This is the anti-ScanCode layer: end-to-end, real-API, cross-implementation diffing
  that a mocked subset can never fake.

### Three Mixpanel-only referees (bonus layers)

1. **`bookmark.json` schema check**: every bookmark payload the TS builders emit in
   Layers 1–2 is additionally validated against
   `analytics/lib/common/mxpnl/report/bookmarks/generated/bookmark.json`.
2. **`bookmark_parser` round-trip**: a small harness feeds TS-built payloads to the
   server-side parser (`bookmark_parser.validate`); must parse cleanly.
3. **schema4api / OpenAPI drift check**: generated entity types are regenerated in CI
   from `webapp/app_api/**` schemas + public OpenAPI specs; a type-level diff flags
   contract drift in either direction.

---

## 6. Execution Plan

### Phase 0 — Spike, rulebook, and stress test ✅ COMPLETE (2026-08-14)

Delivered:
1. **Browser CORS/auth spike** ✅ — results in §4.3. Headline: Query + App APIs are
   browser-callable with bearer auth in all regions; Export is Node-only; Tier C in scope.
2. **Rulebook** ✅ — `context/typescript-port-rulebook.md` v1.1: 11 sections, iron-idiom
   informed (notably: iron's `BaseClient` is deprecated — factory-function clients over an
   injectable transport are the house pattern), error-code registry (V/B/CF/CB/U/UP
   families), and 32 stress-test amendments including the new §11 `pythonCompat` module
   (CPython `str()`/float-repr/int-parse/zfill/codepoint-length semantics, ported once,
   vector-locked).
3. **API map** ✅ — `context/typescript-port-api-map.{md,json}`: 205 public Workspace
   members across 39 sections + 281 exports, each with TS signature sketch, package, and
   batch assignment. The JSON is the machine-readable Phase 3 queue.
4. **Stress test** ✅ — 3 modules (`segfilter`, `pagination`, annotations slice) × 2
   independent ports (rulebook-follower vs iron-expert), arbitrated. Yield: 32 rulebook
   amendments; 2 real wire divergences found by live Python↔TS parity corpora (float
   rendering `"18.0"` vs `"18"` — decision R10.11 pending; Python list-repr in messages —
   resolved by codes-not-messages); 5 latent Python bugs queued for Python-side fixes
   (rulebook R10.7); one process finding promoted to rule: shared client internals port
   once, first (R10.8), and every module runs a throwaway differential harness with a
   mandatory edge-case set before review (R10.9). All stress code discarded.

### Phase 1 — Verification rig (before any real porting; ~1 week of agent time)

1. Record-mode pytest plugin + corpus emission + Python corpus runner wired into the
   Python repo's CI (D5). Target: ≥3,000 vectors extracted.
2. Judge validation: deliberate-break smoke check (sabotage patches × corpus runner)
   `[SA1]`; patch weak coverage.
3. TS repo scaffold: packages, tsconfig strict, Vitest/fast-check, CI. `[SA1]`
4. TS conformance runner (fetch interception + canonicalizer).
5. Differential bridges (`oracle-py`, `oracle-ts` stub) + Hypothesis fuzz harness.
6. Referee harnesses: bookmark.json validator, bookmark_parser round-trip, type
   regeneration from schema4api/OpenAPI.

**Gate**: Python passes 100% of corpus; corpus catches every deliberate-break sabotage
`[SA1]`; TS runner passes on a hand-written hello-world module. Only then does fan-out
begin.

### Phase 2 — Contract layer (types first)

Generate entity types (schema4api + OpenAPI), port `_literal_types`, exceptions,
`Account`/`Session` model, result-type shapes (with `toRows()`), Filter/param types.
Every type gets its serialization locked by vectors before anything consumes it.

### Phase 3 — Dependency-ordered port pipeline (the queue burn-down)

Order: **types → validators (`validation.py`, `user_validators`) → builders
(bookmark_builders/schema/enums, segfilter, transforms, expressions, query/) →
api_client (region table, auth headers, retry, pagination, streaming) → services
(discovery, live_query, replays + rrweb analyzer) → workspace facade → accounts/
session/targets surface → node package (config, storage, callback server, bridge) →
browser package (per spike)**.

Per-module loop (all agentic, resumable, "done" = artifacts on disk):
1. Translate the module's Layer-3 tests (where applicable) — tests first, per house TDD.
2. Implement until `tsc` + module vectors + translated tests are green.
3. Throwaway differential harness with the mandatory edge-case set (rulebook R10.9:
   integral float, fractional float, `True`, `None`, empty list, empty string, non-BMP
   string, every error branch), then fixed-budget fuzz of the module's entry points.
4. Adversarial review pair + arbiter (assertion-weakening check, rulebook compliance,
   `// TODO(port)` flags for unconfident spots).
5. ~~StrykerJS on the module~~ `[SA1]` — dropped (mutation testing out of scope).

Fan-out task packets MUST include the module's call sites or their signatures (rulebook
R10.10) — consumer-ergonomics decisions cannot be made blind.

Failure triage protocol: recurring failure patterns amend the **rulebook** and
regenerate affected modules (fix the pipeline, not the output). Model tiering: volume
translation on the fast/cheap tier; rulebook, api_client, auth, and all review on the
strongest tier. Auth gets doubled review (no second oracle — §2.3 gap).

### Phase 4 — Burn-in (multi-night)

Nightly for ≥4 consecutive green nights: full corpus (both languages), differential
fuzz (fresh seeds), live-suite parity run, referee checks. `[SA1]` Failures cluster
→ upstream fixes → regenerate → reset the counter.

### Phase 5 — Release engineering

npm packaging (ESM + types, conditional exports), docs generated from the API map,
proxy-pattern reference implementation, examples (Next.js/edge/Node), CHANGELOG
discipline, and a **standing CI contract**: Python repo PRs run record-mode + corpus;
TS repo consumes corpus at a pinned version and CI fails on drift.

### Exit criteria (all required)

- [ ] 100% conformance-corpus pass in TS (and Python, continuously)
- [ ] Judge validated: corpus catches all deliberate-break sabotage patches `[SA1]`
- [ ] Zero unexplained differential divergences across ≥4 fuzz-nights
- [ ] Live-suite parity: identical canonicalized results from both implementations
- [ ] All bookmark payloads pass `bookmark.json` + `bookmark_parser` referees
- [ ] Coverage ≥ 90% per package (mutation-score bar dropped per `[SA1]`)
- [ ] Adversarial audit sign-off: no weakened assertions, no unresolved `TODO(port)`
- [ ] `tsc --strict` clean, zero `any` without justification comments

### Effort & cost envelope

~15× smaller than Bun's 1M-LOC/$165K/2-week migration. Estimate: **1–3 weeks
wall-clock**, mostly unattended; token cost plausibly **low thousands of dollars** with
full adversarial review; human time concentrated in Phase 0 (rulebook + spike review)
and gate reviews.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent converges on passing extracted vectors while diverging elsewhere (ScanCode failure) | Layers 2 + 4 are mandatory exits; vectors are the floor, not the ceiling |
| Extraction bugs bake wrong expectations into the corpus | Python must pass its own corpus in CI forever; 5% human sample; mutmut kill-rate check |
| Assertion-weakening during Layer-3 translation | Adversarial reviewer pair + arbiter `[SA1]` |
| Sync→async rewrite introduces ordering/concurrency bugs invisible to wire vectors | Dedicated Layer-3 tests for pagination/streaming/retry timing; fuzz with delayed mock responses |
| String-escaping divergence in engage selector builder | Highest-priority differential fuzz target with adversarial Unicode/quote inputs |
| Auth subsystem has no second oracle | Double review, full Layer-3 translation of auth tests, live-suite auth scenarios in both runtimes |
| JS number semantics (2^53, float rendering) corrupt params silently | Canonicalizer flags precision loss; `bigint` policy decided in rulebook; fuzzer biases huge ints |
| Corpus and Python drift apart post-port | D5: record-mode + corpus run on every Python PR; TS pins corpus version and diffs on bump |
| Browser promises overreach (CORS/rate limits) | D2 spike gates all browser claims; tiered support documented honestly |
| 205-method surface bloats core bundle | Package split (D3) + subpath exports + tree-shaking checks in CI (size-limit) |

## 8. Remaining open questions

1. ~~Numeric wire-rendering policy~~ **RESOLVED 2026-08-14**: server coerces number
   operands via `float()` (`bookmark_parser/.../segfilter_to_property_filter.py:209`) and
   evaluates in V8 doubles; confirmed empirically via live segmentation
   (`1 == 1.0` matches all events). TS uses natural JS rendering; canonicalizer
   normalizes numeric strings only in operand positions (rulebook R10.11). Bonus finding:
   new-format insights `filterValue` must be JSON numbers, not strings (rulebook R10.12).
2. Corpus transport between repos: git submodule vs published
   `@mixpanel-headless/conformance` tarball (lean: published artifact with version pin).
3. Browser-origin PKCE (DCR redirect-URI acceptance for third-party origins) —
   unverified; fallback documented in §4.3. Verify during batch B9.
4. ~~The 5 latent Python bugs from the stress test~~ **FIXED 2026-08-14** —
   [PR #206](https://github.com/mixpanel/mixpanel-headless/pull/206) (merge before
   running vector extraction).
5. Arrow adapter for results: v1.1 candidate, not v1.
6. Whether to upstream the extracted corpus as public API documentation-by-example (it
   is, effectively, an executable spec of Mixpanel's Query/App APIs).

~~Resolved in Phase 0~~: browser scope (Tier C in — §4.3); bigint policy (strings, iron
precedent); CLI/jq/pandas exclusions (rulebook §1, R4.7).

---

## Appendix A — Conformance vector JSON-Schema (sketch)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ConformanceVector",
  "type": "object",
  "required": ["id", "kind", "call", "expect"],
  "properties": {
    "id": { "type": "string" },
    "source_test": { "type": "string" },
    "kind": { "enum": ["builder", "wire", "parse", "validation-error"] },
    "call": {
      "type": "object",
      "required": ["api", "input"],
      "properties": {
        "api": { "type": "string", "description": "dotted public entry point" },
        "input": { "type": "object" },
        "session": { "type": "object", "description": "canonical fake session" }
      }
    },
    "expect": {
      "type": "object",
      "properties": {
        "output": {},
        "request": {
          "type": "object",
          "properties": {
            "method": { "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"] },
            "path": { "type": "string" },
            "params": { "type": "object" },
            "json_body": {},
            "headers_contain": { "type": "object" }
          }
        },
        "given_response": {
          "type": "object",
          "properties": { "status": { "type": "integer" }, "body": {} }
        },
        "result": {},
        "error": {
          "type": "object",
          "properties": { "code": { "type": "string" }, "field": { "type": "string" } }
        }
      }
    }
  }
}
```

Canonicalization rules (both runners): UTF-8, sorted object keys, integers rendered
without exponent, floats via shortest-round-trip, dates as emitted strings (no
re-parsing), auth headers matched by pattern not value, `null` vs absent-key preserved
as distinct.

## Appendix B — Module port order & size

| Batch | Modules | Python LOC | Verification emphasis |
|---|---|---|---|
| B0 | `pythonCompat` (rulebook §11) + shared client internals by name: `app_request`, `_handle_response`, retry/backoff, `maybe_scoped_path`, `_iter_jsonl_lines` (rulebook R10.8) | ~1,000 | ported once, first; every later slice imports, never re-implements; vector-locked |
| B1 | literal types, exceptions, Account/Session, result shapes | ~5,500 | vectors: serialization shape |
| B2 | validation.py, user_validators | ~3,700 | validation-error vectors by rule code |
| B3 | bookmark builders/schema/enums, segfilter, transforms, expressions, query builders | ~4,400 | builder vectors + bookmark.json + bookmark_parser referees + heaviest fuzz |
| B4 | api_client + pagination | ~9,100 | wire vectors + Layer-3 retry/stream/pagination tests |
| B5 | services (discovery, live_query, replays) + rrweb analyzer | ~5,100 | wire + parse vectors; rrweb golden files |
| B6 | workspace facade | ~11,000 | delegation vectors + async equivalence PBT |
| B7 | accounts/session/targets surface + resolver core | ~2,700 | Layer-3 + resolver-precedence PBT |
| B8 | node package (config, io, callback server, bridge) | ~6,000 | Layer-3 translated FS tests |
| B9 | browser package | new | spike-scoped; PKCE redirect flow tests |

## Appendix C — Sources

- [Anthropic — How we run large-scale code migrations with Claude Code](https://claude.com/blog/ai-code-migration)
- [AboutCode — An AI agent ported our codebase from Python to Rust (ScanCode case study)](https://aboutcode.org/blog/agentic-scancode-port-case-study/)
- [Augment — AI code migration guide](https://www.augmentcode.com/guides/ai-code-migration)
- [Google Research — Accelerating code migrations with AI](https://research.google/blog/accelerating-code-migrations-with-ai/)
- [Oxidizer — Scalable, validated project translation (PLDI 2025)](https://dl.acm.org/doi/10.1145/3729315)
- [MatchFixAgent — repo-level translation validation & repair](https://arxiv.org/html/2509.16187v1)
- [TRAM — mock-based in-isolation validation](https://www.arxiv.org/pdf/2511.21878)
- [TransAGENT — multi-agent code translation](https://arxiv.org/html/2409.19894v2)
- [BabelCoder — agentic translation w/ spec alignment](https://www.arxiv.org/pdf/2512.06902)
- [DiffSpec — differential testing from specs](https://arxiv.org/html/2410.04249v3)
- [Kaizen — metamorphic/differential testing of LLM-translated code](https://arxiv.org/html/2607.04058v1)
- [Berkeley EECS-2025-174 — LLM translation needs formal compositional reasoning](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2025/EECS-2025-174.pdf)
- [SpecTra — multi-modal specs improve translation](https://arxiv.org/html/2405.18574)
- [JSON-Schema-Test-Suite (pattern)](https://github.com/json-schema-org/JSON-Schema-Test-Suite) · [Wycheproof (pattern)](https://appsec.guide/docs/crypto/wycheproof/)
- [Hypothesis — QuickCheck in every language](https://hypothesis.works/articles/quickcheck-in-every-language/)
- [Mixpanel Query API authentication](https://docs.mixpanel.com/reference/query-api-authentication) · [Mixpanel public OpenAPI specs](https://github.com/mixpanel/docs)
- [Daniel Janus — Translating non-trivial codebases with Claude](https://blog.danieljanus.pl/2026/03/26/claude-nlp/)
- [InfoWorld — Python→Rust with Claude, a critical take](https://www.infoworld.com/article/4135218/what-i-learned-using-claude-sonnet-to-migrate-python-to-rust.html)
