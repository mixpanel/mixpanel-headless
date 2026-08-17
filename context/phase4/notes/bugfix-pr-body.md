# PR body — R10.7 four-bug Python-first fix batch

**Suggested title**: `fix: R10.7 four-bug batch — frequency-filter clause shape, dataGroupId threading, 403-sniff TypeError, OAuth token-payload redaction (single corpus re-pin 70c904dc → 700db996)`

**Branch**: `ts-port/python-bugfix-batch` → base `ts-port/phase2-contract-support`

> **STACKED PR — merge order matters.** This branch is stacked on
> `ts-port/phase2-contract-support` (PR #207) and must merge AFTER it.
> The TS twin retirements live on `mixpanel-headless-ts` `main`
> (commits `2b72ce1`, `b7152da`, `da68958`); push sequencing note: publish this
> branch before or together with TS main so the TS corpus pin `700db996` never
> dangles (ARB-A R2).

---

## What this is

The post-Phase-3 maintenance batch executing the entire R10.7 Python-first fix
queue (`context/phase4/inbound-ledger.md` row 2) as ONE batch with ONE corpus
re-pin event, per playbook P3-7 trigger 3. Four bugs that the TS port had been
carrying as disclosed bug-compat twins are fixed in Python (strict red-first
TDD), the conformance corpus is re-extracted and re-pinned, and the TS twins
retired in the same change that flips tests/vectors — never a window with two
live behaviors. Both referees now run **fully clean** for the first time: the
two standing deep-oracle REJECTs and the pinned ajv dataGroupId disclosure set
are retired (pins deleted, no allowlists kept).

## Bug (a) — frequency-filter clause shape

Fix-of-record: `context/phase1/addendum/frequency-filter-probe.md` +
`context/phase1/bug-reports/mixpanel-headless-frequency-filter-clause-shape.md`.

`build_frequency_filter_entry` emitted a non-platform clause shape (nested
frequency object) that the analytics deep validator rejected — the 2 standing
referee-(b) deep REJECTs, true positives disclosed since Phase 1. It now emits
the platform-native clause: top-level `filterType`/`filterOperator`/`filterValue`
with `$frequency` under `behavior.behaviorType`, event filters in
`behavior.filters`, label in top-level `value`, `dateRange` in the validated
`{type, unit, window}` spelling. Derivation corroborated against three
read-only analytics oracles (fixtures, deep validator, production migration).
Commit: `bddc576` (FIX-1). Red run: 14 failed / 1 passed before the fix.

## Bug (b) — dataGroupId int-vs-string threading

Fix-of-record: `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`.

`data_group_id` threaded as `int` into bookmark payloads at BOTH sites the
report names, plus the interior cohort entry: clause-level
`GroupClause.dataGroupId` (contract: `string | null`), interior cohort-entry
`data_group_id`, and the sections level — where the correct key is
`globalDataGroupId: string` (the old `sections.dataGroupId` int spelling is not
in the contract at all; `additionalProperties: false`). Parameters stay
`int | None`; emission coerces `str(...)`. This retires the pinned
expected-and-disclosed ajv REJECT set (5 pins: 4 clause-level + 1 sections).
Commit: `bddc576` (FIX-1). Red run: 9 failed / 7 passed before the fix.

## Bug (c) — `_handle_response` 403 TypeError

Fix-of-record: `context/phase3/bug-reports/python-handle-response-403-typeerror.md`.

The 403 sensitive-data sniff crashed with an uncoded `TypeError` on truthy
non-dict/non-str JSON bodies (`42`, `1.5`, `true`) and used element-membership
on list bodies. Now uniform substring semantics over
`str | "" | json.dumps(body)` — truthy scalars map to the coded `QueryError`
permission path, list bodies sniff serialized substrings. No error CODE changed
(R5.4). Commit: `57c5e16` (FIX-2). Red run: 4 failed / 5 passed before the fix.

## Bug (d) — OAuth error details carried the full 200 token payload

Fix-of-record: `context/phase3/bug-reports/python-oauth-error-details-token-payload.md`
(= inbound-ledger row 1, escalated at B9 as FB-3).

`_post_token_request`'s missing-required-fields branch embedded the FULL 200
token payload (live `access_token`/`refresh_token`/`id_token` material) into
`OAuthError.details["response_data"]` — an exfiltration channel into
logging/telemetry/browser error reporters, shared by node refresh and browser
exchange (TS twin at core `oauth-http.ts:245`). Fixed in three layers:

- FIX-2 `57c5e16`: token-bearing keys redacted (`<redacted>`), success path
  untouched, error codes untouched.
- ARB-A `20c7d6b` (pair-A arbiter, red-first): non-dict 200 bodies guarded —
  the initial redaction comprehension crashed with an uncoded
  `AttributeError` on non-dict JSON; now mirrors the TS record guard.
- ARB-B `db8a33e` (pair-B arbiter, red-first): leak class closed — allowlist
  redaction (only primitive `token_type`/`expires_in`/`scope`/`error`/
  `error_description` values render; nested/envelope/case-variant/
  `client_secret` shapes all redact), non-JSON 200 bodies never embedded
  (details carry `content_type` + `body_length` only), non-object 200 bodies
  render a fixed placeholder. Non-200 branches (IdP error documents)
  intentionally unchanged and documented.

TS twins retired/hardened same-change: `2b72ce1` + `b7152da` + `da68958`;
browser README / JSDoc caveats rewritten (scrub-before-telemetry advice
retained for non-200 bodies). R10.9 spot-harness through the shipped browser
entry point: 17 checks / 0 failures, node ≡ browser ≡ Python vector
byte-equality on `response_data`.

## The re-pin (single event)

Per the P3-7 trigger-3 choreography (commit `a1d43a5`):

- Corpus re-recorded at pin `700db996cc952e02aa5a23db1f3c68a3e7251b5b`
  (was `70c904dc`). D8/D9 drift accounting CLEAN: 150 bundles stamp-only;
  exactly the 20 disclosed vectors modified (13 bug-(a) + 7 bug-(b));
  11 vectors ADDED by the batch's new tests ((a) +1, (c) +9, (d) +1);
  0 removed, 0 unexplained.
- Totals: **3,251 → 3,262**; prefix deltas exactly `bookmark_builders`
  134→135, `api_client` 810→819, `oauth_flow` 7→8.
- ARB-A/ARB-B hardening produced ZERO vector flips (verified by full corpus
  replays) — the one-re-pin ruling held through both arbiter passes.

## Referee retirement

- **Referee (b)** (bookmark_parser, analytics checkout READ-ONLY): structural
  **314/314 ACCEPT**; deep **125 ACCEPT / 0 REJECT / 189 SKIP_NON_INSIGHTS** —
  the 2 standing frequency-filter deep REJECTs RETIRED; README disclosure
  section rewritten (no expected-REJECT set remains).
- **Referee (a)** (ajv, TS repo): `npm run referee:bookmark` 9/9 green,
  214 fed vectors, **0 REJECT** — the 5 pinned dataGroupId disclosures DELETED
  (no allowlist kept). Any future REJECT on either referee is a NEW finding.
- Fresh gate reports archived: `context/phase4/reports/2026-08-17-bugfix-gate-*`.

## Test plan (all executed at the final HEADs — gate record `context/phase4/notes/bugfix-batch-gate.md`)

- [x] Strict TDD per fix: red runs recorded in `bugfix-batch-notes.md` and both
      arbiter resolutions before each implementation change.
- [x] Python `env -u FORCE_COLOR -u COLORTERM just check` — GREEN (lint,
      fmt-check, typecheck, docstring-cov, test-cov ≥90%, conformance, build).
- [x] Python conformance runner: **3,262 / 3,262 PASS / 0 FAIL** @ 700db996.
- [x] TS `npm run check` — GREEN (typecheck ×5, eslint, prettier, 9,988 tests /
      243 files, browser-bundle smoke).
- [x] TS conformance replay: **3,262 / 3,262 PASS / 0 FAIL / 0 UNPORTED**
      @ 700db996cc95 — same N as Python.
- [x] Differential regression, full 55-family surface: fresh seed 741097477 +
      the complete B9 gate seed set (10 seeds) — 11 seeds × 28,091 examples,
      **0 divergences, 0 skips** (both sides fixed identically; expected
      divergences: none). Raw reports in `conformance/differential/oracle/`.
- [x] Both referees FULLY CLEAN (above).
- [x] Doubled blind review (two pairs + arbiters), zero surviving findings;
      convergence note in `bugfix-reviewB-resolution.md` and the gate record.
- No live API calls anywhere in the batch; `../analytics` used READ-ONLY.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
