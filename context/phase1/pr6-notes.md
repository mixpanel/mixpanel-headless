# PR-6 scratch notes (corpus runner)

## Inventory (start)
- Branch ts-port/phase1-verification-rig, HEAD 953b0f7 (PR-5 done).
- conformance/runner/ has only __init__.py + canonical.py (PR-4).
- Vectors: 137 .jsonl bundles + manifest.json + api-index.json under conformance/vectors/.
- Uncommitted: context/typescript-port-rulebook.md modified (pre-existing, not mine); context/phase1/bug-reports/, escalation-resolutions.md untracked (not mine — leave alone).

## To build (D7/D18 PR-6)
- runner/vector_types? loading of JSONL bundles ($bundle header line)
- VectorTransport (httpx.BaseTransport + async) — ordered + unordered_group keyed serving, transport_error raising, one-shot consumption, capture actual requests
- kind dispatch: builder/validation-error/wire/parse
- call.setup[] execution
- callback stub injection + callback_calls diffing
- clock: RECORD_EPOCH freeze + uuid patch + virtual sleep (reuse conformance/record/clock.py)
- test_corpus.py with pytest_generate_tests, id = vector id
- CLI python -m conformance.runner --vectors ... [--filter glob] --report json
  - vector_failed vs runner_crashed distinction (D9.3)
  - fail fast with runner_crashed report if freezegun missing

## Findings while reading existing code
- Corpus: 2536 vectors (builder 1302, wire 1170, validation-error 64). No unordered_group/body_stream/callback_calls/params_absent/parse in committed corpus (those arrive PR-7) — still implement per D18.
- Wire apis: api_client(802), workspace(299), pagination.paginate_all(39), region_probe.probe_region(14), oauth_flow.refresh_tokens(7), replays.fetch_files(9). setup[] in 116 vectors; client_options(max_retries) in 22; workspace_session in 275.
- call.input drops client-like args (client rebuilt from session); builder method-on-value entries carry "self" in input; iterator results recorded as list of encoded yielded items (encode_expect_value per item); non-iterator via encode_output(entry.output_codec).
- PROBLEM 1: transport_error records class name only, but region_probe vectors (3) embed "ConnectError: DNS lookup failed" (str(exc)) in expect.error.details_contain.attempts. FIX: pipeline change — capture+emit optional transport_error "message"; schema additive optional field; RE-EXTRACT corpus (allowed by gate, replaces generated commit). Runner raises getattr(httpx, cls)(message).
- PROBLEM 2: probe_region client_factory is $type:callback, but replay needs a REAL factory -> special-case: factory(region) returns httpx.Client(transport=vt, base_url=scheme_host of next unconsumed recorded interaction). scheme_host there is test-env config, not library behavior.
- PROBLEM 3: oauth_flow region not recorded; derive OAuthFlow region by reverse lookup of first recorded scheme_host in OAUTH_BASE_URLS (fixed 3-entry table), default us. Check refresh_tokens does not write storage.
- Request compare plan: reuse plugin._snapshot_request on actual requests; serialize actual via emit-like body rules; compare method/scheme_host/path/params/body via canonicalize; headers via canonical.headers_match; params_absent/headers_absent checks; ordered positional serving; unordered_group keyed by canonical (method,path,params); extra/missing => fail.

## Decisions (final plan)
- PROBLEM 4: recorder NEVER emitted expect.callback_calls (D4.4 gap). Fix record side: CallbackProxy substitution in plugin (wrap callable kwargs, log encoded positional args, delegate), emit callback_calls for measured call; runner injects RecordingCallback stubs and diffs strictly (missing key == []).
- Pipeline fixes bundle: (1) transport_error message, (2) session.headers into call.session, (3) mock-collaborator-invoked exclusion (ReplaysService._api Mock used during span), (4) callback_calls capture+emit. Then full re-extract with committed stamps.
- Runner layout: loading.py, transport.py (VectorTransport sync+async, positional ordered + keyed unordered, one-shot, transport_error raise w/ message), targets.py (session decode + per-prefix target construction; probe_region real factory recording calls + base_url from next unconsumed interaction; oauth region reverse-lookup OAUTH_BASE_URLS; OAuthFlow storage -> tmpdir; builder Workspace w/ dummy? no session -> synthetic SA session + empty VectorTransport), execute.py (kind dispatch, setup exec w/ adopt-returned-client, diffs), test_corpus.py, __main__.py (report json; freezegun fail-fast), README.md.
- Crash taxonomy: per-vector exceptions => vector_failed (reason string); anything outside vector loop => runner_crashed (exit 2). Exit 1 on vector failures.
- Commit order: (a) record-pipeline fixes + runner? NO -> (a) pipeline fixes + tests, (b) re-extraction generated commit, (c) corpus runner + CLI + README + justfile cleanup.
- snapshot_request moves plugin.py -> capture.py (pytest-free) shared with runner.
- Workspace(session=s, _api_client=client) fully offline; builder replays use empty VectorTransport to trap accidental network.

## Progress log
- Record fixes round 1 (msg capture, session.headers, mock-collab excl, callback proxy): extraction #2 green after excluding mocks from proxy eligibility (MagicMock(spec=...) is callable; proxying broke U24 test).
- Runner v1 vs extraction #2: 2508/2535, 27 fail. Categories: (A) form-body dict order 15, (B) served-body key-order-dependent results 3, (C) setup-raise 1, (D/E) input-dict order via json.dumps'd strings 6 (engage/behaviors/cohort), (F/G) stubbed _me_service business-context 4.
- Fixes round 2: KeepOrderDict (preserve insertion order for call.input/setup input/response body subtrees in bundles; comparisons still canonical-sorted), setup exceptions tolerated (D2: setup returns not diffed), _me_service-stub exclusion in plugin.
- Extraction #3: 2530 vectors (dropped exactly: 5 me-stub business-context + 1 replays re-sign; unserializable_input 19->25).
- Runner + per-vector HOME sandbox (found replay writing fake me.json into REAL ~/.mp — cleaned up facade/test_account dirs; also cross-vector me-cache leak): 2530/2530 PASS, CLI runtime ~1.0s.
- Determinism: extraction #4 running for byte-diff vs #3.

## FINAL (PR-6 done)
- Commits: 4eb0b9f (pipeline fixes), 9961fbb (re-extraction, 2530 vectors, byte-deterministic double-run), 33f5973 (runner + CLI + README + justfile).
- Gate: 2530/2530 pass; CLI 1.2s, pytest harness 2.4s (<= 5 min); just check exit 0 at HEAD.
- Schema additions: transportError.message, session.headers. New emit behavior: expect.callback_calls; KeepOrderDict insertion-order payload subtrees (call.input/setup input/response body) — TS loader must preserve object order there.
- Cleaned real-home pollution (~/.mp/accounts/{facade,test_account}) caused by pre-sandbox replay; runner now sandboxes HOME+MP_* per vector.
