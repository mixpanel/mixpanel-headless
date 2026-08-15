# Adversarial review — phase3-playbook.md · Lens: GATES AND VERIFICATION

Reviewer: gates lens · 2026-08-15 · Target: `context/phase3/design/phase3-playbook.md` v1.0
(commit dbb08a7 on `ts-port/phase2-contract-support`). All claims below verified against the
working repos; every finding carries file:line or a reproduced measurement.

## What was verified and held up

- **Vector budget arithmetic (P3-1)**: re-ran the P3-0 provenance command against
  `conformance-runner/corpus` — per-prefix counts match the P3-1 table exactly
  (validation. 512, user_validators. 178, bookmark_builders. 134, segfilter. 51,
  user_builders. 82, expressions. 30, transforms. 2, api_client. 810, pagination. 39,
  workspace. 833, replays. 8, replay_labels. 16, rrweb_analyzer. 2, region_probe. 14,
  oauth_flow. 7; types. 419 + compat. 34 + wirestub. 8 = 461 PASS; total 3,179).
- **B5/B6 workspace split**: joining vector names against api-map `batch` fields gives
  exactly 480 B5 / 353 B6; the six named per-member counts (build_params 143, …,
  query_saved_report 37) are all exact. api-map member totals: B4=3, B5=44, B6=158.
- **B6 sharding sums (P3-6 W1–W7)**: per-section B6 counts in the api-map JSON reproduce
  every W-group subtotal; Σ = 158.
- **`batch-status.ts` semantics**: longest-matching-prefix via `startsWith`
  (`batch-status.ts:84-97`); done-batch straggler → FAIL_ERROR is real (module header
  lines 1-15); the full-corpus prefix-coverage test exists and covers setup apis too
  (`test/batch-status.test.ts:107-140`). Post-B8 flip set covers all 18 corpus prefixes —
  no permanently-UNPORTED families.
- **B0-2 source citations**: every cited `api_client.py` line range is correct on the
  support branch (`_error_message` :81, `_iter_jsonl_lines` :109, `_handle_response` :503,
  `_calculate_backoff` :664 with jitter at :680, `_parse_retry_after` :1159, `app_request`
  :1191, `maybe_scoped_path` :1637, `max_retries=3` :312). Default messages
  ("Permission denied"/"Unknown error"/"Resource not found"/"Request failed"/"Server
  error: ") and the 403 `SESSION_RECORDING_SENSITIVE_DATA` branch (:561-581) all match.
  `wirestub.ts:198` is exactly the `response.json()` line. Test ranges
  `test_api_client.py:444-540/1436-1560/1762-1800/3467-3520` are the 429/Retry-After
  suites as claimed. All cited LOC figures (validation 3,090; accounts 2,028; workspace
  11,292; api_client 8,894; naming 133; region_probe 287; …) are exact.
- **183 `api_client.*` api-index names**: `jq` count = 183. The 6 authored
  `api_client._iter_jsonl_lines` chunk vectors exist; no other api name extends that
  string, so the B0 exact-name flip is collision-free.
- **B1 closure claim**: phase2-audit A1 confirms 274 distinct `__all__` names, 9
  deferrals, owners matching the playbook (`phase2-audit.md:16,47-49,148-155`).
- **Layer-3 file lists**: all spot-checked test files exist (validation suites, bypass
  r2, delegation-equivalence PBT, resolver/region_probe/naming/accounts/session/targets,
  `tests/unit/test_042_edge_cases.py`).
- **[SA1]**: no mutation-testing residue anywhere in the playbook; batch gates use
  `npm run check` / `just check`, neither of which includes mutmut/Stryker.
- **Escalation wiring**: the fable-retry rule is wired into the template (P3-6 failure
  handling) and matches policy rule 2; two-failure abort present.
- **Auth review doubling**: real — P3-3 specifies two independent pairs with information
  isolation (second pair gets only Python source + TS diff) and P3-6 step 3 instantiates
  ×4 reviewers + arbiter for B7/B8/B9 (B8 included, exceeding the plan's B7/B9 ask).
- **GATE-VERDICT R5**: the mandate is present (P3-2(b), B0-2 checklist) and matches the
  source recommendation (`GATE-VERDICT.md` L4-F3/R5 row); the grep is enforceable —
  current `packages/*/src` has zero `JSON.parse`/`response.json()` hits, so the audit
  starts non-vacuous.
- **Discrepancy log**: #2 (batch-status comment bins user_builders/expressions/transforms
  under "B2", `batch-status.ts:37-40`) and #3 (205 vs 158) verified accurate.

## Findings

### F1 (BLOCKER) — Volume-tier module tasks are required to edit `bindings.ts`, violating the fable-only rig rule and the playbook's own Risk-#2 mitigation

P3-2(b) makes every module task "bind the api names in
`conformance-runner/src/bindings.ts`'s registration modules" as part of implement-to-green,
and P3-2(c) requires "oracle-ts gains the module's apis in the same commit via the shared
bindings module." For B2/B5/B6 (sonnet) and B3 (opus) the module task IS the volume tier —
yet the P3-3 table and the tiering policy both say "ANYTHING touching the conformance rig
(bindings.ts, …) — **fable**" ("the judge must be stronger than the judged"), and the
playbook's own Risk #2 mitigation asserts "bindings are rig code = fable-only". The
template never reassigns the binding-registration step to a fable task (the gate task only
flips batch-status; the packet task only writes packets). Consequence: either the loop
stalls (sonnet can't meet its own done-criteria without a rig edit) or — the executed
outcome — sonnet/opus agents write the code that decides PASS/FAIL for their own modules.
A dishonest binding that re-implements the transform (the ScanCode failure mode) makes the
vector gate pass vacuously; the reviewer checklist in P3-2(d) items (1)-(4) has a binding
honesty check only for wire bindings (P3-5 rule 3), not for the pure-module batches where
the volume tiers operate. Fix: carve the bindings/oracle-registration commits out into a
per-module fable sub-task (or fold them into the fable review/arbiter step), and extend the
P3-5.3 honesty check to non-wire bindings.

- Evidence: playbook P3-2(b) lines 230-234, P3-2(c) lines 243-245, P3-3 rig row line 302,
  Risk #2 line 657; `model-tiering-policy.md:25`; policy rule 3.

### F2 (MAJOR) — B5 exact-name flip is not exact: `workspace.list_bookmarks` (B5) prefix-matches `workspace.list_bookmarks_v2` (B6), turning 7 unported B6 vectors into FAIL at the B5 gate

P3-5 §4 claims "`batch-status.ts` longest-prefix matching supports exact names". It does
not — entries match via `api.startsWith(prefix)` (`batch-status.ts:91`), so an "exact
name" also matches every longer name it prefixes. The mechanically generated B5 flip list
(`jq … select(.batch=="B5") | "workspace." + .name`) includes `workspace.list_bookmarks`
(a B5 member with **zero** recorded vectors), which is a string prefix of the B6 member
`workspace.list_bookmarks_v2` — and the corpus carries **7** `workspace.list_bookmarks_v2`
vectors. At the B5 gate, longest-prefix resolution picks the done `workspace.list_bookmarks`
entry (24 chars > `workspace.` 10 chars) for those 7 unbound B6 vectors → FAIL_ERROR. The
gate's own assertions (FAIL = 0; UNPORTED drops by exactly 506) then cannot pass, forcing
mid-gate rig improvisation. Verified exhaustively: this is the only B5-name→other-batch
collision among all 205 members (`events`/`segmentation`/`funnel`/`query`/`sign_replay`/
`fetch_replay` prefix-collide only within B5, which is harmless). Fix: at the B5 gate also
add the exact pending override `workspace.list_bookmarks_v2 → pending` (longest-prefix makes
it win), or generate flip entries only for member names that are not prefixes of any
other member name, and state either rule in P3-5 §4.

- Evidence: `conformance-runner/src/batch-status.ts:84-97`; corpus count
  `workspace.list_bookmarks_v2` = 7, `workspace.list_bookmarks` = 0; api-map batches
  list_bookmarks=B5 / list_bookmarks_v2=B6; playbook P3-5 §4 lines 516-531.

### F3 (MAJOR) — Cross-batch setup dependency breaks the B4 and B6 gate deltas: vector `api_client.resolve_workspace_id` requires setup `workspace.me` (B6)

The runner gates a vector on its measured api AND every `call.setup[]` api
(`runner.ts:368-386`); an unbound setup api yields the setup api's own batch verdict. The
corpus contains exactly one cross-module offender: vector
`auth/api_client.resolve_workspace_id/test_workspace_resolution-…-test_resolves_from_me_cache_without_public_call`
(measured api `api_client.resolve_workspace_id`, setup `workspace.me`). `workspace.me` is
a **B6** member and the facade doesn't exist until B5 creates `workspace.ts`, so at the B4
gate this vector stays UNPORTED (workspace. is pending → no FAIL, correctly), meaning B4's
PASS delta is **842, not 843**, and UNPORTED drops by 842 — the P3-2(e).2 assertion
"PASS grows by exactly the batch's vector count" fails at the B4 gate. The vector then
replays at the B6 gate, making B6's delta **354, not 353**. Both the P3-1 cumulative table
and P3-5's "UNPORTED must drop by exactly the batch's P3-1 vector count" are off by one at
two gates; an executor discovering this mid-gate either hand-edits the expectation (opening
the self-reported-green door the assertion exists to close) or stalls. Fix: footnote the
one vector in P3-1 (B4 expectation 842 + carry-over row at B6 = 354), and add a standing
rule: gate expectations are computed over vectors whose measured AND setup apis are all
owned by flipped batches.

- Evidence: `conformance-runner/src/runner.ts:368-386`; corpus scan: cross-module setups
  are exactly {22× workspace←api_client (benign, B4 lands first), 1× api_client←workspace
  (the offender)}; api-map: `me` → B6; playbook P3-1 table rows B4/B6, P3-2(e).2,
  P3-5 flip rule.

### F4 (MAJOR) — Gate step "verify `oracle.info` lists them" is unimplementable: neither oracle's `info` returns an api list

P3-2(e).3 makes oracle-surface extension a mechanical gate check: "verify `oracle.info`
lists them". But the protocol-1.1 `oracle.info` payload is
`{language, library_version, source_commit, protocol_version}` on BOTH bridges — no api
enumeration exists (`conformance/oracle_py/server.py:274-286`;
`differential/oracle/server.ts:346-354,563-576`). As written the check either gets
silently skipped (the oracle-extension gate criterion becomes a self-reported green —
exactly what the lens forbids) or forces an unscheduled protocol change (rig code, fable,
plus oracle-protocol.md rev). Fix: either (a) replace the check with one that is already
mechanical — issue an `oracle.call` per new api and require a non-`unknown api` response
(oracle-py raises `OracleProtocolError` "unknown api …" for unregistered names,
`server.py:414-418`, and rejects wire entries with `WIRE_OUT_OF_SCOPE`, so callability is
directly probeable) — or (b) schedule a protocol-1.2 `oracle.info.apis` field as a fable
rig task before the first batch gate.

- Evidence: `conformance/oracle_py/server.py:279-286` (info dict, no apis);
  `differential/oracle/server.ts:568-575` (same four fields); playbook P3-2(e).3.

### F5 (MINOR) — `parseLossless` has no library home: B0-2/B4 mandate its use in `packages/core` wire code, but it exists only in the rig, and no packet provisions it

The R5 mandate is present and grep-enforceable (good), and B0-2's `_handle_response` spec
says "parse body first — via `parseLossless`". But `parseLossless` is defined only in
`conformance-runner/src/lossless-json.ts:52`; `packages/core/src` has no lossless parser
(`client/` and `services/` are placeholder `index.ts` files) and no P3-4/P3-6 packet
assigns creating one. The B0-2 builder must improvise: importing from `conformance-runner`
inverts the library→rig dependency direction (the shipping client would depend on the test
rig), while copying the function creates an untested, unvectored duplicate of load-bearing
parse code. Cheap fix, but it should be written down: add a line to Packet B0-2 relocating
(or re-exporting) the lossless parser into `packages/core` with its existing unit tests
moved/duplicated, keeping the rig importing from core (judge-uses-library direction is
fine; the reverse is not).

- Evidence: `conformance-runner/src/lossless-json.ts:52`; `packages/core/src/client/`
  contains only `index.ts`; grep for "lossless" in `packages/*/src` hits only two doc
  comments (`types/vector-codecs.ts:124`, `types/query-params/cohort.ts:118`); playbook
  B0-2 checklist first bullet, P3-2(b).

### F6 (MINOR) — R10.9 harness deleted before anyone else can run it: the RUN record is a self-reported green from the volume tier

P3-2(c): "Throwaway harness code is deleted after the run; the RUN record (counts, seeds,
divergence table) is appended to the batch notes file" — and the harness runs at the
module's tier (sonnet/opus for B2/B3/B5/B6). The fable review pair in step (d) therefore
verifies the fuzz happened only by reading notes the audited agent wrote; with the harness
deleted, seeds are not re-runnable. Compensation exists — the P3-7 gate-time full-suite
differential regression re-fuzzes every oracle-registered api at ≥500/family with fresh
seeds, which would catch most fabricated parity claims for oracle-covered apis — but wire
modules (no oracle surface) get no such backstop: their R10.9 reduces to a
VectorFetch edge-set replay whose evidence is also deleted. Fix: delete the harness only
after arbiter sign-off (review step (d) gains "re-run or spot-check the R10.9 harness"),
or require the harness to live in a `throwaway/` dir in the module commit and be removed
by the gate task.

- Evidence: playbook P3-2(c) final paragraph; P3-3 harness-tier row; rulebook R10.9
  (`typescript-port-rulebook.md:277-281`) mandates the harness but not deletion timing —
  the deletion-before-review sequencing is the playbook's addition.

## Non-findings worth recording

- Corpus pin: `corpus.config.json` `sourceCommit` = `8ae76314…` — the playbook is correct
  against the repo (an orchestrator ground-state note citing a different pin is the stale
  party, not the playbook).
- The "wirestub.ts:198 sole grandfathered exception" wording is technically outside the
  `packages/*/src` grep scope (wirestub lives in `conformance-runner/src`), but the line
  citation is exact and the note is harmless documentation, not a scope hole.
- "Oracle-py already exposes every registry entry point" is accurate as stated: the server
  resolves any registry api and answers wire entries with the `WIRE_OUT_OF_SCOPE` skip
  payload (`oracle_py/server.py:412-428`), matching the playbook's own wire carve-out.
