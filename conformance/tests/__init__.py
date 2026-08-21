"""Unit tests for the conformance tooling itself (design D17.5).

Run by ``just conformance`` and the CI conformance job via
``uv run pytest conformance/tests -o addopts="" -q``. These tests cover the
tooling (schema artifacts, codecs, emit determinism, canonicalizer), not the
library — library conformance is the corpus runner's job.
"""
