---
applyTo: "conformance/**"
---
# Conformance corpus

The conformance corpus records the behavior of `mixpanel_headless` for other
language ports. It is maintainer tooling and is not part of `just check`.

- Recorded vectors (`conformance/vectors/`), golden JSON files
  (`conformance/goldens/`), differential JSON files, and
  `conformance/contract/` are generated. Library PRs do not edit them. The
  corpus is recorded again once per release.
- Review the hand-written tooling (runner, record, contract,
  referee_bookmark_parser, smoke, tests, oracle_py, the differential
  harness, and `goldens/rrweb/generate.py`) as normal code.
- CI runs `conformance/record/check_stamps.py`. It checks that each
  `source_commit` stamp is a commit that `main` can reach, and that corpus
  content does not change without a new stamp. Do not check stamp SHAs by
  hand. A change that weakens either check is a defect.

Greptile rule for this area: `stamp-main-reachable`.
