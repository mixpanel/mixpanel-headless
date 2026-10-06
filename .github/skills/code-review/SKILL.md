---
name: code-review
description: Procedure to review a pull request in mixpanel-headless and check each finding before it is posted. Use for every pull request review in this repository.
---

# Review procedure for mixpanel-headless

`REVIEW.md` sets the priorities, the evidence a finding needs, the severity
scale, and what not to comment on. This skill is the procedure to apply it.

## 1. Collect the context

1. Read the PR description. List the changed areas: library, CLI, tests,
   conformance, replays, specs, plugin, docs, workflows.
2. For each changed area, read its file in `.github/instructions/`. If that
   file names a folder guide (a `CLAUDE.md` in the folder), read the guide
   too. Not every area has one.
3. Read `REVIEW.md`.

## 2. Check each finding before you post it

1. Find the line that shows the behavior. Do not infer behavior from a
   name, a docstring, or a comment.
2. Where you can, prove the finding:
   - `uv run python -c "..."` for a small behavior check.
   - `uv run pytest <file>::<test> -q` for one focused test. The unit tests
     run offline with mocks.
3. Never run tests under `tests/live/`, and never pass `-m live`. Those
   tests call the real Mixpanel API, and some of them write data.
4. Do not run `just check` or the full test suite. CI runs them.
5. If you cannot support the finding with a line or a check, do not post
   it.

## 3. Check public API changes

For a new or changed public method, type, CLI command or flag, or `MP_*`
variable, compare the code with:

- `uv run mp help <Name>`: the built-in reference must describe the new
  behavior.
- `src/mixpanel_headless/__init__.py`: a new package-level name needs an
  export.
- `CHANGELOG.md`: an entry under `## Unreleased`.
- The matching page in `docs/guide/`.
- For an `MP_*` variable: the environment variable table in `CLAUDE.md`.

## 4. Post

- Give each finding a severity from `REVIEW.md`.
- For a bug, state the input that fails and the wrong result.
- Prefer one precise comment to several speculative ones.
- If the PR is clean, say so.
