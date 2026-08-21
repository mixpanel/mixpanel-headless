"""Differential fuzz-harness package (design D14).

Will contain, per the Phase-1 design of record:
    - ``fuzz_harness.py``: spawns oracle-py and oracle-ts bridges, generates
      Hypothesis inputs, canonicalizes (D6) and diffs both outputs.
    - ``strategies.py``: vendored copies of suite strategies where direct
      import proves entangled with fixtures.
    - ``repros/``: shrunken divergence reproductions.

Populated by task PR-10; this package is scaffolded empty by PR-1.
"""
