"""Generate the authored analyzer vectors over mobile replay streams.

Emits ``conformance/vectors/authored/replays/rrweb-analyze-mobile.jsonl``:
authored ``rrweb_analyzer.analyze`` vectors over the nine mobile rrweb
fixtures in ``tests/fixtures/rrweb/``, the synthetic mobile gesture
stream in ``conformance/goldens/rrweb/``, and a few small synthetic
wireframe streams whose Meta width differs from the wireframe viewport.
When the viewport is wider than the Meta width (physical-pixel bounds
against dp touches) the scale is below ``1.0``; when it is narrower (a
coarse viewport) the scale is above ``1.0``. The synthetic streams also
pin the tolerance boundary (a ratio of exactly 1.05 or 0.95 in floating
point still scales), a ratio inside the tolerance that does not scale,
and round-half-to-even on scaled bounds.

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


def _screen(
    offset_ms: int,
    viewport_width: int,
    labels: list[str],
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one ``mp_wireframe`` event with one text element per label.

    Bounds are in the viewport's units: each label is a 300 x 40 box at
    ``x = 20``, stacked 60 units apart from ``y = 100``; a final button
    spans ``[100, 700, 200, 80]``.

    Args:
        offset_ms: Milliseconds after the stream start.
        viewport_width: The wireframe viewport width (height is twice it).
        labels: Text element labels, top to bottom.
        extra: Raw elements appended after the button.

    Returns:
        The rrweb Custom event.
    """
    elements: list[dict[str, Any]] = [
        {"role": "text", "text": label, "bounds": [20, 100 + 60 * index, 300, 40]}
        for index, label in enumerate(labels)
    ]
    elements.append({"role": "button", "text": "Next", "bounds": [100, 700, 200, 80]})
    elements.extend(extra or [])
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


_HALF_EVEN = {"role": "text", "text": "Odd", "bounds": [21, 301, 5, 3]}
"""An element whose bounds land on .5 at scale 0.5 (10.5, 150.5, 2.5, 1.5)."""


def _scaled_stream(
    meta_width: int,
    viewport_width: int,
    tap: tuple[int, int] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a two-screen wireframe stream with one tap near the button.

    By default the tap lands on the button's center in Meta-width units,
    scaled by ``meta_width / viewport_width``. That point misses the raw
    button only when the ratio is far from ``1.0``; near ``1.0`` pass an
    edge ``tap`` that is inside the scaled button but outside the raw
    button plus the hit slop.

    Args:
        meta_width: The Meta width.
        viewport_width: The wireframe viewport width.
        tap: The tap point in Meta-width units, instead of the scaled
            button center.
        extra: Raw elements added to both screens.

    Returns:
        The events.
    """
    ratio = meta_width / viewport_width
    x, y = tap if tap is not None else (round(200 * ratio), round(740 * ratio))
    return [
        _meta(0, meta_width),
        _screen(100, viewport_width, ["Welcome", "Step 1"], extra),
        *_tap(1_000, x, y),
        _screen(1_200, viewport_width, ["Welcome", "Step 2"], extra),
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
        ("scale-0-5-physical-pixels", 200, 400),
        ("scale-2-coarse-viewport", 800, 400),
        ("scale-1-25-coarse-viewport", 500, 400),
    ):
        cases.append((slug, _scaled_stream(meta_width, viewport_width)))
    # At the tolerance boundary the scaled button nearly covers the raw
    # button, so a center tap hits both. Each tap is inside the scaled
    # button but more than the 8 px hit slop outside the raw button
    # [100, 700, 200, 80]: at 1.05 ([105, 735, 210, 84]) y = 800 is 20
    # below the raw bottom; at 0.95 ([95, 665, 190, 76]) y = 670 is 30
    # above the raw top.
    for slug, meta_width, tap in (
        ("scale-1-05-tolerance-boundary-scales", 420, (210, 800)),
        ("scale-0-95-tolerance-boundary-scales", 380, (190, 670)),
    ):
        cases.append((slug, _scaled_stream(meta_width, 400, tap=tap)))
    # 410 / 400 is inside the tolerance: the bounds stay raw. The tap at
    # (100, 701) is inside the raw button [100, 700, 200, 80] but misses
    # the button scaled by 1.025 ([102, 718, 205, 82]) even with hit slop,
    # so the target shows that no scaling happened.
    cases.append(
        (
            "scale-within-tolerance-stays-raw",
            _scaled_stream(410, 400, tap=(100, 701)),
        )
    )
    # 21, 301, 5, 3 at scale 0.5 land on 10.5, 150.5, 2.5, 1.5, which
    # round half to even: 10, 150, 2, 2.
    cases.append(
        (
            "scale-0-5-round-half-even",
            _scaled_stream(200, 400, extra=[_HALF_EVEN]),
        )
    )
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
