"""Generate the authored mobile replay vectors.

Emits ``conformance/vectors/authored/replays/rrweb-mobile.jsonl``: authored
vectors for the mobile replay members ``Replay.capture``,
``Replay.has_wireframes``, ``Replay.screen_path()``, and
``ReplayBundle.rage_taps()`` (through the ``replay.*`` and
``replay_bundle.*`` registry adapters). The inputs are small synthetic
rrweb streams. Every ``expect`` value is computed by a call to the
registered adapter, so the frozen outputs come from the library and are
never typed by hand.

Usage:
    ```bash
    uv run python -m conformance.record.gen_replay_mobile_vectors \\
        --commit <40-hex SHA on main>
    ```

The stamp must be the main commit whose ``src/`` holds the mobile replay
code: the squash SHA of the library pull request, not a branch SHA. The
stamp-provenance guard (``check_stamps.py``) rejects a new authored bundle
whose stamp is not reachable from main.

Deterministic: a re-run with the same stamp writes the same bytes.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from conformance.record import adapters

OUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "vectors"
    / "authored"
    / "replays"
    / "rrweb-mobile.jsonl"
)

SOURCE_FILE = "conformance/vectors/authored/replays/rrweb-mobile.jsonl"

_BASE_MS = 1_789_000_000_000
"""Stream start time. Every event time is this value plus an offset."""


def _meta(offset_ms: int, href: str = "", width: int | None = 400) -> dict[str, Any]:
    """Build one Meta event.

    Args:
        offset_ms: Milliseconds after the stream start.
        href: The page URL. An empty value marks a screenshot recording.
        width: The screen width (the touch space), or None to omit it.

    Returns:
        The rrweb Meta event.
    """
    data: dict[str, Any] = {"href": href}
    if width is not None:
        data["width"] = width
    return {"type": 4, "data": data, "timestamp": _BASE_MS + offset_ms}


def _screen(offset_ms: int, elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one ``mp_wireframe`` Custom event with a 400 x 800 viewport.

    Args:
        offset_ms: Milliseconds after the stream start.
        elements: The raw wireframe elements.

    Returns:
        The rrweb Custom event.
    """
    return {
        "type": 5,
        "data": {
            "tag": "mp_wireframe",
            "payload": {"viewport": [400, 800], "elements": elements},
        },
        "timestamp": _BASE_MS + offset_ms,
    }


def _pointer(offset_ms: int, kind: int, x: int, y: int) -> dict[str, Any]:
    """Build one MouseInteraction event.

    Args:
        offset_ms: Milliseconds after the stream start.
        kind: The interaction type (2 click, 7 touch start, 9 touch end).
        x: The x coordinate.
        y: The y coordinate.

    Returns:
        The rrweb IncrementalSnapshot event.
    """
    return {
        "type": 3,
        "data": {"source": 2, "type": kind, "id": 5, "x": x, "y": y},
        "timestamp": _BASE_MS + offset_ms,
    }


def _tap(offset_ms: int, x: int, y: int) -> list[dict[str, Any]]:
    """Build a tap: a finger-down and a lift-off 40 ms later at the same point.

    Args:
        offset_ms: Milliseconds after the stream start.
        x: The x coordinate.
        y: The y coordinate.

    Returns:
        The two events.
    """
    return [_pointer(offset_ms, 7, x, y), _pointer(offset_ms + 40, 9, x, y)]


def _text(label: str, y: int) -> dict[str, Any]:
    """Build one labeled ``text`` wireframe element.

    Args:
        label: The label.
        y: The top edge.

    Returns:
        The raw element.
    """
    return {"role": "text", "text": label, "bounds": [16, y, 200, 30]}


_BUTTON = {"role": "button", "text": "Add", "bounds": [80, 180, 60, 40]}
"""A button that contains the point (100, 200)."""

_HOME = [_text("Home", 40), _BUTTON]
_HOME_BUSY = [_text("Home", 40), _text("Loading", 300), _BUTTON]
_ICONS = [{"role": "image", "text": "", "bounds": [0, 0, 40, 40]}]
_SETTINGS = [_text("Settings", 40), _text("Clock 9:41", 2)]


def _web_stream() -> list[dict[str, Any]]:
    """Build a web (DOM) recording with three fast clicks.

    Returns:
        The events.
    """
    return [
        _meta(0, href="https://x.test/cart", width=1280),
        _pointer(1_000, 2, 100, 200),
        _pointer(1_200, 2, 100, 200),
        _pointer(1_400, 2, 100, 200),
    ]


def _screens_stream() -> list[dict[str, Any]]:
    """Build a screenshot recording that moves through three screens.

    The second screen has no labeled text, so its heading is ``(screen)``.
    The third screen has a text element above ``Settings``, which is the
    top-most label and so the heading.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        *_tap(1_000, 100, 200),
        _screen(1_200, _ICONS),
        *_tap(3_000, 20, 20),
        _screen(3_200, _SETTINGS),
    ]


def _burst(
    start_ms: int, points: list[tuple[int, int]], step_ms: int = 150
) -> list[dict[str, Any]]:
    """Build a run of taps, one every ``step_ms``.

    Args:
        start_ms: Offset of the first finger-down.
        points: The ``(x, y)`` point of each tap.
        step_ms: Time between two finger-downs.

    Returns:
        The events.
    """
    events: list[dict[str, Any]] = []
    for index, (x, y) in enumerate(points):
        events.extend(_tap(start_ms + index * step_ms, x, y))
    return events


def _dead_burst() -> list[dict[str, Any]]:
    """Four taps on the button with no screen change after them.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        *_burst(1_000, [(100, 200), (102, 201), (98, 199), (101, 203)]),
    ]


def _rage_burst() -> list[dict[str, Any]]:
    """Five taps on the button with one screen change after them.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        *_burst(1_000, [(100, 200)] * 5),
        _screen(1_300, _HOME_BUSY),
    ]


def _late_change_burst() -> list[dict[str, Any]]:
    """Five taps on the button, and one screen change 500 ms after the last.

    The change falls inside the default 1000 ms grace time only.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        *_burst(1_000, [(100, 200)] * 5),
        _screen(2_100, _HOME_BUSY),
    ]


def _intentional_run() -> list[dict[str, Any]]:
    """Three taps, each followed by a new screen (a stepper).

    Returns:
        The events.
    """
    events: list[dict[str, Any]] = [_meta(0), _screen(100, _HOME)]
    for index in range(3):
        start = 1_000 + index * 400
        events.extend(_tap(start, 100, 200))
        events.append(_screen(start + 100, [_text(f"Count {index + 1}", 40), _BUTTON]))
    return events


def _spread_burst() -> list[dict[str, Any]]:
    """Three taps 30 px apart: outside the default 24 px radius.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        *_burst(1_000, [(100, 200), (130, 200), (100, 230)]),
    ]


def _click_burst() -> list[dict[str, Any]]:
    """Three mouse clicks (Flutter web) on the button, no screen change.

    Returns:
        The events.
    """
    return [
        _meta(0),
        _screen(100, _HOME),
        _pointer(1_000, 2, 100, 200),
        _pointer(1_100, 2, 100, 200),
        _pointer(1_200, 2, 100, 200),
    ]


def _cases() -> list[tuple[str, str, dict[str, Any]]]:
    """List every vector case as ``(api, slug, input kwargs)``.

    Returns:
        The cases, in output order.
    """
    return [
        ("replay.capture", "web-href", {"events": _web_stream()}),
        ("replay.capture", "empty-href", {"events": [_meta(0)]}),
        ("replay.capture", "wireframe-without-meta", {"events": [_screen(0, _HOME)]}),
        (
            "replay.capture",
            "no-meta",
            {"events": [{"type": 3, "data": {"source": 3}, "timestamp": _BASE_MS}]},
        ),
        ("replay.capture", "empty-stream", {"events": []}),
        (
            "replay.capture",
            "one-href-among-empty",
            {"events": [_meta(0), _meta(10, href="https://x.test/")]},
        ),
        ("replay.has_wireframes", "screens", {"events": _screens_stream()}),
        (
            "replay.has_wireframes",
            "screenshot-without-wireframes",
            {"events": [_meta(0), *_tap(1_000, 100, 200)]},
        ),
        ("replay.has_wireframes", "web", {"events": _web_stream()}),
        ("replay.screen_path", "three-screens", {"events": _screens_stream()}),
        ("replay.screen_path", "web", {"events": _web_stream()}),
        ("replay_bundle.rage_taps", "dead-burst", {"events": _dead_burst()}),
        ("replay_bundle.rage_taps", "rage-burst", {"events": _rage_burst()}),
        ("replay_bundle.rage_taps", "intentional-run", {"events": _intentional_run()}),
        (
            "replay_bundle.rage_taps",
            "below-threshold",
            {"events": _dead_burst()[:-4]},
        ),
        (
            "replay_bundle.rage_taps",
            "threshold-two",
            {"events": _dead_burst()[:-4], "threshold": 2},
        ),
        (
            "replay_bundle.rage_taps",
            "spread-default-radius",
            {"events": _spread_burst()},
        ),
        (
            "replay_bundle.rage_taps",
            "spread-wide-radius",
            {"events": _spread_burst(), "radius_px": 45},
        ),
        (
            "replay_bundle.rage_taps",
            "short-window",
            {"events": _dead_burst(), "window_ms": 200},
        ),
        (
            "replay_bundle.rage_taps",
            "late-change-default-grace",
            {"events": _late_change_burst()},
        ),
        (
            "replay_bundle.rage_taps",
            "late-change-no-grace",
            {"events": _late_change_burst(), "grace_ms": 0},
        ),
        ("replay_bundle.rage_taps", "flutter-clicks", {"events": _click_burst()}),
        ("replay_bundle.rage_taps", "web", {"events": _web_stream()}),
    ]


_ADAPTERS: dict[str, Callable[..., Any]] = {
    "replay.capture": adapters.replay_capture,
    "replay.has_wireframes": adapters.replay_has_wireframes,
    "replay.screen_path": adapters.replay_screen_path,
    "replay_bundle.rage_taps": adapters.replay_bundle_rage_taps,
}
"""The registry adapter behind each api (see ``registry.py``)."""


def build_vectors() -> list[dict[str, Any]]:
    """Build every vector, with ``expect.output`` computed by the adapter.

    Returns:
        The vector objects, in case order.
    """
    vectors: list[dict[str, Any]] = []
    for api, slug, kwargs in _cases():
        output = _ADAPTERS[api](**kwargs)
        vectors.append(
            {
                "call": {"api": api, "input": kwargs},
                "capability": "replays",
                "expect": {"output": output},
                "id": f"replays/{api}/authored-{slug}",
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


def main() -> int:
    """Write the bundle.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        required=True,
        help="$bundle source_commit stamp: a 40-hex SHA reachable from main.",
    )
    args = parser.parse_args()
    OUT_PATH.write_text(render_bundle(args.commit), encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(build_vectors())} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
