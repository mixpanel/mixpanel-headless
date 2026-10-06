---
applyTo: "src/mixpanel_headless/_internal/replays/**"
---
# Session replay analyzer

`rrweb_analyzer.py` is a fork of an rrweb analyzer that now evolves in this
repository. It uses only the standard library, apart from the public
`UserAction` type. It reads DOM recordings from the JavaScript SDK and
screenshot recordings from the mobile SDKs. `aggregators.py` builds pandas
summaries (clicks, rage clicks, rage taps, pauses) over the actions.

- Review event interpretation, timestamp order, gesture and hit-test logic,
  and changes to the public `UserAction` output.
- A behavior change must regenerate the goldens in
  `conformance/goldens/rrweb/` with `conformance/goldens/rrweb/generate.py`.
- Do not ask for style refactors or docstring changes that differ from the
  conventions of this module.
