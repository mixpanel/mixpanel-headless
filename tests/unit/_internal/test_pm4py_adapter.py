"""Skipif-gated tests for the pm4py event-log path (044, US4/T074).

These run only when ``mixpanel-headless[replay-mining]`` (pm4py) is installed;
otherwise the whole module is skipped. The pm4py-absent DataFrame fallback is
covered by ``tests/unit/test_us2_replay_bundle.py``.

Contract under test (after QA finding #6): with pm4py installed,
``ReplayBundle.event_log()`` returns a pm4py-*formatted* ``DataFrame`` (via
``pm4py.format_dataframe``), NOT a ``pm4py.objects.log.obj.EventLog`` — pm4py
2.7+ treats a formatted DataFrame as a first-class event log and the mining
functions consume it directly.
"""

from __future__ import annotations

import importlib.util

import pandas as pd
import pytest

from mixpanel_headless.types import Replay, ReplayBundle, UserAction

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pm4py") is None,
    reason="pm4py ([replay-mining] extra) not installed",
)


def _action(ts: int, action: str, *, url: str | None, desc: str) -> UserAction:
    """Build a UserAction for the synthetic bundle."""
    return UserAction(
        timestamp=ts,
        action=action,  # type: ignore[arg-type]
        target_node_id=1,
        target_desc=desc,
        url=url,
        metadata={},
    )


def _replay(replay_id: str, actions: list[UserAction]) -> Replay:
    """Build a Replay carrying the given actions."""
    start = min(a.timestamp for a in actions)
    end = max(a.timestamp for a in actions)
    return Replay(
        replay_id=replay_id,
        distinct_id=None,
        project_id=12345,
        start_time=start,
        end_time=max(end, start),
        retention_days=30,
        rrweb_events=[{"type": 4, "data": {"href": "/"}, "timestamp": start}],
        actions=actions,
        mixpanel_events=[],
    )


def _bundle() -> ReplayBundle:
    """A two-replay bundle with a small click/navigate action stream."""
    base = 1_716_810_000_000
    r1 = _replay(
        "r-1",
        [
            _action(base, "navigate", url="https://app.test/login", desc="login"),
            _action(base + 1000, "click", url="https://app.test/login", desc="submit"),
            _action(base + 2000, "navigate", url="https://app.test/home", desc="home"),
        ],
    )
    r2 = _replay(
        "r-2",
        [
            _action(base + 50, "navigate", url="https://app.test/home", desc="home"),
            _action(base + 1500, "click", url="https://app.test/home", desc="cta"),
        ],
    )
    return ReplayBundle(
        replays=[r1, r2],
        computed_at="2026-05-28T00:00:00+00:00",
        project_id=12345,
    )


class TestEventLogWithPm4py:
    """event_log() returns a pm4py-formatted DataFrame the miner can consume."""

    def test_returns_pm4py_formatted_dataframe(self) -> None:
        """With pm4py present the result is a DataFrame carrying XES columns."""
        log = _bundle().event_log()
        assert isinstance(log, pd.DataFrame)
        assert "case:concept:name" in log.columns
        assert "concept:name" in log.columns
        assert "time:timestamp" in log.columns

    def test_consumable_by_inductive_miner(self) -> None:
        """The formatted frame feeds pm4py.discover_petri_net_inductive."""
        import pm4py

        net, init_marking, final_marking = pm4py.discover_petri_net_inductive(
            _bundle().event_log()
        )
        assert net is not None
        assert len(net.transitions) > 0

    def test_convertible_to_legacy_event_log(self) -> None:
        """Callers needing the object form can convert_to_event_log it."""
        import pm4py
        from pm4py.objects.log.obj import EventLog

        assert isinstance(pm4py.convert_to_event_log(_bundle().event_log()), EventLog)

    def test_custom_label_fn_drives_every_activity(self) -> None:
        """label_fn overrides the activity label for every row (FR-031)."""
        log = _bundle().event_log(label_fn=lambda _action: "CUSTOM")
        assert set(log["concept:name"].unique()) == {"CUSTOM"}
