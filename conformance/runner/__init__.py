"""Python corpus-runner package (design D6/D7).

Contents, per the Phase-1 design of record:
    - ``canonical.py``: the normative canonicalization algorithm (D6) —
      landed by task PR-4, selftested against
      ``conformance/schema/canonical-selftest.json``.
    - ``test_corpus.py``: pytest parametrization over every vector (D7).
    - ``__main__.py``: pytest-free CLI ``python -m conformance.runner`` (D7).

The corpus runner pieces land with task PR-6.
"""
