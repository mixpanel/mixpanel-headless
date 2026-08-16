# Phase 3 Playbook — dependency-ordered batch pipeline (EXECUTABLE)

**Status**: v1.1 · 2026-08-15 · Phase-3 designer output, revised per the adversarial review
pair (`review-fidelity.md`, `review-gates.md`) and arbiter resolution
(`review-resolution.md` — all 14 findings confirmed and applied). Precedent: `phase1-design.md` (D18)
and `phase2-design.md` (C10) — an agent with zero prior context builds from this document alone.
Everything here is numbered P3-1..P3-8 per the design brief; the per-batch workflows the
orchestrator launches instantiate P3-6 with the batch rows of P3-1 and the loop of P3-2.

## P3-0 Ground state & binding inputs

- **Python repo**: `/Users/jaredmcfarland/Developer/mixpanel-headless`, branch
  `ts-port/phase2-contract-support` (verify `git branch --show-current` before every commit;
  LOCAL COMMITS ONLY, never push). Conformance rig lives in `conformance/`; recorder registry
  `conformance/record/registry.py`; compat reference module `conformance/record/pycompat_ref.py`;
  oracle-py `conformance/oracle_py/`.
- **TS repo**: `/Users/jaredmcfarland/Developer/mixpanel-headless-ts`, branch `main`
  (local-only, D16). Corpus snapshot pinned in `conformance-runner/corpus.config.json`
  (`sourceCommit 8ae76314…`, `recordEpoch 2026-01-15T12:00:00Z`). Conformance report at
  Phase-2 exit: **3,179 vectors — 461 PASS / 0 FAIL / 2,718 UNPORTED**.
- **Binding docs** (read before building): `context/typescript-port-plan.md` §6 Phase 3 +
  Appendix B; `context/typescript-port-rulebook.md` (ALL — esp. R2, R5, R6, R10, R11);
  `context/typescript-port-api-map.{md,json}` (the queue — `workspace_members[].batch` is
  authoritative for member→batch assignment); `context/phase3/model-tiering-policy.md`
  (= rulebook R10.14); `context/phase1/audit/GATE-VERDICT.md` recommendation **R5**
  (wire batches use lossless response-body parsing — `parseLossless`, never bare
  `JSON.parse`/`response.json()`); `context/phase1/addendum/frequency-filter-probe.md` (R10.7).
- **Standing constraints**: NO mutation testing anywhere `[SA1]`. R10.13 on every agent
  (effort ≤ high + incremental work protocol: skeleton file first, small frequent edits,
  running notes file, assemble final answer from disk). R10.7 bug-compatibility.
  `/Users/jaredmcfarland/Developer/analytics` is READ-ONLY. Python via `uv`; the literal
  p-y-t-e-s-t string and bare `python` are hook-blocked in shell commands — use
  `uv run python -m pytest`.
- **Vector-count provenance**: every count in P3-1 was measured 2026-08-15 by
  `find conformance-runner/corpus -name '*.jsonl' -exec cat {} + | jq -r 'select(.call.api|type=="string")|.call.api'`
  grouped by prefix; the per-prefix totals sum to exactly 3,179 (= the pinned snapshot) and
  the pending groups sum to exactly 2,718 (= the UNPORTED count). Re-run this measurement
  after any corpus re-pin (P3-7) and update the batch-gate expectations.
- **B0-1 re-pin update (2026-08-15, follow-up commit per P3-7)**: corpus re-pinned
  `8ae76314` → `b5c1369` (P3-7 trigger 1: +72 authored `compat.*` vectors, generator
  `conformance/record/gen_b0_vectors.py`; D8/D9 drift check clean — the 3,031 recorded
  vectors are byte-identical, only stamps moved). Re-measured totals: **3,251** vectors
  (`compat` 34→106; every other prefix unchanged), pending groups still sum to exactly
  **2,718**; conformance at B0-1 exit: **533 PASS / 0 FAIL / 2,718 UNPORTED**. The P3-1
  per-batch rows and the † cross-batch-setup footnote are unchanged (the new authored
  vectors carry no `call.setup[]` and no pending prefix); batch-gate PASS baselines shift
  by +72 (B9-gate expectation instantiates as 3,179+N with N=72 so far, plus B0-2's
  authored additions when they land).

- **B3-BIND re-pin update (2026-08-15, follow-up per P3-7)**: corpus re-pinned
  `b5c1369` → `70c904d` (P3-7 trigger 1: the `validate_with_pydantic`
  name-resolving adapter retarget in `conformance/record/{adapters,registry}.py`;
  zero vectors carry the api). D9 drift check CLEAN — all 3,031 recorded vectors
  byte-identical, only `$bundle` stamps + manifest moved. Re-measured totals:
  **3,251** vectors, every per-prefix count UNCHANGED from the B0-1 measurement —
  the P3-1 table and all batch-gate expectations stand as written. B3 gate closed
  at this pin: **1,528 PASS / 0 FAIL / 1,723 UNPORTED**
  (`context/phase3/reports/2026-08-15-b3-gate.json`; batch notes
  `context/phase3/notes/B3-notes.md`).

## P3-1 Batch sequencing and scope

**Sequence (strict): B0 → B2 → B3 → B4 → B5 → B6 → B7 → B8 → B9.**
Rationale: B0 is R10.8 (shared internals once, first); B2/B3 are pure-function layers the
wire batches consume; B4 unlocks all wire replay (P3-5); B5 grows the facade's query half;
B6 finishes the facade; B7–B9 are the auth surface, last because they have no second oracle
and benefit from the most mature review pipeline. B2 may start as soon as B0's packet B0-1
is merged (B2 consumes `pythonCompat` only); B3 additionally waits for B2 (validators are
called from builders). No other overlap is permitted — each batch gate (P3-2 step e) is a
hard barrier.

**B1 confirmation (nothing missing).** Appendix-B B1 (literal types, exceptions,
Account/Session, result shapes) was Phase 2. Diffed against
`context/phase2/audit/phase2-audit.md` A1: all **274 distinct `__all__` names** are ported
or deferred-with-owner; the 9 deferrals all carry Phase-3 owners consistent with this
playbook — `Workspace` → B6; `accounts`/`session`/`targets`/`login_unified` → B7;
`validate_bookmark` → B2; `default_label_fn`/`selector_label_fn`/`url_normalizer` → B5.
Zero missing, zero unlisted extras (A1 "Risk #8 check"). **B1 is closed; no residue moves
into Phase 3 beyond those 9 owned deferrals.**

**Measured replayable-vector budget** (corpus pin `8ae76314`, total 3,179; 461 already PASS
via `types.`/`compat.`/`wirestub.`):

| Batch | api prefixes (batch-status keys) | Vectors | Cumulative pending burned |
|---|---|---|---|
| B0 | `compat.` additions (authored, new) + `api_client._iter_jsonl_lines` (exact name) | 6 recorded-equivalent (authored chunk vectors) + new authored | 6 |
| B2 | `validation.` 512 + `user_validators.` 178 | 690 | 696 |
| B3 | `bookmark_builders.` 134 + `segfilter.` 51 + `user_builders.` 82 + `expressions.` 30 + `transforms.` 2 | 299 | 995 |
| B4 | `api_client.` 810 − 6 (bound at B0) + `pagination.` 39 | 843 (gate delta **842**†) | 1,838 (1,837 at the B4 gate†) |
| B5 | `workspace.<the 44 B5 member names>` 480 + `replays.` 8 + `replay_labels.` 16 + `rrweb_analyzer.` 2 | 506 | 2,344 (2,343 at the B5 gate†) |
| B6 | `workspace.<the 158 B6 member names>` | 353 (gate delta **354**†) | 2,697 |

† **Cross-batch setup carry-over (standing rule)**: the runner gates a vector on its
measured api AND every `call.setup[]` api (`runner.ts:368-386`), so gate-time PASS/UNPORTED
deltas are computed over vectors whose measured **and** setup apis are all owned by flipped
batches. Exactly one corpus vector crosses batches backwards:
`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`
(measured `api_client.resolve_workspace_id`, setup `workspace.me` — a B6 member). It stays
UNPORTED through the B4 and B5 gates (workspace. is pending, so no FAIL) and first passes at
the B6 gate: B4's gate delta is 842, B6's is 354. The 22 forward setups
(workspace-measured vectors with `api_client.*` setups) are benign — B4 lands first.
After any corpus re-pin, re-derive this footnote by re-running the cross-batch setup scan.
| B7 | `region_probe.` | 14 | 2,711 |
| B8 | `oauth_flow.` | 7 | 2,718 |
| B9 | (none — spike-scoped, tests only) | 0 | 2,718 |

At the B9 gate the conformance report must read **3,179+N PASS / 0 FAIL / 0 UNPORTED**
(N = authored vectors added during Phase 3, each registered in
`conformance-runner/src/authored-apis.json` / the Python authored dirs).

Note the B5/B6 split of the `workspace.` prefix follows the api-map `batch` field per
member, NOT the prefix: the five `build_*params` members and the live-query/discovery/replay
members are **B5** (measured: 480 of the 833 `workspace.*` vectors carry B5-member names —
dominated by `build_params` 143, `build_funnel_params` 95, `build_user_params` 80,
`build_retention_params` 55, `build_flow_params` 53, `query_saved_report` 37); the
remaining 353 carry B6-member names. Flip mechanics for this split: P3-5.

### Per-batch scope rows

Format: modules (Python LOC) → owning TS package/home · Layer-3 test-translation scope ·
R10.10 call-site packet. Every task packet embeds the relevant `ts_signature` +
`params`/`kwonly` fields extracted from `context/typescript-port-api-map.json` for the
members it implements AND for its listed consumers — extraction is mechanical
(`jq '.workspace_members[] | select(.batch=="BX")'`); the packet author pastes the result
into the packet, never a reference to "see the api-map".

**B0 — pythonCompat completion + shared client internals** (R10.8; full packets in P3-4).
Modules: `conformance/record/pycompat_ref.py` extensions (Python side) +
`packages/core/src/compat/{python-int,python-float,python-strip,codepoint}.ts` +
`packages/core/src/client/{internals,jsonl,backoff,url,headers,scope,app-request,lossless-json}.ts`.
Owning package: `core`.
Layer-3: `tests/unit/test_api_client.py` retry/backoff/`_parse_retry_after`/
`_handle_response` test classes; `tests/unit/test_app_api_client.py` `app_request` suites;
`tests/unit/test_settings_headers.py::TestSessionHeadersOnOutboundRequests` (the
`_request_headers` merge/precedence lock — the config/bridge attachment classes of that
file stay in B8).
Call sites: every B4 method (183 `api_client.*` entry points), `pagination.paginate`
(B4), streaming (B4), all entity clients (B6 delegations).

**B2 — validators** · opus. Modules: `_internal/validation.py` (3,090) +
`_internal/query/user_validators.py` (580) → `packages/core/src/query/{validation,user-validators}.ts`
(+ finish the `bookmarks/enums.ts` `TODO(port)` module-privates `_MAX_FUNNEL_STEPS`/
`_MAX_HOLDING_CONSTANT` — owner per phase2-audit A7). Also ports the deferred export
`validate_bookmark`. Vectors: 690 (all `kind: builder` — error cases are expressed via
`expect.error` on builder-kind vectors; the corpus carries zero `kind: validation-error`
entries for these prefixes). Layer-3:
`tests/unit/test_validation.py`, `test_validation_pbt.py`, `test_query_validation.py`,
`test_query_validation_pbt.py`, `test_bookmark_validation_pbt.py`,
`tests/test_validation_{funnel,retention,flow,cohort}.py`,
`tests/test_validation_bypass.py`, `tests/test_validation_bypass_r2.py`,
`tests/test_user_validators.py`. Call-site packet: `workspace.build_*params` (B5) and
`workspace.segmentation/funnel/retention/...` guard paths (B5/B6) call
`validate_query_args`-family with the signatures in the api-map B5 rows;
`bookmark_builders.*` (B3) calls the bookmark validators; error codes are the V*/B*/U*
registry families (R5.3) already locked by `errors-codes.gen.ts`.

**B3 — builders** · opus. Modules: `_internal/bookmark_enums.py` (607, tables partially
landed P2-3), `_internal/bookmark_schema.py` (1,553), `_internal/bookmark_builders.py`
(904), `_internal/segfilter.py` (323), `_internal/transforms.py` (130),
`_internal/expressions.py` (52), `_internal/query/user_builders.py` (322 — includes
`filter_to_selector`, semantic-trap watchlist #2, heaviest-fuzz target) →
`packages/core/src/bookmarks/*` + `packages/core/src/query/{segfilter,transforms,expressions,user-builders}.ts`.
Vectors: 299 (+ authored `bookmarks/date-builders.jsonl` already counted). Layer-3:
`tests/unit/test_bookmark_builders{,_pbt}.py`, `test_bookmark_schema{,_pbt}.py`,
`test_bookmark_enums.py`, `test_segfilter.py`, `tests/test_transform_funnel.py`,
`tests/test_transform_retention.py`, `tests/unit/_internal/test_expressions{,_pbt}.py`,
`tests/test_user_builders.py`. Referees (a)+(b) run at the gate (P3-7). Call-site packet:
`build_*params` members (B5, signatures from api-map), `create_cohort`/`update_cohort`
flattening (B6), `query_saved_report`/`query_saved_flows` bookmark paths (B5); R10.12
(new-format `filterValue` = JSON numbers) and R10.11 (operand rendering) apply verbatim.

**B4 — api_client + pagination** · fable. Modules: `_internal/api_client.py` (8,894 minus
B0 internals; 183 `api_client.*` entry points incl. all domain wire methods),
`_internal/pagination.py` (288), `_internal/me.py` selection logic only
(`select_workspace_id` + `/me` parsing — pure; the on-disk MeCache half is B8),
`_internal/client_metadata.py` (73: `QUERY_ORIGIN`, `get_user_agent`) →
`packages/core/src/client/*` + per-domain modules per R7.2 (`services/queries/*`,
entity-client factories per R2.9 arrive here as the client-side halves the B6 facade
delegates to). Vectors: 843 wire (gate delta 842 — see the P3-1 † footnote). Layer-3: `tests/unit/test_api_client.py` +
`test_api_client_{alerts,annotations,bookmarks,crud,crud_edge,data_governance,experiments,flags,governance,pbt,phase008,schemas,session,webhooks}.py`,
`test_app_api_client.py`, `test_pagination.py`, `test_query_workspace_scoping.py`,
`tests/unit/_internal/test_api_client_sign_replays.py`, `tests/test_api_client_engage_stats.py`.
Dedicated async Layer-3 per plan §7: pagination/streaming/retry timing tests with delayed
mock responses; R6.1 (MAX_PAGES=10000, per-paginator 429 retry ×3), R6.6 (item-level
`yield*`), R6.7 (AbortSignal at all four points). Call-site packet: `ws.api` escape hatch +
`stream_events`/`stream_profiles` (api-map B4 rows); every B5/B6 member lists its
`api_client` delegate — the packet for each B4 shard carries the api-map rows of the B5/B6
members that consume that shard's methods.

**B5 — services + rrweb + facade (query half)** · opus. Modules:
`_internal/services/discovery.py` (920), `live_query.py` (2,042), `replays.py` (971),
`_internal/replays/rrweb_analyzer.py` (969), `aggregators.py` (172), `replay_labels.py`
(145), `_internal/response_validation.py` (103), + `workspace.py` **B5-member methods
only** (the 44 members with `batch=="B5"`; the `Workspace` class file is created here and
grows in B6) → `packages/core/src/services/*`, `packages/core/src/replays/*`,
`packages/core/src/workspace.ts`. Vectors: 506 (+ rrweb golden files + authored
`rrweb-seed.jsonl`). Layer-3: `tests/unit/test_discovery{,_pbt}.py`,
`test_discovery_bookmarks.py`, `test_live_query{,_pbt,_phase008,_flow}.py`,
`test_live_query_bookmarks.py`, `test_lexicon_schemas.py`, `test_schema_graph.py`,
`test_rrweb_analyzer.py`, `test_replay_bundle.py`, `test_workspace_replays.py`,
`tests/unit/_internal/test_replays_service.py`, `tests/test_build_{cohort,funnel,retention}_params.py`,
`tests/test_workspace_{funnel,retention,flow,cohort}.py`, `tests/test_workspace_query_user*.py`,
`tests/test_workspace_build_user_params.py`, `tests/test_query_user_{edge_cases,structural}.py`.
This batch closes the phase2-audit A7 `TODO(port)` B5 rows (networkx/anytree/rrweb graph
surfaces) and the C8 deferral "result parsing from raw API response bodies". R6.4:
replays CDN walker keeps parallel fetch + 404 sentinel, concurrency identical to Python.
Call-site packet: B6 facade members that reuse service internals; `Replay*` result classes
(already B1) consumed per api-map Session Replay rows.

**B6 — workspace facade (remaining 158 members)** · opus. Module: `workspace.py`
(11,292 total; the CRUD/entity-management remainder) → `packages/core/src/workspace.ts` +
entity-client factories `create<Entity>Client({transport, getScope})` (R2.9) in
`packages/core/src/services/entities/*`. Vectors: 353 (gate delta 354 — the carried
`api_client.resolve_workspace_id` vector, P3-1 † footnote). Layer-3: the `test_workspace_*.py`
CRUD suites (`alerts,annotations,bookmarks,business_context,crud,crud_edge,
data_governance,experiments,flags,flow,governance,init,schemas,streaming,use,webhooks`)
+ `test_workspace.py` + `test_delegation_equivalence_pbt.py` (the async-equivalence PBT
Appendix-B names) + `test_042_edge_cases.py` (facade axes). Referees (a)+(b) re-run at the
gate (bookmark-touching). Call-site packet: each shard embeds its members' api-map rows
(signature, params, kwonly, returns) — this IS the contract; consumers are end users, so
the packet also carries the Python docstring examples for ergonomics decisions.

**B7 — accounts/session/targets + resolver core** · fable, DOUBLED review. Modules:
`accounts.py` (2,028), `session.py` (79), `targets.py` (99), `_internal/auth/resolver.py`
(474), `region_probe.py` (287), `naming.py` (133) → `packages/core/src/accounts/*` (pure
logic) with node-only seams injected (config/token I/O interfaces implemented in B8).
Vectors: 14 (`region_probe.`). Layer-3: `tests/unit/test_resolver.py`, `tests/pbt/*`
(resolver-precedence PBT), `test_accounts_namespace.py`, `test_session_namespace.py`,
`test_targets_namespace.py`, `test_login_region_check.py`, `test_region_probe.py`,
`test_naming.py`, `test_workspace_resolution.py`, `test_workspace_use.py`,
`test_workspace_oauth.py`. Call-site packet: `Workspace.use(...)` (B6, already built)
consumes `resolve_session`; `login_unified` orchestration signature from api-map exports;
env precedence table from CLAUDE.md (env > param > target > bridge > config) is normative.

**B8 — node package** · fable, DOUBLED review. Modules: `_internal/config.py` (1,061),
`io_utils.py` (545), `auth/storage.py` (635), `token_resolver.py` (288), `bridge.py`
(409), `flow.py` (654), `pkce.py` (73), `client_registration.py` (170),
`callback_server.py` (299), `me.py` MeCache half → `packages/node/src/*`. Vectors: 7
(`oauth_flow.`). Closes the A7 `TODO(port)` on `auth/token.ts` `expires_at` ISO rendering
(`+00:00`/µs vs `Z`/ms — lock with oauth_flow wire vectors). Layer-3: `test_config.py`,
`test_io_utils.py`, `test_auth_storage.py`, `test_storage.py`, `test_token_resolver.py`,
`test_bridge_export.py`, `test_auth_flow.py`, `test_auth_pkce.py`,
`test_auth_registration.py`, `test_auth_callback.py`, `test_me.py`,
`test_settings_headers.py` (the config/bridge attachment classes —
`TestSettingsHeaderAttachment`, `TestBridgeHeaderAttachment`, `TestNoEnvMutation`; the
outbound-request merge class translated at B0 is not re-translated here). R9.2 verbatim (atomic write + chmod 0600, symlink refusal
kept, fd-flag hardening dropped, callback ports 19284–19287). Call-site packet: B7
surfaces consume every one of these via the injected seams defined in B7's packet.

**B9 — browser package** · fable, DOUBLED review. New code (no Python source): injectable
`CredentialStore`, redirect-based PKCE (WebCrypto), `oauth_token` mode first-class,
service-account Basic auth refused at runtime (R9.3). Verify plan open-question 3
(browser-origin DCR redirect-URI acceptance) during this batch and record the result in
the batch notes; fallback stays documented per plan §4.3. Vectors: none; Layer-3: new
Vitest suites (PKCE challenge vectors from `test_auth_pkce.py` translate here since RFC
7636 test values are runtime-independent) + browser-bundle smoke extension.

## P3-2 Per-module loop template

Instantiates plan §6 Phase-3 steps 1–5 with `[SA1]` applied: **there is NO StrykerJS/mutation
step anywhere**. Every module task in every batch runs exactly this loop; "module" means one
shard row from P3-6's sharding tables.

**(a) Translate the module's Layer-3 tests** — same model tier as the module's translation
(policy rule 4). Source files are the P3-1 row's list. Rules: R10.1 (tests first), R10.2
(never weaken an assertion — if unportable, `// TODO(port)` + escalate; document per-file
header exclusions with design citations, phase2-audit A2 style), R1.3 (JSDoc), Vitest +
fast-check, colocated `*.test.ts`. Hypothesis PBT suites translate to fast-check with the
same strategy shapes; pandas-`.df` assertions map to `toRows()` per the C6 precedent.

**(b) Implement to green.** Done for the step = `tsc --strict` clean (workspace typecheck) +
translated tests green + the module's conformance vectors PASS once bound per step (b′).

**(b′) Binding + oracle registration — ALWAYS fable (rig code).** The api names are bound in
`conformance-runner/src/bindings.ts`'s registration modules (one registration point, shared
with oracle-ts). `bindings.ts` and the oracle registration are conformance-rig code, so the
fable-only rig rule (P3-3 table, tiering policy "the judge must be stronger than the
judged") applies: for **fable-tier batches (B0, B4, B7–B9)** the module task lands the
binding inline as part of (b); for **volume-tier batches (B2, B3, B5, B6)** the binding +
oracle-ts registration is a SEPARATE fable task (P3-6 step 3) that (i) writes the thin
adapter bindings, (ii) applies the P3-5 rule-3 binding-honesty check (which covers
pure/builder bindings too), and (iii) runs the module's vectors to green. Vector failures
surfaced at (b′) are the MODULE task's failure for escalation purposes (P3-3 rule: the
attempt-1 failure context goes back to the module, not the binder). Wire modules (B4+): every response body flows
through `parseLossless` (GATE-VERDICT R5 — grep-audited at review: zero `response.json()`
or bare `JSON.parse` on response text in `packages/*/src`; `wirestub.ts:198` is the sole
grandfathered test-double exception).

**(c) R10.9 throwaway differential harness** after (b′), before review, per module. Mandatory edge set,
verbatim: integral float (`18.0`), fractional float (`1.5`), `True`, `None`, empty list,
empty string, non-BMP string (`"𝒳"`), and **every error branch** of the module (enumerate
from the module's registry codes; for wire modules, every `_handle_response` status branch
via canned responses). Then fixed-budget fuzz through the oracle bridges: **≥500 examples
per api family** (P2-9 precedent) over the module's `oracle.call` entry points, zero
unexplained divergences; shrunken repros to `conformance/differential/repros/` block the
task. Oracle-py already exposes every registry entry point; oracle-ts gains the module's
apis via the (b′) binding commit (fable for volume-tier batches) BEFORE the harness runs.
Wire methods have no oracle
`call` surface (the bridges are pure/builder-scoped) — for those, (c) reduces to the edge
set replayed through `VectorFetch` with hand-built interactions covering every status
branch. The harness is NOT deleted by the module task: it lives in a `throwaway/`
directory inside the module commit, the RUN record (counts, seeds, divergence table) is
appended to the batch notes file, the review pair re-runs or spot-checks it from the
recorded seeds (step d item 5), and the BATCH GATE task removes `throwaway/` after
arbiter sign-off.

**(d) Adversarial review PAIR + arbiter — ALWAYS fable tier** (policy: review never
downgrades). Two independent reviewers, then an arbiter. Each reviewer explicitly executes:
(1) the **R10.2 assertion-weakening check** — diff every translated test against its Python
source assertion-by-assertion; any dropped/loosened assertion without a file-header design
citation is a finding; (2) the **rulebook-compliance check** — a pass over R2 (factory
clients, injectable fetch R2.4, string-concat URLs R2.13, redirect:'manual' R2.11, ms units
R2.12), R3.9/R4.10/R4.11 optionality, R4.8 ReadonlyMap, R5 codes-not-messages, R6.6/R6.7,
watchlist §8 items 1/6/7 (destructuring arity, truthiness, prototype membership); (3) the
GATE-R5 lossless-parse grep for wire modules; (4) `TODO(port)` triage (every marker gets an
owner or a fix); (5) **R10.9 harness re-run/spot-check** — re-run the module's `throwaway/`
harness (or a seeded subset) from the RUN record's seeds and confirm the recorded counts
and zero-divergence claim reproduce; a RUN record that cannot be reproduced is a finding.
Arbiter resolves splits, verifies (b′) binding honesty for the module (P3-5 rule 3 — ALL
bindings, not just wire), and files R10.4 rulebook amendments when a fix
pattern recurs ≥3 times (stop, amend, regenerate affected modules).

**(e) Batch-done gate** (one task per batch, after all module tasks + reviews):
1. `conformance-runner/src/batch-status.ts` flips the batch's prefixes to `"done"`
   (UNPORTED→FAIL for stragglers) — flip granularity per P3-5; the flip lands **in the same
   commit** as the gate checkpoint (the module's batch-status unit test's full-corpus
   prefix-coverage check must stay green).
2. Conformance report checkpoint: run `npm run conformance`, verify counts match the P3-1
   row's expectation (PASS grows by exactly the batch's **gate delta** — the vector count
   adjusted per the P3-1 † cross-batch-setup rule; FAIL = 0; UNPORTED
   shrinks by the same), archive the report JSON under `context/phase3/reports/` in the
   Python repo, commit both repos (TS: gate commit on `main`; Python: docs/report commit on
   the support branch).
3. Oracle-ts surface extended to the batch's apis (via the shared bindings registration).
   Verification is a **mechanical probe**, not `oracle.info` (protocol-1.1 `oracle.info`
   returns only `{language, library_version, source_commit, protocol_version}` on both
   bridges — it has no api list): issue one `oracle.call` per newly registered
   registry-covered api against BOTH bridges and require a non-"unknown api" response
   (oracle-py raises `OracleProtocolError` "unknown api …" for unregistered names,
   `oracle_py/server.py:414-418`; wire api names have no oracle call surface and are
   exempt from the probe). Then a **differential full-suite regression run** (P3-7)
   green.
4. `npm run check` green (TS) — includes typecheck/lint/prettier/vitest/browser smoke;
   `just check` green (Python) if the batch touched the Python repo.
5. Batch notes file (`context/phase3/notes/BX-notes.md`) finalized: RUN records, review
   findings, discrepancies, escalations.

**Mechanical done-criteria restated per R10.5**: TS files exist on disk + `tsc --strict`
clean + module vectors green + translated tests green. State lives on disk; the queue
rebuilds from disk — a killed agent's replacement re-derives progress from files, never
from chat history.

## P3-3 Tiering wiring

Per `context/phase3/model-tiering-policy.md` (binding; = rulebook R10.14). Task→model table
the orchestrator sets explicitly on every `agent()` (silently inheriting session effort or
model is forbidden, R10.13):

| Task | Model | Effort |
|---|---|---|
| B0 all packets (compat + client internals) | **fable** | ≤ high |
| B2 module tasks + their Layer-3 translations | **opus** | ≤ high |
| B3 module tasks + their Layer-3 translations | **opus** | ≤ high |
| B4 module tasks + their Layer-3 translations | **fable** | ≤ high |
| B5 module tasks + their Layer-3 translations | **opus** | ≤ high |
| B6 module tasks + their Layer-3 translations | **opus** | ≤ high |
| B7 / B8 / B9 module tasks | **fable** | ≤ high |
| Design-lite packet authoring (per batch, P3-6 step 1) | **fable** | ≤ high |
| Adversarial review pair, arbiter, batch gates, audits, failure triage | **fable** | ≤ high |
| Binding + oracle registration tasks (P3-2 step b′) for volume-tier batches (B2/B3/B5/B6) | **fable** | ≤ high |
| ANYTHING touching the conformance rig (bindings.ts, batch-status.ts, runner, codecs, oracles, recorder, canonicalizers, referees) | **fable** | ≤ high |
| R10.9 throwaway differential harness runs | same tier as the module task (policy rule 3: the harness itself is unchanged and tier-independent; a rig CHANGE escalates to fable per the row above) | ≤ high |

**Escalation rule** (policy rule 2): a volume-tier (opus) task that misses its
done-criteria on attempt 1 retries **once on fable**, with the attempt-1 failure context
(what failed, which vectors/tests, reviewer findings) prepended to the packet. Two failures
abort the chain per the standing contract — orchestrator stops the batch and escalates to
the user.

**Auth doubling** (plan §6 / §7 — no second oracle for auth): B7, B8, and B9 run **two
independent review pairs** (4 reviewers + 1 arbiter per module task) instead of one pair.
The second pair receives only the Python source + the TS diff (not the first pair's
findings) so the reviews stay independent. This is review doubling, not oracle doubling —
there is still no cross-language fuzz surface for auth; compensating controls are full
Layer-3 translation of every auth test file listed in P3-1 and the Phase-4 live-suite auth
scenarios.

TIERING REVISION 2026-08-15 (user directive): Sonnet removed from the program — its harness alias resolved to Sonnet 4.5 on this deployment. Volume tier is Opus 5 (alias pinned to claude-opus-5 via ANTHROPIC_DEFAULT_OPUS_MODEL in .claude/settings.local.json; probe-verified). Two tiers only: fable + opus.

## P3-4 B0 task packets (IN FULL — the next workflow executes these verbatim)

Both packets: model **fable**, effort ≤ high, incremental work protocol (R10.13). Common
done-criteria: `tsc --strict` clean; `npm run check` green; `just check` green on the
Python side when it changes; one commit per repo per packet; no mutation testing `[SA1]`.

### Packet B0-1 — pythonCompat completion (both repos)

Completes rulebook §11. Already done (Phase 1 TS-2): R11.1 `pythonStr`/`pythonRepr`
(`packages/core/src/compat/python-str.ts` + pinned `non-printable.gen.ts`), R11.2
`pythonFloatStr` (`python-float-str.ts`), R11.4 `zfill` (`zfill.ts`). This packet adds the
rest, mirrored in BOTH repos (TS implementation + Python reference wrappers in
`conformance/record/pycompat_ref.py` so the recorder/oracles can call them by api name).

**⚠ Unicode-DB caveat (from TS-2 / phase1 audit-oracles-referees §(e))**: every
generated character table is pinned to **CPython 3.14.6 / Unicode 16.0.0** and carries a
regeneration script + a header comment explaining the V8-Unicode-17 skew and the
re-run-on-CPython-upgrade rule (`python-str.ts:32-37` is the precedent). New tables in this
packet follow the identical pattern.

1. **R11.3 `pythonInt` / `pythonFloat` parse grammars** →
   `packages/core/src/compat/{python-int,python-float}.ts`.
   Semantics = CPython `int(str)` / `float(str)` exactly:
   - both: optional surrounding whitespace (CPython's Unicode whitespace set — see item 4),
     optional single leading `+`/`-`, underscores allowed between digits only
     (`int("1_0")` → 10; `"1__0"`, `"_1"`, `"1_"` all reject);
   - `pythonInt` rejects `"5.5"`, `"0x5"` (base-10 only), `""`, `"inf"`, `"nan"`;
   - `pythonFloat` accepts `"inf"`/`"infinity"`/`"nan"` case-insensitive with sign,
     decimal/exponent forms, `.5`/`5.`; rejects `""`;
   - **CPython accepts non-ASCII decimal digits** (`int("٤٢")` → 42, category Nd). Because
     `Retry-After` parsing is attacker-controlled input and the oracle fuzz WILL find this,
     port it: generate `compat/decimal-digits.gen.ts` (Nd codepoint → digit value) from
     CPython, pinned per the caveat above. Return type: TS `number`; values beyond 2^53−1
     from `pythonInt` throw a coded error (canonicalizer 2^53 policy, R4.5) — no B0
     consumer can produce one legitimately (Retry-After is clamped at 60 downstream).
   - Authored vectors: new `conformance/vectors/authored/compat/` lines for
     `compat.python_int` + `compat.python_float` (≥12 each: the grammar cases above + the
     R10.9 edge set where applicable + one Nd-digit case + whitespace-wrapped + sign cases).
     Python-side registry: extend `_gate_entries()` in `conformance/record/registry.py`
     (add the names to the tuple) with `pycompat_ref.python_int/python_float` wrappers.
     Oracle targets: extend `conformance/differential/strategies.py` with `python_int`/
     `python_float` probe strategies (string-input biased: digits, underscores, hex-ish,
     float-ish, unicode digits/whitespace, inf/nan casings); register in oracle-ts via the
     shared bindings module.
2. **R11.5 codepoint-`sorted`** → `packages/core/src/compat/codepoint.ts` export
   `sortedByCodepoint(values: readonly string[]): string[]` — Python `sorted()` string
   ordering = lexicographic by **codepoint** (JS default `<` compares UTF-16 units, which
   inverts e.g. `"｡"` vs `"😀"`). Comparator iterates codepoints; stable; returns a
   new array. Authored vectors `compat.sorted_strings` (≥8: BMP-only, non-BMP mixes,
   empty-string member, equal-prefix cases) + oracle strategy (string-list arbitrary with
   surrogate-adjacent codepoints biased).
3. **R11.6 codepoint `slice`/`length`** → same file: `cpLength(s)`, `cpSlice(s, start?,
   end?)` with Python slice semantics (negative indices, out-of-range clamping, never
   splits a surrogate pair). Used TODAY by B0-2 (`_error_message` `text[:200]`,
   `_handle_response` `response.text[:500]`) and later by every `max_length` validator
   (B2). Authored vectors `compat.cp_slice`/`compat.cp_length` (≥10: non-BMP at the cut
   point, negative indices, start>end, empty). Oracle strategies likewise.
4. **`pythonStrip`** (enabling dependency, folds into R11.3/R11.6 home): CPython
   `str.strip()` whitespace set ≠ JS `String.trim()` set (Python strips `\x1c–\x1f`; JS
   strips U+FEFF; etc.). Generate `compat/whitespace.gen.ts` from CPython
   (`str.isspace()` sweep, pinned per the caveat) and export `pythonStrip(s)`. Consumed by
   `pythonInt`/`pythonFloat` (whitespace tolerance) and B0-2 `_iter_jsonl_lines`
   (`.strip()` on decoded lines). Authored vectors under `compat.python_strip` (≥8 incl.
   `\x1c`, U+FEFF, NBSP cases).

Done-criteria: all new authored vectors PASS in BOTH runners (Python runner on the support
branch; TS runner after `scripts/sync-corpus.sh` re-sync + re-pin — this is a corpus
re-pin event, follow P3-7 re-sync steps incl. the D9 drift check); oracle fuzz
`compat.*` families ≥500 examples each, zero divergences; `compat/index.ts` exports the
new surface; JSDoc + generated-file caveat headers present.

### Packet B0-2 — shared client internals, ported once by name (R10.8)

TS home: `packages/core/src/client/` (replaces the Phase-1 placeholder `client/index.ts`).
Python source of record: `src/mixpanel_headless/_internal/api_client.py` at the current
support-branch HEAD — **includes the PR-206 fixes** (hostile Retry-After, 400-branch
default message, 401 `request_body`, `request_params` threading); the stress-test bug list
is already fixed upstream, so port current behavior verbatim, no compensation. Spec below
is byte-for-byte from source read 2026-08-15; the builder MUST re-read each cited range.

| Item | Python source | TS home | Locked NOW by | Locked at B4 by |
|---|---|---|---|---|
| `_error_message` | `api_client.py:81-106` | `client/internals.ts` | translated `test_api_client.py` handler tests | every error-branch wire vector |
| `_iter_jsonl_lines` | `api_client.py:109-148` | `client/jsonl.ts` | the 6 authored chunk vectors (`corpus/authored/streaming/jsonl-chunks.jsonl`, api `api_client._iter_jsonl_lines`) — bind the REAL implementation in `bindings.ts` this packet (replaces nothing: the name is currently unbound) + translated streaming unit tests | `streaming` wire vectors (18 `api_client.*`) |
| `ENDPOINTS` region table + URL builder | `api_client.py:151-172` (+ `_build_url` — locate by name) | `client/url.ts` | translated URL tests; R2.3/R2.13: pure functions, **string concatenation only**, never `new URL(path, base)` | every wire vector's request path |
| retry/backoff trio | `_calculate_backoff` `:664-681`, `_retry_wait_seconds` `:683-704`, `_parse_retry_after` `:1159-1185` | `client/backoff.ts` | translated `test_api_client.py:444-540,1436-1560,1762-1800,3467-3520` (429 loops, hostile Retry-After) with injected sleep + injected RNG | 429-sequence wire vectors |
| `_handle_response` | `api_client.py:503-662` | `client/internals.ts` | translated handler tests — EVERY branch, see checklist below | every non-200 wire vector |
| `_execute_with_retry` | `api_client.py:706-820` | `client/internals.ts` | translated tests (429 loop, `httpx.HTTPError`→`HTTP_ERROR` mapping per R2.10) | all Query-host wire vectors |
| `_request_headers` | `api_client.py:452-481` | `client/headers.ts` | translated `test_settings_headers.py::TestSessionHeadersOnOutboundRequests` (merge order + env/session precedence-on-collision) | every wire vector's request headers |
| `app_request` | `api_client.py:1191-1387` | `client/app-request.ts` | translated `test_app_api_client.py` | all App-API wire vectors (the bulk of the 810) |
| `maybe_scoped_path` | `api_client.py:1637-1664` | `client/scope.ts` | translated path tests (workspace set / unset) | scoped-path wire vectors |
| `parseLossless` relocation | (rig code, no Python source) `conformance-runner/src/lossless-json.ts:52` | `client/lossless-json.ts` — MOVE into core with its existing unit tests; `conformance-runner` re-imports from core thereafter (judge-uses-library direction; the library must NEVER import from the rig) | the moved lossless-json unit suite | every wire vector's body parse (GATE-R5) |

R10.8 ownership note: `_request_headers` is consumed by BOTH B0 wire functions
(`_execute_with_retry` at `:747`, `app_request` at `:1264`) and by streaming/replay call
sites (`:1862`, `:7720`, `:7923`) — it is B0-owned, single implementation in
`client/headers.ts` (4-layer merge, each later layer overriding on name collision:
(1) `User-Agent` from `getUserAgent()`; (2) `MP_CUSTOM_HEADER_NAME`/`MP_CUSTOM_HEADER_VALUE`
env pair; (3) `session.headers`; (4) caller extras). B4-C1 IMPORTS it by name and must not
re-implement any header merging.

Byte-for-byte behavior checklist (each line = an assertion the review pair verifies):

- **`_handle_response` branches, in source order**: parse body first — via `parseLossless`
  over the response text (GATE-VERDICT **R5**: never `response.json()`); on parse failure,
  body = `cpSlice(text, 0, 500)` or `null` when empty. Then: 401 → `AuthenticationError`;
  **403 with `SESSION_RECORDING_SENSITIVE_DATA` in the serialized body →
  `SessionReplayAccessError`** with details `{project_id: pythonInt(session.project.id),
  flag, permission_required}` (THE branch the stress test saw silently dropped — R10.8's
  founding example; note the `int()` coercion of project id uses `pythonInt`); other 403 →
  `QueryError` default `"Permission denied"`; 400 → `QueryError` default `"Unknown
  error"`; 404 → `QueryError` default `"Resource not found"`; other 4xx → `QueryError`
  default `"Request failed"`; 5xx → `ServerError` with `"Server error: "` prefix.
  **Fallthrough tail, in EXACT source order (`api_client.py:652-662`)**: (i)
  `response.raise_for_status()` runs FIRST — any remaining non-2xx status (including 3xx,
  reachable in TS because R2.11 mandates `redirect: 'manual'`) goes through the explicit
  throwing helper, which MUST throw a `MixpanelHttpError`-normalized error so that
  `_execute_with_retry`'s catch (`:801`) wraps it as `MixpanelHeadlessError` code
  `HTTP_ERROR` — a 3xx with a JSON object body is an ERROR, never a success return; (ii)
  parsed body is object/array → return it; (iii) otherwise re-parse the body: a JSON
  **scalar** (`42`, `"ok"`, `true`, `null`) is RETURNED as the result (verified against
  httpx: `Response(200, b"42").json()` → `42`); only a parse FAILURE raises
  `MixpanelHeadlessError` code `INVALID_RESPONSE` with `cpSlice(text, 0, 500)` in the
  message. All error constructors carry
  `status_code`/`response_body`/`request_method`/`request_url`/`request_params`/
  `request_body` (serialized detail bags keep Python spelling, R7.6). Message text is out
  of contract (R5.4) but defaults above are ported anyway (they flow into `expect.error`
  details only via codes — do not vector-assert text).
- **`_error_message`** (`api_client.py:98-100`): dict body — `error` key ABSENT **or
  `null`** → the default (Python `body.get("error") is None` cannot distinguish the two;
  never map `{"error": null}` to the string `"None"`); string `error` → as-is; other
  non-null `error` → `pythonStr(raw)`; string body → `cpSlice(body, 0, 200)`;
  blank/whitespace-only result (Python `.strip()` → `pythonStrip`) falls back to the
  default.
- **Retry policy (R2.5, clarified against source — see Discrepancy #1)**: 429-only; loop
  `for attempt in 0..maxRetries` (default `maxRetries = 3`, `api_client.py:312`); on final
  attempt raise `RateLimitError` with `retry_after` (parsed header, may be null) +
  lossless-parsed body + **`project_id`** — EVERY raise site passes
  `project_id=self.project_id` (`api_client.py:779, :819, :1322, :1386, :1890`; Python
  spelling in the detail bag, R7.6; the corpus's `details_contain` subset matching does
  NOT assert it, so only faithful translation of the Layer-3 asserts at
  `test_api_client.py:504,527,1567,4090` locks it). Constructor shapes vary by site: the
  type-checker fallthrough raises (`:814-820`, `:1381-1387`) omit
  `retry_after`/`status_code`/`response_body`; the streaming-export site (`:1883-1891`)
  omits `response_body` only — port each shape verbatim.
  Otherwise wait = header present ? `min(pythonFloat-of-int, 60)`
  **without jitter** : `min(1.0 * 2^attempt, 60) + uniform(0, delay*0.1)` **with jitter**
  (`random.uniform` ports to an injectable `random: () => number` seam; conformance/tests
  inject a fixed source). `_parse_retry_after`: `pythonInt(header)`; unparseable or
  negative → null; HTTP-date → null. 5xx/network: NO retry, throw immediately.
  **R2.12**: the TS sleep seam takes milliseconds (`sleep(seconds * 1000)` at the one
  conversion point); serialized `retry_after` stays seconds under its Python name.
- **`_execute_with_retry`**: injects `params.query_origin = QUERY_ORIGIN`
  (`client_metadata.py` ports alongside: `QUERY_ORIGIN` + `getUserAgent()` stamped via
  `_request_headers`, `api_client.py:452`); catch clause is
  `if (!(e instanceof MixpanelHttpError)) throw e;` → wrap as `MixpanelHeadlessError`
  code `HTTP_ERROR` with `{error, request_method, request_url, request_params}` details
  (R2.10 — the transport adapter owns fetch `TypeError`/`DOMException`/`UND_ERR_*`
  normalization to `MixpanelHttpError` first).
- **`app_request`**: guard `AC1_BODY_MUTUALLY_EXCLUSIVE` (`ParamValidationError`) when
  both `json_body` and `form_body`; auth header resolved **per request** via the Phase-2
  `sessionAuthHeader`/TokenResolver seam (R2.9 — never captured at construction); NO
  `query_origin` on App-API params; 204 → `{status: "ok"}`; its own 429 loop (same trio);
  422 → `QueryError` with lossless body; else delegate to `_handle_response`; unwrap
  `results` key when present and `_raw` is false (`Object.hasOwn`, R4.8/watchlist #7).
- **`_iter_jsonl_lines`** → `async function*` over `ReadableStream<Uint8Array>`: byte
  buffer (`Uint8Array` concat), split on `\n` (byte 0x0A), decode UTF-8 with replacement
  (`TextDecoder` default — matches `errors="replace"`), `pythonStrip`, skip empty, flush
  tail without trailing newline. Chunk boundaries preserved through the R2.6
  gzip-boundary semantics; the 6 authored vectors replay recorded chunk sequences through
  `VectorFetch`'s `body_stream` rebuild.
- **`maybe_scoped_path`**: workspaceId set → `/workspaces/{wid}/{path}` else
  `/projects/{pid}/{path}` (template concatenation). `require_scoped_path` and
  `resolve_workspace_id` are NOT B0 (they do network discovery) — they port in B4 shard C1
  and import this module.

R10.10 consumer list (ship in the packet): all 183 `api_client.*` entry points (B4) call
`_execute_with_retry`/`app_request`/`maybe_scoped_path`; `pagination.paginate` (B4) calls
`app_request` per page via a `PageFetcher`-style function seam that preserves per-request
auth resolution (R2.8); `stream_events`/`stream_profiles` (B4, api-map:
`streamEvents(fromDate, toDate, …): AsyncIterable<…>`) consume `_iter_jsonl_lines`; every
`create<Entity>Client` factory (B6) receives `{transport, getScope}` built on these.
Signatures for the three B4 api-map members are embedded verbatim in the packet from
`api-map.json` (`stream_events`, `stream_profiles`, `api`).

Done-criteria: table's "Locked NOW" column all green; the 6
`api_client._iter_jsonl_lines` vectors PASS (conformance report: 461 + 6 + new-authored
PASS, 0 FAIL); R10.9 harness run with the full edge set incl. **every `_handle_response`
branch** (200-object, 200-array, 200-non-JSON, 400, 401, 403-plain, 403-sensitive-data,
404, 412, 422-via-app_request, 429-exhausted, 500, 204-app, network-error) — recorded in
the notes file; review pair + arbiter (fable) signed off; NO batch-status flip (B0 has no
owned prefix beyond the exact-name `api_client._iter_jsonl_lines` entry, which IS added as
`done`).

## P3-5 Wire-batch enablement plan (B4+)

How the 1,700+ wire vectors start replaying.

**1. Client construction from `call.session`.** Wire vectors carry
`call.session` (D5 canonical fake session, e.g. `{account_name, project_id, region, token,
type: "oauth_token"}`) and some carry `call.workspace_session` (both already surfaced by
`runner.ts` as `session`/`workspaceSession` on the binding context). B4 adds ONE shared
helper in `bindings.ts` (fable — rig code): `clientFromSession(context)` →
`parseAccount(session)` (Phase-2 C4 factory) → `Session` → `createMixpanelClient({session,
fetch, sleep, random, now})`. Auth headers are therefore built by the REAL Phase-2 auth
model (`accountAuthHeader`/`sessionAuthHeader`) and diffed byte-exactly against recorded
headers (fake creds make exact match safe; the canonicalizer's pattern-matching for auth
headers stays as the backstop per plan Appendix A).

**`call.setup[]` + shared state (MANDATORY)**: the runner creates ONE `state` map and ONE
`createVectorFetch` harness per vector and executes every `call.setup[]` entry through the
bindings with that shared context BEFORE the measured call (`runner.ts:446`, `:478-500`;
doc comment `:51-52`). `clientFromSession` therefore MUST memoize the constructed client
in `context.state` (single well-known key) so setup entries and the measured call operate
on the SAME instance — a fresh client per binding invocation would let the 97
`api_client.set_workspace_id` setup entries (plus `close` 8, `retention` 4,
`list_bookmarks` 4, `use` 2, `resolve_workspace` 2, `resolve_workspace_id` 2, and the
other discovery prerequisites) mutate a throwaway object, and every workspace-scoped wire
vector would FAIL_REQUEST with a project-scoped path. Corollary: every api name appearing
in ANY `call.setup[]` needs a binding by the time its vectors replay (all setup names are
within the 183 `api_client.*` api-index names except `workspace.me` — see the P3-1 †
footnote), or `gateApis` (`runner.ts:368-386`) short-circuits the vector.

**2. The R2.4 injected-fetch seam.** `createMixpanelClient` accepts `fetch?: typeof fetch`.
The runner passes `harness.fetch` from `createVectorFetch(interactions)` — already built
(positional serving, unordered-group keying, `transport_error` rejection tables,
`body_stream` chunk rebuild). The library adapter normalizes fetch failures to
`MixpanelHttpError` (R2.10) and sets `redirect: 'manual'` (R2.11). Determinism seams
injected by every wire binding: `sleep: () => Promise.resolve()` (zero-delay),
`random: () => 0` (kills backoff jitter variance — legal because sleep durations are not
vector-observable, only request sequences are), `now: () => recordEpoch` (D1.4 clock
freeze). Timing-sensitive behavior is Layer-3's job (fake timers), never Layer-2's.

**3. Binding honesty rule (ALL bindings, not only wire).** A binding calls the same public
entry point the recorder wrapped (`api_client.X` → the ported client method;
`workspace.X` → the real facade member; `validation.X`/`bookmark_builders.X`/… → the
ported pure function). Bindings NEVER re-implement request assembly, re-derive the
transform, or bypass the facade — that is the ScanCode failure mode. Every binding commit
is fable-authored (P3-2 b′), and the arbiter checks each module's new bindings against
this rule explicitly for pure/builder batches exactly as for wire batches.

**4. Flip granularity (decision).** `batch-status.ts` matching is `api.startsWith(prefix)`
with longest-prefix-wins (`batch-status.ts:90-95`) — an "exact name" entry is still a
PREFIX and also captures every longer api name it prefixes. Flips track the OWNING BATCH,
not the raw prefix, with the following standing safety rule: **after generating any set of
exact-name entries, mechanically assert that no still-pending corpus api name
`startsWith` a generated entry** (scan the corpus api names against the new entries; any
hit requires a longer overriding entry pinned to `pending`). One such collision exists
today and is resolved explicitly below (`workspace.list_bookmarks` → `_v2`):

- **B0**: add exact-name entry `api_client._iter_jsonl_lines` → `done`.
- **B2 gate**: `validation.` + `user_validators.` → `done`.
- **B3 gate**: `bookmark_builders.` + `segfilter.` + `user_builders.` + `expressions.` +
  `transforms.` → `done` (NOTE: the current file comment bins user_builders/expressions/
  transforms under "B2" — the comment is informal; scope follows this playbook, see
  Discrepancy #2).
- **B4 gate**: `api_client.` + `pagination.` → `done` (single flip at the gate — bound
  names already replay while pending, so per-shard progress is visible in the PASS count
  without any interim flip; the gate flip is purely the straggler ratchet).
- **B5 gate**: 44 exact-name entries `workspace.<member>` → `done` (generated
  mechanically: `jq -r '.workspace_members[] | select(.batch=="B5") | "workspace." + .name'
  context/typescript-port-api-map.json`), plus `replays.` + `replay_labels.` +
  `rrweb_analyzer.` → `done`, **plus the longer overriding entry
  `workspace.list_bookmarks_v2` → `pending`**: the generated B5 entry
  `workspace.list_bookmarks` (a B5 member with ZERO corpus vectors) prefix-captures the
  B6 member `workspace.list_bookmarks_v2` (7 corpus vectors) under `startsWith` matching
  and would flip those 7 unported B6 vectors to FAIL_ERROR; the longer `pending` entry
  wins the longest-prefix resolution and keeps them UNPORTED until B6. Run the standing
  collision assertion above after generating the list (this is the only collision at the
  current pin).
- **B6 gate**: replace the 44 exact-name entries AND the `workspace.list_bookmarks_v2`
  pending override with the single `workspace.` → `done`
  (longest-prefix keeps them equivalent; collapsing keeps the table readable).
- **B7 gate**: `region_probe.` → `done`. **B8 gate**: `oauth_flow.` → `done`.

Every flip commit re-runs the batch-status unit suite (full-corpus prefix coverage) and
the conformance report; UNPORTED must drop by exactly the batch's **gate delta** (the
P3-1 vector count adjusted per the † cross-batch-setup footnote: B4 −842, B6 −354, all
other batches equal to their vector count).

**5. B4-before-B5/B6 semantics.** Landing B4 flips only `api_client.`/`pagination.`;
`workspace.*` vectors stay UNPORTED (not FAIL) until their owning member's batch gate.
This is the designed behavior of the longest-prefix table — no intermediate state where a
not-yet-ported facade member reads as a failure, and no silent skip after its batch closes.

## P3-6 Per-batch workflow template

Task-list shape the orchestrator instantiates per batch (all agents get the P3-0 ground
state + R10.13 protocol + their P3-3 model assignment stated explicitly):

1. **Design-lite packet task** (fable): one agent reads the P3-1 batch row + the Python
   sources + api-map rows and writes `context/phase3/packets/BX-packets.md` — one packet
   per module shard containing: file list, Python source line ranges, TS homes, the
   shard's vector ids/counts, its Layer-3 test files, the R10.10 call-site signatures
   PASTED IN, known traps (watchlist references), and shard-local done-criteria. B0 skips
   this step (P3-4 IS the packet).
2. **N module tasks** (batch tier; sequential or parallel per the dependency notes in the
   packet — default: parallel within a shard group, sequential across groups that share
   files): each runs the P3-2 loop steps (a)+(b). For fable-tier batches (B0, B4, B7–B9)
   the module task also performs (b′) inline and continues into (c).
3. **Binding task per module — fable, volume-tier batches only (B2/B3/B5/B6)**: P3-2
   step (b′) — registers the module's api names in `bindings.ts`/oracle-ts, applies the
   P3-5 rule-3 honesty check, runs the module's vectors to green. Rig code never runs at
   opus (P3-3 rig row; tiering policy "the judge must be stronger than the
   judged"). Vector failures found here are the MODULE task's attempt-1 failure for
   escalation purposes. After (b′) lands, the module tier runs P3-2 step (c) (the R10.9
   harness — same tier as the module per policy rule 3; a fresh module-tier task if the
   original agent has exited).
4. **Review pair task ×2 per module** (fable; ×4 for B7/B8/B9 per P3-3 doubling) then
   **arbiter task** (fable): P3-2 step (d), including the harness re-run/spot-check
   (item 5) and the binding-honesty verification. Arbiter output: findings resolved,
   rulebook amendments filed, GO/NO-GO per module.
5. **Batch gate task** (fable): P3-2 step (e) — flips, report checkpoint, oracle
   extension probe, differential regression, referee runs where scheduled (P3-7),
   `throwaway/` harness cleanup after arbiter sign-off, notes finalization, commits.

Failure handling: module task misses done-criteria → P3-3 escalation (retry once on fable
with failure context); second miss aborts the chain. Recurring fix patterns (≥3) → R10.4
stop-amend-regenerate.

### Sharding tables (module tasks per batch)

**B0**: 2 packets (P3-4). **B9**: 2 tasks (CredentialStore + PKCE redirect flow; DCR
verification folded into the second).

**B2** (3 tasks, opus): V1a `validation.py` query-args half; V1b `validation.py`
bookmark half + `validate_bookmark` export + `bookmarks/enums.ts` TODO closure; V2
`user_validators.py`. Split V1a/V1b along the file's function families; the design-lite
packet fixes the exact function lists.

**B3** (4 tasks, opus): K1 `bookmark_enums` + `bookmark_schema`; K2 `bookmark_builders`;
K3 `segfilter` + `expressions` + `transforms`; K4 `user_builders`
(`filter_to_selector` — heaviest-fuzz mandate: the R10.9 budget for K4 doubles to ≥1,000
examples with adversarial Unicode/quote/backslash inputs). K2–K4 depend on K1's tables.

**B4** (6 tasks, fable): C1 client assembly (constructor/`_ensure_client`/`_request`/
`with_project`/`resolve_workspace_id`+`require_scoped_path`+me-selection logic; header
composition is NOT re-implemented here — C1 imports the B0-owned `client/headers.ts`
`_request_headers` by name, R10.8) —
first, everything depends on it; C2 Query-host methods (segmentation family, funnels,
retention, flows, activity feed, frequency, engage/user profiles, top events) +
streaming (`stream_events`/`stream_profiles`, export) — the 3 B4 api-map members land
here; C3 entity CRUD wire methods: dashboards + bookmarks + cohorts; C4 flags +
experiments + annotations + webhooks + alerts; C5 data governance (lexicon, drop filters,
custom properties, lookup tables, custom events, tracking/history) + schemas + audit +
anomalies + deletion requests + business context + replays signing; C6 `pagination.py`
(after C1; R6.1/R6.6/R6.7 apply in full). The design-lite packet assigns each of the 183
`api_client.*` api-index names to exactly one of **C1–C6** — the 183 include the
client-assembly/scoping names (`use`, `set_workspace_id`, `close`, `with_project`,
`resolve_workspace`, `resolve_workspace_id`, `require_scoped_path`, `request`) which
belong to C1, plus the two B0-ported names bound in B4 shards (`maybe_scoped_path` —
B0 module, C1 binds/imports it by name; `api_client._iter_jsonl_lines` — already bound
at B0, listed as B0-owned in the assignment) — and the gate task verifies the
assignment covers all 183 (mechanical diff against
`jq -r 'keys[]|select(startswith("api_client."))' corpus/api-index.json`).

**B5** (3 tasks, opus): S1 DiscoveryService + lexicon schemas + schema graph + the 12
discovery/lexicon facade members; S2 LiveQueryService + `response_validation` + the 22
query facade members incl. the five `build_*params` (426 builder vectors — the volume
center of the batch); S3 ReplaysService + rrweb analyzer + aggregators + replay_labels +
the 10 Session Replay members. S2 creates `workspace.ts` (class skeleton + B5 members);
S1/S3 extend it — run S2 first or accept a merge point in the packet.

**B6** (8 tasks, opus — 158 members by api-map section groups; counts measured from the
api-map JSON): W1 Lifecycle & construction 6 + workspace management 2 + /me & project
discovery 3 + business context 4 = **15**; W2 Dashboard CRUD 6 + dashboard advanced 16 =
**22**; W3 Bookmark/report CRUD 9 + cohort CRUD 7 = **16**; W4 Feature flags 11 +
experiments 12 = **23**; W5 Annotations 7 + webhooks 5 + alerts 11 = **23**; W6a Lexicon
11 + tracking & history 4 = **15**; W6b Drop filters 5 + custom properties 6 + lookup
tables 9 + custom events 4 = **24**; W7 Schema registry 6 + schema enforcement 5 + audit
2 + anomalies 3 + deletion requests 4 = **20**. Σ = 158. W1 first (`use()`/`close()`/
session axes — R6.2 connection-reuse invariant, `[Symbol.asyncDispose]`); W2–W7
parallelizable after W1. Each W-task also builds its `create<Entity>Client` factories
(R2.9) over the B4 client.

**B7** (2 tasks, fable, doubled review): A1 resolver + region_probe + naming; A2 accounts
+ session + targets namespaces + `login_unified` (depends on A1; node-only effects behind
injected interfaces that B8 implements).

**B8** (3 tasks, fable, doubled review): N1 config + io_utils; N2 storage + token_resolver
+ bridge + MeCache; N3 flow + pkce + client_registration + callback_server (the
`oauth_flow.` vectors land here, closing the `token.ts` `expires_at` TODO).

## P3-7 Standing verification posture during Phase 3

- **Differential full-suite regression at EVERY batch gate**: oracle-py ↔ oracle-ts over
  the entire registered surface (cumulative — grows each batch), fresh seeds, P2-9 budget
  (≥500 examples per api family + the harvested edge set). Zero unexplained divergences;
  repros block the gate. Run record appended to `differential/oracle/RUN.md`.
- **Referees**: (a) bookmark.json ajv validator + (b) bookmark_parser round-trip harness
  re-run at the **B3 and B6 gates** (the bookmark-touching batches; B5's
  `query_saved_report`/`query_saved_flows` read bookmarks but don't construct them — if a
  B5 module emits a bookmark payload anyway, its gate adds the referees). Referee (c)
  (type regeneration) stays CI-passive.
- **Layer-4 live parity: DEFERRED to Phase 4** per plan §6 (burn-in: nightly full corpus,
  fresh-seed fuzz, live-suite parity, ≥4 green nights). Phase 3 runs nothing against live
  Mixpanel. Confirmed.
- **Corpus re-syncs only when the Python side changes.** Named triggers: (1) authored
  vectors / registry entries added by a Phase-3 packet (B0-1 is the known one);
  (2) a recorder/vector bug discovered during replay (Phase-2 Risk-#3 workflow: fix on
  the support branch, re-extract, re-pin, D9 drift check); (3) an R10.7 event — a latent
  Python bug scheduled for a Python-first fix, then regenerate + re-pin; (4) upstream
  `main` merged into the support branch (avoid during Phase 3 unless a fix is needed).
  Every re-sync: re-run the P3-0 vector-count measurement and update the P3-1 table in a
  follow-up commit to this playbook.
- **Standing TS CI posture**: `npm run check` on every commit; conformance run at every
  gate; batch-status prefix-coverage test keeps the flip table total.

## P3-8 Risk register (top 8) · discrepancy log · escalations

### Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | **B4 decomposition drift**: splitting the 8.9k-LOC client across 6 shards invites re-implemented internals (the exact failure R10.8 exists to stop) | B0 lands first and exports by name; review checklist item: grep shards for local reimplementations of `_handle_response`/backoff/URL building; gate diff verifies all 183 api-index names bound exactly once |
| 2 | **Binding dishonesty**: bindings that re-implement the transform or assemble requests themselves would pass vectors while the library diverges (ScanCode mode) | P3-5 rule 3 (ALL bindings, pure/builder included); arbiter check per module; bindings are rig code = fable-only, enforced structurally by the P3-2 (b′) fable binding task for volume-tier batches |
| 3 | **Volume-tier assertion weakening at B6 volume** (158 members, 16 test files) | Fable review pair with mandatory R10.2 diff per file; escalation rule; delegation-equivalence PBT is tier-independent |
| 4 | **429/backoff nondeterminism** breaking vector replay or flaky Layer-3 timing tests | Injected `sleep`/`random`/`now` seams (P3-5 §2); Layer-3 uses Vitest fake timers; no real timers anywhere in tests |
| 5 | **Unicode-DB skew** (V8 Unicode 17 vs pinned CPython 16 tables) in the new digit/whitespace tables | Pinned generated tables + caveat headers + regeneration scripts (TS-2 precedent); oracle fuzz biases the affected ranges |
| 6 | **Facade-growth merge conflicts** (`workspace.ts` touched by S1–S3 then W1–W7) | S2 creates the skeleton first; B6 shards each own disjoint member blocks; gate task is the single integrator |
| 7 | **Auth has no second oracle** (B7–B9) and only 21 vectors | Doubled review (P3-3), full Layer-3 translation of all listed auth test files, Phase-4 live auth scenarios; PKCE RFC test vectors runtime-independent |
| 8 | **Flip-table drift**: a forgotten or premature batch-status flip silently converts stragglers to skips (or floods FAIL) | Flip only in gate commits; UNPORTED-delta assertion against the P3-1 table at every gate; prefix-coverage unit test |

### Discrepancy log

1. **R2.5 says "no jitter" but Python jitters the backoff fallback**
   (`_calculate_backoff`, `api_client.py:680`: `+ uniform(0, delay*0.1)`); the header
   path is the unjittered one. Resolution: port source truth (jitter on fallback via an
   injectable RNG; none on Retry-After). Propose rulebook amendment to R2.5 wording at
   the next amendment pass. Not observable in vectors (sleep durations aren't recorded).
2. **`batch-status.ts` doc comment** bins `user_builders.`/`expressions.`/`transforms.`
   under "B2" — plan Appendix B and this playbook assign them to **B3** (tiering: the
   escaping-risk modules belong on opus). Prefix table entries are batch-agnostic;
   comment corrected at the B3 gate flip.
3. **Tiering policy calls B6 "205 members"** — 205 is the full Workspace surface; the
   api-map `batch` field says B4=3, B5=44, B6=158. Sizing in P3-6 uses the measured 158.
4. **Plan Appendix B row "B0 ~1,000 LOC"** — measured B0 scope (compat additions +
   client internals incl. `app_request`) is smaller in file count but touches both repos;
   no scope change, noted for effort estimation only.
5. **Appendix B puts `me.py` nowhere explicitly** — this playbook splits it: pure
   selection logic → B4-C1; on-disk MeCache → B8-N2.
6. **Retry-After beyond 2^53−1 reads as ABSENT in TS** (B0 arbiter blessing,
   `b0-review-resolution.md` F2, 2026-08-15): `parseRetryAfter` maps `pythonInt`'s
   `PY_INT_UNSAFE_INTEGER` to null where CPython parses the raw big int (Python: sleep
   `min(x, 60)` unjittered + raw huge int in `RateLimitError.retry_after`; TS: jittered
   exponential fallback + `retry_after: null`). Sanctioned deviation — the R4.5 2^53
   policy leaves TS no faithful numeric representation, the 60s cap makes the sleep
   path behaviorally inert (and unobservable in vectors), and no corpus vector or
   Layer-3 assert exercises such a header. NOTE the P3-4 B0-1 packet justification
   "no B0 consumer can produce one legitimately" is INCORRECT for attacker-controlled
   headers — this entry supersedes it. Re-examine only if Phase-4 burn-in ever sees a
   live >2^53 Retry-After. (The B0-1 fix F1 — `parseLossless` `pythonConstants` for
   json.loads' `NaN`/`Infinity`/`-Infinity` at the wire body-parse sites — is a FIX,
   not a deviation; recorded in the same resolution.)
7. **`safeInt` on a numeric string beyond 2^53−1 returns `default_` in TS** (B2-HK
   spot-review blessing, 2026-08-15, remediation commit `3c07d4e`): Python
   `types._safe_int` (`types.py:10548-10583`) returns the exact big int via `int(str)`;
   TS `safeInt` (`results/query-engine.ts`) maps `pythonInt`'s `PY_INT_UNSAFE_INTEGER`
   to the default through the guarded catch. Sanctioned deviation per R4.5 — no
   faithful TS number exists; throwing would break `_safe_int`'s total-function
   contract (Python never raises there); the pre-fix `parseInt` path returned an
   IMPRECISE number (strictly worse); consumers are flows-API `totalCount` fields,
   where a >2^53 count is not producible by real responses; not vector- or
   fuzz-observable (no oracle family drives `_safe_int`/`from_response`). Re-examine
   only if Phase-4 burn-in ever sees such a count. Verified against live CPython
   (B2-HK probe record, `context/phase3/notes/B2-HK-notes.md`).
8. **Out-of-annotation scalars: CPython raises, TS returns** (B2 arbiter class ruling,
   `b2-review-resolution.md` F2, 2026-08-15). Inputs that violate a validator's declared
   parameter annotation (`last="30"` for `last: int`; `params=5.0` for `dict[str, Any]`;
   a str element in `segment_by: list[int]`; `workers=None`; 15 oracle-confirmed sites
   across all three B2 shards) make CPython raise TypeError/AttributeError at guard-free
   comparison/`.strip()`/`len()` sites, while the TS port — whose compile-time types
   reject those inputs outright — returns normally (sometimes with codes Python never
   reaches). **Sanctioned as a CLASS with the boundary at the annotation**: the port's
   behavioral contract covers exactly the in-annotation domain (including every value
   inside `dict[str, Any]`/`Any` interiors — which is why the requireHashable R10.7
   raise-emulation stands: those sites are IN-annotation); out-of-annotation behavior is
   unspecified and the fuzz domains are annotation-constrained by construction
   (documented in `conformance/differential/strategies.py` §B2 domain notes, superseding
   the earlier lone `workers=None` mention). Rationale: emulating CPython's comparison
   TypeErrors would require an unbounded Python-type-model layer with zero benefit to TS
   consumers (the compiler already polices these), and Python library users keep Python's
   raises. Re-examine only if a B5-facade path is found that forwards out-of-annotation
   values across the language boundary at runtime.
9. **S4 warning emission order flips for integer-like unknown chart-type keys** (B2
   arbiter blessing, `b2-review-resolution.md` F4, 2026-08-15). JS objects order
   integer-like keys first, so `validate_sorting_block({"zzz": {}, "1": {}})` emits the
   two S4 warnings in reversed order vs Python's insertion order. Sanctioned deviation:
   plain JS objects CANNOT hold integer-like keys in insertion order (the loss happens at
   object construction for library consumers and at `JSON.parse` for the rig — a code fix
   would require an ordered-map value domain end-to-end). Emission order stays contract
   everywhere else; integer-like unknown chart keys are excluded from the sorting fuzz
   domain (documented omission). The `{path, code, severity}` triples are order-flipped
   only — no code/path/severity difference. Re-examine only if a real consumer workflow
   is found to depend on S4 ordering across integer-like keys.
10. **`extra_forbidden` emission order flips for integer-like unknown keys on
    `extra="forbid"` bookmark-schema models** (B3 arbiter ruling on escalation K1-D1,
    `b3-review-resolution.md`, 2026-08-15; disclosed at `throwaway/b3-k1/RUN.md` §6 and
    `B3-K1-notes.md` §6). Same JS-engine mechanism as Discrepancy #9 at a NEW site:
    `JSON.parse`/object construction hoists array-index-like keys, so a params dict with
    ≥2 unknown top-level keys mixing integer-like and non-integer-like spellings emits
    `extra_forbidden` in JS object order instead of Python insertion order (py `2,b,1` →
    ts `1,2,b`; `{path, code, severity}` CONTENT identical, order only; the validator
    cannot recover the order — it is destroyed at decode time). Recorded as a **standing
    disclosed divergence** rather than an extension of #9's order-insensitive comparison
    (Caution #17 forbids extending #9; per the #9 precedent a comparison relaxation
    would need a user ratification — offered to the user as an optional follow-up, not
    required, since the exclusion approach changes no comparison logic). Integer-like
    unknown keys stay excluded from the `bookmark_schema_family` fuzz domain — now a
    documented omission at the strategy site (`strategies.py::_b3_schema_calls`, the
    #9-comment pattern) so the gate's fresh-seed regression cannot draw them.
    Reachability: zero corpus vectors carry a `bookmark_schema.*` api; the sole planned
    consumer (B6-W3 `_validate_bookmark_params_schema`) surfaces warning lists whose
    cross-key order no caller is known to depend on. Re-examine if a real consumer
    workflow is found to depend on `extra_forbidden` ordering across integer-like keys,
    or at the B6-W3 review.
11. **CPython raises `OSError` (errno 84) across most of the above-`datetime.max`
    timestamp span; the TS twin raises `ValueError`** (B3 arbiter promotion of the K3
    code-comment disclosure, per fidelity review F2, 2026-08-15). Measured boundary
    (macOS, CPython 3.14.6, arbiter-reproduced bisect): OSError for ALL
    `t >= 67,768,036,191,676,800` (~6.78e16 — the `gmtime` `tm_year > INT_MAX`
    overflow) and `t <= -67,768,040,609,740,801`, up to the ±2^63 OverflowError bound —
    five orders of magnitude, NOT the "narrow band" the original disclosure claimed
    (comment corrected in `transforms.ts` and `B3-K3-notes.md` §5 by the arbiter).
    Sanctioned class-level deviation of the #6/#7 kind: every affected input RAISES on
    both sides (class-only divergence, no wrong success); year > 2.1 billion is
    unreachable from any real Mixpanel export; the boundary is platform-dependent
    (`gmtime`), so matching it byte-exactly would pin platform trivia; the fuzz domain
    caps `|time| <= 1e12` (documented omission, packet-authorized "exclude |t| beyond
    datetime.max"). Re-examine only if Phase-4 burn-in ever sees a live timestamp in
    the band or the port targets a platform with a different `gmtime` overflow
    boundary.

### Escalations

None. All open questions encountered during design were resolvable inside existing
rules (the two rulebook frictions above are logged as proposed amendments, not blockers).
