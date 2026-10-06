---
applyTo: "src/mixpanel_headless/**"
---
# Library code

Read first: `src/mixpanel_headless/CLAUDE.md` (public surface, exception
hierarchy, result types). For `_internal/`, also read
`src/mixpanel_headless/_internal/CLAUDE.md`. For services, also read
`src/mixpanel_headless/_internal/services/CLAUDE.md`.

- Errors that reach callers are subclasses of `MixpanelHeadlessError`,
  chained with `raise NewError(...) from exc`. Validators on value types in
  `types.py` can raise `ValueError` or `TypeError`.
- A broad `except Exception` that re-raises is correct: it chains the
  error into a library error (`raise OAuthError(...) from exc`), or it
  cleans up and then re-raises with a bare `raise`.
- A broad `except Exception` that swallows the error is correct only when
  it records the failure for one item in a result and carries a
  `# noqa: BLE001` comment with the reason. Any other broad catch that
  swallows the error is a defect.
- Follow the neighbors in the same module for frozen or mutable models.
  Result dataclasses are frozen. Not all Pydantic models are frozen, and
  the write-parameter models (`Create*Params`, `Update*Params`) are mutable
  on purpose. Do not ask to freeze a model only for consistency.
- `bool` is a subclass of `int`. Integer validation must reject `bool`
  first.
- A public signature must not need an import from
  `mixpanel_headless._internal`. Re-export the type from a public module.
  `Workspace.api` is a deliberate exception.
- A new or changed public method, type, CLI command or flag, or `MP_*`
  variable needs a CHANGELOG line under `## Unreleased` and a docs update.
  A new package-level name also needs an `__init__.py` export. A new or
  changed `MP_*` variable also needs a row in the environment variable
  table in `CLAUDE.md`. Workspace methods, CLI flags, and `MP_*` variables
  are not package-level names, so they need no export.
- `tests/unit/help/test_registry_completeness.py` checks the built-in help
  (`mp help`) for Python names only: each public `Workspace` method is in
  one help domain, and each export with no docstring of its own has an
  `ALIAS_DOCS` entry. CLI `--help` text comes from the command docstrings.

Greptile rules for this area: `workspace-scope-enforced`,
`reject-bool-as-int`, `no-internal-in-public-signatures`,
`exception-hierarchy`, `secret-handling`, `behavior-change-needs-test`,
`public-surface-sync`, `docstring-accuracy`.
