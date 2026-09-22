"""Public replay surface for screenshot recordings (mobile, React Native, Flutter).

Covers :attr:`Replay.capture`, :attr:`Replay.has_wireframes`,
:meth:`Replay.screen_path`, :attr:`ReplayBundle.screens_df`, and
:meth:`ReplayBundle.rage_taps` (with its aggregator and the
``finger_downs`` helper), on hand-built streams and on the real replays in
``tests/fixtures/rrweb/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from mixpanel_headless._internal.replays.aggregators import rage_taps
from mixpanel_headless._internal.replays.rrweb_analyzer import (
    FingerDown,
    RrwebAnalyzer,
    finger_downs,
)
from mixpanel_headless.types import Replay, ReplayBundle

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rrweb"

_RAGE_COLUMNS = [
    "replay_id",
    "t_start",
    "t_end",
    "target_desc",
    "x",
    "y",
    "count",
    "kind",
]

_SCREEN_COLUMNS = [
    "replay_id",
    "t",
    "heading",
    "fingerprint",
    "element_count",
    "description",
]


# =============================================================================
# Builders
# =============================================================================


def _load(name: str) -> list[dict[str, Any]]:
    """Load one rrweb fixture by name.

    Args:
        name: The fixture name, without ``.json``.

    Returns:
        The rrweb event list.
    """
    events: list[dict[str, Any]] = json.loads(
        (_FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    )
    return events


def _replay(events: list[dict[str, Any]], replay_id: str = "r-1") -> Replay:
    """Build a Replay the way ``fetch_replay`` does: run the analyzer.

    Args:
        events: The rrweb event list.
        replay_id: The replay id.

    Returns:
        A :class:`Replay` with ``actions`` from the analyzer.
    """
    stamps = [int(e["timestamp"]) for e in events if int(e["timestamp"]) > 0] or [1]
    return Replay(
        replay_id=replay_id,
        distinct_id=None,
        project_id=1,
        start_time=min(stamps),
        end_time=max(stamps),
        retention_days=30,
        rrweb_events=events,
        actions=RrwebAnalyzer().analyze(events).actions if events else [],
    )


def _bundle(*replays: Replay) -> ReplayBundle:
    """Wrap replays in a bundle.

    Args:
        *replays: The replays.

    Returns:
        A :class:`ReplayBundle` for project 1.
    """
    return ReplayBundle(replays=list(replays), computed_at="now", project_id=1)


def _meta(ts: int, href: str | None = None) -> dict[str, Any]:
    """Build a Meta event, with an ``href`` for a DOM recording.

    Args:
        ts: Unix ms timestamp.
        href: The page URL, or None for a screenshot recording.

    Returns:
        The rrweb Meta event dict.
    """
    data: dict[str, Any] = {"width": 400, "height": 800}
    if href is not None:
        data["href"] = href
    return {"type": 4, "timestamp": ts, "data": data}


def _screen(ts: int, label: str, *extra: dict[str, Any]) -> dict[str, Any]:
    """Build a wireframe with a heading and a button under (100, 100).

    Args:
        ts: Unix ms timestamp.
        label: The heading label (it also makes the screen distinct).
        *extra: Extra element dicts.

    Returns:
        The rrweb Custom event dict.
    """
    elements = [
        {"role": "text", "text": label, "bounds": [16, 40, 200, 30]},
        {"role": "button", "text": "Add", "bounds": [50, 80, 100, 40]},
        *extra,
    ]
    return {
        "type": 5,
        "timestamp": ts,
        "data": {"tag": "mp_wireframe", "payload": {"elements": elements}},
    }


def _down(ts: int, x: int = 100, y: int = 100, kind: int = 7) -> dict[str, Any]:
    """Build a finger-down (TOUCH_START) or a mouse CLICK event.

    Args:
        ts: Unix ms timestamp.
        x: The x coordinate.
        y: The y coordinate.
        kind: The MouseInteraction type (7 TOUCH_START, 2 CLICK).

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": kind, "id": 28, "x": x, "y": y},
    }


def _up(ts: int, x: int = 100, y: int = 100) -> dict[str, Any]:
    """Build a lift-off (TOUCH_END) event.

    Args:
        ts: Unix ms timestamp.
        x: The x coordinate.
        y: The y coordinate.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": 9, "id": 28, "x": x, "y": y},
    }


def _taps(
    start: int, n: int, step: int = 100, x: int = 100, y: int = 100
) -> list[dict[str, Any]]:
    """Build ``n`` complete taps at one point.

    Args:
        start: Timestamp of the first finger-down.
        n: The tap count.
        step: Milliseconds between taps.
        x: The x coordinate.
        y: The y coordinate.

    Returns:
        The finger-down and lift-off events, in order.
    """
    events: list[dict[str, Any]] = []
    for i in range(n):
        ts = start + i * step
        events.extend([_down(ts, x, y), _up(ts + 10, x, y)])
    return events


# =============================================================================
# Replay.capture / has_wireframes / screen_path
# =============================================================================


class TestReplayCapture:
    """``Replay.capture`` reads the recording type from the raw events."""

    def test_web_sample_is_dom(self) -> None:
        """The web sample replay is a DOM recording."""
        assert _replay(_load("sample-replay-001")).capture == "dom"

    @pytest.mark.parametrize(
        "name",
        [
            "android-wireframe-001",
            "rn-android-no-wireframe-001",
            "flutter-web-clicks-001",
        ],
    )
    def test_real_screenshot_replays(self, name: str) -> None:
        """Mobile and Flutter replays are screenshot recordings.

        Args:
            name: The fixture name.
        """
        assert _replay(_load(name)).capture == "screenshot"

    def test_empty_events_are_dom(self) -> None:
        """A replay with no events is a DOM recording."""
        assert _replay([]).capture == "dom"

    def test_to_dict_has_no_capture_key(self) -> None:
        """``capture`` is derived, so ``to_dict`` does not carry it."""
        assert "capture" not in _replay(_load("android-wireframe-001")).to_dict()


class TestReplayScreens:
    """``has_wireframes`` and ``screen_path``."""

    def test_android_replay_has_screens(self) -> None:
        """The Android replay has wireframes and a Home → Settings path."""
        replay = _replay(_load("android-wireframe-001"))
        assert replay.has_wireframes is True
        assert replay.screen_path() == ["Home", "Settings"]

    def test_screenshot_replay_without_wireframes(self) -> None:
        """A screenshot recording with wireframes off has no screens."""
        replay = _replay(_load("rn-android-no-wireframe-001"))
        assert replay.has_wireframes is False
        assert replay.screen_path() == []

    def test_web_replay_has_no_screens(self) -> None:
        """A web replay has no screens."""
        replay = _replay(_load("sample-replay-001"))
        assert replay.has_wireframes is False
        assert replay.screen_path() == []


# =============================================================================
# ReplayBundle.screens_df
# =============================================================================


class TestScreensDf:
    """One row per screen action across the bundle."""

    def test_rows_and_columns(self) -> None:
        """Rows carry the replay id, time, heading, fingerprint, count, text."""
        bundle = _bundle(
            _replay(_load("android-wireframe-001"), "a"),
            _replay(_load("sample-replay-001"), "w"),
        )
        df = bundle.screens_df
        assert list(df.columns) == _SCREEN_COLUMNS
        assert list(df["replay_id"]) == ["a", "a"]
        assert list(df["heading"]) == ["Home", "Settings"]
        assert all(isinstance(f, str) and len(f) == 12 for f in df["fingerprint"])
        assert all(n > 0 for n in df["element_count"])
        assert all(d.startswith("Wireframe: ") for d in df["description"])
        assert df["t"].is_monotonic_increasing

    def test_empty_bundle(self) -> None:
        """An empty bundle gives an empty frame with the columns."""
        df = _bundle().screens_df
        assert df.empty
        assert list(df.columns) == _SCREEN_COLUMNS

    def test_cached(self) -> None:
        """The projection is computed once."""
        bundle = _bundle(_replay(_load("android-wireframe-001")))
        assert bundle.screens_df is bundle.screens_df


# =============================================================================
# finger_downs
# =============================================================================


class TestFingerDowns:
    """Finger-downs come from the raw events, not from emitted taps."""

    def test_counts_every_finger_down_and_click(self) -> None:
        """TOUCH_START and CLICK both count; lift-offs and other types do not."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            _down(2000),
            _down(2100, 300, 300),  # overlapping second finger
            _up(2200),
            _up(2300, 300, 300),
            _down(3000, kind=2),  # a screenshot click
            _down(3100, kind=1),  # MouseDown: not a finger-down
        ]
        downs = finger_downs(events)
        assert [(d.timestamp, d.x, d.y) for d in downs] == [
            (2000, 100, 100),
            (2100, 300, 300),
            (3000, 100, 100),
        ]
        assert downs[0] == FingerDown(2000, 100, 100, "button:Add")
        assert downs[1].target_desc == "(300, 300)"

    def test_dom_recording_has_none(self) -> None:
        """A DOM recording gives no finger-downs."""
        assert finger_downs([_meta(1, "/x"), _down(2000)]) == []

    def test_skips_unusable_events(self) -> None:
        """Downs without coordinates, bad timestamps, and junk entries are skipped."""
        events: list[Any] = [
            _meta(1),
            "junk",
            _down(0),
            {"type": 3, "timestamp": 5, "data": {"source": 2, "type": 7}},
            {"type": 3, "timestamp": "x", "data": "junk"},
            _down(2000, 4, 5),
        ]
        assert finger_downs(events) == [FingerDown(2000, 4, 5, "(4, 5)")]

    def test_target_uses_the_screen_current_at_the_down(self) -> None:
        """The target comes from the latest screen at the finger-down."""
        events = [
            _meta(1, None),
            _screen(1000, "Home"),
            _down(2000, 10, 10),
            {
                "type": 5,
                "timestamp": 2500,
                "data": {
                    "tag": "mp_wireframe",
                    "payload": {
                        "elements": [
                            {
                                "role": "switch",
                                "text": "Wi-Fi",
                                "bounds": [0, 0, 20, 20],
                            }
                        ]
                    },
                },
            },
            _down(3000, 10, 10),
        ]
        assert [d.target_desc for d in finger_downs(events)] == [
            "(10, 10)",
            "switch:Wi-Fi",
        ]


# =============================================================================
# ReplayBundle.rage_taps
# =============================================================================


class TestRageTaps:
    """Bursts of finger-downs near one point, classified by screen changes."""

    def test_dead_burst(self) -> None:
        """A burst with no screen change is ``dead``."""
        events = [_meta(1), _screen(1000, "Home"), *_taps(2000, 4)]
        df = _bundle(_replay(events)).rage_taps()
        assert list(df.columns) == _RAGE_COLUMNS
        assert len(df) == 1
        row = df.iloc[0]
        assert (row["kind"], row["count"]) == ("dead", 4)
        assert (row["t_start"], row["t_end"]) == (2000, 2300)
        assert (row["x"], row["y"], row["target_desc"]) == (100, 100, "button:Add")

    def test_rage_burst_changes_once_after(self) -> None:
        """A burst followed by one screen change is ``rage``."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            *_taps(2000, 4),
            _screen(2800, "Cart"),
        ]
        df = _bundle(_replay(events)).rage_taps()
        assert list(df["kind"]) == ["rage"]

    def test_change_after_the_grace_period_is_dead(self) -> None:
        """A screen change later than the grace period does not count."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            *_taps(2000, 4),
            _screen(3400, "Later"),
        ]
        bundle = _bundle(_replay(events))
        assert list(bundle.rage_taps()["kind"]) == ["dead"]
        assert list(bundle.rage_taps(grace_ms=2000)["kind"]) == ["rage"]

    def test_intentional_stepper_is_not_reported(self) -> None:
        """A burst where each tap changes the screen is intentional."""
        events: list[dict[str, Any]] = [_meta(1), _screen(1000, "Qty 0")]
        for i in range(4):
            ts = 2000 + i * 200
            events.extend([_down(ts), _up(ts + 10), _screen(ts + 50, f"Qty {i + 1}")])
        assert _bundle(_replay(events)).rage_taps().empty

    def test_threshold(self) -> None:
        """Fewer finger-downs than the threshold is not a burst."""
        events = [_meta(1), _screen(1000, "Home"), *_taps(2000, 3)]
        bundle = _bundle(_replay(events))
        assert len(bundle.rage_taps()) == 1
        assert bundle.rage_taps(threshold=4).empty

    def test_window(self) -> None:
        """Finger-downs spread wider than the window split apart."""
        events = [_meta(1), _screen(1000, "Home"), *_taps(2000, 4, step=900)]
        bundle = _bundle(_replay(events))
        assert bundle.rage_taps().iloc[0]["count"] == 3
        assert bundle.rage_taps(window_ms=3000).iloc[0]["count"] == 4

    def test_radius(self) -> None:
        """Finger-downs farther apart than the radius are not one burst."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            _down(2000, 100, 100),
            _down(2100, 130, 100),
            _down(2200, 100, 130),
        ]
        bundle = _bundle(_replay(events))
        assert bundle.rage_taps().empty
        assert bundle.rage_taps(radius_px=30).iloc[0]["count"] == 3

    def test_interleaved_tap_elsewhere_does_not_break_the_burst(self) -> None:
        """A finger-down at another point inside the window is skipped."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            _down(2000),
            _down(2050, 350, 700),
            _down(2100),
            _down(2200),
        ]
        df = _bundle(_replay(events)).rage_taps()
        assert list(df["count"]) == [3]

    def test_counts_finger_downs_not_emitted_taps(self) -> None:
        """Overlapping fingers and drifting lift-offs still count as downs."""
        events = [_meta(1), _screen(1000, "Home")]
        for i in range(4):
            ts = 2000 + i * 100
            events.append(_down(ts))
        for i in range(4):
            events.append(_up(2500 + i * 10, 100, 400))  # lift-offs far away
        replay = _replay(events)
        taps = [a for a in replay.actions if a.action == "touch_start"]
        assert len(taps) < 4
        assert list(_bundle(replay).rage_taps()["count"]) == [4]

    def test_screenshot_clicks_count(self) -> None:
        """Mouse clicks in a screenshot recording count as finger-downs."""
        events = [
            _meta(1),
            _screen(1000, "Home"),
            *[_down(2000 + i * 100, kind=2) for i in range(3)],
        ]
        assert list(_bundle(_replay(events)).rage_taps()["count"]) == [3]

    def test_dom_replay_is_ignored(self) -> None:
        """A web replay never reports rage taps (``rage_clicks`` covers web)."""
        events = [_meta(1, "/x"), *[_down(2000 + i * 100) for i in range(5)]]
        assert _bundle(_replay(events)).rage_taps().empty

    def test_empty_bundle(self) -> None:
        """An empty bundle gives an empty frame with the columns."""
        df = _bundle().rage_taps()
        assert df.empty
        assert list(df.columns) == _RAGE_COLUMNS

    def test_function_matches_method(self) -> None:
        """The bundle method is a thin wrapper over the aggregator."""
        bundle = _bundle(_replay([_meta(1), _screen(1000, "H"), *_taps(2000, 3)]))
        pd.testing.assert_frame_equal(bundle.rage_taps(), rage_taps(bundle))

    def test_flutter_android_bursts(self) -> None:
        """The real Flutter burst replay has three bursts: rage, rage, dead."""
        df = _bundle(_replay(_load("flutter-android-rage-001"), "f")).rage_taps()
        assert list(df["count"]) == [20, 33, 39]
        assert list(df["kind"]) == ["rage", "rage", "dead"]
        assert list(zip(df["x"], df["y"], strict=True)) == [
            (257, 638),
            (275, 368),
            (244, 678),
        ]
        assert all(df["t_end"] - df["t_start"] <= 2000)
        assert set(df["replay_id"]) == {"f"}
