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

The Conformance workflow (`.github/workflows/conformance.yml`) enforces
this with `conformance/record/check_stamps.py` (step "Stamp-provenance
guard", before the drift check; locally `just conformance-stamps`):

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

A commit cannot contain its own SHA, so a PR that changes vectors cannot
stamp them with its own future squash SHA. Vector changes therefore land in
a separate re-pin PR that stamps a commit already on `main`.

### When to re-pin

Once per release. The TypeScript port follows releases, not `main`, so the
corpus only needs to match the code that shipped.

The Conformance workflow runs in one of two modes:

- **Strict mode**: a pull request that changes `manifest.source_commit`
  (a re-pin). Any drift fails the job.
- **Report mode**: every other run (other pull requests that change
  `conformance/`, pushes to `main`, releases, manual runs). The job
  summary and a warning annotation report drift, the drift report and the
  re-extracted corpus upload as the `conformance-drift` artifact, and the
  job passes.

In both modes, a type error in `conformance/`, a crashed pytest session, a
failed recording run, and a stamp-provenance finding fail the job.

The cycle:

1. **Library PRs** never touch `conformance/vectors/` or
   `conformance/contract/`, and the workflow does not run on them.
   Between releases, `main` drifts from the corpus. The workflow runs after
   each merge to `main`, so the job summary and the artifact show which
   merge changed which vectors.
2. **Release.** The workflow also runs on each published release. If the
   code drifted, its job summary names the release commit to stamp.
3. **Re-pin PR.** After the release commit is on `main`, open one
   conformance-only PR from a worktree cut from `origin/main`:
   1. Check that `src/` and `tests/` still equal the release commit:
      `git diff --quiet <release SHA> origin/main -- src tests`.
   2. Re-extract with `--mp-record-commit=<release SHA>` and
      `--mp-record-date=<today>`.
   3. Regenerate the contract with `--generated-from <the same SHA>`, and
      regenerate each authored bundle whose generator output changed.
   4. Append an `EXTRACTION-LEDGER.md` entry.

   Strict mode applies. Rule 2 passes because the stamp moved with the
   content, and rule 1 passes because the SHA is on `main`. The workflow
   also fails the PR if `src/` or `tests/` differ from the new stamp.

If a library change reached `main` after the release, the release SHA no
longer names the code that records the corpus: the drift check records from
the PR's own code, not from the code at the stamp. Stamp the current `main`
commit instead, say so in the ledger entry, and pin the TypeScript port to
that SHA.

A conformance tooling PR between re-pins runs in report mode. Some tooling
tests compare committed files with the live library (the enums snapshot,
the generated help bundle, contract census counts), so a failure there can
be drift, and the workflow cannot tell it from a tooling bug. Run
`just conformance` locally and read the job summary before you merge. The
next re-pin runs everything in strict mode.

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
`destructive` via marker, `env_base_url_override` via an `os.environ` check
at each capture, the rest per-capture at emit time), which keeps
the corpus denominator honest without brittle `-k` selectors (see
`EXTRACTION-LEDGER.md`). Add exclusion selectors here only if a future
exclusion cannot be runtime-detected; the file must stay shell-word-safe
(no comments, no quotes needing evaluation).

Runtime-detected buckets that are NOT in the D10 design list:

- `env_base_url_override` — captures taken while `MP_API_BASE_URL` /
  `MP_APP_BASE_URL` was set; the recorded URLs are host-dependent and
  cannot replay without that environment. The plugin reads both variables
  at every entry-call open and every transport interaction (not only at
  setup, because the tests set them with `monkeypatch.setenv` inside the
  test body), applies the library's own unset rule (a value that is empty
  after `rstrip("/")` — `""`, `"/"`, `"///"` — is NOT an override), and
  flags the test capture; the classifier then withholds
  every vector from that test and lists its nodeid in
  `manifest.exclusion_details` (PR #235's override tests are the whole
  population). Added at the 2026-09-11 `0dde506` re-pin, where the
  unfiltered extraction produced 30 loopback-host `wire` vectors that
  failed 26/30 under the runner.

## Drift check

The Conformance workflow re-extracts to `/tmp/re-extract` with the committed
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
match in BOTH directions. Any asymmetry is drift: it fails a re-pin PR, and
every other run reports it (see "When to re-pin").
