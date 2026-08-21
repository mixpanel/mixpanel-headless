"""Unit tests for Replay (044-session-replay, data-model §2.5).

The analyzer has shipped: ``Workspace.fetch_replay()`` runs ``RrwebAnalyzer``
and populates ``actions``. For an actionless replay (``actions=[]``, e.g. a
unit-test fixture), the analyzer-dependent accessors (``summary_markdown``,
``errors``, ``clicks_on``) return safe defaults rather than raising.
"""

from __future__ import annotations

import pytest

from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import Replay, ReplayEvent, UserAction


def _meta(ts: int, href: str) -> dict[str, object]:
    """Build a Meta-type rrweb event for fixtures."""
    return {
        "type": 4,
        "data": {"href": href, "width": 1280, "height": 800},
        "timestamp": ts,
    }


def _click(ts: int, node_id: int) -> dict[str, object]:
    """Build an IncrementalSnapshot Click event for fixtures."""
    return {
        "type": 3,
        "data": {"source": 2, "type": 2, "id": node_id, "x": 100, "y": 200},
        "timestamp": ts,
    }


def _full_snapshot(ts: int) -> dict[str, object]:
    """Build a FullSnapshot event for fixtures."""
    return {
        "type": 2,
        "data": {
            "node": {"id": 1, "type": 0, "childNodes": []},
            "initialOffset": {"left": 0, "top": 0},
        },
        "timestamp": ts,
    }


def _build(
    *,
    rrweb_events: list[dict[str, object]] | None = None,
    actions: list[UserAction] | None = None,
    mixpanel_events: list[ReplayEvent] | None = None,
) -> Replay:
    """Build a Replay with a tiny event stream by default."""
    events = (
        rrweb_events
        if rrweb_events is not None
        else [
            _meta(1716810000000, "https://app.example.com/login"),
            _full_snapshot(1716810000500),
            _click(1716810002000, 13),
            _meta(1716810005000, "https://app.example.com/dashboard"),
        ]
    )
    return Replay(
        replay_id="r-19221",
        distinct_id="user-42",
        project_id=3713224,
        start_time=1716810000000,
        end_time=1716810015000,
        retention_days=30,
        rrweb_events=events,
        actions=actions if actions is not None else [],
        mixpanel_events=mixpanel_events if mixpanel_events is not None else [],
    )


class TestReplayConvenience:
    """duration_seconds, to_rrweb_player_json, page_path."""

    def test_duration_seconds(self) -> None:
        """duration_seconds == (end_time - start_time) / 1000."""
        r = _build()
        assert r.duration_seconds == 15.0

    def test_to_rrweb_player_json_returns_sorted_dicts(self) -> None:
        """to_rrweb_player_json returns timestamp-sorted dicts."""
        unsorted = [
            _click(1716810002000, 13),
            _meta(1716810000000, "https://app.example.com/login"),
            _meta(1716810005000, "https://app.example.com/dashboard"),
        ]
        r = _build(rrweb_events=unsorted)
        out = r.to_rrweb_player_json()
        timestamps = [int(e["timestamp"]) for e in out]
        assert timestamps == sorted(timestamps)

    def test_page_path(self) -> None:
        """page_path returns the URL sequence from navigate actions."""
        actions = [
            UserAction(
                timestamp=1716810000000,
                action="navigate",
                target_node_id=None,
                target_desc="Navigated to https://app.example.com/login",
                url="https://app.example.com/login",
                metadata={},
            ),
            UserAction(
                timestamp=1716810005000,
                action="navigate",
                target_node_id=None,
                target_desc="Navigated to https://app.example.com/dashboard",
                url="https://app.example.com/dashboard",
                metadata={},
            ),
        ]
        r = _build(actions=actions)
        path = r.page_path()
        assert path == [
            "https://app.example.com/login",
            "https://app.example.com/dashboard",
        ]


class TestReplayEventsDataFrame:
    """events_df derives from raw rrweb events (data-model §2.5)."""

    def test_columns_documented(self) -> None:
        """events_df has t, type, source, mouse_type, target_node_id, url, raw."""
        r = _build()
        df = r.events_df
        for col in (
            "t",
            "type",
            "source",
            "mouse_type",
            "target_node_id",
            "url",
            "raw",
        ):
            assert col in df.columns

    def test_row_per_event(self) -> None:
        """Each rrweb event produces one row."""
        r = _build()
        assert len(r.events_df) == len(r.rrweb_events)


class TestReplayActionsDefaultEmpty:
    """With no analyzer output, actions defaults to empty; actions_df keeps its schema."""

    def test_actions_default_empty(self) -> None:
        """actions defaults to an empty list."""
        assert _build().actions == []

    def test_actions_df_empty_with_schema(self) -> None:
        """actions_df is empty but carries the documented columns."""
        df = _build().actions_df
        assert len(df) == 0
        for col in (
            "t",
            "action",
            "target_node_id",
            "target_desc",
            "description",
            "url",
            "metadata",
        ):
            assert col in df.columns

    def test_df_default_is_actions_df(self) -> None:
        """Replay.df returns actions_df (default projection per FR-018)."""
        r = _build()
        assert r.df.equals(r.actions_df)


class TestReplayAnalyzerAccessorsEmptyActions:
    """With actions=[] the analyzer accessors return safe defaults.

    When the Replay is hand-constructed with actions=[] (e.g. a unit-test
    fixture) the analyzer-dependent accessors still return sensible
    empty/placeholder values rather than raise.
    """

    def test_summary_markdown_placeholder(self) -> None:
        """summary_markdown returns a one-line placeholder for an actionless replay."""
        out = _build().summary_markdown
        assert "no actions extracted" in out

    def test_errors_empty(self) -> None:
        """errors returns an empty DataFrame for an actionless replay."""
        out = _build().errors
        assert len(out) == 0

    def test_clicks_on_empty(self) -> None:
        """clicks_on returns an empty DataFrame for an actionless replay."""
        out = _build().clicks_on(lambda _a: True)
        assert len(out) == 0


class TestReplayMixpanelDataFrame:
    """mixpanel_df shape — empty unless mixpanel_events is populated."""

    def test_mixpanel_df_empty_default(self) -> None:
        """mixpanel_df is empty when mixpanel_events == [] (default)."""
        df = _build().mixpanel_df
        assert len(df) == 0
        for col in ("t", "event_name", "properties"):
            assert col in df.columns


# =============================================================================
# E2 coding pass — coded guard tests (class + .code assertions only, R5.4)
# =============================================================================


def _build_kwargs(**overrides: object) -> dict[str, object]:
    """Valid Replay constructor kwargs; override per-test to violate a guard."""
    defaults: dict[str, object] = {
        "replay_id": "r-19221",
        "distinct_id": "user-42",
        "project_id": 3713224,
        "start_time": 1716810000000,
        "end_time": 1716810015000,
        "retention_days": 30,
        "rrweb_events": [],
        "actions": [],
        "mixpanel_events": [],
    }
    defaults.update(overrides)
    return defaults


class TestCodedReplayCodes:
    """Coded-guard tests for Replay (RP1-RP5, design §1.4)."""

    @pytest.mark.parametrize(
        ("overrides", "code"),
        [
            ({"replay_id": ""}, "RP1_EMPTY_REPLAY_ID"),
            ({"replay_id": None}, "RP1_EMPTY_REPLAY_ID"),
            ({"project_id": 0}, "RP2_PROJECT_ID_NOT_POSITIVE"),
            ({"project_id": -1}, "RP2_PROJECT_ID_NOT_POSITIVE"),
            ({"start_time": 0}, "RP3_START_TIME_NOT_POSITIVE"),
            ({"start_time": -9}, "RP3_START_TIME_NOT_POSITIVE"),
            ({"end_time": 1716809999999}, "RP4_TIME_ORDER"),
            ({"end_time": 1}, "RP4_TIME_ORDER"),
            ({"retention_days": 2}, "RP5_INVALID_RETENTION_DAYS"),
            ({"retention_days": 365}, "RP5_INVALID_RETENTION_DAYS"),
        ],
    )
    def test_guard_raises_coded_error(
        self, overrides: dict[str, object], code: str
    ) -> None:
        """Each Replay guard raises ParamValidationError with its code."""
        with pytest.raises(ParamValidationError) as excinfo:
            Replay(**_build_kwargs(**overrides))  # type: ignore[arg-type]
        assert excinfo.value.code == code
