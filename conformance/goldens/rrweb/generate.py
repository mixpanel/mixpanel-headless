"""Freeze rrweb-analyzer goldens for the TypeScript port's Layer-3 suite.

Runs the Python analyzer (``RrwebAnalyzer.analyze`` + ``analyze_events``)
over every fixture in ``tests/fixtures/rrweb/`` plus the synthetic
streams defined below, and writes one JSON golden per fixture into this
directory. The TS suite
(``packages/core/test/replays/rrweb-analyzer.golden.test.ts`` in the
mixpanel-headless-ts repo) asserts deep equality against the SAME files,
so a behavioural drift on either side turns red.

Regeneration
------------

    uv run python conformance/goldens/rrweb/generate.py

Then copy the outputs into the TS repo:

    cp conformance/goldens/rrweb/*.golden.json \\
       ../mixpanel-headless-ts/packages/core/test/replays/goldens/

Both copies are committed (Phase-3 plan §Layer-3,
``context/typescript-port-plan.md:351-354``; the TS-2 pinned-table
precedent for two-repo generated artifacts).

The frozen shape per fixture is
``{actions[], markdown, page_visits, console_errors}`` — every public
field of :class:`AnalyzerResult`, with ``UserAction`` projected through
its ``to_dict()`` codec so the comparison is byte-level.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mixpanel_headless._internal.replays.rrweb_analyzer import (
    RrwebAnalyzer,
    analyze_events,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "rrweb"
_OUT_DIR = Path(__file__).resolve().parent


def _synthetic_streams() -> dict[str, list[dict[str, Any]]]:
    """Build the synthetic fixtures that widen coverage past the sample.

    The sample replay exercises navigate / input / click / scroll. These
    add the branches a real recording rarely contains in one stream:
    console-plugin errors, text selection, mutation adds / removes /
    text / attribute changes, the ancestor-description fallback, and the
    duplicate-run collapse in the markdown reporter. The mobile stream
    (:func:`_mobile_gesture_stream`) covers the touch gesture rules of a
    screenshot recording.

    Returns:
        A ``{fixture_name: events}`` mapping. Each value is a raw rrweb
        event list suitable for :meth:`RrwebAnalyzer.analyze`.
    """
    root = {
        "id": 1,
        "type": 0,
        "childNodes": [
            {
                "id": 2,
                "type": 2,
                "tagName": "html",
                "attributes": {"lang": "en"},
                "childNodes": [
                    {
                        "id": 3,
                        "type": 2,
                        "tagName": "body",
                        "attributes": {},
                        "childNodes": [
                            {
                                "id": 10,
                                "type": 2,
                                "tagName": "p",
                                "attributes": {},
                                "childNodes": [
                                    {
                                        "id": 11,
                                        "type": 3,
                                        "textContent": "hello 𝒳 world",
                                    }
                                ],
                            },
                            {
                                "id": 20,
                                "type": 2,
                                "tagName": "button",
                                "attributes": {
                                    "id": "go",
                                    "data-testid": "go-button",
                                },
                                "childNodes": [
                                    {"id": 21, "type": 3, "textContent": "Go"},
                                    {
                                        "id": 22,
                                        "type": 2,
                                        "tagName": "span",
                                        "attributes": {},
                                        "childNodes": [],
                                    },
                                ],
                            },
                            {
                                "id": 30,
                                "type": 2,
                                "tagName": "a",
                                "attributes": {"href": "https://x.test/docs/intro"},
                                "childNodes": [
                                    {"id": 31, "type": 3, "textContent": "Docs"}
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    return {
        "synthetic-mobile-gestures-001": _mobile_gesture_stream(),
        "synthetic-mixed-001": [
            {
                "type": 4,
                "data": {"href": "https://x.test/users/12345/p?ref=a"},
                "timestamp": 1_700_000_000_000,
            },
            {
                "type": 2,
                "data": {"node": root, "initialOffset": {"left": 0, "top": 0}},
                "timestamp": 1_700_000_000_100,
            },
            # Selection over a non-BMP-bearing text node (code-point slice).
            {
                "type": 3,
                "data": {
                    "source": 14,
                    "ranges": [
                        {"start": 11, "end": 11, "startOffset": 6, "endOffset": 7}
                    ],
                },
                "timestamp": 1_700_000_001_000,
            },
            # Click on the span → ancestor-context description fallback.
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 22},
                "timestamp": 1_700_000_002_000,
            },
            # Three identical clicks → the markdown (×N) run collapse.
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_000,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_100,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_200,
            },
            # Anchor with an http href → "to /docs/intro".
            {
                "type": 3,
                "data": {"source": 2, "type": 4, "id": 30},
                "timestamp": 1_700_000_004_000,
            },
            # Mutation: attribute change, text change, add, remove.
            {
                "type": 3,
                "data": {
                    "source": 0,
                    "attributes": [
                        {"id": 30, "attributes": {"aria-label": "Read the docs"}}
                    ],
                    "texts": [{"id": 21, "value": "Go now"}],
                    "adds": [
                        {
                            "parentId": 3,
                            "node": {
                                "id": 40,
                                "type": 2,
                                "tagName": "input",
                                "attributes": {"type": "checkbox", "id": "agree"},
                                "childNodes": [],
                            },
                        }
                    ],
                    "removes": [{"id": 10}],
                },
                "timestamp": 1_700_000_005_000,
            },
            {
                "type": 3,
                "data": {"source": 5, "id": 40, "isChecked": True},
                "timestamp": 1_700_000_006_000,
            },
            {
                "type": 3,
                "data": {"source": 3, "id": 1, "x": 0, "y": 120},
                "timestamp": 1_700_000_007_000,
            },
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {
                        "level": "error",
                        "payload": ['"TypeError: 𝒳 is not a function"'],
                    },
                },
                "timestamp": 1_700_000_008_000,
            },
            # Non-error plugin + unknown interaction type: both no-ops.
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {"level": "warn", "payload": ['"deprecated"']},
                },
                "timestamp": 1_700_000_009_000,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 99, "id": 20},
                "timestamp": 1_700_000_010_000,
            },
        ],
    }


def _mobile_gesture_stream() -> list[dict[str, Any]]:
    """Build a screenshot recording that covers the touch gesture edge cases.

    The real mobile fixtures contain few scrolls and no cancelled touch.
    This stream holds each gesture rule once, in time order:

    1. A Meta event with an empty ``href``. This makes the stream a
       screenshot recording, and the width (540) sets the touch space.
    2. A finger drag with no open gesture: the session started mid-drag,
       so the drag is a scroll.
    3. A tap before the first wireframe. It has no screen to hit test, so
       the target is the point.
    4. The first wireframe. Its viewport (1080) is twice the Meta width,
       so every rect is scaled by 0.5. Several rects have odd values, so
       the scaled value ends in .5. Python rounds half to even (50.5 gives
       50), and a port must round the same way. The screen also holds a
       label with a ``|``, an unlabeled image, an element without bounds,
       and an element without a role.
    5. A scroll by drag travel: the lift-off point is near the finger-down
       point, but the drag samples travel far.
    6. A lift-off with no open gesture, which does nothing.
    7. A cancelled touch: no action, but the next screen is kept.
    8. A Flutter-style mouse click, which is a one-event gesture.
    9. A finger-down with no lift-off before the end of the stream. The
       analyzer reports it as a tap at its finger-down time.

    Returns:
        The raw rrweb event list.
    """
    base = 1_700_100_000_000

    def touch(offset_ms: int, kind: int, x: int, y: int) -> dict[str, Any]:
        """Build one MouseInteraction event on the screenshot image node.

        Args:
            offset_ms: Milliseconds after the stream start.
            kind: The MouseInteraction type (2 click, 7 touch start,
                9 touch end, 10 touch cancel).
            x: The x coordinate in the touch space.
            y: The y coordinate in the touch space.

        Returns:
            The rrweb IncrementalSnapshot event.
        """
        return {
            "type": 3,
            "data": {"source": 2, "type": kind, "id": 5, "x": x, "y": y},
            "timestamp": base + offset_ms,
        }

    def drag(offset_ms: int, points: list[tuple[int, int]]) -> dict[str, Any]:
        """Build one finger-drag (TouchMove) event.

        Args:
            offset_ms: Milliseconds after the stream start.
            points: The ``(x, y)`` drag samples.

        Returns:
            The rrweb IncrementalSnapshot event.
        """
        return {
            "type": 3,
            "data": {
                "source": 6,
                "positions": [
                    {"x": x, "y": y, "id": 5, "timeOffset": 0} for x, y in points
                ],
            },
            "timestamp": base + offset_ms,
        }

    def wireframe(offset_ms: int, elements: list[dict[str, Any]]) -> dict[str, Any]:
        """Build one ``mp_wireframe`` Custom event with a 1080 x 2400 viewport.

        Args:
            offset_ms: Milliseconds after the stream start.
            elements: The raw wireframe element list.

        Returns:
            The rrweb Custom event.
        """
        return {
            "type": 5,
            "data": {
                "tag": "mp_wireframe",
                "payload": {"viewport": [1080, 2400], "elements": elements},
            },
            "timestamp": base + offset_ms,
        }

    inbox: list[dict[str, Any]] = [
        {"role": "text", "text": "Inbox", "bounds": [33, 101, 201, 55]},
        {"role": "text", "text": "Alerts | Mentions", "bounds": [33, 301, 401, 51]},
        {"role": "image", "text": "", "bounds": [961, 101, 81, 81]},
        {"role": "button", "text": "Compose", "bounds": [101, 1901, 877, 121]},
        {"role": "text", "text": "No bounds here"},
        {"text": "Role missing", "bounds": [0, 0, 0, 0]},
    ]
    inbox_scrolled: list[dict[str, Any]] = [
        {"role": "text", "text": "Inbox", "bounds": [33, 101, 201, 55]},
        {"role": "text", "text": "Older messages", "bounds": [33, 301, 401, 51]},
        {"role": "button", "text": "Compose", "bounds": [101, 1901, 877, 121]},
    ]
    dialog: list[dict[str, Any]] = [
        {"role": "text", "text": "Discard draft?", "bounds": [201, 901, 677, 81]},
        {"role": "button", "text": "Discard", "bounds": [201, 1101, 301, 101]},
        {"role": "button", "text": "Keep", "bounds": [577, 1101, 301, 101]},
    ]
    return [
        {
            "type": 4,
            "data": {"href": "", "width": 540, "height": 1200},
            "timestamp": base,
        },
        {
            "type": 2,
            "data": {
                "node": {
                    "id": 1,
                    "type": 0,
                    "childNodes": [
                        {
                            "id": 5,
                            "type": 2,
                            "tagName": "img",
                            "attributes": {"src": "data:image/webp;base64,AAAA"},
                            "childNodes": [],
                        }
                    ],
                },
                "initialOffset": {"left": 0, "top": 0},
            },
            "timestamp": base + 10,
        },
        drag(50, [(100, 900), (100, 700)]),
        touch(2_000, 7, 100, 200),
        touch(2_080, 9, 100, 200),
        wireframe(3_000, inbox),
        # Scroll by drag travel: the lift-off is 4 px from the start.
        touch(5_000, 7, 270, 700),
        drag(5_050, [(270, 650), (270, 500)]),
        touch(5_200, 9, 272, 703),
        wireframe(5_300, inbox_scrolled),
        # A lift-off with no open gesture.
        touch(6_000, 9, 10, 10),
        # A cancelled touch, then the screen it leaves.
        touch(7_000, 7, 300, 400),
        touch(7_050, 10, 300, 400),
        wireframe(7_100, dialog),
        # A Flutter-style click inside "Keep" (scaled to [288,550,150,50]).
        touch(9_000, 2, 300, 560),
        wireframe(9_100, inbox_scrolled),
        # A finger-down that never lifts.
        touch(11_000, 7, 60, 960),
    ]


def _freeze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the analyzer over ``events`` and project the frozen shape.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        A JSON-serializable dict with ``actions`` (each via
        ``UserAction.to_dict()``), ``markdown``, ``page_visits``, and
        ``console_errors``. ``markdown`` is also cross-checked against
        :func:`analyze_events`, which must agree exactly.
    """
    result = RrwebAnalyzer().analyze(events)
    if events:
        wrapper_markdown = analyze_events(events)
        if wrapper_markdown != result.markdown_summary:  # pragma: no cover
            raise AssertionError(
                "analyze_events() and RrwebAnalyzer().analyze() disagree"
            )
    return {
        "actions": [a.to_dict() for a in result.actions],
        "markdown": result.markdown_summary,
        "page_visits": [asdict(p) for p in result.pages],
        "console_errors": [asdict(e) for e in result.errors],
    }


def main() -> None:
    """Regenerate every golden file in this directory.

    Reads each ``*.json`` fixture under ``tests/fixtures/rrweb/`` plus
    the synthetic streams, freezes the analyzer output, and writes
    ``{name}.golden.json`` with sorted keys and a trailing newline.

    Returns:
        None. Files are written in place.
    """
    streams: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(_FIXTURE_DIR.glob("*.json")):
        with path.open() as handle:
            streams[path.stem] = json.load(handle)
    streams.update(_synthetic_streams())
    streams["empty-stream"] = []

    for name, events in sorted(streams.items()):
        out_path = _OUT_DIR / f"{name}.golden.json"
        payload = _freeze(events)
        with out_path.open("w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {out_path.relative_to(_REPO_ROOT)}")

    # The synthetic INPUT streams are generated too, so the TS suite
    # feeds byte-identical events rather than a hand-retyped twin.
    for name, events in sorted(_synthetic_streams().items()):
        in_path = _OUT_DIR / f"{name}.input.json"
        with in_path.open("w") as handle:
            json.dump(events, handle, indent=2)
            handle.write("\n")
        print(f"wrote {in_path.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
