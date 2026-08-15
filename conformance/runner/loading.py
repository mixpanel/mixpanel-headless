"""Corpus loading for the Python corpus runner (design D3/D7).

Walks ``conformance/vectors/**/*.jsonl``, skips each bundle's ``$bundle``
header line, and yields one :class:`LoadedVector` per vector line. JSONL
bundles load with one ``json.loads`` per line and no per-vector file I/O —
the design D7 collection-cost lever.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CorpusLoadError(Exception):
    """Raised when the corpus tree itself is malformed (design D9.3).

    A load failure is infrastructure, not vector behavior: the CLI reports
    it as ``runner_crashed``, never as a vector failure.
    """


@dataclass(frozen=True)
class LoadedVector:
    """One vector loaded from a JSONL bundle.

    Attributes:
        id: The vector's deterministic id (design D3).
        kind: ``builder`` / ``wire`` / ``parse`` / ``validation-error``.
        body: The full vector object as loaded.
        bundle: Repo-relative-ish path of the owning bundle (diagnostics).
    """

    id: str
    kind: str
    body: dict[str, Any]
    bundle: Path


def load_vectors(root: Path, pattern: str | None = None) -> list[LoadedVector]:
    """Load every vector under ``root``, sorted by vector id.

    Args:
        root: The corpus root (``conformance/vectors``).
        pattern: Optional ``fnmatch`` glob applied to vector ids
            (the CLI ``--filter`` option, design D7).

    Returns:
        The loaded vectors sorted by id (deterministic run order).

    Raises:
        CorpusLoadError: If the root does not exist, a bundle line is not
            valid JSON, a vector misses required keys, or two vectors share
            an id (duplicate ids are a corpus bug — design D3).
    """
    if not root.is_dir():
        raise CorpusLoadError(f"corpus root {root} is not a directory")
    seen: dict[str, Path] = {}
    vectors: list[LoadedVector] = []
    for bundle in sorted(root.rglob("*.jsonl")):
        for line_number, line in enumerate(
            bundle.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise CorpusLoadError(
                    f"{bundle}:{line_number}: invalid JSON: {exc}"
                ) from exc
            if not isinstance(obj, dict):
                raise CorpusLoadError(
                    f"{bundle}:{line_number}: vector line is not an object"
                )
            if "$bundle" in obj:
                continue
            try:
                vector_id = str(obj["id"])
                kind = str(obj["kind"])
            except KeyError as exc:
                raise CorpusLoadError(
                    f"{bundle}:{line_number}: vector missing {exc}"
                ) from exc
            if vector_id in seen:
                raise CorpusLoadError(
                    f"duplicate vector id {vector_id!r} in {bundle} "
                    f"(also in {seen[vector_id]})"
                )
            seen[vector_id] = bundle
            if pattern is not None and not fnmatch.fnmatch(vector_id, pattern):
                continue
            vectors.append(
                LoadedVector(id=vector_id, kind=kind, body=obj, bundle=bundle)
            )
    vectors.sort(key=lambda vector: vector.id)
    return vectors
