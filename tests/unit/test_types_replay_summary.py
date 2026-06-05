"""Unit tests for ReplaySummary (044-session-replay, data-model §2.1)."""

from __future__ import annotations

import json

import pytest

from mixpanel_headless.types import ReplaySummary


def _build(**overrides: object) -> ReplaySummary:
    """Build a ReplaySummary with sensible defaults; override per-test as needed."""
    defaults: dict[str, object] = {
        "replay_id": "r-19221",
        "distinct_id": "user-42",
        "project_id": 3713224,
        "start_time": 1716810000000,
        "retention_days": 30,
    }
    defaults.update(overrides)
    return ReplaySummary(**defaults)  # type: ignore[arg-type]


class TestReplaySummaryConstruction:
    """Construction-time validation per data-model.md §2.1."""

    def test_happy_path(self) -> None:
        """All fields populated correctly."""
        s = _build()
        assert s.replay_id == "r-19221"
        assert s.distinct_id == "user-42"
        assert s.project_id == 3713224
        assert s.start_time == 1716810000000
        assert s.retention_days == 30

    def test_distinct_id_none_allowed(self) -> None:
        """distinct_id may be None for anonymous sessions."""
        s = _build(distinct_id=None)
        assert s.distinct_id is None

    def test_empty_replay_id_rejected(self) -> None:
        """replay_id must be non-empty."""
        with pytest.raises(ValueError, match="replay_id"):
            _build(replay_id="")

    def test_non_positive_project_id_rejected(self) -> None:
        """project_id must be positive."""
        with pytest.raises(ValueError, match="project_id"):
            _build(project_id=0)
        with pytest.raises(ValueError, match="project_id"):
            _build(project_id=-1)

    def test_non_positive_start_time_rejected(self) -> None:
        """start_time must be a positive unix ms timestamp."""
        with pytest.raises(ValueError, match="start_time"):
            _build(start_time=0)
        with pytest.raises(ValueError, match="start_time"):
            _build(start_time=-1)

    @pytest.mark.parametrize("bad_retention", [0, 2, 5, 14, 60, 100])
    def test_invalid_retention_rejected(self, bad_retention: int) -> None:
        """retention_days must be in {1, 7, 30, 90}."""
        with pytest.raises(ValueError, match="retention_days"):
            _build(retention_days=bad_retention)

    @pytest.mark.parametrize("good_retention", [1, 7, 30, 90])
    def test_valid_retention_accepted(self, good_retention: int) -> None:
        """All four allowed retention values construct cleanly."""
        s = _build(retention_days=good_retention)
        assert s.retention_days == good_retention


class TestReplaySummaryRoundTrip:
    """to_dict() preserves every field."""

    def test_to_dict_round_trip(self) -> None:
        """All fields make it through to_dict()."""
        s = _build()
        d = s.to_dict()
        assert d["replay_id"] == "r-19221"
        assert d["distinct_id"] == "user-42"
        assert d["project_id"] == 3713224
        assert d["start_time"] == 1716810000000
        assert d["retention_days"] == 30

    def test_to_dict_json_serializable(self) -> None:
        """to_dict output round-trips through json.dumps."""
        json.dumps(_build().to_dict())


class TestReplaySummaryDataFrame:
    """ResultWithDataFrame.df returns a single-row DataFrame."""

    def test_df_single_row(self) -> None:
        """df has one row per summary, with the documented columns."""
        s = _build()
        df = s.df
        assert len(df) == 1
        for col in (
            "replay_id",
            "distinct_id",
            "project_id",
            "start_time",
            "retention_days",
        ):
            assert col in df.columns
        assert df.iloc[0]["replay_id"] == "r-19221"
        assert df.iloc[0]["retention_days"] == 30

    def test_df_cached(self) -> None:
        """Second .df access returns the same cached object."""
        s = _build()
        assert s.df is s.df
