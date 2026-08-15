# Phase-1 Gate Verdict — TypeScript Port Verification Rig

- Arbiter: independent gate arbiter (consolidated six lens audits; spot-re-verified key claims).
- Date: 2026-08-15.
- Python repo: `ts-port/phase1-verification-rig` @ `63db3b08a69afa3aacdc2cac8da23f9db7d313bc` (base `fix/latent-bugs-stress-test` @ `52696743…`).
- TS repo: `main` @ `8110cea` (no remotes, clean tree).
- Inputs: `audit-python-rig.md`, `audit-smoke.md`, `audit-fidelity.md`, `audit-ts-rig.md`, `audit-oracles-referees.md`, `audit-hygiene.md` (all in this directory).
- Arbiter's own re-runs: full Python corpus (2609/2609 ok), TS conformance CLI (42/0/2561, corpus pinned @ 52696743b913), `ruff check`/`format --check conformance/` clean, `git diff c0eefab..HEAD` empty for `src/`+vectors+runner, justfile/D17 text reads, smoke `last-run.json` parse (PASS, 13/13 caught, control clean), analytics dry-run carve-out grep (read-only), CI conformance-job grep, 13 patch files on disk.

## VERDICT: **GATE_MET_WITH_CONDITIONS**

Every Phase-1 gate criterion in plan §6 is met, and every supporting deliverable is
verified operational by independent re-execution. The conditions are provenance/hygiene,
not capability: the design-of-record chain is partly uncommitted at the gate SHA, and
committing it will move the SHA, which in turn warrants one final full smoke run at the
SHA the gate is actually declared at. No blocker or major finding exists in any of the
six audits; all 23 findings are minor and dispositioned below.

## 1. Per-criterion table (plan §6 Phase-1 gate)

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| G1 | Python passes 100% of corpus | **PASS** | Arbiter re-ran `python -m conformance.runner`: `{"status":"ok","total":2609,"passed":2609,"failed":0}` at HEAD 63db3b0. Independently reproduced by Lens 1 (both harnesses: pytest 2609 passed; CLI ok) and Lens 3 (2609/2609). Totals reconcile: manifest 2,530 extracted + 79 authored = 2,609 (Lens 1 arithmetic verified against jsonl line counts). |
| G2 | Corpus catches every deliberate-break sabotage [SA1] | **PASS** (see condition C2) | Committed `last-run.json`: control clean 0/2609; **13/13 patches caught** (S01:13 … S13:21 failing vectors) — arbiter re-parsed the artifact. Lens 2 re-executed control + S04/S06/S08/S10/S11 at HEAD via the real `run_smoke.py` path: exact reproduction of status, counts, and first_failing_id. Crash-vs-catch discrimination proven empirically (import-break → exit 2 `runner_crashed` → smoke ERROR, never a catch). All 13 patches match the D9.1 table; S10/S11 are held exclusively by the 6 authored gap-fill vectors (necessary and sufficient). Caveat: `last-run.json` pinned to `c0eefab8`, 5 commits behind HEAD — arbiter independently confirmed `git diff c0eefab..HEAD` touches **zero** files under `src/`, `conformance/vectors/`, `conformance/runner/`, so the record is representative; condition C2 closes the provenance gap. |
| G3 | TS runner passes hello-world module — all six D13 criteria | **PASS** | Lens 4 re-executed all six: (1) Python compat filter 42/42; (2) TS compat replay 42/42 (CLI + vitest); (3) canonicalizer selftests both languages (py 61 pass, TS 59 pass, contract file sha-identical); (4) builder sabotage (zfill sign branch) → exactly the GATE.md 5-failure set, reverted clean; (5) 8 wirestub vectors pass through VectorFetch; (6) wire sabotage (param drop + swallowed rejection) → byte-for-byte the GATE.md 3-failure set, reverted clean. Arbiter re-ran the CLI: `42 passed, 0 failed, 2561 unported, 0 failures[]` (UNMAPPED_API would be a failure; array is empty). |

## 2. Supporting Phase-1 deliverables

| # | Deliverable | Verdict | Evidence |
|---|---|---|---|
| S1 | Record plugin + corpus committed and CI-wired | **PASS** | 17 rig commits map 1:1 to D16/D18 plan (Lens 1 §e); arbiter confirmed `.github/workflows/ci.yml` conformance job (mypy conformance/, tooling tests, corpus runner, D8 drift re-extraction with manifest-stamped injection) and `conformance/**` in both `paths:` lists. Drift determinism: Lens 1 re-extracted the full corpus and got **byte-identical** output (diff tool sensitivity proven by a perturbed-byte control). |
| S2 | Oracle bridges: zero-divergence self- and cross-parity | **PASS** | Lens 5 re-executed: compat cross-language fuzz 1,517 examples / **0 divergences** (per-api split identical to RUN.md); full-surface 200/target run 1,466 examples / 0 divergences; UNPORTED verified as skip-never-pass in code and empirically; R5.4 message-strip verified in `canonical.py`. |
| S3 | All three referee harnesses operational | **PASS** | Lens 5 re-executed: (a) TS Ajv2020 bookmark referee 7/7 + vendored `bookmark.json` sha256 matches live analytics file today; (b) structural batch 314/314 ACCEPT byte-identical to committed artifact, selftest controls 3/3 non-vacuous; (c) deep voluptuous batch 123 ACCEPT / 2 REJECT / 189 SKIP reproduced (exit-1 contract honored). The 2 REJECTs are the triaged frequency-filter finding (§5). Coverage-weight caveat on modern-funnels payloads recorded (L5-F2, recommendation R6). |
| S4 | Repo standards green in both repos | **PASS** | Python: Lens 1 ran full `just check` → PASS (all seven recipes); mypy --strict covers conformance/; arbiter confirmed `docstring-cov` **does** include `interrogate conformance/ --fail-under=95` (justfile:173, landed in PR-1 4f885f4 — Lens 1 finding F1 is REFUTED, see §3) and ruff over conformance/ is clean (45/45). TS: `npm run check` exit 0 (typecheck, eslint incl. re-probed R9.1 core-purity boundary, prettier, vitest 383 pass/2561 skip, browser-bundle smoke); tsconfig R1.1 flags all present; zero StrykerJS anywhere [SA1]; lossless-number loader verified real. |
| S5 | No pushes / publishes | **PASS** | Lens 6: rig branch has no upstream, 17 commits local-only, `ls-remote` shows no ts-port/phase1/conformance remote heads, no PRs from the rig branch; TS repo has **zero remotes**. PR #206 carries exactly the pinned base 5269674 (zero rig content) and is sanctioned by D16. |
| S6 | analytics untouched | **PASS** | Lens 6: `git status --porcelain` in /Users/jaredmcfarland/Developer/analytics empty (tracked + untracked), no stashes, branch at upstream commit. Arbiter's own reads of analytics were read-only greps. |
| S7 | ~/.mp hygiene / whitelist compliance | **PASS** | Lens 6: test accounts deleted, only pre-existing real accounts remain; out-of-scope file changes confined to `justfile`, `pyproject.toml`, `ci.yml`, `uv.lock` (mechanical, additions-only fallout of the two permitted dev deps + typed stubs — accepted, see D-H3). |

## 3. Audit-report correction (arbiter finding)

**Lens 1 finding F1 is factually wrong and is REFUTED.** It claims `just docstring-cov`
"contains only the src/ and tests/ invocations (lines 170-172)". The tracked justfile at
HEAD contains the D17.3-required third line at line 173
(`uv run interrogate conformance/ --fail-under=95`), added in PR-1 commit `4f885f4`
(verified via `git log -L170,174:justfile` and `git log -S`). Lens 6's contrary claim
(§d, "docstring-cov gains interrogate conformance/") is correct. No gate impact either
way (Lens 1 itself measured conformance/ at 100% docstring coverage), but the
contradiction between two audits was resolved by direct inspection, in Lens 6's favor.
Lens 1's F2 (lint/fmt-check path-scoped to `src/ tests/`, contradicting D17.2's
"whole tree" rationale) **is confirmed** by arbiter inspection of justfile:148-161.

## 4. Vector-count shortfall and the approved addendum (REPORTED SHORTFALL — not a gate criterion)

Committed corpus: **2,530 extracted + 79 authored = 2,609** vs the 3,000 target →
gap **391**. (The task-brief figures "2,536 + 73" are the stale EXTRACTION-LEDGER
headline numbers — see disposition D-L1F3; `manifest.json` is authoritative and the
ledger itself says so.)

Assessment of the approved addendum (escalation-resolutions.md E1 + E2, both ruled
2026-08-14; arbiter read the rulings and the underlying design text):

- **E2 — uncoded-ValueError coding pass** (~130 uncoded builder guard sites → real
  registry codes, Python-side, before Phase 2): directly recovers the 14
  `uncoded_raise`-excluded tests as `validation-error` vectors, and — the dominant
  term — the strict-TDD coding pass necessarily adds new recordable tests per site.
  At the corpus's observed density (existing validation vectors run ≈2–5 per guard
  site), ~130 sites plausibly yield **260–390** new vectors on re-extraction.
- **E1 — storybook harvest** (81 files from `iron/.storybook/mocks/api/`, scrubbed +
  re-keyed, 9 wrappers unwrapped): yields approximately **81** authored parse-kind
  vectors.

**Conclusion: the addendum plausibly closes the 391-vector gap** (plausible combined
yield ≈340–470), but closure is **contingent on E2 test density** — the deterministic
floor (14 recovered exclusions + 81 storybook files ≈ 95) does not close it alone.
Recommendation R1 asks the addendum workflow to set an explicit per-site vector-yield
expectation and re-baseline the count after re-extraction. Since 3,000 is a target and
not a gate criterion, a residual miss after the addendum would need documenting, not
gating.

## 5. Frequency-filter deep-oracle finding — classification (per Lens-5 triage)

**Classification: verdict (ii) — validator stricter than current live enforcement —
with a real, recorded future-compatibility risk. NOT a gate blocker. Escalation stays
OPEN.**

Arbiter endorses the Lens-5 triage after spot-verifying the decisive evidence
(read-only): `analytics/api/version_2_0/insights/params.py` carries the
"dry-run insights bookmark require keys" carve-out at line ~2970 for
"required key not provided" errors, and the same "TODO remove try-except" pattern
appears at both bookmark-save call sites in
`webapp/app_api/projects/bookmarks/views.py` (2 occurrences) — so the exact error the
deep oracle raises on the library's `build_frequency_filter_entry` payloads is today
logged-and-ignored at every server ingestion gate. The REJECT is correctly produced by
the harness (no routing error); the payloads are genuine insights payloads.

Binding dispositions:
1. The **structural referee remains the binding referee** for this clause type; the deep
   oracle's REJECT on these 2 payloads does not fail the gate (exit-1 is the designed
   signal, disclosed in the committed artifact and GATE record).
2. Per R10.7, the shape divergence (library's `customProperty`-nested clause vs the
   platform-native top-level `filterType`/`filterOperator` form in analytics' own
   fixtures) is a REPORTED potential latent Python issue — **not fixed in Phase 1**.
3. Per R2.x, the **TS port must replicate the Python shape byte-for-byte** until the
   escalation is settled.
4. Settlement path: a wire-level probe (does the query engine interpret or silently
   ignore the nested form?) — queued, not blocking (recommendation R7).

## 6. Findings disposition

No audit reported any blocker or major finding; all 23 are minor. Disposition of every
one (RF = required fix, ACC = accepted with reason, REC = recommendation, REF = refuted,
DUP = duplicate):

| ID | Finding (abbrev) | Disposition |
|---|---|---|
| L1-F1 | docstring-cov missing conformance line | **REF** — line exists at justfile:173 since PR-1 (§3). No action. |
| L1-F2 | `just lint`/`fmt-check` scoped to src/tests, contradicting D17.2 rationale | **ACC** (present state clean: arbiter re-ran ruff check + format --check on conformance/, all green; pre-commit per-file hooks cover commit time) + **REC R8** (add conformance/ to the recipes; amend D17.2 wording). |
| L1-F3 | EXTRACTION-LEDGER headline counts stale vs manifest (2,536/19 vs 2,530/25; true shortfall 470 extracted-only) | **ACC** (ledger carries "manifest.json is authoritative" disclaimer; delta fully documented in commit 9961fbb) + **REC R1** (refresh during addendum re-extraction). |
| L1-F4 / L2-F4 / L6-H4 | Uncommitted +9-line rulebook edit (R10.13) on a tracked file | **RF-1** — commit or deliberately discard before Phase 2. |
| L2-F1 | `last-run.json` pinned 5 commits behind gate HEAD | **RF-2** (run one full 13-patch smoke at the final gate SHA — which moves anyway due to RF-1 — and commit the record). Risk today is nil: arbiter confirmed zero src/vectors/runner delta since c0eefab, and Lens 2 reproduced control+5 patches at HEAD exactly. |
| L2-F2 | In-vector harness exceptions classify as catches | **ACC** (correct semantics for src-only sabotage; clean control mitigates; all 13 patches' sampled reasons are genuine behavioral diffs) + **REC R9** (smoke flags all-infrastructure-reason runs for manual review). |
| L2-F3 | Two non-smoke worktrees present (pr195, audit-sabotage) | **ACC** (neither is rig debris; pr195 pre-existing developer worktree, audit-sabotage is Lens 1's declared scratch) + **REC R10** (remove audit scratch worktree + /tmp residue post-gate). |
| L3-F1 | Pin-lifecycle vectors lose pinned-workspace precondition (2 vectors non-discriminating) | **ACC for the gate** (encoding correct for what it captures; contract covered at Layer 3 when test_query_workspace_scoping.py is ported) + **REC R2** (emit pre-setup session or `set_workspace_id` setup entry during addendum re-extraction, or add explicit ledger deferral). |
| L3-F2 | Credential-redaction message assertions structurally dropped (D6 rule 6) | **ACC for the gate** (documented global rule; Layer-3 tests will carry the assertion) + **REC R3** (`message_not_contains` field or explicit ledger note for the redaction family — do in addendum). |
| L4-F1 | TS corpus snapshot 6 vectors behind (2,603 vs 2,609) | **ACC** (GATE.md discloses; gate needs only compat vectors, which are present and pass) + **REC R4** (re-sync after the addendum re-extraction, before first Phase-3 batch — one sync covers both this and the addendum vectors). |
| L4-F2 | TS commit order deviates from D16 numbering; 3 unplanned well-scoped commits | **ACC** — granularity/reviewability preserved; informational ledger entry only. |
| L4-F3 | wirestub.ts uses lossy `response.json()` | **ACC for the gate** (test double only; gate vectors avoid the distinguishing bodies) + **REC R5** (mandatory line in Phase-3 wire-batch instructions: response bodies flow through the lossless parse path). |
| L5-F1 | Deep-oracle REJECT message nondeterministic across runs | **ACC** (D15b comparison is verdict-level by design; verdicts/ids/counts identical) + **REC R11** (normalize recorded error before committing artifacts). |
| L5-F2 | Structural 314/314 near-vacuous for modern-dialect payloads; 88 modern funnels have almost no oracle coverage | **ACC** (asset limitation, not a routing error; routing verified sound; insights side covered by deep oracle + TS referee) + **REC R6** (document in referee README; treat modern-funnels oracle coverage as a Phase-2+ gap). |
| L5-F3 | Frequency-filter triage | **Dispositioned in §5** — verdict (ii), escalation open, structural binding, TS byte-for-byte, wire probe queued (REC R7). |
| L6-H1 | escalation-resolutions.md / pr6-notes.md / bug-reports/ untracked | **RF-1** — these are binding design-of-record and the sole deviation trail (KeepOrderDict, TS-loader order obligation); must be SHA-pinned before Phase 2 branches off the rig branch (E2 sequencing bases the coding pass on it). |
| L6-H2 | phase1-design.md D3 sorted-keys text stale vs KeepOrderDict | **REC R12** (amendment note in D3 or escalation-resolutions.md; deviation itself is fully documented in commit 4eb0b9f and drift-enforced). |
| L6-H3 | uv.lock outside literal D17 whitelist | **ACC** — verified mechanical, additions-only fallout of the permitted dev deps; acknowledge in whitelist wording (part of R12). |
| L6-H5 | conformance/schema/vector.schema.json diverged (4 additive, $comment-documented) from design-dir copy | **REC R12** (declare conformance/schema the operative source of truth in the design doc). |
| L6-H6 | /tmp build residue | **REC R10** (cleanup list in audit-hygiene.md §e). |

## 7. Required fixes (conditions — before Phase 2 kicks off)

1. **RF-1 — Pin the design-of-record chain.** On `ts-port/phase1-verification-rig`,
   commit `context/phase1/design/escalation-resolutions.md`,
   `context/phase1/pr6-notes.md`, `context/phase1/bug-reports/`, and the
   `context/typescript-port-rulebook.md` R10.13 amendment (or deliberately discard the
   latter with a recorded reason). Binding rulings and the KeepOrderDict/TS-loader
   deviation trail must not live only in a working tree that Phase-2 branches from.
2. **RF-2 — Re-declare smoke provenance at the final gate SHA.** After RF-1 moves HEAD,
   run one full 13-patch `run_smoke.py` at that SHA and commit the refreshed
   `last-run.json` (generated artifact, separate commit per D16). Expected outcome:
   identical to the current record (arbiter verified zero behavioral delta since
   c0eefab), so this is provenance alignment per D9.3's release-gate wording, not
   re-validation risk.

Neither fix touches library code, vectors, or the TS repo; both are hours, not days.

## 8. Recommendations (for the addendum workflow and Phase 2/3 setup)

- **R1** — Addendum: set an explicit per-site vector-yield expectation for the E2 coding
  pass (≥2 recordable tests/site keeps 3,000 in reach); after re-extraction, refresh
  EXTRACTION-LEDGER.md headline counts from the new manifest and re-baseline the target
  check. If still short of 3,000, document the residual — it is a target, not a gate.
- **R2** — Addendum re-extraction: emit the pre-setup session (or a `set_workspace_id`
  setup entry) for tests whose client session mutates before the measured call
  (pin-lifecycle family), or ledger-defer the pin-clear contract to Layer 3 explicitly.
- **R3** — Addendum: add a `message_not_contains` assertion field (schema + both
  runners) for the credential-redaction test family, or an explicit ledger entry
  stating these contracts are Layer-3-only.
- **R4** — After the addendum re-extraction: `scripts/sync-corpus.sh` + commit a
  refreshed TS snapshot before the first Phase-3 batch (covers today's 6-vector lag and
  all addendum vectors in one sync).
- **R5** — Phase-3 wire-batch instructions must state: response bodies flow through the
  lossless parse path, never bare `JSON.parse`/`response.json()` (wirestub.ts:198 is a
  test-double-only exception).
- **R6** — Referee README: document that structural ACCEPT is near-vacuous for
  modern-dialect payloads and that the 88 modern funnel payloads currently have minimal
  oracle coverage; track a modern-funnels contract (vendored sections schema or wire
  probes) as a Phase-2+ oracle gap.
- **R7** — Queue the wire-level probe that settles the frequency-filter escalation
  (does the query engine interpret the `customProperty`-nested clause?). Until then, TS
  replicates the Python shape byte-for-byte.
- **R8** — Add `conformance/` to the justfile `lint`/`lint-fix`/`fmt`/`fmt-check`
  recipe paths; amend D17.2's wording to match reality.
- **R9** — Smoke script: flag any caught run whose failure reasons are ALL
  "replay infrastructure error inside vector" for manual review.
- **R10** — Post-gate cleanup: remove `/private/tmp/audit-sabotage` worktree
  registration and the /tmp build residue listed in audit-hygiene.md §e.
- **R11** — Normalize the deep-oracle recorded REJECT error (all missing required keys,
  sorted, or path-only) before committing/diffing deep-run artifacts.
- **R12** — Design-doc housekeeping in one commit: D3 KeepOrderDict amendment note,
  D17 whitelist wording (uv.lock, lint-scope reality), and a line declaring
  `conformance/schema/vector.schema.json` the operative schema of record.

## 9. Bottom line

The rig does what Phase 1 demanded: a 2,609-vector corpus that Python passes 100%,
provably non-tautological (live sabotage flips 37/67 segmentation vectors red), byte-
deterministic under re-extraction, catching 13/13 deliberate breaks with crash-vs-catch
discrimination proven; a TS runner that passes all six D13 hello-world criteria with
both sabotage probes reproducing the recorded failure sets byte-for-byte; zero-divergence
oracle bridges; three operational referees with an honestly triaged open finding; and
clean process hygiene (nothing pushed, analytics untouched). Complete RF-1 and RF-2,
then fan-out (Phase 2 via the E2 coding pass first, per the binding ruling) may begin.
