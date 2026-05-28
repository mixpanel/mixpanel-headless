"""Unit tests for Workspace replay methods (044-session-replay).

These tests verify the Workspace-level wiring and validation:
- list_replays argument validation (XOR, date window required)
- events_for_replay's <=5-properties cap
- fetch_replay's include_mixpanel_events flow
- replays_for_user stub raises NotImplementedError until US2 lands

The ReplaysService is replaced with a MagicMock on each constructed
Workspace so we can assert on the calls without doing real I/O. A separate
test that exercises ReplaysService.discover with a mocked query_fn is in
tests/unit/_internal/test_replays_service.py.
"""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import MagicMock

import pytest

import mixpanel_headless as mp
from mixpanel_headless.types import (
    Replay,
    ReplayEvent,
    ReplaySummary,
    SignedReplay,
)
from tests.conftest import make_session

# =============================================================================
# Fixtures
# =============================================================================


def _make_workspace(api_client_mock: MagicMock | None = None) -> mp.Workspace:
    """Build a Workspace bound to a fake session for unit tests."""
    api = api_client_mock or MagicMock()
    api.project_id = "12345"
    return mp.Workspace(session=make_session(), _api_client=api)


def _install_mock_replays_service(ws: mp.Workspace) -> MagicMock:
    """Replace the workspace's lazy ReplaysService with a MagicMock."""
    svc = MagicMock()
    ws._replays_svc = svc
    return svc


def _summary(
    replay_id: str = "r-1",
    *,
    retention_days: int = 30,
    distinct_id: str | None = "u-42",
) -> ReplaySummary:
    """Build a ReplaySummary for fixture seeding."""
    return ReplaySummary(
        replay_id=replay_id,
        distinct_id=distinct_id,
        project_id=12345,
        start_time=1716810000000,
        retention_days=retention_days,
    )


def _signed(replay_id: str = "r-1") -> SignedReplay:
    """Build a SignedReplay for fixture seeding."""
    return SignedReplay(
        replay_id=replay_id,
        url="https://cdn.test/srr-us/sha/",
        query_string="URLPrefix=A&Signature=S",
        env="prod",
        signed_at=1716810000.0,
    )


# =============================================================================
# list_replays validation
# =============================================================================


class TestListReplaysValidation:
    """Argument validation matches error-messages.md §5."""

    def test_neither_arg_raises(self) -> None:
        """list_replays with no args raises ValueError."""
        ws = _make_workspace()
        _install_mock_replays_service(ws)
        with pytest.raises(ValueError, match="exactly one"):
            ws.list_replays()

    def test_both_args_raise(self) -> None:
        """Both distinct_id and replay_ids raises ValueError."""
        ws = _make_workspace()
        _install_mock_replays_service(ws)
        with pytest.raises(ValueError, match="both were given"):
            ws.list_replays(distinct_id="u-1", replay_ids=["r-1"])

    def test_distinct_id_without_window_raises(self) -> None:
        """distinct_id without from_date/to_date raises ValueError."""
        ws = _make_workspace()
        _install_mock_replays_service(ws)
        with pytest.raises(ValueError, match="from_date"):
            ws.list_replays(distinct_id="u-1")
        with pytest.raises(ValueError, match="from_date"):
            ws.list_replays(distinct_id="u-1", from_date="2026-05-20")

    def test_replay_ids_without_window_works(self) -> None:
        """replay_ids alone is enough — date window is inferred."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.discover.return_value = []
        result = ws.list_replays(replay_ids=["r-1"])
        assert result == []
        svc.discover.assert_called_once()

    def test_empty_result_returns_empty_list(self) -> None:
        """Empty discovery → empty list (not raise)."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.discover.return_value = []
        out = ws.list_replays(
            distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
        )
        assert out == []


# =============================================================================
# list_replays issues the documented query call
# =============================================================================


class TestListReplaysQueryCall:
    """ReplaysService.discover sees the right kwargs from list_replays."""

    def test_distinct_id_path_delegates(self) -> None:
        """list_replays passes distinct_id + dates straight through to discover."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.discover.return_value = [_summary()]

        result = ws.list_replays(
            distinct_id="u-42",
            from_date="2026-05-20",
            to_date="2026-05-27",
        )

        assert result == [_summary()]
        svc.discover.assert_called_once_with(
            distinct_id="u-42",
            replay_ids=None,
            from_date="2026-05-20",
            to_date="2026-05-27",
            limit=100,
        )

    def test_discover_uses_workspace_query(self) -> None:
        """Real ReplaysService.discover calls the bound Workspace.query.

        Exercises the actual delegation path: build a Workspace, swap its
        query method for a Mock, then call list_replays. The query Mock
        should see ``$mp_session_record`` plus group_by keys.
        """
        from mixpanel_headless._internal.services.replays import ReplaysService

        query_mock = MagicMock()
        # query() returns an object with .df — empty DataFrame keeps the
        # parser path simple (returns []).
        import pandas as pd

        query_mock.return_value = MagicMock(df=pd.DataFrame())

        ws = _make_workspace()
        # Replace the lazy service with one that uses the mocked query_fn.
        ws._replays_svc = ReplaysService(ws._require_api_client(), query_fn=query_mock)

        ws.list_replays(
            distinct_id="u-42",
            from_date="2026-05-20",
            to_date="2026-05-27",
        )

        assert query_mock.call_count == 1
        # The single positional arg is the event name.
        args, kwargs = query_mock.call_args
        assert args[0] == "$mp_session_record"
        # group_by must include both replay-id and retention.
        gb = kwargs.get("group_by", [])
        assert "$mp_replay_id" in gb
        assert "$mp_replay_retention_period" in gb
        assert kwargs.get("from_date") == "2026-05-20"
        assert kwargs.get("to_date") == "2026-05-27"


# =============================================================================
# Retention default + UserWarning
# =============================================================================


class TestRetentionWarning:
    """Missing $mp_replay_retention_period defaults to 30 with UserWarning."""

    def test_missing_retention_emits_userwarning(self) -> None:
        """A discover result missing retention triggers UserWarning + default 30."""
        import pandas as pd

        from mixpanel_headless._internal.services.replays import ReplaysService

        query_mock = MagicMock()
        # Synthetic discover result: rows have $mp_replay_id and $time but
        # $mp_replay_retention_period is missing → parser defaults to 30.
        query_mock.return_value = MagicMock(
            df=pd.DataFrame(
                [
                    {
                        "$mp_replay_id": "r-1",
                        "$mp_replay_retention_period": None,
                        "$time": 1716810000000,
                    }
                ]
            )
        )

        ws = _make_workspace()
        ws._replays_svc = ReplaysService(ws._require_api_client(), query_fn=query_mock)

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            result = ws.list_replays(
                distinct_id="u-42",
                from_date="2026-05-20",
                to_date="2026-05-27",
            )

        assert len(result) == 1
        assert result[0].retention_days == 30
        # At least one UserWarning fired naming the missing property.
        assert any(
            issubclass(w.category, UserWarning)
            and "$mp_replay_retention_period" in str(w.message)
            for w in recorded
        )


# =============================================================================
# events_for_replay validation
# =============================================================================


class TestEventsForReplayValidation:
    """5-property cap on event_properties matches error-messages.md §4."""

    def test_six_properties_raises_valueerror(self) -> None:
        """events_for_replay with 6 props raises ValueError naming the cap."""
        ws = _make_workspace()
        _install_mock_replays_service(ws)
        with pytest.raises(ValueError, match="at most 5"):
            ws.events_for_replay("r-1", event_properties=["a", "b", "c", "d", "e", "f"])

    def test_six_properties_raises_for_batched_variant(self) -> None:
        """events_for_replays enforces the same cap."""
        ws = _make_workspace()
        _install_mock_replays_service(ws)
        with pytest.raises(ValueError, match="at most 5"):
            ws.events_for_replays(
                ["r-1"], event_properties=["a", "b", "c", "d", "e", "f"]
            )

    def test_five_properties_ok(self) -> None:
        """Exactly 5 properties hits the cap inclusively (no raise)."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.events_for.return_value = {}
        ws.events_for_replay("r-1", event_properties=["a", "b", "c", "d", "e"])
        svc.events_for.assert_called_once()


# =============================================================================
# fetch_replay flow
# =============================================================================


class TestFetchReplay:
    """fetch_replay signs, fetches, and optionally joins Mixpanel events."""

    def test_explicit_retention_skips_discovery(self) -> None:
        """retention_days set → no list_replays call, single sign + fetch."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.sign.return_value = [_signed()]
        svc.fetch_files.return_value = [
            {"type": 4, "data": {}, "timestamp": 1716810000000},
            {"type": 3, "data": {}, "timestamp": 1716810015000},
        ]

        replay = ws.fetch_replay("r-1", retention_days=30)

        # discover should NOT have been called.
        svc.discover.assert_not_called()
        # sign + fetch_files should have fired once each.
        svc.sign.assert_called_once()
        svc.fetch_files.assert_called_once()
        # Phase 1 invariants on the result.
        assert isinstance(replay, Replay)
        assert replay.replay_id == "r-1"
        assert replay.actions == []
        assert replay.duration_seconds == 15.0
        assert replay.mixpanel_events == []

    def test_include_mixpanel_events_triggers_follow_up(self) -> None:
        """include_mixpanel_events=True populates Replay.mixpanel_events."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.sign.return_value = [_signed()]
        svc.fetch_files.return_value = [
            {"type": 4, "data": {}, "timestamp": 1716810000000},
            {"type": 3, "data": {}, "timestamp": 1716810005000},
        ]
        svc.events_for.return_value = {
            "r-1": [
                ReplayEvent(
                    replay_id="r-1",
                    event_name="Login",
                    event_time=1716810002,
                    properties={"$browser": "Chrome"},
                )
            ]
        }

        replay = ws.fetch_replay("r-1", retention_days=30, include_mixpanel_events=True)

        # events_for fired exactly once.
        svc.events_for.assert_called_once()
        assert len(replay.mixpanel_events) == 1
        assert replay.mixpanel_events[0].event_name == "Login"

    def test_default_skips_mixpanel_events(self) -> None:
        """Without include_mixpanel_events, events_for is not called."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.sign.return_value = [_signed()]
        svc.fetch_files.return_value = [
            {"type": 4, "data": {}, "timestamp": 1716810000000},
        ]
        ws.fetch_replay("r-1", retention_days=30)
        svc.events_for.assert_not_called()

    def test_retention_none_discovers(self) -> None:
        """retention_days=None triggers one list_replays(replay_ids=[id]) call."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.discover.return_value = [_summary(retention_days=7)]
        svc.sign.return_value = [_signed()]
        svc.fetch_files.return_value = [
            {"type": 4, "data": {}, "timestamp": 1716810000000},
        ]

        replay = ws.fetch_replay("r-1")  # no retention_days

        # discover called with replay_ids=["r-1"] (single-replay hydrate).
        svc.discover.assert_called_once_with(
            distinct_id=None,
            replay_ids=["r-1"],
            from_date=None,
            to_date=None,
            limit=100,
        )
        # fetch_files called with the discovered retention.
        _args, kwargs = svc.fetch_files.call_args
        assert kwargs["retention_days"] == 7
        assert replay.retention_days == 7


# =============================================================================
# replays_for_user stub
# =============================================================================


class TestReplaysForUserUS2:
    """Phase 2 / T062 — replays_for_user returns a ReplayBundle.

    Replaces the Phase 1 stub. The full coverage of bundle internals is
    in tests/unit/test_types_replay_bundle.py; here we only verify the
    composition (list_replays + fetch_replays) and the empty-result
    short-circuit.
    """

    def test_method_exists(self) -> None:
        """The Workspace class advertises replays_for_user."""
        ws = _make_workspace()
        assert hasattr(ws, "replays_for_user")

    def test_empty_window_returns_empty_bundle(self) -> None:
        """No replays in the window → empty bundle, no fetch_replays call."""
        from mixpanel_headless.types import ReplayBundle

        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.discover.return_value = []
        bundle = ws.replays_for_user(
            "u-42", from_date="2026-05-20", to_date="2026-05-27"
        )
        assert isinstance(bundle, ReplayBundle)
        assert bundle.replays == []
        svc.sign.assert_not_called()


# =============================================================================
# sign_replay / sign_replays
# =============================================================================


class TestSignReplaysWiring:
    """sign_replay/sign_replays delegate to ReplaysService.sign."""

    def test_sign_replay_returns_first_signed(self) -> None:
        """sign_replay is sugar over sign_replays([id])[0]."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.sign.return_value = [_signed("r-1")]
        out = ws.sign_replay("r-1")
        assert isinstance(out, SignedReplay)
        assert out.replay_id == "r-1"
        svc.sign.assert_called_once_with(["r-1"], env="prod")

    def test_sign_replays_passes_through(self) -> None:
        """sign_replays just delegates."""
        ws = _make_workspace()
        svc = _install_mock_replays_service(ws)
        svc.sign.return_value = [_signed("r-1"), _signed("r-2")]
        out = ws.sign_replays(["r-1", "r-2"], env="dev")
        assert [s.replay_id for s in out] == ["r-1", "r-2"]
        svc.sign.assert_called_once_with(["r-1", "r-2"], env="dev")


# Touch Any to keep the import meaningful for type-stubs scenarios.
_ = Any
