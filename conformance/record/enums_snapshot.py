"""bookmark_enums snapshot generator (design D4.2 item 10, PR-7).

Serializes every public constant of
``mixpanel_headless._internal.bookmark_enums`` that is a ``frozenset`` or
``dict`` into ``conformance/vectors/enums/bookmark_enums.json`` — frozensets
as sorted arrays, dicts key-sorted — because the TS enum tables are exactly
the drift risk this snapshot catches cheaply.

The file is regenerated ONLY by explicitly running this module (the design
D8 "explicit flag": the record-mode drift check excludes ``enums/`` by
path, and ``conformance/tests/test_authored_vectors.py`` fails whenever
the committed file no longer matches the live constants):

    ```bash
    uv run python -m conformance.record.enums_snapshot --write
    ```
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "vectors" / "enums" / "bookmark_enums.json"
)
"""The committed snapshot location (design D3 corpus layout)."""


def build_snapshot() -> dict[str, Any]:
    """Build the snapshot object from the live ``bookmark_enums`` module.

    Selection rule (mechanical, so the snapshot cannot rot against the
    module): every module attribute whose name is public UPPER_CASE and
    whose value is a ``frozenset`` or ``dict``. Frozensets serialize as
    sorted arrays (design D4.2 item 10 — deterministic, set-order-free);
    dicts serialize with sorted keys.

    Returns:
        ``{"source_module": ..., "constants": {name: value, ...}}`` with
        constant names in sorted order.

    Raises:
        TypeError: If a selected constant contains values ``json.dumps``
            cannot serialize (would mean the module changed shape — the
            snapshot must then be redesigned deliberately, never coerced).
    """
    from mixpanel_headless._internal import bookmark_enums

    constants: dict[str, Any] = {}
    for name in sorted(vars(bookmark_enums)):
        if name.startswith("_") or not name.isupper():
            continue
        value = getattr(bookmark_enums, name)
        if isinstance(value, frozenset):
            constants[name] = sorted(value)
        elif isinstance(value, dict):
            constants[name] = {key: value[key] for key in sorted(value)}
    snapshot = {
        "source_module": "mixpanel_headless._internal.bookmark_enums",
        "constants": constants,
    }
    json.dumps(snapshot)  # fail loudly on unserializable content
    return snapshot


def render_snapshot() -> str:
    """Render the snapshot as its canonical committed file content.

    Returns:
        Pretty-printed JSON (2-space indent, sorted keys, trailing
        newline) — byte-stable across regenerations when the constants
        are unchanged (design D3 determinism).
    """
    return json.dumps(build_snapshot(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: check or rewrite the committed snapshot.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``). ``--write``
            regenerates the file; without it the tool only reports
            whether the committed file matches.

    Returns:
        ``0`` when the snapshot is up to date (or was just written),
        ``1`` when ``--write`` was not given and the file is stale or
        missing.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate conformance/vectors/enums/bookmark_enums.json",
    )
    args = parser.parse_args(argv)
    rendered = render_snapshot()
    if args.write:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {SNAPSHOT_PATH}")
        return 0
    if (
        SNAPSHOT_PATH.is_file()
        and SNAPSHOT_PATH.read_text(encoding="utf-8") == rendered
    ):
        print("snapshot up to date")
        return 0
    print("snapshot stale or missing — run with --write")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
