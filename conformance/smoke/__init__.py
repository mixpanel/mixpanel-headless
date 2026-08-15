"""Deliberate-break smoke-test package (design D9).

Will contain, per the Phase-1 design of record:
    - ``run_smoke.py``: worktree-based control + 13 sabotage runs (D9.2).
    - ``patches/S01..S13.patch``: the fixed deliberate-break patch set (D9.1).
    - ``last-run.json``: committed provenance of the latest smoke run (D9.3).

Populated by task PR-8; this package is scaffolded empty by PR-1.
"""
