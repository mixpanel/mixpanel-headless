"""Phase-1 TypeScript-port verification rig (conformance corpus tooling).

This package holds the record plugin, corpus runner, smoke test, differential
oracles, and referee harnesses defined by the Phase-1 design of record at
``context/phase1/design/phase1-design.md``. It is repo tooling, not part of
the published ``mixpanel_headless`` distribution: it is held to the same
mypy --strict / ruff / docstring bar as ``src/`` (design D17) but is excluded
from the 90% coverage floor and from the wheel.

Subpackages:
    - ``record``: pytest record plugin, builder/wire registry, codecs (D1/D4).
    - ``runner``: Python corpus runner + canonicalizer (D6/D7).
    - ``smoke``: deliberate-break smoke test (D9).
    - ``oracle_py``: JSON-RPC differential oracle (D14).
    - ``differential``: Hypothesis fuzz harness + strategies (D14).
    - ``referee_bookmark_parser``: bookmark_parser round-trip referee (D15b).
    - ``tests``: unit tests for the conformance tooling itself (D17.5).

Data directories (not packages):
    - ``schema/``: vector JSON Schema + canonical selftest artifacts.
    - ``vectors/``: the committed conformance-vector corpus (D3).
"""
