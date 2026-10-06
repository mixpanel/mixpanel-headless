---
applyTo: "conformance/**"
---
# Conformance corpus

The conformance corpus records the behavior of `mixpanel_headless` for other
language ports. It is maintainer tooling and is not part of `just check`.

- Library PRs do not edit `conformance/vectors/` or
  `conformance/contract/`. A maintainer records them again once per
  release, in a conformance-only re-pin PR.
- The rrweb golden files (`conformance/goldens/rrweb/`) follow the
  analyzer. A PR that changes analyzer behavior regenerates them with
  `conformance/goldens/rrweb/generate.py` in the same PR.
- The differential JSON files under `conformance/differential/` are
  generated. Do not edit them by hand.
- Review the hand-written tooling (runner, record, contract,
  referee_bookmark_parser, smoke, tests, oracle_py, the differential
  harness, and `goldens/rrweb/generate.py`) as normal code.
- CI runs `conformance/record/check_stamps.py`. It checks that each
  `source_commit` stamp is a commit that `main` can reach, and that corpus
  content does not change without a new stamp. Do not check stamp SHAs by
  hand. A change that weakens either check is a defect.

Greptile rule for this area: `stamp-main-reachable`.
