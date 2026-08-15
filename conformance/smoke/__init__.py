"""Deliberate-break smoke-test package (design D9).

Contains, per the Phase-1 design of record plus the AD-7 addendum:
    - ``run_smoke.py``: worktree-based control + 14 sabotage runs (D9.2).
    - ``patches/S01..S13.patch``: the fixed deliberate-break patch set (D9.1).
    - ``patches/S14.patch``: AD-7 addendum — flips the coded-guard condition
      at ``ES6_CONTAINS_EXPECTS_STR`` (``user_builders.filter_to_selector``)
      so the E2 coding-pass validation vectors prove they catch sabotage.
    - ``last-run.json``: committed provenance of the latest smoke run (D9.3).
"""
