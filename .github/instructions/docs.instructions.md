---
applyTo: "docs/**,CHANGELOG.md,README.md,CONTRIBUTING.md"
---
# Docs and changelog

- Docs must match the code: names, defaults, timeouts, and the meaning of
  negated operators. Check examples against `uv run mp help <Name>`.
- CHANGELOG entries go under `## Unreleased`. Release PRs move them.
- Give reasons in plain words. Do not cite internal planning documents by
  number or code.
- Examples use fenced code blocks with a language hint, not doctest `>>>`.

Greptile rule for this area: `no-internal-planning-shorthand`.
