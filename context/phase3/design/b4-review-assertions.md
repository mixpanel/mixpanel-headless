# B4 adversarial review — ASSERTION FIDELITY + DEFERRAL CLOSURE lens (P3-2d)

**Status**: 2026-08-16 · fable reviewer (one of the B4 pair) · scope = all six B4 shard
commits on TS `main` since the B4-DL commit (`4f7bfa5` C1, `99ba862` C2, `be74c38` C3,
`e42c6c7` C4, `9305700` C5, `023cab5` C6) + the Python-side notes commits
(`d8e13d6`..`358cfb4`). Spec of record: `phase3-playbook.md` v1.1 + `b4-packets.md` v1.0.
No code edited (review-only).

**VERDICT: GO with 1 MAJOR finding + 2 minors** (arbiter to resolve F1 before the gate;
every deviation-3 deferral landed; all replay/binding/lossless checks green).

---

## 1. Deferral closure (B0-ARB carried item 6b / packet Caution #7) — ALL LANDED ✅

Every named B0 deviation-3 deferral was grepped in BOTH the packet and the commits, then
diffed against its Python original:

| Deferral | TS location | Fidelity |
|---|---|---|
| `TestRetryStateResetRegression` ×4 (`test_api_client.py:1401-1572`) | `client-export.test.ts:176-278` | Diffed test-by-test: batch-count reset (`>=1`, `contain 1000`, `contain 1500`), profile-page reset (`length 1`, `[1]`), multi-retry (`attempts==3`, `len==5`), stream project_id — all assertions preserved 1:1 |
| Streaming project_id raise `api_client.py:1883-1891` | `streaming.ts:339-347` | Constructor shape verbatim: carries `retryAfter`/`statusCode`/`requestMethod:"GET"`/`requestUrl`/`requestParams`/`projectId`, **omits responseBody only** (FF4 reduced shape) |
| Layer-3 lock `test_api_client.py:1551-1572` (`:1567` assert) | `client-export.test.ts:263-277` | `expect((caught as RateLimitError).projectId).toBe("12345")` after full drain — exact twin |
| `test_export_events_negative_retry_after_uses_backoff` (`:3810`) | `client-export.test.ts:281-299` | Python `monkeypatch.setattr(client, "_calculate_backoff", λ 0.75)` → injected-RNG pin (`random()=0` ⇒ backoff exactly 1.0 s ⇒ `sleeps == [1000]` ms). Assertion content (negative header rejected; exactly one backoff sleep) preserved; substitution documented in the file header per the B0 deviation-5 precedent — legal under R10.2 |
| `test_form_body_sent_as_form_encoded` (`test_app_api_client.py:316`) | `client-request.test.ts:279-308` | content-type + `parse_qs` equivalence preserved AND strengthened (byte-exact `quote_plus` body: `name=X&alternatives=%5B%7B%22event%22%3A+%22Y%22%7D%5D`) |
| Auth-header wire captures (Bearer/Basic end-to-end) | `client-request.test.ts:236-258` | `test_uses_bearer_auth_header` (:81) / `test_uses_basic_auth_when_configured` (:95) / `test_builds_correct_url` (:109) — now through the real client + Phase-2 auth model via `clientFromSession`-style construction |

Caution #3 (project_id at all five raise sites): Layer-3 locks confirmed present —
`:504`/`:527` (B0 `internals.test.ts:181,191`), app_request sites
(`app-request.test.ts:164,177,445` — the `:4090` request_params+project_id twin), `:1567`
(above). GATE item 5(b) can be checked off.

## 2. Replay verification (run by this reviewer, 2026-08-16) ✅

- Full run: **3,251 = 2,370 PASS / 0 FAIL / 881 UNPORTED** @ 70c904dc — byte-matches the
  packet's post-C6 interim expectation (gate delta 842 pre-positioned; no flip yet, correct).
- `--filter "api_client."`: **810 → 809 PASS / 0 FAIL / 1 UNPORTED**; the single UNPORTED
  is exactly the P3-1 † carried vector
  (`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`,
  setup `workspace.me` — verified by id-filtered run). 804 B4-owned + 6 B0 `_iter_jsonl_lines` = 810.
- `--filter "pagination.paginate_all"`: **39/39 PASS**. Cumulative 843-vector replay confirmed.
- Setup-api check: **96** B4-measured vectors carry `call.setup[]` (measured via jq —
  matches the packet); with 0 FAIL overall and only the carried vector UNPORTED, there are
  **zero setup-api resolution failures**. All 15 `api_client.*` setup names bound; the one
  `workspace.me` setup is unbound **by design** (B6 owner, P3-1 †).
- `npm run check`: green (128 files, 6,052 passed / 881 corpus-skipped).
- R10.9 spot re-run: `throwaway/b4-c2/run.sh` reproduces its RUN record **52/52**
  deterministically (no seeds — hand-built branch matrix, as the wire rule prescribes).

## 3. Binding honesty (P3-5 §3; risk-register #2) ✅

- `clientFromSession` (`wire-client.ts`): real `parseAccount` → `Session` →
  `createMixpanelClient`; **memoized in `context.state` under the ONE key `"api_client"`**;
  determinism seams exactly per P3-5 §2 (harness fetch, zero-delay sleep, `random: () => 0`,
  frozen `now` from `context.shims`). `call.client_options.max_retries` plumb mirrors the
  Python runner (`execute.py` `make_api_client`).
- **184 names registered exactly once** (mechanical extraction from the six `wire-*.ts`
  modules): the union equals the 183 `api-index` `api_client.*` keys + `pagination.paginate_all`;
  zero duplicates, zero extras, zero missing (the gate's 183-name audit will reproduce this).
- Grep over all six binding modules: **zero** `fetch(`/URL-literal/`buildUrl`/`appRequest`
  hits — every binding is memoized client + ONE ported-method call + kwarg passthrough
  (absent-stays-absent spreads) + output-codec twins only (`coreToVectorJson`,
  `encodeWorkspaceRef`, `EntityModel.toJSON`, bytes `encodeExpectValue` for
  `download_lookup_table`, drain for generators = the recorder's `list(...)`).
- **Keyed unordered serving intact**: the B4 diff to `vector-fetch.ts` touches only
  response building; `pickSlot`'s (method, path, params) keyed group serving is unchanged.
- Rig changes are FAITHFUL PORTS of the Python runner, verified against source:
  (a) setup raises swallowed → `execute.py:532-541` verbatim (comment cites it);
  (b) `storedJsonText` (compact, stored key order) → `transport.py` `json.dumps(...,
  separators=(",", ":"), ensure_ascii=False)`;
  (c) transport-error `message` threading → `transport.py::build_transport_error`
  (`cls(str(response.get("message", "")))`). None is a comparison relaxation.

## 4. GATE-R5 lossless grep (Caution #1) ✅

`grep JSON.parse|.json()` over `packages/core/src/client/` + `packages/core/src/services/`:
the ONLY real `JSON.parse` is `lossless-json.ts:288` (the parser's own string-token
unescape — B0 code, in-contract); all other hits are comments. All **8** `parseLossless`
wire call sites carry `{ pythonConstants: true }`, matching a Python `json.loads` each:
`internals.ts:334`/`:544`, `app-request.ts:227`, `streaming.ts:371` (429 body `:1911`) /
`:399` (per-line `:1931`), `pagination.ts:419`, `lookup-tables.ts:271`. JSONDecodeError-analog
catches carry `instanceof LosslessJsonError` guards (streaming.ts both sites — B0-ARB F3
pattern held).

## 5. R10.2 assertion-fidelity sweep (all 19 Layer-3 source files)

Method: multiset name-level diff (`def test_*` vs `it("test_*` incl. `it.each`) per file
pair, then body-level diffs on ~15 high-risk tests (retry-state, negative Retry-After,
pagination Retry-After parametrize grids, delete_lexicon_tag POST-body, form encoding,
auth-header PBT strategies, activity-feed, export limit/filtering).

Clean 1:1 (names AND spot-diffed assertion content): `test_api_client_session.py`,
`test_api_client_phase008.py`, `test_api_client_engage_stats.py`, `test_api_client_crud.py`,
`test_api_client_crud_edge.py`, `test_api_client_bookmarks.py`, `test_api_client_flags.py`,
`test_api_client_experiments.py`, `test_api_client_annotations.py`,
`test_api_client_webhooks.py`, `test_api_client_alerts.py`,
`test_api_client_data_governance.py`, `test_api_client_governance.py`,
`test_api_client_schemas.py`, `test_pagination.py` (parametrize grids byte-identical incl.
the 9-case hostile list and `1,000` thousands-separator; `MAX_PAGES` monkeypatch →
injectable `maxPages` per packet; sleep seconds→ms documented), `test_api_client_pbt.py`
(strategy shapes preserved — `unit:"binary"`, NUL/`pythonStrip` filters, numRuns =
max_examples; the B2 ASSERT-F1 Unicode lesson held).

Documented, citation-carrying exclusions (all verified legitimate):
- `test_query_workspace_scoping.py`: the 2 facade tests → B5/B6 (`client-scoping.test.ts`
  header cites packet C1; the C1→C2 hand-off `test_export_stream_carries_no_workspace_id_param`
  LANDED in `client-export.test.ts:302`).
- `test_workspace_resolution.py`: `TestMeServiceResolveWorkspace` (5) → B8,
  `TestFacadeResolverWiring` (4) → B6 — header cites packet C1 + Discrepancy #5; the B6
  half is the carried vector's suite, consistent with it staying UNPORTED.
- `test_me.py`: the 31 MeCache/MeService/symlink tests → B8-N2 (header cited); pure-model
  13 + `TestSelectWorkspaceId` all present.
- `test_workspace_resolution_pbt.py`: 2 pure properties translated; the 3 MeService-backed
  properties → B8 (verified against the Python source: they drive
  `MeService.resolve_workspace` over a warm on-disk cache).
- `test_api_client_sign_replays.py`: `TestSignReplaysRequest` translated;
  `TestSensitiveDataMapping`/`TestOtherHttpErrors` halves at B0 (`internals.test.ts:459+`,
  header cites `b0-review-assertions.md`).
- `test_api_client.py` `TestIterJsonlLines` (8): at B0 `jsonl.test.ts` with the
  arbiter-corrected mapping header (A1). Retry/backoff/handler classes at B0. Entry-point
  substitutions in `client-scoping.test.ts`/`client-core.test.ts` headers are disclosed and
  assertion-preserving.

### FINDINGS

**F1 — MAJOR (R10.2 silent omission): three whole `test_api_client.py` classes untranslated
with NO header exclusion, NO notes entry, NO TODO(port).** Full-tree grep (every one of the
23 test names, all TS test files + `throwaway/`): zero hits; zero mentions in
`context/phase3/notes/B4-*.md`; the `client-core.test.ts`/`client-request.test.ts` headers
enumerate their sources and simply skip these:
1. `TestAuthenticatedRequests` (`:332-441`, 7 tests) — end-to-end query-host auth header,
   project_id in query params, 401 → AuthenticationError, **`test_credentials_not_in_error_messages`
   (a security lock)**, regional routing us/eu/in through the real request path.
2. `TestWithProject` (`:2885-2973`, 9 tests) — **`with_project` is packet-listed
   index-absent C1 surface whose ONLY lock is Layer-3** (b4-packets.md §Index-absent:
   "locked by Layer-3 only"). It is implemented (`client.ts:1166`, spot-read: faithful,
   truthy-vs-`is not None` guards mirrored) but has ZERO locks of any kind — no vectors,
   no tests, and no `throwaway/` harness case (grep confirmed).
3. `TestClientIdentificationHeaders` (`:2974-3129`, 7 tests) — User-Agent stamped on
   standard/app/export-stream requests, session-header/env/caller override precedence
   end-to-end (B0's `headers.test.ts` locks the merge FUNCTION; these lock the client
   actually calling it on each path).
Mitigation exists for 1 and 3 (the 810 wire vectors diff recorded auth/User-Agent headers
byte-exactly), NONE for 2. Ask: translate the three classes (C1 scope) or land
arbiter-approved header exclusions with real owners; `TestWithProject` should be translated,
not excluded — there is no other lock and no other batch owns it.

**F2 — minor (root cause of F1): the C1 packet's Layer-3 row under-enumerates
`test_api_client.py`** ("construction/close/context-manager and TestPublicRequest" for C1;
"streaming/export/query classes" for C2) — the three F1 classes fall between the
enumerations, while the playbook B4 row scopes the whole file. The fix for F1 should add a
packet/notes addendum so the B5/B6 packet authors enumerate against the file's full class
list (the B6 volume risk, risk-register #3, is exactly this failure mode at 16 files).

**F3 — nit: 4 `TODO(port)` markers in B4 src** (`pagination.ts:180` exponent-cursor
spelling, `response-validation.ts:22` non-missing pydantic wording unlocked,
`py-dates.ts:14` local-midnight clock disclosure, `schemas.ts:76` AttributeError→TypeError
stand-in). All four carry R10.3-style disclosures with "no lock reaches this" rationale —
adequate; arbiter should record owners (B5 records vectors for response-validation rows if
any appear; the rest are permanent disclosures) so the gate's TODO triage has a paper trail.

## 6. Checks with no findings (for the arbiter's checklist)

- Caution #2 (403-TypeError bug-compat): C5 harness re-exercises the matrix through the
  real `sign_replays`; no B4 code routes around the B0 branch.
- Caution #11 (no pre-shaping): spot-read C3/C5 methods return `handleResponse`/`appRequest`
  passthrough; result classes untouched.
- R6.7/AbortSignal: signal-aware closures at client assembly (`core.executeDeps(signal)`),
  B0 signatures untouched; `pagination-async.test.ts` + `client-streaming-async.test.ts`
  lock abort-between-pages/during-sleep/early-`return()` as TS-native suites (correctly
  headered as having no Python source).
- Runner/rig test adjustments (`runner.test.ts`): stub tests moved to a fresh registry to
  avoid colliding with real B4 bindings; UNPORTED probe renamed to a B6 name — no weakening.

## 7. Verdict

**GO for the B4 gate CONDITIONAL on F1 resolution** (translate the 23 tests or arbiter-approved
cited exclusions; `TestWithProject` translation strongly recommended as mandatory). All
blocker-class checks — deviation-3 deferral closure, 843-vector replay, binding honesty,
lossless grep, setup-api resolution — pass outright.
