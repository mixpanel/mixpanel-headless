"""Record-mode pytest plugin package (design D1/D4/D5).

Will contain, per the Phase-1 design of record:
    - ``plugin.py``: transport hook, wire entry-point span attribution,
      clock/UUID freeze, virtual sleep (D1).
    - ``registry.py``: builder + wire entry-point registry (D4.4).
    - ``codecs.py``: ``$type``-tagged input/output codec table (D4.4).
    - ``emit.py``: vector serialization, JSONL bundling, redaction (D3/D5).
    - ``clock.py``: freeze helpers (D1.4).

Populated by task PR-2/PR-3; this package is scaffolded empty by PR-1.
"""
