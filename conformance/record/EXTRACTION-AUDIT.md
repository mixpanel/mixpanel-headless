# PR-5 Extraction Audit — 5% sample, method and findings

Per design D18/PR-5 and Risk Register #1: a 5% random sample of emitted
vectors was audited against their source tests; extractor bugs found were
fixed IN THE EXTRACTOR and the corpus re-extracted (vectors were never
hand-edited).

## Sampling method (reproducible)

- Population: every vector in `conformance/vectors/**/*.jsonl` (final run).
- Sample: `random.Random(20260814).sample(sorted(ids), ceil(0.05 * N))`
  → 127 vector ids over N = 2,536.
- Split by kind (final corpus): 63 builder/validation-error, 64 wire.
  (Earlier audit rounds over pre-fix corpora drew 64/63 — ids shifted when
  the F5 capability fix moved 9 `replays.*` vector ids.)

## Audit procedure

1. **Builder/validation-error vectors (automated re-execution)**: each
   sampled vector's `call.input` was decoded through the production codec
   table, the registry target re-invoked under the D1.4 frozen clock, and
   the encoded outcome (output or structured error) compared canonically
   against `expect`. This is the PR-6 runner's execution model applied as
   an audit instrument. **Final result: 63/63 pass.**
2. **Wire vectors (manual review)**: each sampled wire vector was rendered
   as a structured summary (api, input, setup chain, session, per-
   interaction method/host/path/params/body-kind/status, expected
   result/error) and reviewed against expectations; a subset was verified
   line-by-line against the source test bodies (`test_query_workspace_
   scoping` workspace_id pinning, `test_api_client_phase008` 429 retry
   count vs `max_retries=1`, `test_workspace_schemas` URL-encoding,
   `test_workspace_crud` two-session create_bookmark POST+PATCH,
   `test_discovery` suggestion-fetch setup/measured split). Sampled-wire
   capability spread: bookmarks 11, entities 25, discovery 10, cohorts 6,
   data-governance 3, pagination 3, segmentation 2, engage/funnels/
   retention 1 each. After the F5 re-extraction shifted 9 `replays.*`
   ids, the refreshed sample's 13 new members (2 replays incl. a 50-
   interaction CDN walk, 2 hostile-Retry-After pagination sequences,
   funnels sort, 8 entities CRUD) were reviewed the same way — zero new
   findings. The random draw contained no streaming/flows/auth wire
   vectors, so vectors from those capabilities were additionally reviewed
   by hand (supplemental, outside the 5% frame) — see "Supplemental
   review" below.

## Findings (all RESOLVED by extractor fixes + re-extraction)

Pre-audit fixes (surfaced by the first full record run and the double-run
byte-diff, before sampling):

- **B1** `_sessions_for` assumed real client objects; tests wrapping a
  `unittest.mock` client made 632 facade-builder tests FAIL under record
  mode (their captures would have been lost as `freeze_incompatible`).
  Fixed with type-gated session extraction.
- **B2** D5.2 abort fired for `probe_region` (no bound session; the
  credential travels in `call.input.headers`). Fixed: acceptance path 3 —
  observed auth must appear verbatim in the call's own input.
- **B3** D5.2 abort fired for resolver-backed accounts (`oauth_browser`,
  env-backed `oauth_token`). Fixed: emit adopts the observed bearer as the
  session token when unique across the vector; per-request-varying bearers
  (rotating-resolver freshness tests) exclude the vector as
  `unserializable_input`.
- **B4** Nondeterministic sub-second timestamps in `OAuthTokens.expires_at`
  across double runs: jittered virtual-sleep ticks accumulated in the
  frozen clock ACROSS tests. Fixed: `reset_test_state` moves the clock
  back to `RECORD_EPOCH` per test (mirrors the UUID counter reset).
- **B5** `SecretStr` fields inside Pydantic models serialized as
  `"**********"` (pydantic JSON-mode masking), making `OAuthTokens`
  vectors unreplayable and violating D5.5. Fixed: field-level model
  encoding (reveals SecretStr, tags datetime/date, keeps computed fields
  expect-side only).
- Also: vector ids containing class-cased api segments violated the schema
  id charset (lowercased in ids only); the low-entropy `"x" * 4096`
  truncation fixture false-positived the D5.4 entropy screen (added a
  10-distinct-character floor).

Audit findings from the 5% sample:

- **F1 (codec table gap, CONFIRMED + FIXED)** `HoldingConstant` — and a
  systematic scan then found **61** `call.input` `$type` tags in the
  corpus with no decode entry (every entities-CRUD `*Params` Pydantic
  model, `OAuthTokens`, `Exclusion`, `SignedReplay`, …). Any runner replay
  would have crashed on decode. Fixed with a mechanical public-type
  fallback table (`_public_type_codecs`: every public BaseModel/dataclass
  in `mixpanel_headless.types` + `OAuthTokens`) and a Pydantic decode path
  (`_decode_model`), with round-trip regression tests.
- **F2 (false contract, CONFIRMED + FIXED)** The U24 vector
  (`validate_user_args(cohort=MagicMock(spec=CohortDefinition))` whose
  `to_dict` raises) encoded the mock as `$type: callback`; replay would
  inject a benign stub and get `[]` instead of the U24 error — a baked-in
  wrong expectation. Fixed: `unittest.mock` arguments now raise
  `UnencodableValueError` → `unserializable_input` exclusion (the mock's
  behavior IS the contract and cannot be a vector). Corpus total went
  2,537 → 2,536.
- **F3 (URL-encoding contract erased, CONFIRMED + FIXED)**
  `test_create_schema_url_encodes_names` asserts `"My Event / Test"` is
  percent-encoded in the URL, but the recorder stored `httpx.URL.path`,
  which percent-DECODES — a TS port that fails to encode would replay
  identically. Fixed: the snapshot now records the RAW encoded path
  (`url.raw_path`); query params stay structured/decoded (both runners
  decode consistently).
- **F4 (unreplayable retry sequences, CONFIRMED + FIXED)** 429 vectors
  from tests constructing `MixpanelAPIClient(max_retries=1)` record
  2-attempt sequences, but nothing in the vector carried `max_retries` —
  a default-configured replay client would issue 4 requests and fail on
  unmutated src (poisoning the D9 control run). Fixed: schema extension
  (12) `call.client_options` (captured only when non-default; currently
  `max_retries`), emitted on wire vectors.

## Supplemental review (capabilities missed by the random draw)

Wire vectors from `streaming`, `replays`, and `auth` were reviewed by
hand after the final extraction (`flows` has 51 builder vectors and no
wire vectors — flow wire tests route through `api_client`-level entries).
Findings and observations:

- **F5 (capability misfiling, CONFIRMED + FIXED)** `replays.fetch_files`
  vectors landed under capability `entities`: the mechanically-generated
  `ReplaysService` wire entries carried no capability and the emit-time
  endpoint table has no CDN-host row, so the fallback fired. Fixed:
  the registry pins `capability="replays"` on ReplaysService entries.
- **Streaming**: export vectors record the mock's in-memory JSONL body as
  `body_text` and the yielded items as `expect.result`. No `body_stream`
  vectors exist in the extracted corpus — correct by design: the only
  chunk-boundary tests drive a raw `httpx.Client` (excluded as
  `raw_transport_no_entrypoint`, D1.3) and their contract arrives as
  PR-7 authored `_iter_jsonl_lines` chunk vectors (D2/D4.2 item 9).
- **CDN walker ordering (documented decision)**: `replays.fetch_files`
  interactions are recorded ORDERED with no `unordered_group` marking.
  The transport seam has no batch-boundary signal, and under CPython
  asyncio + a synchronous mock transport the gather order is
  deterministic (proven by the double-run byte-diff). The Python runner
  replays under the same scheduler, so ordered comparison holds for the
  Phase-1 gate. If the TS runner's scheduling diverges on these vectors,
  TS-4/TS-5 can derive group boundaries mechanically from
  `call.input.concurrency` plus the file index in each CDN path (the
  schema/emit/canonicalizer group machinery from PR-4 is already in
  place). Recorded in notes for the TS tasks.

## Runner note recorded for PR-6

The setup/measured model can record a setup entry whose re-execution
RAISES by design (e.g. `get_event_properties` 400 → suggestion fetch via
`get_events` as the measured call). The corpus runner must tolerate
exceptions from `call.setup[]` entries (their request sides are still
diffed via `expect.interactions[]`).

## Outcome

Zero unresolved fidelity findings. After the final fixes the automated
builder re-execution audit passes 63/63 sampled vectors, the wire sample
review is clean, and the double-run byte-diff is clean.
