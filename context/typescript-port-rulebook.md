# TypeScript Port Rulebook

**Status**: v1.1 (Phase 0 complete — stress-test amendments applied) · **Date**: 2026-08-14
**Authority**: This document governs every translation decision in the port. Agents follow it
exactly; ambiguities get flagged as `// TODO(port): <reason>` and escalated, never guessed.
Recurring failures amend THIS file and regenerate affected modules — fix the pipeline, not the output.
Rules tagged `[ST]` originate from the Phase 0 stress test (3 modules × 2 independent ports, diffed
and arbitrated; parity corpora run against the live Python implementation).
Companion artifacts: `typescript-port-plan.md` (architecture & verification),
`typescript-port-api-map.{md,json}` (the mechanical queue).

---

## 1. Language & toolchain baseline

| Rule | Value |
|---|---|
| R1.1 TS config | `strict: true`, `exactOptionalPropertyTypes: true`, `noUncheckedIndexedAccess: true` `[ST]`, ESM only |
| No `any` | `unknown` + narrowing; `any` requires a justification comment (mirrors mypy-strict culture) |
| No `@ts-strict-ignore` | Greenfield repo; iron's incremental escape hatch is not adopted |
| Formatting | Prettier defaults (NOT iron's backtick-everything lint rule — external npm package) |
| R1.2 Lint `[ST]` | No backtick-quotes rule, no `@ts-strict-ignore`, no `eslint-disable camelcase` wrappers. Iron-internal conventions are not adopted; do not copy a neighbouring file's lint suppressions |
| Test stack | Vitest + fast-check + undici MockAgent/MSW for wire. `[SA1]` Mutation testing (StrykerJS/mutmut) is OUT OF SCOPE for the port per user directive 2026-08-14 — no mutation gates anywhere in the pipeline |
| R1.3 Docs `[ST]` | JSDoc on every exported symbol. Port the Python docstring's *content*, not its structure: keep `@throws`, `@example`, and every comment explaining *why*; omit `@param` lines that only restate the signature |
| Node floor | Node 20+ (native fetch, WebCrypto, `Symbol.asyncDispose`) |

## 2. HTTP & client architecture (iron-informed, standalone-adapted)

Iron's `BaseClient` is **deprecated in-repo — do not imitate it.** The blessed iron pattern is
module-level verb functions over a shared HTTP client with envelope unwrapping. We adapt it to a
standalone library (no singletons — the library is multi-instance by design):

- R2.1 **One `MixpanelHttpClient` instance per `Workspace`/session** (ports `api_client.py`).
  Generic verb helpers: `get<T>`, `post<T>`, `put<T>`, `patch<T>`, `delete<T>` — unwrap the App
  API envelope, return bare `T`. Envelope-preserving variants `getRaw`/`postRaw` return
  `SuccessResponse<T>`.
- R2.2 **Envelope types** (copy iron's shape verbatim):
  ```ts
  type SuccessResponse<T> = { status: 'ok'; results: T; metadata?: unknown; pagination?: CursorPagination };
  type ErrorResponse = { status: 'error'; error: string; type?: string };
  ```
- R2.3 **URL builders** are pure functions mirroring iron's `appApiUrl`/`queryApiUrl`, extended
  with the region table from `api_client.py` (`us|eu|in` × `query|export|engage|app`). Scope
  threads as `{ projectId, workspaceId? }`.
- R2.4 **Injectable transport**: constructor accepts `fetch?: typeof fetch` (the TS analog of
  the `_transport` kwarg; conformance runner and tests inject here).
- R2.5 **Retry**: port Python behavior exactly — 429-only, exponential from 1s doubling, honor
  `Retry-After` (with Python's parse grammar and 60s cap; no jitter), `maxRetries` config;
  5xx/network throw immediately. Token refresh lives in `TokenResolver.getToken()` before the
  request (NOT iron's 401-refresh-recurse). `AbortSignal` threaded through every request.
- R2.6 **Streaming**: `ReadableStream` + ported byte-buffered JSONL splitter
  (`_iter_jsonl_lines` semantics preserved, including gzip chunk-boundary handling), exposed as
  `AsyncIterable<T>`.
- R2.7 In-flight dedup (iron's `pendingResponseCache`): **not ported** in v1 — no Python
  equivalent; changes observable request counts (breaks wire vectors).
- R2.8 `[ST]` **Cross-module access to Python `_private` members**: declare the TS member
  public + `/** @internal */` and exclude from the published `.d.ts`. Free functions never get
  `private` access. Where the Python module boundary buys nothing, prefer injecting a narrow
  **function** seam (`PageFetcher`-style) over a client object — but the seam must preserve
  *when* Python resolves auth (per page/request, not per traversal).
- R2.9 `[ST]` **Entity clients are `create<Entity>Client({transport, getScope})` factories, not
  classes.** `getScope()` is a provider invoked **per request**; capturing scope at construction
  silently pins the client across `Workspace.use()` switches.
- R2.10 `[ST]` **Transport-error normalization**: adapters normalize every transport failure to
  `MixpanelHttpError`. Every `except httpx.HTTPError` ports to
  `if (!(e instanceof MixpanelHttpError)) throw e;` — never a bare `catch`. Adapters own the
  fetch `TypeError` / `DOMException` / `UND_ERR_*` mapping.
- R2.11 `[ST]` **Redirects**: `raise_for_status()` ports as an explicit helper that throws
  (preserving `cause`). Transport MUST set `redirect: 'manual'` — httpx raises on 3xx; `fetch`
  silently follows.
- R2.12 `[ST]` **Time units**: all durations are **milliseconds** in TS; convert once at the
  client boundary. Fields carrying Python's seconds are named `*Seconds`, everything else `*Ms`.
- R2.13 `[ST]` **URL builders concatenate strings.** Never `new URL(path, base)` — it
  normalizes `//` and drops path prefixes; the App API is trailing-slash sensitive
  (observed live iron bug: `annotations/tags` + `42/` → `annotations/tags42/`).

## 3. Signatures & shapes

- R3.1 **All public I/O methods are `async` returning `Promise<T>`** — no sync escape hatches.
  Python properties that do I/O become methods; pure/cached getters stay `get` accessors only if
  they never touch the network.
- R3.2 **Streaming methods** return `AsyncIterable<T>` directly (not `Promise<AsyncIterable<T>>`).
- R3.3 **Parameter mapping** (per method, from the Python signature):
  - Required positional params → required positional TS params (max 3).
  - Keyword-only params → a single trailing `options` object with a named
    `interface <Method>Options`.
  - Suffixes: `*Options` (input bags), `*Result` (returns — matches `SegmentationResult` etc.),
    wire-only shapes `*Request`/`*Response`.
- R3.4 **Wire keys stay snake_case inside wire-facing interfaces.** Public surface (method
  names, options keys) is camelCase; the builder/serializer layer owns camelCase→snake_case,
  vectors lock it. Result objects preserve exact Python result field names — do NOT camelize
  result fields.
- R3.5 Conditional param inclusion uses the spread idiom
  `...(workspaceId ? { workspace_id: workspaceId } : {})`. **`null` vs absent-key is
  semantically distinct and must match Python's serializer byte-for-byte** (vector-enforced).
- R3.6 `[ST]` **Input DTO casing**: wire-shaped param models keep Python/API field names
  (`user_id`) so serialization is a pure drop-nulls; pure argument bags are camelCased
  (`fromDate`). Both may appear on one client; that is intended.
- R3.7 `[ST]` R3.1's async rule is **scoped to the `Workspace`/service facade and anything doing
  I/O**. Pure module-level functions (builders, validators, transforms) stay synchronous.
- R3.8 `[ST]` R3.3's options-object rule means **keyword-only** params. Python positionals stay
  positional even when they have defaults.
- R3.9 `[ST]` Every Python `T | None = None` ports to `x?: T | undefined`, never bare `x?: T` —
  `exactOptionalPropertyTypes` otherwise rejects the explicit-`undefined` call sites mechanical
  translation produces.

## 4. Types

- R4.1 Entity/wire types: **generate** from schema4api (`webapp/app_api/**/types.d.ts`) and
  public OpenAPI specs; import and compose/alias (iron's `app_api/*` pattern). Hand-write only
  what has no schema source.
- R4.2 Validation: JSON-Schema at trust boundaries (API responses in debug mode, config files).
  **No Zod** — generated static types + boundary validation (house pattern).
- R4.3 Enums: string `enum` for closed domain values with wire meaning that Python defines as
  `Enum` classes (`FeatureFlagStatus`); string-literal unions for option bags and the ~50
  Python `Literal` aliases (`BookmarkType` is a `Literal` alias, so it takes the union form —
  source kind wins); `const` objects + literal unions for rrweb numeric IntEnums (preserve
  numeric values). (Editorial fix per phase2-design Discrepancy Log #3: an earlier revision
  named `BookmarkType` as the string-enum example.)
- R4.4 Discriminated unions on a `type` field (Account), narrowed via exhaustive `switch` with
  `never` check.
- R4.5 **Numbers policy** (iron precedent: `data_group_id?: string`): IDs documented/observed to
  exceed 2^53 → `string`; project/workspace/bookmark ids, counts, timestamps → `number`.
  Canonicalizer flags any numeric field > 2^53 in fixtures → escalate to the string list.
  ⚠ Resolve together with R10.11 (float rendering) — one decision.
- R4.6 `SecretStr` → `Secret` wrapper (`toString()`/`toJSON()`/inspect → `'**********'`,
  explicit `.reveal()`). Frozen Pydantic models → compile-time `readonly` interfaces only —
  **no runtime `Object.freeze`** `[ST]` (both stress pairs independently converged on this).
- R4.7 Dataclass result types → plain classes with `readonly` fields, `toJSON()` matching
  Python's dict shape, `toRows()` replacing `.df` (identical row shape).
- R4.8 `[ST]` **Python `dict` used as a lookup table → `ReadonlyMap`.** Plain objects are
  prototype-unsafe: `map['constructor']` returns a function where Python's `in` returns `False`.
  If an object literal is required for ergonomics, every membership test uses `Object.hasOwn`.
- R4.9 `[ST]` **Python `Any` → `unknown`, never `any`.** Generify (`paginateAll<T>`) only where
  the API map says the call site knows its entity type.
- R4.10 `[ST]` **Python `None` → `null`** at every data-model and result boundary. `undefined`
  is reserved for genuinely-absent optional *parameters*.
- R4.11 `[ST]` Python conditional key insertion (`if x: d['k'] = v`) → a distinct object literal
  per branch. Never assign `undefined` to a key; `{k: undefined}` and an absent key are
  distinguishable to the canonicalizer.
- R4.12 `[ST]` **Response parsing replicates Pydantic v2 lax coercion** via one shared `coerce`
  module: `coerceInt` accepts `42`/`42.0`/`"42"`, rejects `42.5` and booleans; `coerceStr` does
  not coerce int→str; `coerceBool` accepts the `true|t|yes|y|on|1` sets. `default_factory`
  fires only on an **absent** key — explicit `null` is a validation error. Never
  `as unknown as T`.

## 5. Errors

- R5.1 Two-tier split (iron model + Python hierarchy):
  - `MixpanelApiError` (app-level: HTTP responded, body has `status:'error'` or query-API error
    shape) — carries `statusCode`, `responseBody`, `requestId?`.
  - `MixpanelHttpError` (HTTP-level: unparseable body / transport) — carries `response`.
  - Base: `MixpanelError extends Error` with `this.name = this.constructor.name` and `cause`.
- R5.2 Port all ~35 Python exception classes as subclasses preserving names. The Python
  exception name is the conformance key: vectors assert error CLASS NAME + machine `code`,
  never message text.
- R5.3 Validation errors carry the structured registry codes — families `V0–V27` (+`V3b`,
  `V22a/b`), `B1–B26` (+`B22b`), `CF1–CF2`, `CB1–CB3`, `U0–U30`, `UP1–UP4`, full codes like
  `V7_LAST_POSITIVE`. **Codes are the cross-language contract; message strings may differ.**
  `difflib.get_close_matches` suggestions are advisory (excluded from vectors).
- R5.4 `[ST]` **Error message text is explicitly out of contract**: never emulate Python
  `repr()`, list formatting, or httpx wording. Conformance canonicalizers strip messages before
  diffing.
- R5.5 `[ST]` **Python builtins (`ValueError`, `TypeError`) and `pydantic.ValidationError`** are
  not in the ~35-class hierarchy and have no code. Mint two registry codes —
  `VALIDATION_ERROR` (param/construction) and `RESPONSE_VALIDATION_ERROR` (`model_validate`
  failure) — and map builtin raises in pure builders to the owning domain error with a `V*`
  code. Until a site has a code, its vector is excluded from the corpus.

## 6. Async & resource idioms

- R6.1 Generators (`yield`) → `async function*`. Pagination: `for await` consumable, lazy,
  `MAX_PAGES = 10000` guard preserved, per-paginator 429 retry (3 attempts) preserved.
- R6.2 Context managers → `close(): Promise<void>` + `[Symbol.asyncDispose]`. `Workspace.use()`
  preserves the connection-reuse invariant (same client instance, swapped auth).
- R6.3 `time.sleep` → injectable `sleep(ms)` (fake-timer friendly).
- R6.4 Replays CDN walker keeps parallel-fetch + 404-sentinel design; concurrency limit
  identical to Python's.
- R6.5 Python `Protocol` → `interface`.
- R6.6 `[ST]` Python `yield from results` ports as **item-level** `yield*` (vector parity).
  Page-level iteration and array collection are additive helpers (`collectPaginated`), never
  the primitive.
- R6.7 `[ST]` **`AbortSignal` is threaded through four points**: between pages, into the
  request, into the backoff sleep, and normalized on exit. Every cancellation path throws
  `DOMException('…', 'AbortError')` — a sleep rejecting with a plain `Error` evades every
  name-based check.
- R6.8 `[ST]` Python `assert` → an `invariant(cond, msg)` helper throwing `MixpanelError`.
  Never a `!` non-null assertion (erases the runtime check). Prefer restructuring so
  control-flow analysis proves it.

## 7. Module & file conventions

- R7.1 Kebab-case filenames; entity client modules `<entity>-client.ts` with sibling
  `<entity>-types.ts` when large. Tests: Vitest-standard `*.test.ts` colocated (iron's
  `__test__/` dirs are Bazel-driven; not adopted).
- R7.2 Service decomposition mirrors iron's `queries/{query-api,app-api}` split; packages per
  plan §4.1.
- R7.3 Method naming: verb + entity (`listBookmarks`, `createAnnotation`) — iron style. The
  Workspace facade keeps the Python-derived name camelized (API map is authoritative per
  member); internal service modules use iron verbs. No `Async` suffixes.
- R7.4 Booleans: `is*`/`include*`/`use*`/`has*`. **No lodash** — stdlib only in `core`.
- R7.5 Generated types: alias then compose; generated files are read-only.
- R7.6 `[ST]` **Identifier casing**: TS identifiers (functions, methods, params, locals) are
  camelCase; module constants SCREAMING_SNAKE. **Exception**: anything crossing the wire or
  entering a serialized `details`/result bag keeps its Python/API spelling. Vector keys
  therefore need a documented snake↔camel mapping in the Phase-1 extractor. Python
  `_`-prefixed module-privates drop the underscore; privacy = not exported.

## 8. Semantic-trap watchlist (fuzzer priorities, in order)

1. `[ST]` **Tuple-unpacking arity** — Python raises on mismatch; JS destructuring silently
   binds `undefined` and ships corrupt payloads. Worst class on the list.
2. **Selector-string escaping** (`filter_to_selector`): quote/backslash/Unicode escaping must
   match Python char-for-char.
3. **Number rendering** in params: CPython float repr switches to exponent when exponent < −4
   or ≥ 16 (two-digit zero-padded exponent); `str(18.0)` = `"18.0"` vs JS `"18"`. See R11.2 and
   the R10.11 decision.
4. **`None`/`null`/absent** tri-state in JSON bodies and query params (per-field,
   vector-locked).
5. **Date handling**: dates are STRINGS end-to-end (`YYYY-MM-DD`); never construct `Date` in
   the request path. Result parsing keeps date strings verbatim.
6. `[ST]` **Empty-collection truthiness** — `[]`/`{}`/`""` falsy in Python; `[]`/`{}` truthy in
   JS. `if not steps` → `if (steps.length === 0)`, never `if (!steps)`. (Observed: three
   adjacent Python guards where two translate literally and one does not.)
7. `[ST]` **Prototype-chain membership** — `'toString' in obj` is true in JS, `False` in
   Python. See R4.8.
8. `[ST]` **`str(True)`/`str(None)`** → `"True"`/`"None"` where Python stringifies operands
   (see R11.1); bare `String()` emits `"true"`/`"null"`.
9. `[ST]` **`str.zfill` vs `padStart`** — sign handling differs (`"-1".zfill(3)` = `"-01"`).
10. **Dict/key ordering**: never rely on it; canonicalizer sorts; serialized param order
    defaults to Python's emission order.
11. **Unicode**: no implicit NFC/NFD changes; `[ST]` Python slicing/`max_length` count
    codepoints, JS `.slice`/`.length` count UTF-16 units (see R11.6).
12. **Float equality in validators**: identical comparison semantics; no epsilon introduction.

## 9. Platform boundaries

- R9.1 `core` imports NOTHING from `node:*`; touches no globals beyond
  `fetch`/`crypto`/`TextEncoder`. CI enforces via lint boundary + browser-bundle smoke test.
- R9.2 `node`: TOML config (same schema), token files (atomic write + `chmod 0600`; keep
  symlink refusal, drop POSIX fd-flag hardening), localhost OAuth callback (ports 19284–19287),
  bridge file, env resolution. Resolver precedence identical: env > param > target > bridge >
  config.
- R9.3 `browser`: injectable `CredentialStore` (default in-memory; documented localStorage
  adapter with security warning), redirect-based PKCE (WebCrypto), `oauth_token` mode
  first-class. Service-account Basic auth **refused at runtime in browser builds** with an
  explanatory error. (Spike result: Query API + App API are CORS-open with bearer auth in all
  regions; Export API is not — export streaming is Node-only.)
- R9.4 Env-var reading only in `node` (`MP_*` identical to Python). `core` receives config as
  constructor input only.
- R9.5 `[ST]` `core` takes an injected `Logger` interface; never `console`. Log text is not
  vector-compared.

## 10. Porting workflow rules (agent behavior)

- R10.1 Tests-first per module: translate/port the module's Layer-3 tests, then implement to
  green.
- R10.2 Never weaken an assertion. If an assertion can't be ported faithfully, `TODO(port)` +
  escalate. Adversarial review checks this specifically.
- R10.3 Unconfident translation → `// TODO(port): <reason>` and continue; never silently guess.
- R10.4 A recurring fix (≥3 occurrences) is a RULEBOOK bug: stop, amend here, regenerate.
- R10.5 "Done" = TS file exists + `tsc --strict` clean + module vectors green + translated
  tests green. State lives on disk; the queue rebuilds from disk.
- R10.6 Python is the arbiter of behavior; iron is the arbiter of style; this file records
  every resolution.
- R10.7 `[ST]` **Bug-compatibility is the default.** Latent Python bugs found while porting are
  reproduced verbatim, commented, and filed as Python-side issues — never fixed in TS alone
  (guaranteed oracle divergence). To change behavior: fix Python first, regenerate vectors,
  then port. The stress-test bug queue (`results: null` TypeError; hostile `Retry-After`;
  400-branch empty message; 401 `request_body` asymmetry; missing `request_params`) was
  **fixed in Python on 2026-08-14** — PR #206 — so vectors extract from the fixed behavior.
- R10.8 `[ST]` **Shared client internals are ported once, first, by name** — `app_request`,
  `_handle_response`, retry/backoff, `maybe_scoped_path`, `_iter_jsonl_lines` — before any
  domain slice. Slice ports import; they never re-implement. (Observed: two independent
  `_handle_response` ports diverged; one silently dropped the 403
  `SESSION_RECORDING_SENSITIVE_DATA` branch.)
- R10.9 `[ST]` **Every module port runs a throwaway differential harness before review**, not
  only vector replay after. The harness corpus must include the fixed edge-case set: integral
  float, fractional float, `True`, `None`, empty list, empty string, non-BMP string, and every
  error branch. (Observed: a 32-case harness whose only float was `1.5` reported false parity
  on a divergence its own author had documented.)
- R10.10 `[ST]` **Fan-out tasks ship the module's call sites** (or at minimum their
  signatures). Union-vs-optional, `unknown`-vs-precise-union, and input-field casing are
  consumer-ergonomics decisions that cannot be made blind.
- R10.11 `[ST]` **RESOLVED (2026-08-14)**: `"18"` and `"18.0"` are **server-equivalent** for
  number-type segfilter operands. Evidence: server coerces via
  `parse_number` (`analytics/bookmark_parser/common/segfilter/segfilter_to_property_filter.py:209`,
  `float(v)` then int-if-integer) before selector generation
  (`backend/util/arb_selector_utils.py:232`) and V8 evaluation (IEEE-754 doubles); confirmed
  empirically (live segmentation: `where=1 == 1.0` matched all events, `1 != 1.0` matched none).
  **Policy**: the TS serializer uses natural JS number rendering (`18.0` → `"18"`); the
  conformance canonicalizer normalizes numeric strings ONLY in number-filter operand positions
  (narrow, field-scoped — not a general weakening). `pythonFloatStr` (R11.2) stays in
  `pythonCompat` for any other contractual `str(float)` site vectors reveal.
- R10.13 `[ST2]` **Pipeline hygiene — no xhigh workflow agents.** Subagents doing large
  synthesis or implementation tasks run at effort ≤ high WITH an explicit incremental work
  protocol (write a skeleton to disk first; one section/function at a time; frequent tool
  calls; assemble the final answer from a running notes file). Evidence: the Phase-1
  designer and the PR-2 record-plugin builder — both inheriting session xhigh — were killed
  repeatedly (6 and 5 attempts) by the harness's 3-minute silent-thinking stall detector,
  always at whole-artifact planning/synthesis moments; every effort-high agent with the
  protocol completed first try. The orchestrator sets effort explicitly on every workflow
  agent; silently inheriting session effort is forbidden.
- R10.12 `[ST]` **New-format insights `filterValue` takes JSON numbers, not strings.** Unlike
  segfilter `operand` (strings, coerced server-side), `filterValue` is passed through as-is
  (`backend/util/arb_selector.py:1862` `_get_filter_value`) and a string would be quoted into
  the selector as a string literal. Builders emitting new-format filter clauses must emit
  native JSON numbers; vectors lock this per clause type.
- R10.14 `[SA2]` **Model tiering (Phase 3+).** Workflow agents run on fixed per-batch model
  tiers: volume translation batches on the cheap/mid tiers (B2/B5/B6 sonnet, B3 opus) while
  B0/B4/B7/B8/B9 and everything auth- or client-critical stays on the strongest tier. Design,
  adversarial review, arbitration, audits, gate verdicts, failure triage, and any work
  touching the conformance rig itself NEVER leave the strongest tier. A volume-tier task that
  misses its done-criteria retries once on the strongest tier with the failure context (two
  failures still aborts the chain), and R10.13 effort discipline (effort ≤ high + incremental
  work protocol) applies unchanged on every tier. Normative assignment table:
  `context/phase3/model-tiering-policy.md`.

## 11. Python stdlib semantics — the `pythonCompat` module `[ST]`

One shared, vector-locked `pythonCompat` module in `core`, ported once. No module re-derives
these. (Root cause of parity findings P1, P2, P6 and half the watchlist.)

- R11.1 `pythonStr` / `pythonRepr`: `str(True)` → `"True"`, `str(None)` → `"None"`, list/dict
  repr where (and only where) a serialized value is contractual.
- R11.2 `pythonFloatStr`: CPython float repr incl. the exponent rule (switch when exponent
  < −4 or ≥ 16; two-digit zero-padded exponent; `18.0` → `"18.0"`).
- R11.3 `pythonInt` / `pythonFloat` parse grammars: reject `"5.5"` (for int), `"0x5"`, `""`;
  accept `"inf"`/`"nan"`, leading sign, surrounding whitespace. Used by `Retry-After` parsing
  and lax coercion (R4.12).
- R11.4 `zfill` with Python sign handling (`"-1".zfill(3)` → `"-01"`).
- R11.5 Codepoint-aware `sorted` for locale-independent orderings Python produces.
- R11.6 Codepoint-based `slice`/`length` for every `text[:N]` truncation and `max_length`
  validation (UTF-16 units ≠ codepoints; never split surrogate pairs).

---

## Appendix: stress-test provenance

Phase 0 shakedown (2026-08-14): `segfilter.py`, `pagination.py`, and the annotations CRUD slice
each ported twice (rulebook-follower vs iron-idiom expert), diffed by an arbiter agent, with
two live Python↔TS parity corpora (29 + 32 cases). Yield: 32 amendments (tagged `[ST]`),
5 latent Python bugs queued (R10.7), 2 real wire divergences (float rendering — pending
R10.11), and the §11 `pythonCompat` module mandate. All stress-test code was discarded.
