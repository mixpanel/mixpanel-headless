"""bookmark_parser round-trip referee package (design D15b, task PR-11).

Contents:

- ``harness.py`` — drives the structural draft-04 and deep voluptuous
  oracles in the read-only analytics checkout over the payload-handoff
  JSONL (stdlib-only at import time; oracle imports are lazy).
- ``handoff.py`` — produces the handoff by re-executing every
  bookmark-capability builder vector live under the replay clock.
- ``README.md`` — the two proven PYTHONPATH invocation recipes (pinned
  wheels), routing/dialect rules, and the committed batch results.
"""
