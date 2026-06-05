"""Unit tests for ReplayEvent (044-session-replay, data-model §2.4)."""

from __future__ import annotations

import json

import pytest

from mixpanel_headless.types import ReplayEvent


def _build(**overrides: object) -> ReplayEvent:
    """Construct a ReplayEvent with sensible defaults."""
    defaults: dict[str, object] = {
        "replay_id": "r-19221",
        "event_name": "Login",
        "event_time": 1716810000,
        "properties": {"$browser": "Chrome", "plan": "pro"},
    }
    defaults.update(overrides)
    return ReplayEvent(**defaults)  # type: ignore[arg-type]


class TestReplayEventConstruction:
    """Construction validation per data-model.md §2.4."""

    def test_happy_path(self) -> None:
        """All fields populated."""
        e = _build()
        assert e.replay_id == "r-19221"
        assert e.event_name == "Login"
        assert e.event_time == 1716810000
        assert e.properties == {"$browser": "Chrome", "plan": "pro"}

    def test_properties_none_allowed(self) -> None:
        """properties may be None when the caller skips enrichment."""
        e = _build(properties=None)
        assert e.properties is None

    def test_empty_replay_id_rejected(self) -> None:
        """replay_id must be non-empty."""
        with pytest.raises(ValueError, match="replay_id"):
            _build(replay_id="")

    def test_empty_event_name_rejected(self) -> None:
        """event_name must be non-empty."""
        with pytest.raises(ValueError, match="event_name"):
            _build(event_name="")

    def test_non_positive_event_time_rejected(self) -> None:
        """event_time must be a positive unix seconds timestamp."""
        with pytest.raises(ValueError, match="event_time"):
            _build(event_time=0)
        with pytest.raises(ValueError, match="event_time"):
            _build(event_time=-1)


class TestReplayEventDataFrame:
    """ResultWithDataFrame.df projection (data-model §2.4)."""

    def test_columns_documented(self) -> None:
        """df has the documented columns."""
        df = _build().df
        for col in ("replay_id", "event_name", "event_time", "properties"):
            assert col in df.columns

    def test_single_row(self) -> None:
        """df is a single-row projection of one event."""
        df = _build().df
        assert len(df) == 1

    def test_values_round_trip(self) -> None:
        """Values in the row match the input."""
        df = _build().df
        row = df.iloc[0]
        assert row["replay_id"] == "r-19221"
        assert row["event_name"] == "Login"
        assert row["event_time"] == 1716810000


class TestReplayEventRoundTrip:
    """to_dict() preserves every field and is JSON-serializable."""

    def test_to_dict_round_trip(self) -> None:
        """All four fields are present after to_dict()."""
        d = _build().to_dict()
        assert d["replay_id"] == "r-19221"
        assert d["event_name"] == "Login"
        assert d["event_time"] == 1716810000
        assert d["properties"]["$browser"] == "Chrome"

    def test_to_dict_json_serializable(self) -> None:
        """JSON round-trip works."""
        json.dumps(_build().to_dict())
