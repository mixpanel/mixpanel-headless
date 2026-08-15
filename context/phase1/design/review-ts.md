# Adversarial Review — TS Consumability + Referees lens (D11–D15, naming-map)

Status: FINAL
Reviewer lens: Can the TS side actually consume what Phase 1 produces? (D11–D15, naming-map.md, vector.schema.json)
Design under review: context/phase1/design/phase1-design.md @ repo commit 5269674; vector.schema.json; naming-map.md
Method: every claim below verified against repo source/tests/recon by grep or spot-read; citations are file:line at commit 5269674.

---

## F1 — BLOCKER — The TS runner cannot resolve `call.api` for the bulk of the corpus: api-map.json covers ONLY Workspace members

**Claim.** D12 says `api-map.gen.ts` is "generated into `conformance-runner/src/api-map.gen.ts` from `context/typescript-port-api-map.json` at scaffold time" plus the naming-map §4 exceptions table. But wire vectors carry `call.api` values like `api_client.get_events` (vector.schema.json:33 gives exactly this example; D7 dispatches on `call.api` prefix to `MixpanelAPIClient`/`ReplaysService`/`OAuthFlow`/`probe_region`). Neither mapping source contains any of those names:

- `context/typescript-port-api-map.json` has exactly two top-level arrays: `workspace_members` (205 entries, all `Workspace` methods/properties) and `exports` (281 bare strings like `"Workspace"`, `"Account"`). Zero `api_client.*`, `replays.*`, `oauth_flow.*`, `region_probe.*` entries. Verified by parsing the file.
- naming-map §4 seed rows cover only: `workspace.build_params`, `segfilter.*`, `bookmark_builders.*`, `query.user_builders.*`, `expressions.*`, `transforms.*`, `compat.*`, and three `_`-privates. No api_client, no services, no auth entry points.

**Failure scenario.** Concrete vector: `{"kind":"wire","call":{"api":"api_client.update_annotation","input":{"annotation_id":123,"body":{"description":"x"}}}}` (from tests exercising api_client.py:5771). naming-map §4 says the runner "FAILS FAST (`UNMAPPED_API` verdict) on any `call.api` it cannot resolve via api-map.gen.ts + this table — silent fuzzy matching is forbidden." The recon-estimated ~1,400 wire-classified vectors nearly all carry `api_client.*`/service names → the very first full-corpus run (TS-5 done-criterion: "completes with PASS for compat vectors, UNPORTED for everything else, zero FAIL*") is unachievable as specified: the runner cannot even distinguish UNPORTED (module known, not built) from UNMAPPED for these names, because no artifact enumerates the modules. TS-4's done-criterion ("every call.api resolves to mapped-name-or-UNPORTED without throwing") is likewise unmeetable from the stated inputs.

**Aggravator (signature metadata).** Even where a name maps, replaying requires per-method positional-order/options-bag reconstruction (R3.3/R3.8: positionals stay positional, keyword-only → options object). api-map.json carries `params`/`kwonly` lists for Workspace members only; nothing exists for `api_client.*` (e.g. `update_annotation(self, annotation_id: int, body: dict)` — api_client.py:5771-5773). The design never says where the TS runner gets this arity data for non-Workspace APIs.

**Cross-lens note (D1, flagged for the Python-rig reviewer).** The design also never specifies the *mechanism* that captures `call.api` + `call.input` for wire vectors at all: D1.1 hooks the transport (records requests/responses), D1.2/D4 wrap only the 5 facades + a builder short-list. Nothing wraps the hundreds of `MixpanelAPIClient` public methods whose name/kwargs must populate `call.api`/`call.input` for a wire vector to be replayable. Without that, wire vectors are schema-invalid (`call.api` is required, vector.schema.json:28).

**Fix.** Either (a) extend the api-map generator to emit an `api_client_members` (+ services/auth) section with `params`/`kwonly`, and generate the module-known list for UNPORTED classification from it; or (b) make the record plugin emit a `registry`-style sidecar (`conformance/vectors/api-index.json`) enumerating every recorded `call.api` with its signature shape, and have TS-4 consume that instead. Also specify the client-method capture mechanism in D1.

---

## F2 — MAJOR — `bytes` values are unrepresentable: `csv_bytes` input, `download_lookup_table` bytes result, no binary request-body encoding

**Claim.** D2's own rationale names "lookup-table orchestration" as an in-scope multi-request family, but:
- `upload_to_signed_url(self, url: str, csv_bytes: bytes)` (api_client.py:7606) is called with raw bytes in tests (tests/unit/test_api_client_data_governance.py:1477-1478: `b"col1,col2\na,b"`). A wire vector for it puts a Python `bytes` object in `call.input`. The codec table (D4.4 + PR-3 list: Filter, FunnelStep, …, datetime, SecretStr) has no `bytes` codec; the schema's `taggedValue` examples (vector.schema.json:227) list none.
- `download_lookup_table(...) -> bytes` (api_client.py:7855-7861, "Returns raw bytes (not JSON)") — `expect.result` is defined as "canonical JSON of the value the library returned" (vector.schema.json:61); D6 has no rule for bytes.
- `expectedRequest` offers only `json_body` and `body_text: string` (vector.schema.json:119-124). Today's test CSV bytes are UTF-8 so `body_text` limps by, but any non-UTF8 upload body (the design's own D1.1 says response bodies get "base64/text" — requests get no such option) is unencodable.

**Failure scenario.** Record mode reaches `test_upload_to_signed_url_network_failure` (test_api_client_data_governance.py:2325) → emitter must serialize `call.input = {"url": ..., "csv_bytes": b"..."}` → either crashes (`TypeError: Object of type bytes is not JSON serializable`) or an ad-hoc encoding is invented that `conformance-runner/src/codecs.ts` has no mirror for → TS replay cannot reconstruct the `Uint8Array` body and the request diff fails.

**Fix.** Add `{"$type":"bytes","encoding":"base64","data":...}` to both codec tables; add `body_base64` to `expectedRequest`; define `expect.result` encoding for bytes returns (same `$type` tag).

---

## F3 — MAJOR — Filesystem-dependent inputs (`UploadLookupTableParams.file_path`) make lookup-table facade vectors unreplayable; no exclusion category covers them

**Claim.** `Workspace.upload_lookup_table(params: UploadLookupTableParams, ...)` (workspace.py:7750) reads a local CSV via `params.file_path` (types.py:5672). The tests create the file under pytest `tmp_path` (tests/unit/test_workspace_data_governance.py:1467, 1538, 1592, 1642). A recorded vector's `call.input.params.file_path` is a run-specific temp path on the recording machine.

**Failure scenario.** TS runner decodes the `$type: UploadLookupTableParams` input and invokes `workspace.uploadLookupTable` → the TS impl must read `/private/var/folders/.../products.csv` (or `/tmp/pytest-of-runner/...` on CI) → ENOENT → vector fails forever, in every environment including the Python runner's own re-execution (D7 re-executes library code; the temp file is gone even on the recording machine). D10's exclusion table has no category for local-file-dependent inputs, so these vectors land in the corpus and break PR-6's "100% pass" done-criterion.

**Fix.** Either exclude file-reading facades (new D10 category `fs_dependent`, logged) and cover the 3-step orchestration via the `api_client`-level wire vectors instead, or define a codec rule that inlines file content (`{"$type":"file","name":...,"content_base64":...}`) with both runners materializing a temp file (node:fs is legal in the runner, not core).

**Adjacent record-mode hazard (cross-lens, D1).** `upload_lookup_table`'s poll loop deadline uses `time.monotonic()` (workspace.py:7858-7860); freezegun freezes monotonic and D1.4 no-ops `time.sleep`, so the async-timeout test (`max_poll_seconds=0.05`, test_workspace_data_governance.py:1592-1595) can spin forever in record mode — a hang, which Risk-register #2's "test failing under freeze is logged and excluded" protocol does not catch.

---

## F4 — MAJOR — The hello-world gate never executes the wire half of the TS runner: VectorFetch, session construction, interaction diffing, transport-error mapping, body_stream all ship unproven

**Claim.** Every D13 gate vector is `builder`-kind (`zfill`/`pythonStr`/`pythonFloatStr`, ~30 authored vectors). Gate criteria 1-4 therefore exercise: loader, manifest pin, `$type` codecs (trivially — inputs are strings/floats), api-map (3 entries), canonicalizer, diff reporting, and one builder-path deliberate break. They exercise NONE of: `VectorFetch` (sequence assertion, Request capture, canned Response construction incl. `body_stream` → `ReadableStream`, 204-null-body handling), `call.session`/`workspace_session` → TS client auth construction, `expect.interactions[]` request diffing (`headers_contain` patterns, `params_absent`, `unordered_group` multisets), or `transport_error` throwing. TS-5's done-criterion explicitly allows all of that code to be dead: "full-corpus run completes with PASS for compat vectors, UNPORTED for everything else."

**Failure scenario.** Phase-1 gate declared met; first Phase-3 wire batch (e.g. annotations CRUD) lands months of vectors on a never-executed replay path; systematic defects in VectorFetch (e.g. comparing httpx-decoded `params` against un-decoded `URLSearchParams`, or wrong auth-pattern matching) surface as hundreds of simultaneous FAIL_REQUESTs indistinguishable from port bugs — exactly the "wrong or useless verdict" the gate exists to prevent, discovered at the most expensive moment.

**Fix.** Add to D13: a set of authored `wire` vectors replayed against a hand-written stub TS "client" registered in the api-map (a ~30-line module that issues fetch calls per its input — not a real port), covering: single interaction, multi-interaction sequence, transport_error, body_stream, headers_contain pattern, unordered_group. Plus one wire-path deliberate break. This keeps the gate cheap while proving the whole verdict pipeline.

---

## F5 — MAJOR — Referee (a) feed contradicts its own scope: piping funnels/flows/retention builder outputs through the insights-only schema guarantees false REJECTs (or a silently dead check)

**Claim.** D15a states both: "the schema is INSIGHTS-ONLY (root `InsightsBookmarkParams`); … Funnels/retention payloads go to referee (b), not (a)" AND "the conformance runner pipes each `builder`-kind vector output whose capability ∈ {segmentation, funnels, flows, retention, bookmarks} through the referee as a secondary assert." Recon confirms the scope caveat: referee-assets.md:34 ("Funnels/retention report params are covered elsewhere: draft-04 hand-written schemas in `bookmark_parser/{common,funnels}/schema/`").

**Failure scenario.** A perfectly correct `buildFunnelParams` output (funnel-shaped params, no insights `sections.show` metric clause) is validated against root `InsightsBookmarkParams` → ajv REJECT → the PR-blocking conformance job (D15 "CI hooks: referee (a) as part of the conformance-runner job") fails on correct code. The inevitable "fix" is to ignore referee-(a) failures for those capabilities — at which point the secondary assert is dead weight nobody trusts.

**Fix.** Restrict the referee-(a) feed to capabilities whose payloads are insights bookmark params ({segmentation, bookmarks-insights}); route funnels/flows/retention outputs to the D15b handoff JSONL only.

---

## F6 — MAJOR — `headers_contain` content policy is unspecified; recording httpx's auto-headers makes wire vectors unreplayable by fetch (and browser-impossible where the library sets `Accept-Encoding`)

**Claim.** D1.1 records "(seq, method, url, headers, decoded-body) of every request"; the schema says only "Subset match: only listed headers are compared" (vector.schema.json:138) and D5 specifies treatment for exactly one header (authorization). Nothing states WHICH headers the emitter writes into `headers_contain`. httpx adds `host`, `accept`, `accept-encoding: gzip, deflate, br, zstd`, `connection`, `user-agent: python-httpx/x.y`, `content-length` to every request.

**Failure scenario.** If the emitter dumps the captured header map verbatim (the natural reading of D1.1), every wire vector asserts `user-agent: python-httpx/…` and `accept-encoding: gzip, deflate, br, zstd`. In the TS runner, `VectorFetch` captures a `Request` whose headers contain only what the TS library set — undici adds `host`/`accept-encoding`/`user-agent` at dispatch time, after any injectable-fetch capture point; browsers forbid setting `Accept-Encoding` at all → 100% FAIL_REQUEST across the wire corpus. Separately, the export path sets `Accept-Encoding: gzip` explicitly (api_client.py:1856) — if recorded as contract, the browser build can never satisfy streaming-export vectors (moot today only because R9.3 makes export Node-only, but the policy must say so).

**Fix.** Add a normative emitter allowlist to D5: record only headers the library or test explicitly sets (authorization [pattern], content-type, `MP_CUSTOM_HEADER_*`-derived headers, and library-set accept-encoding flagged `node_only`); everything else dropped at emit time. Add a `canonical-selftest` case proving both canonicalizers ignore unlisted headers.

---

## F7 — MAJOR — Cross-repo corpus coupling depends on the Python repo's mutable working-tree state; api-map.gen.ts is generated from an UNTRACKED file

**Claim.** D12 pins consumption to a relative path into the Python repo working tree (`"vectorsPath": "../../mixpanel-headless/conformance/vectors"`), whose vectors exist only on the local, never-pushed branch `ts-port/phase1-verification-rig` (D16: "LOCAL COMMITS ONLY — never push"). The plan itself prescribed "git submodule or published tarball" (typescript-port-plan.md §4.1, conformance-runner comment); the design adopts neither and does not log the deviation.

**Failure scenario.** The Python repo is the user's active dev repo (branch `fix/latent-bugs-stress-test` today). Any checkout of another branch removes/changes `conformance/vectors/` under the TS runner's feet mid-Phase-3; the manifest `source_commit` check then makes every TS conformance run (including CI's `conformance` job and the D13 gate re-run) refuse to start until a human flips the other repo's branch back. The gate is hostage to unrelated work in a different repo. Two-machine or CI use is impossible (no remote).

**Aggravator.** TS-4 generates `api-map.gen.ts` "from `context/typescript-port-api-map.json`" — that file is untracked in the Python repo (git status: `?? context/typescript-port-api-map.json`) and D16's commit plan never commits it. The generated mapping's provenance is a file that can silently change or vanish, with no SHA to pin against.

**Fix.** Snapshot the corpus into the TS repo (committed `conformance-runner/corpus/` keyed by `source_commit`, refreshed by a documented copy script that verifies the manifest SHA), or at minimum resolve `vectorsPath` through a dedicated git worktree pinned to the rig branch. Commit the api-map JSON (either repo) and record its hash in `api-map.gen.ts`'s header.

---

## F8 — MAJOR — Tests that patch the clock themselves record vectors that deterministically FAIL replay under RECORD_EPOCH — and they are exactly the "clock-hazard date builders" the corpus most wants

**Claim.** D1.4 handles tests that *read* the ambient clock ("test and src see the same frozen clock"). It does not handle tests that install their own clock: tests/unit/test_bookmark_builders.py:55-57 does `with patch("mixpanel_headless._internal.bookmark_builders.date") as mock_date: mock_date.today.return_value = date(2025, 6, 15)`. At record time the test's mock shadows freezegun, so the registry wrap on `build_date_range` (D4.2 item 2) records `expect.output` computed from 2025-06-15. Both runners replay under `RECORD_EPOCH = 2026-01-15` (D7 "installs the same RECORD_EPOCH freeze"; D12 clock shim) → replay output uses 2026-01-15 → guaranteed diff.

**Failure scenario.** PR-6's done-criterion ("100% pass over the committed corpus") fails on these vectors; the triage options are exclude-and-lose-coverage or invent an unplanned "vector-local clock" field. Either way the design's D1.4 determinism claim is wrong for this class, and the blast lands on the highest-value date-builder vectors (D4.2 explicitly targets `build_date_range`/`build_time_section` for the frozen-clock treatment). Census: this is the only test file that patches the module date (grep over tests/), so the count is small — but the affected surface is the one D4.2 calls out.

**Fix.** Record-plugin rule: if the wrapped callable's module clock attribute is a `unittest.mock` object at call time, either (a) skip emission with manifest category `test_local_clock`, and hand-author replacements for `build_date_range` under RECORD_EPOCH; or (b) add an optional `call.clock_epoch` field that overrides RECORD_EPOCH per vector (both runners honor it).

---

## F9 — MINOR — D11 pins `ajv-draft-04` "(referee a)" but referee (a) requires `Ajv2020`; draft-04 validation lives Python-side in this design

D15a correctly mandates `Ajv2020` (recon referee-assets.md:39: plain Ajv silently ignores `prefixItems`). The draft-04 schemas (`bookmark_parser/{common,funnels}/schema/`, referee-assets.md:118) are validated by the PYTHON harness in D15b (jsonschema Draft4 auto-selected). `ajv-draft-04` is therefore a dead dependency in the TS scaffold under this design — recon:252 lists it only for the option (not taken) of running the draft-04 schemas in TS. Failure scenario: a TS-8 implementer follows D11's parenthetical, wires referee (a) with `ajv-draft-04`, and the `prefixItems` tuple check on `checkpoints` silently weakens — the exact trap recon documented. Fix: correct the D11 line ("ajv 8.x `Ajv2020`, strict:false; NO ajv-draft-04 unless the draft-04 schemas move TS-side").

---

## F10 — MINOR — `transport_error` replay shape ambiguous: "throws the mapped transport error per R2.10" reads as throwing `MixpanelHttpError`, which would bypass the adapter under test

R2.10 makes the ADAPTER own the fetch `TypeError`/`DOMException`/`UND_ERR_*` → `MixpanelHttpError` mapping. If `VectorFetch` throws an already-mapped `MixpanelHttpError` (the literal reading of D12), the adapter's mapping code is never exercised and, worse, may double-wrap (e.g. `upload_to_signed_url`'s port catches transport failures to wrap as `MixpanelHeadlessError` code `UPLOAD_ERROR`, api_client.py:7646-7651 — the vector from test_api_client_data_governance.py:2325 expects exactly that class/code). Fix wording: VectorFetch must reject the way native fetch rejects (a `TypeError` with `cause`, per class-mapping table httpx-name → fetch-rejection committed next to the codec tables); the httpx class name in the vector selects which rejection to synthesize.

---

## F11 — MINOR — Naming-map mechanical gaps (no wrong verdicts, but unimplementable as written)

1. §3 says the transform applies "to top-level kwarg names flagged `camel` in the exceptions table's domain defaults" — but the §4 row format (`{"python","ts","scope","rule"}`) has no domain-default construct; nothing machine-readable says, per API, which kwargs are pure-bag (camel, R3.6) vs wire-shaped (keep). Workable today only because wire-shaped inputs are `$type`-tagged models; state that explicitly or add a `domain` row kind.
2. naming-map §4 calls api-map.json "authoritative per member" (R7.3), but its `ts_signature` fields are not TS (`"async list_workspaces(): Promise<list[PublicWorkspace]>"` — snake name, Python generics). The mechanical transform is the real authority; the generator for `api-map.gen.ts` must not trust `ts_signature`.
3. Vector-id slugging (`[^a-z0-9_-]` → `-`, lowercased) can collide across DIFFERENT nodeids (parametrize ids `"A"` vs `"a"`); the `-N` ordinal only disambiguates multiple vectors from ONE nodeid (D3). Two distinct vectors with one id breaks the TS loader's id-keyed reporting. Cheap fix: collision detection at emit time (abort) or append a nodeid hash.

## F12 — MINOR — Canonicalizer/schema edge cases unpinned

1. Negative zero: ECMAScript `String(-0)` is `"0"`, Python `repr(-0.0)` is `"-0.0"`. D6 rule 5 says "one rule: ECMAScript semantics" with a conversion table, but neither D6 nor the D13 selftest enumeration names −0.0 as a JSON-number case (D13 lists it only as a `pythonFloatStr` string output). If Python-side canonicalization emits `-0.0`, an identical-behavior TS run diffs. Add `-0.0` to canonical-selftest.json.
2. vector.schema.json:119 — "`json_body` … null means no body" conflates a literal JSON `null` body with body-absent. No current endpoint posts literal `null`, but the schema should use key-absence for "no body" (the design's own R3.5/absent-vs-null discipline).
3. `givenResponse.body`/`body_text`/`body_stream` mutual exclusivity lives only in a `$comment` (vector.schema.json:162) — not schema-enforced (`oneOf` costs three lines; the drift check self-validates vectors against this schema, so enforcement is free).

## F13 — MINOR — Bridge protocol: sound overall (no stdout writers in the library — verified: all `print(` hits in src are docstring examples), two unpinned edges

1. Lone-surrogate strings: Python `json.dumps` happily emits `"\udc80"`, but writing that line to a UTF-8 stdout raises `UnicodeEncodeError`, killing oracle-py mid-session. Hypothesis default `st.text()` excludes surrogates, but D14 mandates importing/vendoring the suite's 41 composite strategies unaudited. Spec should mandate `ensure_ascii=True` framing plus a surrogate-reject rule in the D6 encoder.
2. D14's oracle-ts UNPORTED responses are counted "as skip, not divergence" — fine, but the harness done-criterion ("oracle-py↔oracle-ts for the compat module") plus F4 means the bridge, like the runner, never touches a wire-shaped payload in Phase 1. Same fix as F4 (stub surface) would double here.

## F14 — MINOR — D12's injected-fetch choice deviates from plan §4.1 ("replays via undici MockAgent / MSW") — the deviation is correct (R2.4-aligned, browser-honest) but is not recorded in the Discrepancy Log, which claims to reconcile design vs plan ("repo reality wins"). Log it; the next agent reading plan §4.1 verbatim will otherwise re-litigate the seam.

---

## Explicitly checked and NOT findings

- **R2.4/R2.11 conflict**: none. Injected fetch IS the R2.4 seam; `redirect: 'manual'` is the library's own init and no recorded test serves 3xx (grep over tests: no `Response(30x)` mocks), so VectorFetch never needs redirect semantics. Vectors can't verify the library passes `redirect:'manual'` — acceptable residual for Layer-3.
- **R9.1 purity**: runner/oracle are separate workspaces; D11's ESLint boundary + browser-bundle smoke matches R9.1's stated enforcement. Clock/UUID injectability (D12) keeps shims out of core globals.
- **R1.1/scaffold vs rulebook §1**: D11's tsconfig is a superset of R1.1 (strict, exactOptionalPropertyTypes, noUncheckedIndexedAccess, ESM-only all present); Node 20 floor present; Prettier defaults per R1.2; StrykerJS correctly absent per the scope amendment (checked: zero mutation references in D11-D15).
- **gzip replay hazard**: latent only — no test serves actual gzipped bodies (`gzip` appears in tests only in comments/PBT docstrings; `_iter_jsonl_lines` operates on httpx-decoded bytes, api_client.py:107-116), so `body_stream` chunks are plaintext and `new Response(ReadableStream)` replay is faithful. Should a future mock serve content-encoding'd bytes, D2 needs a decoded-vs-raw rule — one sentence, not Phase-1-blocking.
- **204-status mocks (61 in tests)**: all body-less; TS `new Response(null, {status:204})` is legal. Implementation note only.
- **D15b recipes**: match recon transcripts A/B exactly (PYTHONPATH variants, 4 pinned wheels, enum-loose `math`, legacy-vs-modern dialect routing — referee-assets.md:120-207). No discrepancy found.
- **D15c vendoring**: coverage holes (webhooks in iron tree, no cohorts types, alerts/custom only) are faithfully recorded from recon §3a and escalated. Correct.
- **Strategy imports (D14)**: `tests/` and `tests/unit/` are real packages (`__init__.py` present), so `from tests....import` works as claimed.

## Severity summary

| ID | Severity | One-liner |
|---|---|---|
| F1 | blocker | call.api unmappable for all non-Workspace wire vectors; TS-4/TS-5 criteria unmeetable from stated inputs |
| F2 | major | bytes inputs/results/request-bodies unrepresentable (lookup-table family is in scope by name) |
| F3 | major | file_path-dependent vectors unreplayable anywhere; no exclusion category |
| F4 | major | hello-world gate leaves the entire wire replay path unexecuted |
| F5 | major | referee (a) feed vs insights-only scope contradiction → false REJECTs in a PR-blocking job |
| F6 | major | headers_contain allowlist unspecified; httpx auto-headers unfulfillable by fetch |
| F7 | major | corpus/api-map coupling to mutable working tree + untracked file |
| F8 | major | test-local clock mocks poison the flagship date-builder vectors under RECORD_EPOCH replay |
| F9-F14 | minor | ajv-draft-04 mislabel; transport_error throw shape; naming-map mechanics; −0.0/schema laxities; bridge edges; unlogged plan deviation |
