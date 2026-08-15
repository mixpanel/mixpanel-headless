# Wire-Test Seam Map — record-mode pytest plugin target

Repo: mixpanel-headless @ 5269674 (branch fix/latent-bugs-stress-test). All counts derived
by grep / `pytest --collect-only` on 2026-08-14; commands noted inline. Companion inventory:
`wire-seam.json`.

## 0. Scope and totals

49 test files (plus 2 conftests) touch the HTTP wire via `httpx.MockTransport` or an
injected transport/client. Union built from
`grep -rl "MockTransport" tests` (50 files incl. conftest) ∪ `grep -rl "mock_client_factory"`
(5) ∪ `grep -rl "_transport=" tests` (42) → 51 unique paths, 49 non-conftest test files.
`pytest --collect-only -q` over those 49 files collects **1,505 tests** (per-file counts in
wire-seam.json). Not all 1,505 hit the wire — e.g. `tests/unit/test_api_client.py` contains
pure-URL/`ENDPOINTS` tests (TestEndpoints at tests/unit/test_api_client.py:82, TestBuildUrl
at :280) and `_iter_jsonl_lines` byte-stream tests (:2708) that never issue a request — so
the plan's "~1,400 wire tests" figure is consistent: 1,505 collected minus an estimated
~100 non-wire tests living in the same files (estimate, not derived per-test).

## 1. Client-construction patterns (how a test gets a mocked client)

Seven distinct wiring patterns exist. File counts from the classification grep recorded in
wire-seam.json (`patterns` field per file).

### P1 `direct-client` — 40 files (dominant)
`MixpanelAPIClient(session=..., _transport=httpx.MockTransport(handler))`, usually via a
local `create_mock_client(credentials, handler)` helper copied file-to-file:
- tests/unit/test_api_client.py:68-74 (`create_mock_client`)
- tests/unit/test_api_client_annotations.py:33-51 (same helper, oauth_token session)
- tests/unit/test_pagination.py:42-56
Some tests inline it to tune `max_retries` (tests/unit/test_api_client.py:474-477, 493-496).
Count: `grep -rl "MixpanelAPIClient(" tests | xargs grep -l "_transport"` → 40 files.

### P2 `conftest-factory` — 4 files + fixture
`mock_client_factory` fixture at tests/conftest.py:285-307: takes a handler, returns
`MixpanelAPIClient(session=mock_session, _transport=httpx.MockTransport(handler))`.
Users: tests/unit/test_discovery.py, test_lexicon_schemas.py, test_live_query.py,
test_live_query_phase008.py (`grep -rl mock_client_factory tests`). These files wrap the
client in `DiscoveryService`/`LiveQueryService` — the wire seam is identical, one layer up.

### P3 `workspace-inject` — 21 files
Workspace has **no** `_transport` parameter. Tests build a mocked `MixpanelAPIClient` and
inject it via the `_api_client=` constructor kwarg:
- Canonical helper `_make_workspace` at tests/unit/test_workspace_crud.py:81-100:
  `client = MixpanelAPIClient(session=creds, _transport=transport)` then
  `Workspace(session=_TEST_SESSION, _api_client=client)`.
- Workspace side: `workspace.py:410-509` — `_api_client: MixpanelAPIClient | None = None`
  (src/mixpanel_headless/workspace.py:418), stored at :506-507; if omitted, a real client
  is built lazily at :746.
- Integration variant with fixture chain (request_log → mock_transport → workspace):
  tests/integration/test_cross_project_iteration.py:80-118.
All 21 files (19 `Workspace(` + `_transport=` matches, plus integration pair) also match P1
since they construct the client directly.

### P4 `async-cdn` — 2 files
Replays CDN walker uses its own `httpx.AsyncClient`; tests inject
`ReplaysService(api_mock, _async_transport=httpx.MockTransport(handler))`:
- tests/unit/_internal/test_replays_service.py:156-157, 108-140 (`_make_cdn_handler`)
- tests/pbt/test_cdn_walker_pbt.py
`sign_replays` is mocked at the *method* level (MagicMock, test_replays_service.py:34-39);
only the CDN GETs go through MockTransport. Note `httpx.MockTransport` satisfies both
`BaseTransport` and `AsyncBaseTransport`, so the same class serves sync and async seams.

### P5 `http-client-inject` — 2 files (OAuth subsystem, NOT MixpanelAPIClient)
`OAuthFlow(region=..., storage=..., http_client=httpx.Client(transport=MockTransport(h)))`
— tests/unit/test_auth_flow.py:127-131; OAuthFlow default at
src/mixpanel_headless/_internal/auth/flow.py:168 (`http_client or httpx.Client()`).
Same idiom for `ensure_client_registered(http_client=...)` in
tests/unit/test_auth_registration.py (function signature requires http_client:
src/mixpanel_headless/_internal/auth/client_registration.py:54-58).

### P6 `region-factory` — 1 file
`probe_region(client_factory, headers)` takes a `region -> httpx.Client` factory; tests
build per-region MockTransport-backed clients and log visit order:
tests/unit/test_region_probe.py:28-66 (`_client`, `_factory_for(visited=...)`).
Production factory constructs real `httpx.Client(base_url=...)` at
src/mixpanel_headless/_internal/auth/region_probe.py:278.

### P7 `raw-httpx` — 1 file
tests/unit/test_api_client_pbt.py:508 uses a bare
`httpx.Client(transport=httpx.MockTransport(handler))` with no library client at all.

## 2. Handler idioms

Aggregate occurrence counts (grep over the 49 files):
- **Closure returning `httpx.Response`** — universal. 1,145 `def handler`/`def handle_request`
  definitions (one per test, roughly).
- **Canned-response fixtures** — tests/conftest.py:310-337 defines `success_handler`
  (200 `[]`), `auth_error_handler` (401 `{"error": "Invalid credentials"}`),
  `rate_limit_handler` (429, `Retry-After: 60`). 21 uses, confined to
  tests/unit/test_live_query.py and test_discovery.py.
- **`nonlocal` scalar capture** — 109 occurrences (`nonlocal captured_url` /
  `call_count` / `attempt`), e.g. tests/unit/test_api_client.py:352-354, 447-449.
- **List-append capture** — 347 occurrences (`captured_urls.append(str(request.url))`,
  `captured_params.append(dict(request.url.params))`, `request_log.append(request)`,
  `call_log.append(file_num)`), e.g. test_api_client_annotations.py:128-131,
  test_pagination.py:206-209, test_cross_project_iteration.py:85-88,
  test_replays_service.py:129-138.
- **Stateful branching handlers** — 44 counter declarations
  (`call_count = 0` / `attempt = 0` / `poll_count`) drive sequenced responses:
  429-then-200 (test_api_client.py:445-452), cursor pages keyed on
  `request.url.params.get("cursor")` (test_pagination.py:71-103), PENDING→SUCCESS polling
  (test_workspace_data_governance.py:1482-1532).
- **Path-routing handlers** — 33 `request.url.path` dispatch sites; handlers act as a mini
  server routing `/api/app/me` vs `/api/query/events/names` vs fall-through 404
  (test_cross_project_iteration.py:85-95), or URL-substring routing across the 3-step
  lookup-table upload (`"upload-url" in url` / `"storage.googleapis.com" in url` /
  register / `"upload-status"` — test_workspace_data_governance.py:1430-1460, 1484-1532).
- **Handlers that RAISE** — 9 sites in 6 files raise `httpx.ConnectError` / `httpx.HTTPError`
  from inside the handler to simulate network failure
  (tests/unit/test_region_probe.py:79-81, plus test_api_client.py,
  test_api_client_data_governance.py, test_app_api_client.py, test_auth_flow.py,
  test_replays_service.py). Record mode must represent "transport raised" vectors, not
  just status codes.
- **Handlers asserting inline** — rare; assertion normally happens after the call on the
  captured data, not inside the handler. The dominant post-hoc idiom keeps handlers pure.
- **Custom byte streams** — `_IterableByteStream(SyncByteStream)` at
  tests/unit/test_api_client.py:2680-2703 feeds `_iter_jsonl_lines` with controlled chunk
  boundaries. These bypass MockTransport entirely (pure function tests) — exclude from the
  wire corpus but note them as the JSONL chunk-reassembly contract.

## 3. Assertion targets on the captured request

Concrete examples of every asserted attribute:
- **method** — `captured[0][0] == "POST"` (test_api_client_annotations.py:225, 240);
  `captured_methods[0] == "GET"` (:204-213); `request.method == "POST"` routing
  (test_workspace_data_governance.py:1507).
- **url.path** — `captured_path.endswith("/events/properties/top")`
  (test_api_client.py:927-938); substring on full URL `"/annotations/" in captured_urls[0]`
  (test_api_client_annotations.py:137); `"/webhooks/wh-uuid-123/" in captured_urls[0]`
  (test_api_client_webhooks.py:269).
- **url.params** — dict copy `dict(request.url.params)` then exact match:
  `captured_params["event"] == "Purchase"` (test_api_client.py:711-721);
  param-as-string coercion matters: `captured_params["limit"] == "5000"` (:781),
  `captured_params["funnel_id"] == "12345"` (:1125-1133); absence asserted:
  `"interval" not in captured_params` (:1181); raw-URL substring style
  `"fromDate=2026-01-01" in captured_urls[0]` (test_api_client_annotations.py:152),
  `"limit=1000" in captured_url` (test_api_client.py:656);
  telemetry lock `captured_params["query_origin"] == "mixpanel-headless"`
  (test_api_client.py:1678, test_pagination.py:276).
- **headers** — `captured_headers.update(dict(request.headers))` then
  `captured_headers["authorization"].startswith("Basic ")` (test_api_client.py:334-346);
  exact bearer/custom header `captured_headers["x-custom-header"] == "custom-value"`
  (:1657); content-type `"application/json" in captured_content_type` (:1381-1392).
  NOTE: httpx normalizes header names to lowercase in `dict(request.headers)` — vectors
  must compare case-insensitively.
- **json body** — `json.loads(request.content)` then key/exact-dict compare:
  `captured_body.get("filter_by_cohort") == '{"id": "12345"}'` (test_api_client.py:1024-1038);
  full equality (:1634-1638); absence `"output_properties" not in captured_body` (:1110).
- **raw content / form body** — refresh POST body decoded as string:
  `"grant_type=refresh_token" in body` (test_auth_flow.py:527-528); GCS upload asserts PUT
  content-type text/csv via handler branch (api_client.py:7640-7643 exercised by
  test_workspace_data_governance.py:1450-1451).
- **request COUNT and ORDER** — `call_count == 2` (test_api_client.py:457),
  `cursors_seen == [None, "c2", "c3"]` (test_pagination.py:162),
  `Counter(path for ...)` over `request_log` (test_cross_project_iteration.py),
  `visited == ["us"]` short-circuit order (test_region_probe.py:99),
  `sorted(call_log) == [0, 1, 2]` for parallel CDN batches (test_replays_service.py:196).

## 4. Multi-interaction families

Families whose single test drives >1 HTTP request through the transport:
1. **429-retry sequences** — retry loop re-issues the request; handler counts calls
   (test_api_client.py:443-548, retry-state-reset suite :1400-1566; pagination retry
   with `patch("time.sleep")` test_pagination.py:406-450, 647-824).
2. **Cursor pagination incl. MAX_PAGES guard** — test_pagination.py:67-162 (2-3 pages),
   MAX_PAGES infinite-loop guard patched to 50 pages → 50 requests (:338-378).
3. **Engage `session_id` pagination** — export_profiles loops until `session_id: None`
   (test_api_client.py:983-1007).
4. **JSONL streaming export** — one request, but streamed body + retry interplay
   (test_api_client.py:556-696, 1407-1462); counts as multi-request only when combined
   with 429.
5. **Token refresh** — OAuthFlow refresh POST (single request per call) but
   login = DCR register + token exchange when not mocked; test_auth_flow mostly mocks
   register/callback so wire = 1 request (test_auth_flow.py:100-135). Registration retry
   in test_auth_registration.py (2 counter sites).
6. **Lookup-table upload orchestration** — 3-5 requests: GET upload-url → PUT GCS →
   POST register → poll upload-status until SUCCESS/timeout
   (test_workspace_data_governance.py:1423-1645; client-level pieces in
   test_api_client_data_governance.py:1321+).
7. **Replays CDN walker** — N parallel file GETs + 404 sentinel + 403 re-sign retry
   (test_replays_service.py:143-330; up to 200 files in test_respects_max_files_bound:198-219;
   async + `asyncio.gather` ⇒ intra-batch order nondeterministic).
8. **Region probe** — up to 3 sequential region requests (test_region_probe.py:87+).
9. **Workspace auto-resolution / cross-project iteration** — `/me` + per-project query
   requests, `httpx.Client` identity preserved across `ws.use()`
   (test_cross_project_iteration.py, test_cross_account_iteration.py,
   test_workspace_lazy_resolve.py:75-104 — /workspaces/public fallback chains).

**Share estimate**: summing family sizes read from the files — ~18/204 (test_api_client) +
~26/40 (test_pagination) + ~20/27 (test_replays_service) + 3 (cdn_walker_pbt) + ~9
(test_discovery counters) + ~12/16 (region_probe) + 11 (integration) + ~6 (data-governance
upload/poll across both files) + ~13 (app_api_client, lexicon, auth_registration,
workspace_crud, business_context_pbt counters) ≈ **115-130 tests ≈ 8% of the 1,505**.
Method: counted the 44 stateful-counter declarations
(`grep "call_count = 0|attempt = 0|request_count|poll_count"`), then added
whole families that are multi-request by construction without counters (CDN walker file
maps, region-probe visited lists, integration request_logs, parametrized retry-after
suite). Labelled estimate — per-test request counts were not instrumented.

## 5. The seam itself (src side)

`MixpanelAPIClient` — src/mixpanel_headless/_internal/api_client.py:
- **:312** constructor kwarg `_transport: httpx.BaseTransport | None = None`, stored at
  :339 (`self._transport = _transport`). Documented as test-only (:323).
- **:444-447** `_ensure_client()` — THE single funnel: lazily builds
  `httpx.Client(timeout=self._timeout, transport=self._transport)`. Every request path
  reaches it: `__enter__` (:489), `_execute_with_retry` (:740), `_http` property (:1032),
  `app_request` (:1262), `export_events` streaming via `client.stream(` (:1852/:1864),
  `register_lookup_table` (:7696), `download_lookup_table` (:7892). Headers are composed
  per-request by `_request_headers` (:450+), NOT cached on the client — record plugin can
  therefore observe auth headers on each request.
- **:1726-1733** `with_project()` — builds a sibling client for another project passing
  `_transport=self._transport` through, so mocks survive cross-project fan-out.
- **:7632-7638** `upload_to_signed_url()` — deliberately builds a FRESH
  `httpx.Client` (to strip custom headers that would break the GCS signature) but branches:
  if `self._transport is not None` the fresh client still wraps the mock transport
  (`httpx.Client(transport=self._transport, timeout=self._timeout)`); else a bare
  `httpx.Client(timeout=...)`. The GCS PUT therefore flows through the same MockTransport
  handler in tests — a record plugin hooking only `_ensure_client` would MISS this request;
  hook the transport itself.

Replays CDN walker — src/mixpanel_headless/_internal/services/replays.py:
- `ReplaysService.__init__(..., _async_transport: httpx.AsyncBaseTransport | None)` :156,
  stored :172; consumed at **:331-334**:
  `async with httpx.AsyncClient(transport=self._async_transport, timeout=_CDN_TIMEOUT)`.
  Batch fetch + 403 re-sign at :335-354. Tests mock via P4 above; `sign_replays` (auth'd
  App API call) is MagicMocked, so replay-service vectors have a pure-CDN wire shape.

Bypass sites — every `httpx.Client(`/`AsyncClient(` construction in src
(`grep -rn "httpx.Client(\|httpx.AsyncClient(" src/mixpanel_headless`):
- api_client.py:444 (honors _transport), :7634 (honors), :7638 (real client — only when
  _transport is None, i.e. never in tests).
- auth/flow.py:168 — `http_client or httpx.Client()`; bypasses _transport entirely; tests
  must inject `http_client` (P5).
- auth/client_registration.py:16, :83 — docstring examples only; the function requires an
  `http_client` argument (:54-58).
- auth/region_probe.py:136 — docstring example; :278 — the real default `_factory` inside
  the login orchestration builds `httpx.Client(base_url=...)`; injectable via
  `client_factory` (P6).
There is NO other httpx client construction in src. The TS port needs exactly four
injectable transport seams: MixpanelAPIClient transport, ReplaysService async transport,
OAuthFlow http client, region-probe client factory.

## 6. Canonical fake Session (values vectors should embed)

`make_session()` defaults — tests/conftest.py:65-129:
- ServiceAccount: `name="test_account"`, `region="us"`, `username="test_user"`,
  `secret=SecretStr("test_secret")` (no default_project set by the helper)
- `Project(id="12345")` (string), `workspace=None` (WorkspaceRef only when
  `workspace_id` truthy — note `if workspace_id` means `workspace_id=0` also yields None)
- OAuth variant (`oauth_token=...`): `OAuthTokenAccount(name="test_account", region="us",
  token=SecretStr(<given>))` — CRUD/App-API files use `oauth_token="test-oauth-token"`
  (test_api_client_annotations.py:30) or `"test-token"` (test_workspace_crud.py:72).
- `mock_session` fixture (tests/conftest.py:278-281) = `make_session()` with all defaults.
- Resulting wire facts: SA auth header `Basic dGVzdF91c2VyOnRlc3Rfc2VjcmV0`
  (base64("test_user:test_secret"), locked by test_api_client.py:174-185); oauth header
  `Bearer test-oauth-token`; `project_id=12345` in query params (test_api_client.py:348-360).
- Workspace-facade files additionally pin `_TEST_SESSION` with
  `ServiceAccount(..., default_project="12345")` (test_workspace_crud.py:50-59) while the
  injected API client carries the oauth session — the two sessions intentionally differ.
- Autouse `_clean_mp_env` (tests/conftest.py:143-154) scrubs all 7 MP_* env vars per test;
  integration adds hermetic `$HOME`/`MP_CONFIG_PATH` (test_cross_project_iteration.py:69-73,
  tests/integration/conftest.py:18-36).

## 7. Nondeterminism hazards for record mode

Run-to-run variance sources found in wire paths (src + tests):
1. **today-derived request params (HIGH)** —
   - `get_events` default `to_date` = today (api_client.py:2380 `today = date.today()`);
     tests only assert `len(to_date)==10` (test_api_client.py:783-785) but a recorded URL
     changes daily.
   - date-range-403 fallback retries with `today - N days` (asserted EXACTLY at
     test_api_client.py:830 `(date.today() - timedelta(days=90)).isoformat()`).
   - saved-report/funnel default 30-day window `datetime.now()` (api_client.py:2937-2948);
     test_api_client_bookmarks.py:409-410 builds the expected strings from
     `datetime.now()` at test time.
   Record mode must either freeze the clock (freezegun-style) or normalize date params.
2. **retry timing jitter** — `random.uniform(0, delay*0.1)` (api_client.py:678) affects
   sleep durations, not payloads; pagination tests neutralize via `patch("time.sleep")`
   (test_pagination.py:444). Vectors should capture request sequences, not wall time.
3. **`time.time()`** — `signed_at` on SignedReplay (replays.py:207) and
   `as_of_timestamp` future-validation (api_client.py:2025). In-process values, not wire
   bytes, but SignedReplay equality snapshots would drift.
4. **async batch ordering (HIGH for replays)** — CDN walker issues `concurrency`-sized
   parallel batches; tests already `sorted(call_log)` (test_replays_service.py:196).
   Recorded request ORDER within a batch is nondeterministic; corpus must treat batches as
   order-insensitive sets keyed by file number.
5. **OAuth PKCE randomness** — code_verifier/state are random per run; token-exchange
   request bodies recorded from `OAuthFlow.login()` differ each run (auth/pkce.py). Refresh
   requests are deterministic (test_auth_flow.py:497-528 asserts exact body substrings).
6. **token expiry fixtures** — `datetime.now(timezone.utc) ± timedelta` in
   test_auth_flow.py (10+ sites, e.g. :516) and test_cross_account_iteration.py:52 decide
   refresh-vs-reuse branches; behavior is stable (always expired/valid by construction)
   but embedded ISO timestamps in any recorded artifact will differ per run.
7. **Hypothesis-driven wire tests** — test_api_client_pbt.py, test_cdn_walker_pbt.py,
   test_business_context_pbt.py, test_bookmark_* PBT generate random payloads per run
   (deterministic only under `HYPOTHESIS_PROFILE=ci`, tests/conftest.py:30-37
   `derandomize=True`). Record under the ci profile or exclude PBT files from the corpus.
8. **dict/param ordering** — httpx encodes query params in dict insertion order (stable in
   CPython); JSON bodies asserted as parsed dicts (order-free). Raw-URL substring
   assertions are order-free too. Risk is only if the TS runner re-serializes with
   different key order — compare parsed, not raw, forms.
9. **parallelism** — no pytest-xdist in addopts (pyproject.toml:140
   `addopts = "-vv --tb=short -m 'not live'"`); tests run serially. No port randomness in
   wire tests (callback server is mocked with fixed port 19284, test_auth_flow.py:108-110).
10. **header case** — `dict(request.headers)` lowercases names; recorded vectors should
    store lowercase header keys to match both httpx and any TS HTTP layer.
