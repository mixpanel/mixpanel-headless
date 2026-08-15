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

## exclusions.args

`exclusions.args` holds extra pytest selector arguments appended to the
record invocation (word-split via `$(cat ...)` by both the CI drift step and
`just conformance-record`). It is INTENTIONALLY EMPTY: every D10 exclusion
besides `-m "not live"` is detected at runtime by the plugin (Hypothesis via
`hasattr(item.obj, "hypothesis")`, CLI via `CliRunner.invoke` observation,
`destructive` via marker, the rest per-capture at emit time), which keeps
the corpus denominator honest without brittle `-k` selectors (see
`EXTRACTION-LEDGER.md`). Add selectors here only if a future exclusion
cannot be runtime-detected; the file must stay shell-word-safe (no comments,
no quotes needing evaluation).

## Drift check (D8)

CI's `conformance` job re-extracts to `/tmp/re-extract` with the committed
manifest's own stamps injected, then runs the bidirectional byte-diff:

```bash
uv run python -m conformance.record.diff /tmp/re-extract conformance/vectors
```

Scope is the extracted subset only (`authored/**` and `enums/**` excluded —
record mode never emits them; `enums/` is regenerated only by an explicit
flag). Within scope, bundle-path sets, per-bundle vector-id sets, per-line
bytes, `$bundle` headers, `manifest.json`, and `api-index.json` must all
match in BOTH directions; any asymmetry fails the PR.
