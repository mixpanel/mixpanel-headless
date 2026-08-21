"""Python corpus-runner package (design D6/D7).

Contents, per the Phase-1 design of record:
    - ``canonical.py``: the normative canonicalization algorithm (D6) —
      landed by task PR-4, selftested against
      ``conformance/schema/canonical-selftest.json``.
    - ``loading.py``: JSONL corpus loading (D3 layout, ``--filter`` glob).
    - ``transport.py``: ``VectorTransport`` — ordered + keyed
      unordered-group serving, one-shot consumption, ``transport_error``
      re-raising, ``body_stream`` rebuild (D2/D7).
    - ``targets.py``: session + replay-target reconstruction per
      ``call.api`` prefix (D5.1/D7).
    - ``execute.py``: kind dispatch, ``call.setup[]`` execution, diffing,
      per-vector environment sandbox (D7).
    - ``test_corpus.py``: pytest parametrization over every vector (D7).
    - ``__main__.py``: pytest-free CLI ``python -m conformance.runner``
      with the ``vector_failed`` vs ``runner_crashed`` distinction (D9.3).

See ``README.md`` here for the execution model and measured runtime.
"""
