# ARB-A — Pair A arbiter resolution (fidelity + repin reviews)

Date: 2026-08-17. Arbiter for review pair A of the R10.7 four-bug Python-first
maintenance batch. Inputs: `bugfix-reviewA-fidelity.md` (1 major F1, 2 minor
F2/F3), `bugfix-reviewA-repin.md` (2 minor R1/R2). Every claim re-verified
independently at source/history level before action.

## Verdict table

| ID | Reviewer | Severity | Claim (short) | Verdict | Action |
|----|----------|----------|---------------|---------|--------|
| F1 | fidelity | major | flow.py redaction crashes uncoded AttributeError on non-dict 200 token body; TS guards with isPlainRecord (shipped divergence) | CONFIRMED | APPLIED (red-first, both repos — see below) |
| F2 | fidelity | minor | dataGroupId `globalDataGroupId:string` spelling live-unconfirmed (fix-of-record's live probe skipped per batch no-live-calls rule) | CONFIRMED | NO CHANGE (skip was correct); Phase-4 burn-in item carried forward — HUMAN-CALL below |
| F3 | fidelity | minor | TS main carries out-of-batch docs commit a382687 in the reviewed window | CONFIRMED | NO CHANGE; orchestrator ledger note only |
| R1 | repin | minor | batch-status.ts TERMINAL STATE comment still reads "3,251 / pin 70c904dc" post re-pin | CONFIRMED | APPLIED (dated ADDENDUM appended to the header comment; comment-only) |
| R2 | repin | minor | new pin 700db996 dangles remotely until the Python work branch is pushed | CONFIRMED | NO CHANGE; orchestrator push-sequencing note below |

## F1 — verification and applied fix (the one major)

Independent verification (not taken from the reviewer's notes):
- Source: `src/mixpanel_headless/_internal/auth/flow.py` `_post_token_request`
  iterated `data.items()` unguarded; `data` comes from `response.json()` whose
  runtime range is any JSON value (the `dict[str, object]` annotation is
  aspirational — same annotation-lie class as bug (c)). TS twin
  `packages/core/src/auth/oauth-http.ts` `postTokenRequest` guards with
  `isPlainRecord` and raises the coded OAuthError; its comment explicitly
  admitted the divergence.
- Red run (recorded): new
  `TestTokenPayloadRedaction::test_exchange_non_dict_200_body_raises_oauth_error[list]`
  failed pre-fix with `AttributeError: 'list' object has no attribute 'items'`
  at `flow.py:625`, raised while handling the `TypeError` from
  `from_token_response` (token.py:138) — exactly the reviewer's reproduction.
  Pre-batch behavior for the same inputs was OAuthError, so this was a genuine
  crash regression introduced by the bug-(d) fix, and a live cross-language
  divergence contradicting R10.7 flip discipline.

Applied (Python-first, red-first, reviewer's suggested one-liner):
- `flow.py`: redaction comprehension wrapped in
  `... if isinstance(data, dict) else data`, mirroring the TS `isPlainRecord`
  branch exactly (a non-dict body has no token-bearing keys → renders as-is,
  `str(data)`, byte-matching TS `pythonStr(data)`); comment updated.
- `tests/unit/test_auth_flow.py`: red-first tests added to
  `TestTokenPayloadRedaction` —
  `test_exchange_non_dict_200_body_raises_oauth_error` parametrized over
  `[1, 2]` / `"hello"` / `42` / `null` bodies (code `OAUTH_TOKEN_ERROR`,
  `details["response_data"] == str(body)`), and
  `test_refresh_non_dict_200_body_raises_oauth_error` (shared
  `_post_token_request` edge on `OAUTH_REFRESH_ERROR`). Codes-not-messages
  per R5.4. Red verified, then green post-guard (48/48 in the file).
- TS mirror locks (no behavior change — TS was already correct, so no red run
  is possible there; these are convergence locks): same two members added to
  `packages/node/test/oauth-flow-login.test.ts` (it.each, 4 bodies) and
  `packages/node/test/oauth-flow-refresh.test.ts`, asserting the identical
  codes and byte-identical `response_data` strings ("[1, 2]", "hello", "42",
  "None") — this cross-validates `str()` ≡ `pythonStr()` on the edge.
  48/48 green across both files.
- TS `oauth-http.ts` divergence comment truthed up: Python now mirrors the
  record guard (ARB-A F1); the "Python has no such branch" parenthetical is
  gone.

Ripple checks:
- Python conformance runner over the pinned corpus: 3,262/3,262 PASS after the
  guard — zero vector flips (no corpus vector covers the edge, as the fidelity
  review established), so NO second re-pin event is needed and none was
  performed (the batch ruling is ONE re-pin event; pin stays 700db996).
- Corpus-locking the edge: the new refresh-path test is written seam-style
  (MockTransport 200 with JSON body), i.e. extraction-recordable; the exchange
  members will land in the `raw_transport_no_entrypoint` exclusion bucket like
  their 3 sibling members. Both get captured automatically at the NEXT re-pin
  event — carried as a follow-up note, not forced now.
- Full gates: Python `env -u FORCE_COLOR -u COLORTERM just check` and TS
  `npm run check` — results recorded in the gate section below / final report.

## F2 — dataGroupId spelling evidence base (minor, no change)

Verified: fix-of-record `mixpanel-headless-datagroupid-int-clause.md` line 59
does instruct "probe the live App API first to confirm which spelling"; the
batch ground state forbids live calls, so the skip was correct and forced. The
spelling rests on three static oracles (ajv contract `DataGroupId
string|null` + `Sections additionalProperties:false` with `globalDataGroupId`;
deep voluptuous validator; analytics fixture `test_behaviors.py:15109`
emitting `"globalDataGroupId": str(...)`). That is strong but not a live
round-trip. HUMAN-CALL: Phase-4 burn-in must include one live check — save a
bookmark with `data_group_id` through the App API and confirm the stored
sections spelling is `globalDataGroupId` with a string value. No batch change.

## F3 — out-of-batch TS commit a382687 (minor, no change)

Verified: `git show --stat a382687` = README.md only (622 lines), message
"README: consumer-facing rewrite", not named by any fix-of-record doc or the
TS-FOLLOW step list. Docs-only rider on TS main inside the reviewed window
8fa150d..main. Ledger note for the orchestrator; no revert (no code impact).

## R1 — stale batch-status.ts TERMINAL STATE comment (minor, applied)

Verified: `conformance-runner/src/batch-status.ts` header comment stated
"3,251 PASS / 0 FAIL / 0 UNPORTED (corpus pin `70c904dc`)" — dated "B8 gate,
2026-08-16", historical, read by no code, but shipped rig source that reads
like current state. Applied the reviewer's suggested fix: a dated ADDENDUM
paragraph appended to the same header comment recording the R10.7 re-pin
(70c904dc -> 700db996, 3,251 -> 3,262, 0 FAIL / 0 UNPORTED). Comment-only;
no behavior change; covered by `npm run check`.

## R2 — pin reachability sequencing (minor, no repo change)

Verified: `git branch -r --contains 700db99` is empty and the commit is
contained only in local `ts-port/python-bugfix-batch`; TS
`conformance-runner/corpus.config.json` `sourceCommit` references it. Expected
under the LOCAL-COMMITS-ONLY ruling. ORCHESTRATOR SEQUENCING NOTE: push
`ts-port/python-bugfix-batch` (keeping 700db996 reachable, e.g. via the PR
branch) BEFORE or together with pushing TS main, so the TS pin never dangles
on the remotes.

## Gate results (all green)

- Python: `env -u FORCE_COLOR -u COLORTERM just check` EXIT=0 (full recipe:
  lint, fmt-check, typecheck, docstring-cov, test-cov, conformance —
  3,262 passed — and build). First attempt caught a ruff-format diff in the
  new test file; formatted and re-run clean.
- TS: `npm run check` EXIT=0 (typecheck, lint, fmt:check, test incl. the new
  mirror members, smoke:browser).
- TS full-corpus conformance: `npm run conformance` = 3,262 / 3,262 passed,
  0 failed, 0 unported @ 700db996cc95 (unchanged pin — no vector flips).
- ajv bookmark referee (ripple check): `npm run referee:bookmark` 9/9 green,
  0 REJECT.

## Commits

- TS (`main`): b7152da — F1 twin locks + oauth-http.ts comment truth-up +
  R1 batch-status.ts addendum (comment-only rig change).
- Python (`ts-port/python-bugfix-batch`): the ARB-A commit containing the
  flow.py guard, the red-first tests, and this notes file (hash in the
  arbiter's final report — this file is part of that commit).
