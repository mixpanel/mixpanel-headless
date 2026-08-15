# Adversarial Review — Extraction Fidelity Lens (D1–D5, D10)

Reviewer lens: will recorded vectors faithfully capture the contract?
Status: COMPLETE — 2026-08-14, design/vector-schema/naming-map @ commit 5269674 working tree
Verdict: NOT BUILD-READY as written. Four blockers (F1–F4) mean the record run either cannot emit schema-valid wire vectors at all, aborts on the first non-canonical fake credential, hangs on the poll-timeout test, or produces vectors whose control-run replay fails. All are fixable with bounded design amendments (wire entry-point registry + `calls[]`, per-session credential allow-list, monotonic/sleep policy, keyed unordered serving, nodeid-derived ids); none invalidates the overall record→corpus→runner architecture.

## Findings

### F1 [BLOCKER] Wire vectors have no capture mechanism for `call.api` / `call.input` / `expect.result`
- vector.schema.json requires `call` (`required: ["id","kind","call","expect"]`, line 7) with `api`+`input`; D7 (design line 204) replays wire vectors by invoking "the library call in `call.api`+`call.input`" and diffing "the returned/raised value against `expect.result`".
- But the ONLY two capture layers defined are D1.1 (transport hook — sees HTTP requests/responses only) and D1.2 (registry wrap — explicitly "for pure builders"; D4 registry lists only build_*/validators/transforms, no client query/CRUD methods).
- Nothing in D1–D5 wraps `MixpanelAPIClient.get_events`, `Workspace.create_dashboard`, `LiveQueryService.segmentation`, etc. — so the recorder cannot know which library call produced the transport traffic, what its kwargs were, or what it returned. Wire vectors (the claimed ~1,400, D10) cannot be emitted as schema-valid vectors at all.
- Failure scenario: run the plugin over tests/unit/test_api_client.py::test anything — the hook records interactions, then `emit.py` has no `call.api`/`input`/`result` to write. Either extraction crashes or emits garbage vectors the runner can't execute.
- Fix: add a third capture layer — a wire entry-point registry (every public client/service/workspace method) wrapped like D1.2, with kwargs codecs and return-value serialization; size and codec effort must be added to PR-2/PR-3.

### F2 [BLOCKER] One-vector-per-test breaks on multi-CALL tests (distinct from multi-REQUEST)
- D2 handles one library call → many requests (retry/pagination) via `interactions[]`. It never handles one TEST → many library calls, which is common:
  - retry-state-reset suite (tests/unit/test_api_client.py:1400-1566 per recon wire-seam §4.1) calls the client method twice to prove the retry counter resets;
  - tests/integration/test_cross_project_iteration.py iterates projects issuing several different method calls against one request_log;
  - CRUD tests calling create-then-get.
- Schema `call.api` is a single string; D7 invokes exactly one call. A two-call test's vector would carry interactions from both calls but replay only one → "extra or missing interactions fail the vector" (line 204) → the CONTROL run (unmutated src) fails, poisoning D9's pass criterion ("control run yields 0 failures").
- Fix: either `call` becomes `calls[]` (ordered) or the plugin splits per library-call sub-vectors (`-N` suffix per call, interactions partitioned by which call was on-stack). Requires the F1 entry-point wrap to know call boundaries.

### F3 [BLOCKER] D5 known-credential allow-list is wildly incomplete — extraction aborts on the first non-canonical fake credential
- D5.2: "any authorization value that does NOT decode to one of the known test credentials aborts the record run"; known list = test_user/test_secret, `Bearer test(-oauth)?-token`.
- Repo census (grep over tests/): `username="u"` ×101, `SecretStr("s")` ×91, `username="test_user"` only ×56; plus `team.sa`/`team-secret`, `u1`/`u2`/`s1`/`s2`, `sa`/`sa-secret`, `brw-tok`, `expired-access`, `ey.tok`… dozens of distinct fake credentials.
- Failure scenario: first recorded request from any test using `make_session`-style `username="u", secret="s"` produces `Basic dTpz` → not in the table → record run aborts, per the design's own rule ("Hits fail extraction loudly"). Extraction never completes.
- Fix: the allow-list must be derived per-test from the session actually bound to the client (the recorder already captures it per D5.1) — i.e. "authorization must decode to THIS vector's session credentials", plus an entropy heuristic (real tokens are long/high-entropy; `"s"` is not). The fixed-literal table cannot work.

### F4 [BLOCKER] Frozen clock + no-op sleep makes the poll-timeout test hang or emit an unbounded vector
- D1.4: record mode runs the WHOLE suite under `freezegun.freeze_time(RECORD_EPOCH)` and "patches `time.sleep` to no-op globally".
- The lookup-table upload poll loop is `deadline = time.monotonic() + max_poll_seconds; while time.monotonic() < deadline: time.sleep(poll_interval)` (src/mixpanel_headless/workspace.py:7858-7861).
- `tests/unit/test_workspace_data_governance.py:1546-1595` (`test_async_upload_timeout_raises`) uses a handler that ALWAYS returns PENDING with `max_poll_seconds=0.05`.
- freezegun freezes `time.monotonic` (documented freezegun behavior since 1.x). Frozen monotonic ⇒ `time.monotonic() < deadline` is true forever ⇒ the record run HANGS on this test.
- Even if the plugin's freeze deliberately left `monotonic` real, `time.sleep` no-op turns the loop into a busy-spin issuing thousands of poll requests in 0.05 s of wall time — the vector's `interactions[]` length becomes machine-speed-dependent, so the D8 byte-diff drift gate can never be stable for this test.
- Fix: D1.4 must specify monotonic handling explicitly and D10 needs a `wall_clock_loop` exclusion (or a virtual-clock sleep that advances the frozen clock).

### F5 [MAJOR] VectorTransport position-based replay contradicts `unordered_group`, corrupting CDN-walker replays
- D7 (design line 204): VectorTransport "serves interaction *i*'s recorded `response` ... to request *i*". D2 (line 71): CDN batches are order-nondeterministic (`asyncio.gather`; tests use `sorted(call_log)`, test_replays_service.py:196) and only COMPARED as a multiset.
- Failure scenario: at record time file-0's body was interaction 3; at replay time the walker requests file-2 third; position-based serving hands file-0's rrweb bytes to the file-2 request → the assembled ReplayBundle content is wrong → `expect.result` diff fails on UNMUTATED src → control run non-zero, poisoning D9's pass criterion for the replays capability.
- Serving must be keyed by `(method, path, params)` within an unordered group, not by position; the design specifies multiset semantics only for COMPARISON, not for SERVING.
- Related emit-side gap: D6 rule 9 sorts group members at comparison time only; nothing sorts them at EMIT time, so re-extraction can reorder intra-group interactions → the D8 record-mode drift byte-diff is flaky for every CDN vector.

### F6 [MAJOR] Vector-id scheme omits the test class — 838 tests in 60 files collide
- D3 (line 99): `slug` = "the test's function name + parametrization id"; the `-N` ordinal covers only "same nodeid emitting multiple vectors".
- Census (regex over tests/**/*.py): 60 files contain duplicate `def test_*` names across different classes — 838 affected tests. Examples: `tests/test_user_builders.py` (`test_integer_value` ×2, `test_float_value` ×2), `tests/test_validation_flow.py` (`test_valid_count_type_unique_no_error` ×2), `tests/test_types_cohort_behaviors.py` (3 dup names).
- Two DISTINCT nodeids map to the same id → last-writer-wins overwrite (silent vector loss) or nondeterministic `-N` attribution that reshuffles when unrelated tests are added — vector-id instability across re-extraction.
- Fix: slug must be derived from the full nodeid path (module::Class::function[param]), not the bare function name.

### F7 [MAJOR] The ≥3,000-vector arithmetic double-counts its own exclusions
- D10 (line 289): "~1,400 wire-classified + ~1,700 builder-classified ⇒ ≥3,000".
- Builder side: the recon ground truth is 1,723 collected in 38 files (builder-registry.json), but that INCLUDES ~133 Hypothesis tests (bookmark_builders_pbt 8, query_pbt 28, query_validation_pbt 4, validation_pbt 13, bookmark_validation_pbt 8, bookmark_schema_pbt 14, delegation 6, roundtrip 7, user_query_pbt 29, expressions_pbt 6, custom_property_pbt 10) + 2 structural `@given` tests — all excluded by D10's `hypothesis` rule — plus ~51 tests asserting uncoded `ValueError`/`TypeError` (grep `raises\((ValueError|TypeError)` over the 38 files) excluded as `uncoded_raise`, plus 39 `test_bookmark_enums.py` tests that call no registry function (`no_seam_hit`). Net ≈ 1,500, not 1,700.
- Wire side: 1,505 − ~100 colocated non-wire − 19 PBT (test_api_client_pbt 13, business_context_pbt 3, cdn_walker_pbt 3) − 10-25 layer3_deferred − 8 uncoded-raise ≈ ~1,355.
- Net recon-supported total ≈ 2,850 — BELOW the plan's ≥3,000 Phase-1 target. It may still be reached via nested emission (F9) and `-N` multi-emission, but the design presents un-netted numbers as if they proved the target; PR-5's "Done: ≥3,000 vectors" gate is at risk and should either re-derive the target arithmetic honestly or budget authored vectors to close the gap.

### F8 [MAJOR] "`_IterableByteStream` tests bypass MockTransport" is false — stream-backed responses break the recorder
- D2 (line 78) claims the `_IterableByteStream` tests "(test_api_client.py:2680-2703) bypass MockTransport and are NOT wire vectors". In fact tests at tests/unit/test_api_client.py:2795-2840 (`test_chunk_boundary_handling`, `test_utf8_split_across_chunks`, …) run `httpx.Client(transport=httpx.MockTransport(handler))` with handlers returning `httpx.Response(200, stream=_IterableByteStream(chunks))` (:2803, :2833) — they go straight THROUGH the class-level D1.1 hook.
- D1.1's capture rule ("captures the full body bytes from the mock httpx.Response before iteration — mock bodies are in-memory, so this is safe") is unsafe for `stream=`-backed responses: `response.read()` in the recorder marks the stream consumed; the test's subsequent `_iter_jsonl_lines(response)` iteration hits httpx `StreamConsumed` → the test FAILS under record mode. Reading also collapses the chunk boundaries the design claims `body_stream` preserves.
- These tests are also P7 raw-httpx with no library entry point, so per D1.3 they'd classify `wire` with nothing valid to put in `call.api`.
- Fix: recorder must TEE streams (wrap the SyncByteStream, record chunks as they are yielded) and D10 needs an explicit exclusion for raw-httpx/P7 tests.

### F9 [MAJOR] Registry wrap captures INTERNAL nested calls — corpus couples to Python's internal call graph
- `unittest.mock.patch` on module attributes intercepts same-module bare-name calls (dynamic global lookup): `build_filter_entry(f)` is called inside `build_filter_section`'s loop (src/mixpanel_headless/_internal/bookmark_builders.py:203) and RECURSIVELY inside `build_filter_entry` itself for compound filters (:563); function-local self-imports at :50, :746, :800, :859 also bind the wrapper at call time.
- Consequence: one test calling `build_filter_section` with 3 filters emits 1 + 3 vectors; a compound-filter test emits a vector per sub-filter. (a) Manifest counts are inflated by implementation-detail invocations, silently propping up the F7 target; (b) `-N` ordinals and vector sets change whenever internal call structure is refactored, even with identical public behavior — violating the "byte-identical when behavior is unchanged" regeneration story; (c) behavior is asymmetric: `Workspace.build_*` facades call bookmark_builders via workspace.py:70 static `from ... import`, bound BEFORE `pytest_configure` patches (conftest.py imports the package at conftest-load time), so facade tests do NOT nest — two inconsistent capture semantics the design never states.
- Fix: the wrapper must suppress capture while another registry wrapper is on-stack (re-entrancy guard), or the design must explicitly declare nested capture intended and account for it in counts/ids.

### F10 [MAJOR] Wire calls with callback kwargs are unserializable and un-replayable — no policy exists
- `export_events(..., on_batch=on_batch)` (tests/unit/test_api_client.py:1407-1450, retry-state-reset suite), `stream_*` progress callbacks, and replays `label_fn` closures are function-valued kwargs. `call.input` is JSON (schema line 36); no codec can encode a closure, and the TS runner cannot reconstruct the callback whose observed effects (batch counts resetting across retries) are the very contract those tests assert.
- D10 has no exclusion category for callback-kwarg tests; D4.4's codec table covers only dataclasses/datetime/SecretStr. As designed the recorder either crashes serializing `on_batch` or emits a vector that drops the kwarg — silently changing the exercised code path (`on_batch=None` skips the batch-count logic).
- Fix: either an explicit `unserializable_input` exclusion (logged in manifest) or a `$type: "callback"` sentinel with defined replay semantics (inject a counting stub and record its call log as part of `expect`).

### F11 [MINOR] File-level `typer.testing` CLI exclusion throws away colocated library tests
- D10 `cli` rule: "nodeid under tests/unit/cli/ or importing typer.testing". Importing is a module-level property; tests/unit/test_schema_graph.py imports CliRunner for 3 CLI smoke uses but contains 38 tests (2 MockTransport wire sites); test_lexicon_write_metadata.py 22 tests / 5 CLI uses; test_042_edge_cases.py 32/9. Whole-file exclusion silently drops ~70+ library-level tests from the corpus and mislabels them `cli` in the manifest.
- Fix: per-test detection (does the test function use CliRunner) or per-class, not per-import.

### F12 [MINOR] D9.1's S12 rationale cites a D10 exclusion that D10 does not define
- Design line 257: the auth-resolver patch was dropped because "resolver precedence is exercised by env-dependent tests the record plugin largely excludes (D10)". D10 has no env-dependent category; those tests are (at best) `no_seam_hit`. Internal citation is dangling — if resolver tests DO fire the transport, the assumption behind swapping S12 is unverified.

### F13 [MINOR] Bearer-token pattern in D5 misses recorded token literals (folds into F3)
- oauth token census: besides `test-token`(12)/`test-oauth-token`(11), tests use `oauth_token="token"`, `"my-oauth-token"`, `"eu-token"`. The fixed pattern `^Bearer test(-oauth)?-token$` (D5.2) rejects them → abort per the same rule as F3.

### F14 [MINOR] Wire-precedence classification silently discards builder captures in dual-seam tests
- D1.3: transport fired ⇒ the test "emits a `wire` vector"; registry captures in the same test are neither emitted nor counted in any manifest category. Tests that build params via `ws.build_*` then send them (workspace facade round-trip tests) lose their builder-contract half with no ledger entry — undermines the manifest-as-denominator claim.

## Verified-OK claims (attacks that failed)

- **Tests patching clock/uuid themselves**: no `freeze_time`/`freezegun` usage and no `patch(...uuid...)`/`patch(...date.today...)` in tests/ (grep clean) — no conflict between test-local patches and the D1.4 freeze.
- **RECORD_EPOCH vs hardcoded dates**: the only today-comparing validators are U8 `as_of > date.today()` (user_validators.py:211) and `build_date_range` default (bookmark_builders.py:114). All `as_of` literals in tests are ≤ 2025 (census), so freezing to 2026-01-15 flips no pass/fail; the 164 post-epoch date literals elsewhere (e.g. test_api_client.py:3177 activity_feed `from_date="2026-05-01"`) are pure pass-through strings. Risk register #2 (freeze-incompatible → excluded) is an adequate backstop.
- **Inline-asserting handlers**: recon wire-seam §2 confirms the post-hoc capture idiom dominates; handler routing logic is reproduced by position-based (ordered) replay plus request diffs, so handler-resident contract IS captured for ordered families (retry 429→200, cursor pagination, path routing). The gap is only the unordered case (F5).
- **`_clean_mp_env` / write-guard coexistence**: verified conftest.py:143-154 scrubs only `_MP_ENV_VARS`; a non-MP-prefixed flag/env is safe as designed.
- **`time.sleep`-patch overbreadth worry**: only 2 `patch("time.sleep")` sites exist in the 49 wire files (both test_pagination.py) — the layer3_deferred heuristic cannot mass-exclude the retry family.
- **Wire/builder file overlap**: the 49 wire files and 38 builder files are disjoint (set intersection empty) — no cross-set double counting in the D10 arithmetic (the problem is intra-set netting, F7).
- **client `_session` attribute** exists (api_client.py `self._session.project.id`, e.g. :2046 region) — D5.1's capture source is real.

## Method notes

- All greps/censuses run at commit 5269674 (branch fix/latent-bugs-stress-test).
- Duplicate-test-name census: regex `def test_\w+` grouped per file, counting names occurring >1 (class-scoped duplicates).
- Builder PBT overlap: per-file collected counts from context/phase1/recon/builder-registry.json `.totals.per_file_collected_counts`.
- Uncoded-raise counts: regex `raises\((ValueError|TypeError)` over the 38 builder files (51) and 49 wire files (8) — assertion-site counts, close proxy for test counts.
- freezegun/time.monotonic behavior cited from freezegun's documented API (monotonic/perf_counter frozen since 1.x); flagged for empirical confirmation in PR-2 regardless.

