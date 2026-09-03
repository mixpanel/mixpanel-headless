# conformance/record — vector extraction (record mode)

Design of record: `context/phase1/design/phase1-design.md` (D1 plugin, D3
corpus layout/regeneration, D8 CI drift check, D10 exclusions).

## Regeneration command (D3)

The exact command line that (re)generates `conformance/vectors/`:

```bash
uv run python -m pytest tests -p conformance.record.plugin \
  --mp-record-vectors=conformance/vectors \
  --mp-record-date=<extraction date, e.g. 2026-08-14> \
  --mp-record-commit=<full 40-char source SHA> \
  -o addopts="" -m "not live" $(cat conformance/record/exclusions.args)
```

Equivalent recipe: `just conformance-record --mp-record-date=... --mp-record-commit=...`.

Notes:

- `uv run python -m pytest` (NOT bare `uv run pytest`) is required: only the
  `-m` form puts the repo root on `sys.path`, without which
  `-p conformance.record.plugin` cannot import (found at PR-5).
- `--mp-record-date` / `--mp-record-commit` are injected externally — never
  the wall clock, never `git rev-parse` — so a re-extraction can reproduce
  the committed manifest stamps byte-for-byte (D3/D8). The D8 drift check
  reads both values back out of the committed manifest.
- `-o addopts=""` is required because the repo default addopts pollute
  collection parsing.
- Regeneration is a deliberate act: re-run, `git diff conformance/vectors/`,
  commit if changed with the new `source_commit`, then re-run the D9 smoke
  test (`just conformance-smoke`) before committing a regenerated corpus.

### Which SHA to stamp (stamp-provenance rule)

`--mp-record-commit` and the contract generator's `--generated-from` must
name **the `main` commit whose `src/` is the code the vectors were
extracted from**, as a full 40-hex SHA. Never stamp with the HEAD of the
branch you are working on: this repo squash-merges PRs, so a branch SHA
survives only in local reflogs and the stamp stops resolving once the
branch is deleted (every stamp in the corpus before the 2026-09 re-pin had
this defect — see `EXTRACTION-LEDGER.md`).

CI enforces this with `conformance/record/check_stamps.py` (step
"Stamp-provenance guard", before the drift check; locally
`just conformance-stamps`):

1. `manifest.source_commit`, every extracted `$bundle.source_commit`, and
   every `conformance/contract/*.json` `generated_from` must be a 40-hex
   SHA that is an ancestor of `origin/main`
   (`git merge-base --is-ancestor`). Extracted bundle stamps must also
   equal the manifest stamp. Authored bundles are exempt only through the
   explicit `LEGACY_AUTHORED_STAMPS` allowlist in the script; a new
   authored bundle, or an allowlisted one whose stamp changes, must carry
   a reachable SHA.
2. On pull requests: if any file under `conformance/vectors/**`
   (excluding `authored/**` and `enums/**`) differs from the merge-base
   with `main` in anything other than the stamp fields, then
   `manifest.source_commit` must also differ from the merge-base's value.

Consequence: a commit cannot contain its own SHA, so a PR that changes
vectors cannot stamp them with its own future squash SHA. The repo adopts
the **two-step protocol**:

1. **Library PR.** Land the `src/` / `tests/` change WITHOUT touching
   `conformance/vectors/` or `conformance/contract/`. The drift check will
   fail on that PR if the change alters recorded behavior; that is the
   expected signal, and the PR should say so (the R10.7 batch, PR #208,
   is the precedent: "Conformance vectors deliberately NOT touched
   (RE-PIN task owns re-extraction)"). Merge it; note the squash SHA on
   `main`.
2. **Re-pin PR.** Re-extract with `--mp-record-commit=<that squash SHA>`
   and `--mp-record-date=<today>`, regenerate the contract with
   `--generated-from <the same SHA>`, append an `EXTRACTION-LEDGER.md`
   entry, and open a conformance-only PR. Rule 2 passes because the stamp
   moved with the content; rule 1 passes because the SHA is on `main`.

The single-PR alternative — stamping with the PR's merge-base on `main` —
also satisfies both rules, but the stamp then names the code BEFORE the
change and anyone following it will not find the source of the new
vectors. It is NOT adopted. Use the two-step protocol.

After each re-pin PR merges, the TypeScript port (`mixpanel-headless-ts`)
re-pins to the same SHA: set `conformance-runner/corpus.config.json`
`sourceCommit` to it, run `npm run sync:corpus` (which refuses to copy
unless `manifest.source_commit` equals the pin), and commit.

## exclusions.args

`exclusions.args` holds extra pytest selector arguments appended to the
record invocation (word-split via `$(cat ...)` by both the CI drift step and
`just conformance-record`). Since P2-1 it carries exactly one entry:

- `conformance/tests/test_coverage_cases.py` — the Phase-2 recorder-coverage
  closure cases (phase2-design C10, Discrepancy Log #10). The five
  previously-uncovered `types.*` guard seams (`FunnelStep`,
  `RetentionEvent`, `CohortCriteria.did_not_do_event` /
  `property_is_set` / `property_is_not_set`) need guard-failure calls to
  record, and `tests/` is frozen during Phase 2 (support-branch rule:
  `conformance/`-only changes), so the recordable cases live under
  `conformance/tests/` and join the record run through this file — an
  INCLUSION selector, not an exclusion. The same file also runs in the
  normal `just conformance` job.

No D10 *exclusion* selectors live here: every exclusion besides
`-m "not live"` is detected at runtime by the plugin (Hypothesis via
`hasattr(item.obj, "hypothesis")`, CLI via `CliRunner.invoke` observation,
`destructive` via marker, the rest per-capture at emit time), which keeps
the corpus denominator honest without brittle `-k` selectors (see
`EXTRACTION-LEDGER.md`). Add exclusion selectors here only if a future
exclusion cannot be runtime-detected; the file must stay shell-word-safe
(no comments, no quotes needing evaluation).

## Drift check (D8)

CI's `conformance` job re-extracts to `/tmp/re-extract` with the committed
manifest's own stamps injected, then runs the bidirectional byte-diff.
Because the stamps are injected back in, this check proves that the
vectors reproduce but says nothing about whether the stamps are RIGHT;
that is the job of the stamp-provenance guard above.

```bash
uv run python -m conformance.record.diff /tmp/re-extract conformance/vectors
```

Scope is the extracted subset only (`authored/**` and `enums/**` excluded —
record mode never emits them; `enums/` is regenerated only by an explicit
flag). Within scope, bundle-path sets, per-bundle vector-id sets, per-line
bytes, `$bundle` headers, `manifest.json`, and `api-index.json` must all
match in BOTH directions; any asymmetry fails the PR.
