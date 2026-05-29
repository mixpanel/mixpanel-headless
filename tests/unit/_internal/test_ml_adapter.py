"""Skipif-gated tests for the tslearn clustering path (044, US4/T075).

These run only when ``mixpanel-headless[replay-ml]`` (tslearn) is installed;
otherwise the module is skipped. The tslearn-absent ``ImportError`` path is
covered by ``tests/unit/test_us2_replay_bundle.py``.
"""

from __future__ import annotations

import importlib.util

import pytest

from mixpanel_headless.types import Replay, ReplayBundle, UserAction

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("tslearn") is None,
    reason="tslearn ([replay-ml] extra) not installed",
)


def _action(ts: int, action: str, *, url: str, desc: str) -> UserAction:
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


def _bundle(n: int = 6) -> ReplayBundle:
    """An n-replay bundle with two distinct action-sequence shapes.

    Half the replays follow a short click pattern and half a longer
    navigate-heavy pattern, so DTW k-means has structure to separate.
    """
    base = 1_716_810_000_000
    replays: list[Replay] = []
    for i in range(n):
        if i % 2 == 0:
            actions = [
                _action(base, "click", url="https://app.test/a", desc="x"),
                _action(base + 500, "click", url="https://app.test/a", desc="y"),
            ]
        else:
            actions = [
                _action(base, "navigate", url="https://app.test/a", desc="a"),
                _action(base + 500, "navigate", url="https://app.test/b", desc="b"),
                _action(base + 1000, "navigate", url="https://app.test/c", desc="c"),
                _action(base + 1500, "click", url="https://app.test/c", desc="z"),
            ]
        replays.append(_replay(f"r-{i}", actions))
    return ReplayBundle(
        replays=replays,
        computed_at="2026-05-28T00:00:00+00:00",
        project_id=12345,
    )


class TestClusterWithTslearn:
    """cluster() assigns every replay a cluster_label via DTW k-means."""

    def test_labels_every_replay_in_range(self) -> None:
        """cluster(n=2) tags each replay with a label in {0, 1}."""
        clustered = _bundle(6).cluster(n=2, seed=0)
        labels = [getattr(r, "cluster_label", None) for r in clustered.replays]
        assert len(labels) == 6
        assert all(label in {0, 1} for label in labels)

    def test_deterministic_with_seed(self) -> None:
        """A fixed seed yields identical labels across runs."""
        first = [r.cluster_label for r in _bundle(6).cluster(n=2, seed=7).replays]  # type: ignore[attr-defined]
        second = [r.cluster_label for r in _bundle(6).cluster(n=2, seed=7).replays]  # type: ignore[attr-defined]
        assert first == second

    def test_original_bundle_unmutated(self) -> None:
        """Clustering returns a new bundle; the source replays gain no label."""
        bundle = _bundle(6)
        bundle.cluster(n=2, seed=0)
        assert not hasattr(bundle.replays[0], "cluster_label")

    def test_features_pages(self) -> None:
        """features='pages' clusters on page sequences and labels every replay."""
        clustered = _bundle(6).cluster(n=2, features="pages", seed=0)
        labels = [getattr(r, "cluster_label", None) for r in clustered.replays]
        assert all(label in {0, 1} for label in labels)
