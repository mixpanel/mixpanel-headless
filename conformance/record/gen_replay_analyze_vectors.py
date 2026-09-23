"""Generate the authored analyzer vectors over mobile replay streams.

Emits ``conformance/vectors/authored/replays/rrweb-analyze-mobile.jsonl``:
authored ``rrweb_analyzer.analyze`` vectors over the nine mobile rrweb
fixtures in ``tests/fixtures/rrweb/``, the synthetic mobile gesture
stream in ``conformance/goldens/rrweb/``, and a few small synthetic
wireframe streams whose Meta width differs from the wireframe viewport
(physical-pixel bounds, so ``metadata.scale`` is not ``1.0``).

The existing analyzer vectors (``rrweb-seed.jsonl``) cover web streams
only, so without these no vector ran the analyzer over a wireframe stream
and a port never saw, for example, that ``metadata.scale`` is the float
``1.0``.

Every ``expect`` value is computed by the registered adapter and encoded
with the entry's output codec, exactly as the corpus runner encodes the
replayed value, so the frozen outputs come from the library and are never
typed by hand. Floats keep their float spelling in the JSON text
(``1.0``, ``2.0``, ``1.25``), which the TypeScript runner reads losslessly.

Two fixtures are too large to carry whole; each is cut to the shortest
prefix that still holds the actions it exists for (see
:data:`FIXTURES`).

Usage:
    ```bash
    uv run python -m conformance.record.gen_replay_analyze_vectors \\
        --commit <40-hex SHA on main>
    uv run python -m conformance.record.gen_replay_analyze_vectors \\
        --commit <SHA> --out /tmp/rrweb-analyze-mobile.jsonl
    ```

The stamp must be the main commit whose ``src/`` holds the analyzer code:
the squash SHA of the pull request that adds this generator, not a branch
SHA. The stamp-provenance guard (``check_stamps.py``) rejects a new
authored bundle whose stamp is not reachable from main.

Deterministic: a re-run with the same stamp writes the same bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from conformance.record import adapters
from conformance.record.codecs import encode_output
from conformance.record.registry import REGISTRY_BY_API

_REPO = Path(__file__).resolve().parents[2]

OUT_PATH = (
    _REPO
    / "conformance"
    / "vectors"
    / "authored"
    / "replays"
    / "rrweb-analyze-mobile.jsonl"
)

SOURCE_FILE = "conformance/vectors/authored/replays/rrweb-analyze-mobile.jsonl"

API = "rrweb_analyzer.analyze"

FIXTURE_DIR = _REPO / "tests" / "fixtures" / "rrweb"

GESTURES_INPUT = (
    _REPO
    / "conformance"
    / "goldens"
    / "rrweb"
    / "synthetic-mobile-gestures-001.input.json"
)

FIXTURES: tuple[tuple[str, int | None], ...] = (
    ("android-snacks-001", 18),
    ("android-wireframe-001", None),
    ("android-wireframe-masked-001", None),
    ("flutter-android-rage-001", 73),
    ("flutter-web-clicks-001", None),
    ("ios-early-touch-001", None),
    ("ios-wireframe-001", None),
    ("rn-android-no-wireframe-001", None),
    ("rn-ios-001", None),
)
"""``(fixture name, events kept)`` for each mobile fixture; ``None`` keeps all.

``android-snacks-001`` keeps the first 18 events (three screens, three
taps); ``flutter-android-rage-001`` keeps the first 73 (six screens, two
scrolls, ten taps). The whole streams add several hundred kilobytes and no
new action shapes.
"""

_BASE_MS = 1_789_000_000_000
"""Synthetic stream start time. Every event time is this value plus an offset."""


def _meta(offset_ms: int, width: int) -> dict[str, Any]:
    """Build one screenshot-recording Meta event.

    Args:
        offset_ms: Milliseconds after the stream start.
        width: The Meta width (the touch coordinate space).

    Returns:
        The rrweb Meta event.
    """
    return {
        "type": 4,
        "data": {"href": "", "width": width},
        "timestamp": _BASE_MS + offset_ms,
    }


def _screen(offset_ms: int, viewport_width: int, labels: list[str]) -> dict[str, Any]:
    """Build one ``mp_wireframe`` event with one text element per label.

    Bounds are in the viewport's units: each label is a 300 x 40 box at
    ``x = 20``, stacked 60 units apart from ``y = 100``; a final button
    spans ``[100, 700, 200, 80]``.

    Args:
        offset_ms: Milliseconds after the stream start.
        viewport_width: The wireframe viewport width (height is twice it).
        labels: Text element labels, top to bottom.

    Returns:
        The rrweb Custom event.
    """
    elements: list[dict[str, Any]] = [
        {"role": "text", "text": label, "bounds": [20, 100 + 60 * index, 300, 40]}
        for index, label in enumerate(labels)
    ]
    elements.append({"role": "button", "text": "Next", "bounds": [100, 700, 200, 80]})
    return {
        "type": 5,
        "data": {
            "tag": "mp_wireframe",
            "payload": {
                "viewport": [viewport_width, viewport_width * 2],
                "elements": elements,
            },
        },
        "timestamp": _BASE_MS + offset_ms,
    }


def _tap(offset_ms: int, x: int, y: int) -> list[dict[str, Any]]:
    """Build a tap: a finger-down and a lift-off 40 ms later at the same point.

    Args:
        offset_ms: Milliseconds after the stream start.
        x: The x coordinate, in Meta-width units.
        y: The y coordinate, in Meta-width units.

    Returns:
        The two MouseInteraction events.
    """
    return [
        {
            "type": 3,
            "data": {"source": 2, "type": kind, "id": 5, "x": x, "y": y},
            "timestamp": _BASE_MS + offset_ms + delay,
        }
        for kind, delay in ((7, 0), (9, 40))
    ]


def _scaled_stream(meta_width: int, viewport_width: int) -> list[dict[str, Any]]:
    """Build a two-screen wireframe stream with one tap on the button.

    The tap lands on the button's center in Meta-width units, so it only
    resolves to the button once the bounds are scaled by
    ``meta_width / viewport_width``.

    Args:
        meta_width: The Meta width.
        viewport_width: The wireframe viewport width.

    Returns:
        The events.
    """
    ratio = meta_width / viewport_width
    return [
        _meta(0, meta_width),
        _screen(100, viewport_width, ["Welcome", "Step 1"]),
        *_tap(1_000, round(200 * ratio), round(740 * ratio)),
        _screen(1_200, viewport_width, ["Welcome", "Step 2"]),
    ]


def _cases() -> list[tuple[str, list[dict[str, Any]]]]:
    """List every vector case as ``(slug, events)``.

    Returns:
        The cases, in output order.
    """
    cases: list[tuple[str, list[dict[str, Any]]]] = []
    for name, keep in FIXTURES:
        events: list[dict[str, Any]] = json.loads(
            (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
        )
        slug = name if keep is None else f"{name}-first-{keep}"
        cases.append((slug, events if keep is None else events[:keep]))
    gestures: list[dict[str, Any]] = json.loads(
        GESTURES_INPUT.read_text(encoding="utf-8")
    )
    cases.append(("synthetic-mobile-gestures-001", gestures))
    for slug, meta_width, viewport_width in (
        ("scale-2-physical-pixels", 800, 400),
        ("scale-1-25", 500, 400),
        ("scale-0-5", 200, 400),
        ("scale-within-tolerance-stays-1", 410, 400),
    ):
        cases.append((slug, _scaled_stream(meta_width, viewport_width)))
    return cases


def build_vectors() -> list[dict[str, Any]]:
    """Build every vector, with ``expect.output`` computed by the adapter.

    Returns:
        The vector objects, in case order.
    """
    codec = REGISTRY_BY_API[API].output_codec
    vectors: list[dict[str, Any]] = []
    for slug, events in _cases():
        output = encode_output(codec, adapters.analyze_rrweb(events))
        vectors.append(
            {
                "call": {"api": API, "input": {"events": events}},
                "capability": "replays",
                "expect": {"output": output},
                "id": f"replays/{API}/authored-mobile-{slug}",
                "kind": "builder",
                "origin": "authored",
                "schema_version": "1.0",
            }
        )
    return vectors


def render_bundle(commit: str) -> str:
    """Render the whole bundle file: the ``$bundle`` header and the vectors.

    Args:
        commit: The ``$bundle.source_commit`` stamp.

    Returns:
        The JSONL text, with a trailing newline.
    """
    vectors = build_vectors()
    header = {
        "$bundle": {
            "count": len(vectors),
            "source_commit": commit,
            "source_file": SOURCE_FILE,
        }
    }
    lines = [
        json.dumps(header, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
    ]
    lines.extend(
        json.dumps(vector, separators=(",", ":"), ensure_ascii=True, sort_keys=True)
        for vector in vectors
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the bundle.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        required=True,
        help="$bundle source_commit stamp: a 40-hex SHA reachable from main.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help="Bundle path (default: the authored replays directory).",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render_bundle(args.commit)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({text.count(chr(10)) - 1} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
