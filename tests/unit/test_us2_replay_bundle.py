"""Combined US2 verification: analyzer + labels + aggregators + ReplayBundle.

This is the consolidated equivalent of T045-T052 from the task list.
Tests are organized by component but stay lean — exercising the public
contracts documented in data-model.md §2.6 and contracts/python-api.md §4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mixpanel_headless._internal.replays.aggregators import (
    long_pauses,
    rage_clicks,
    top_clicks,
)
from mixpanel_headless._internal.replays.labels import (
    default_label_fn,
    selector_label_fn,
    url_normalizer,
)
from mixpanel_headless._internal.replays.rrweb_analyzer import RrwebAnalyzer
from mixpanel_headless.types import (
    Replay,
    ReplayBundle,
    UserAction,
)

_FIXTURE_001 = Path("tests/fixtures/rrweb/sample-replay-001.json")


# =============================================================================
# Helpers
# =============================================================================


def _load_sample(path: Path = _FIXTURE_001) -> list[dict[str, Any]]:
    """Load the hand-built sample rrweb stream for analyzer tests."""
    with path.open() as f:
        events = json.load(f)
    return events  # type: ignore[no-any-return]


def _build_action(
    timestamp: int = 1716810000000,
    action: str = "click",
    target_desc: str = "button",
    url: str | None = "https://example.com/login",
    metadata: dict[str, Any] | None = None,
) -> UserAction:
    """Construct a UserAction for label / aggregator tests."""
    return UserAction(
        timestamp=timestamp,
        action=action,  # type: ignore[arg-type]
        target_node_id=1,
        target_desc=target_desc,
        url=url,
        metadata=metadata or {},
    )


def _make_replay(replay_id: str, actions: list[UserAction]) -> Replay:
    """Build a Replay with the given actions for bundle tests."""
    if actions:
        start = min(a.timestamp for a in actions)
        end = max(a.timestamp for a in actions)
    else:
        start = 1716810000000
        end = 1716810060000
    return Replay(
        replay_id=replay_id,
        distinct_id=None,
        project_id=12345,
        start_time=start,
        end_time=max(end, start),
        retention_days=30,
        rrweb_events=[
            {"type": 4, "data": {"href": a.url}, "timestamp": a.timestamp}
            for a in actions
            if a.action == "navigate"
        ]
        or [{"type": 4, "data": {"href": "/"}, "timestamp": start}],
        actions=actions,
        mixpanel_events=[],
    )


# =============================================================================
# Labels
# =============================================================================


class TestUrlNormalizer:
    """url_normalizer collapses parameterized URLs."""

    def test_strips_query_string(self) -> None:
        """Query strings disappear."""
        assert url_normalizer("/x?a=1&b=2") == "/x"

    def test_replaces_numeric_segments(self) -> None:
        """Numeric path segments become :id."""
        assert url_normalizer("/users/12345/profile") == "/users/:id/profile"

    def test_preserves_host(self) -> None:
        """Host portion stays when the URL is absolute."""
        out = url_normalizer("https://app.example.com/users/12345/profile?ref=x")
        assert out == "https://app.example.com/users/:id/profile"

    def test_empty_url(self) -> None:
        """Empty input returns empty (no crash)."""
        assert url_normalizer("") == ""


class TestDefaultLabelFn:
    """default_label_fn produces the canonical action:tag@url shape."""

    def test_label_shape(self) -> None:
        """Label is "{action}:{tag}@{normalized_url}"."""
        action = _build_action(
            target_desc='button "Sign in"',
            url="/users/12345/profile?ref=x",
        )
        assert default_label_fn(action) == 'click:button "Sign in"@/users/:id/profile'

    def test_no_url(self) -> None:
        """Missing URL becomes (no-url) placeholder."""
        action = _build_action(url=None)
        assert "@(no-url)" in default_label_fn(action)


class TestSelectorLabelFn:
    """selector_label_fn prefers stable attributes when present."""

    def test_uses_data_testid_when_present(self) -> None:
        """data-testid attribute wins over target_desc."""
        fn = selector_label_fn("data-testid")
        action = _build_action(
            target_desc="some long ugly description",
            metadata={"data-testid": "signin-button"},
            url="/login",
        )
        out = fn(action)
        assert "signin-button" in out
        assert "ugly description" not in out

    def test_falls_back_to_default(self) -> None:
        """Missing attribute → behaves like default_label_fn."""
        fn = selector_label_fn("data-testid")
        action = _build_action(target_desc="button", url="/login")
        assert fn(action) == default_label_fn(action)


# =============================================================================
# Analyzer
# =============================================================================


class TestRrwebAnalyzer:
    """Analyzer produces actions + markdown from the sample fixture."""

    def test_analyzes_sample_fixture(self) -> None:
        """Sample fixture produces ≥1 click + navigate actions and 3 navigations."""
        events = _load_sample()
        result = RrwebAnalyzer().analyze(events)

        # The sample stream has 4 Meta events (navigations).
        navigations = [a for a in result.actions if a.action == "navigate"]
        assert len(navigations) == 4

        # And at least one click on the Sign in button (id=13).
        clicks = [a for a in result.actions if a.action == "click"]
        assert any('"Sign in"' in a.target_desc for a in clicks)

        # And two inputs (email, password).
        inputs = [a for a in result.actions if a.action == "input"]
        assert len(inputs) == 2

        # markdown_summary is non-empty; format is one "{timestamp_seconds}: {description}"
        # line per action.
        assert result.markdown_summary
        assert "Navigated to https://app.example.com/login" in result.markdown_summary

    def test_empty_input_returns_empty_result(self) -> None:
        """Empty event stream → empty result, no crash."""
        result = RrwebAnalyzer().analyze([])
        assert result.actions == []
        assert result.markdown_summary == ""


# =============================================================================
# ReplayBundle: projections + aggregations + filters
# =============================================================================


def _sample_bundle() -> ReplayBundle:
    """Build a small bundle from synthetic action streams for aggregation tests."""
    r1 = _make_replay(
        "r-1",
        [
            _build_action(
                timestamp=1, action="navigate", target_desc="/login", url="/login"
            ),
            _build_action(
                timestamp=100, action="click", target_desc="button.signin", url="/login"
            ),
            _build_action(
                timestamp=200,
                action="navigate",
                target_desc="/dashboard",
                url="/dashboard",
            ),
        ],
    )
    r2 = _make_replay(
        "r-2",
        [
            _build_action(
                timestamp=1, action="navigate", target_desc="/login", url="/login"
            ),
            _build_action(
                timestamp=50, action="click", target_desc="button.signin", url="/login"
            ),
            _build_action(
                timestamp=70, action="click", target_desc="button.signin", url="/login"
            ),
            _build_action(
                timestamp=90, action="click", target_desc="button.signin", url="/login"
            ),
            _build_action(
                timestamp=1_000_000,
                action="navigate",
                target_desc="/dashboard",
                url="/dashboard",
            ),
        ],
    )
    r3 = _make_replay(
        "r-3",
        [
            _build_action(
                timestamp=1, action="navigate", target_desc="/login", url="/login"
            ),
            _build_action(
                timestamp=500,
                action="console_error",
                target_desc="TypeError",
                url="/login",
            ),
        ],
    )
    return ReplayBundle(
        replays=[r1, r2, r3], computed_at="2026-05-27T00:00:00Z", project_id=12345
    )


class TestReplayBundleProjections:
    """The seven DataFrame projections have the documented column shape."""

    def test_sessions_df(self) -> None:
        """sessions_df has one row per replay with derived counts."""
        b = _sample_bundle()
        df = b.sessions_df
        assert len(df) == 3
        for col in ("replay_id", "n_actions", "n_clicks", "n_pages", "n_errors"):
            assert col in df.columns
        # r-2 has 3 clicks; r-3 has 1 error.
        r2_row = df[df["replay_id"] == "r-2"].iloc[0]
        assert int(r2_row["n_clicks"]) == 3
        r3_row = df[df["replay_id"] == "r-3"].iloc[0]
        assert int(r3_row["n_errors"]) == 1

    def test_actions_df_long_format(self) -> None:
        """actions_df is long-format keyed by replay_id."""
        b = _sample_bundle()
        df = b.actions_df
        assert "replay_id" in df.columns
        # Total actions = 3 + 5 + 2 = 10
        assert len(df) == 10

    def test_elements_df(self) -> None:
        """elements_df aggregates clicks per (target_desc, url)."""
        b = _sample_bundle()
        df = b.elements_df
        if not df.empty:
            assert "n_clicks" in df.columns
            row = df[df["target_desc"] == "button.signin"].iloc[0]
            # 1 click from r1 + 3 from r2 = 4
            assert int(row["n_clicks"]) == 4

    def test_elements_df_normalizes_urls(self) -> None:
        """The same element on parameterized URLs collapses to one row."""
        r = _make_replay(
            "r-n",
            [
                _build_action(
                    timestamp=10,
                    action="click",
                    target_desc="row",
                    url="/users/1/profile",
                ),
                _build_action(
                    timestamp=20,
                    action="click",
                    target_desc="row",
                    url="/users/2/profile",
                ),
            ],
        )
        b = ReplayBundle(replays=[r], computed_at="t", project_id=12345)
        rows = b.elements_df[b.elements_df["target_desc"] == "row"]
        assert len(rows) == 1
        assert rows.iloc[0]["url"] == "/users/:id/profile"
        assert int(rows.iloc[0]["n_clicks"]) == 2

    def test_default_df_is_sessions(self) -> None:
        """ReplayBundle.df returns sessions_df."""
        b = _sample_bundle()
        assert b.df.equals(b.sessions_df)


class TestReplayBundleAggregations:
    """Bundle aggregation methods return non-empty for relevant fixtures."""

    def test_top_clicks(self) -> None:
        """top_clicks returns button.signin first (4 clicks across bundle)."""
        b = _sample_bundle()
        out = b.top_clicks()
        assert out.iloc[0]["target_desc"] == "button.signin"
        assert int(out.iloc[0]["count"]) == 4

    def test_top_clicks_excludes_focus(self) -> None:
        """A focus+click pair on one target counts as a single click."""
        r = _make_replay(
            "r-f",
            [
                _build_action(
                    timestamp=10,
                    action="click",
                    target_desc="btn",
                    url="/x",
                    metadata={"interaction": "focused"},
                ),
                _build_action(
                    timestamp=20,
                    action="click",
                    target_desc="btn",
                    url="/x",
                    metadata={"interaction": "clicked"},
                ),
            ],
        )
        b = ReplayBundle(replays=[r], computed_at="t", project_id=12345)
        out = b.top_clicks()
        assert int(out[out["target_desc"] == "btn"].iloc[0]["count"]) == 1

    def test_rage_clicks(self) -> None:
        """rage_clicks catches r-2's 3-burst on button.signin (50ms span)."""
        b = _sample_bundle()
        out = b.rage_clicks(threshold=3, window_ms=100)
        assert len(out) == 1
        assert out.iloc[0]["replay_id"] == "r-2"
        assert int(out.iloc[0]["count"]) == 3

    def test_long_pauses(self) -> None:
        """long_pauses catches r-2's near-1s gap between actions."""
        b = _sample_bundle()
        out = b.long_pauses(threshold_s=10)
        assert any(row["replay_id"] == "r-2" for _, row in out.iterrows())


class TestReplayBundleFilters:
    """Filters return new bundles that are proper subsets."""

    def test_filter_predicate(self) -> None:
        """filter returns a new bundle with only matching replays."""
        b = _sample_bundle()
        out = b.filter(lambda r: r.replay_id == "r-1")
        assert [r.replay_id for r in out.replays] == ["r-1"]
        # Original is unchanged (immutability).
        assert len(b.replays) == 3

    def test_where_distinct_id(self) -> None:
        """where(distinct_id=...) filters to that user."""
        b = _sample_bundle()
        out = b.where(distinct_id=None)
        # All synthetic replays have distinct_id=None, so all match.
        assert len(out.replays) == 3

    def test_error_sessions(self) -> None:
        """error_sessions returns only replays with console errors (r-3)."""
        b = _sample_bundle()
        out = b.error_sessions()
        assert [r.replay_id for r in out.replays] == ["r-3"]

    def test_head_bound(self) -> None:
        """head(n) returns up to n replays."""
        b = _sample_bundle()
        assert len(b.head(2).replays) == 2
        assert len(b.head(10).replays) == 3  # bound clamped to total

    def test_sample_determinism(self) -> None:
        """Same seed → same sample."""
        b = _sample_bundle()
        a = [r.replay_id for r in b.sample(2, seed=42).replays]
        c = [r.replay_id for r in b.sample(2, seed=42).replays]
        assert a == c
        assert len(a) == 2


# =============================================================================
# Aggregator functions directly
# =============================================================================


class TestAggregatorFunctions:
    """Module-level aggregators are accessible without going through Bundle."""

    def test_rage_clicks_module(self) -> None:
        """rage_clicks module-level catches the same burst."""
        b = _sample_bundle()
        out = rage_clicks(b, threshold=3, window_ms=100)
        assert len(out) == 1

    def test_long_pauses_module(self) -> None:
        """long_pauses module-level returns rows for the pause."""
        b = _sample_bundle()
        out = long_pauses(b, threshold_s=10)
        assert len(out) >= 1

    def test_top_clicks_module(self) -> None:
        """top_clicks module-level matches Bundle.top_clicks."""
        b = _sample_bundle()
        assert top_clicks(b).iloc[0]["target_desc"] == "button.signin"
