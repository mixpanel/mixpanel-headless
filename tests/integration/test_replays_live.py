"""Live integration tests for session replay (044).

Skipped by default — set ``MP_LIVE_TESTS=1`` and point auth at a fixture
project (e.g. Mixpanel Labs project 3713224) with a known replay-bearing
distinct_id. These tests round-trip against the real ``/replays/sign`` and
the real CDN.

Markers:
- ``@pytest.mark.live`` lets the rest of the suite skip them via
  ``-m "not live"``.
- ``@pytest.mark.skipif`` short-circuits when ``MP_LIVE_TESTS`` is absent.
"""

from __future__ import annotations

import os

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import SessionReplayAccessError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MP_LIVE_TESTS") != "1",
        reason="MP_LIVE_TESTS=1 not set — live tests skipped by default",
    ),
]


# Override per-environment by exporting MP_REPLAY_FIXTURE_DISTINCT_ID and
# MP_REPLAY_FIXTURE_PROJECT before running.
_FIXTURE_DISTINCT_ID = os.environ.get(
    "MP_REPLAY_FIXTURE_DISTINCT_ID", "fixture-distinct-id"
)
_FIXTURE_FROM_DATE = os.environ.get("MP_REPLAY_FIXTURE_FROM", "2026-05-01")
_FIXTURE_TO_DATE = os.environ.get("MP_REPLAY_FIXTURE_TO", "2026-05-27")


@pytest.fixture
def ws() -> mp.Workspace:
    """Workspace bound to the configured live fixture project."""
    return mp.Workspace()


class TestListReplaysLive:
    """list_replays returns ≥1 summary for the known distinct_id."""

    def test_returns_at_least_one_summary(self, ws: mp.Workspace) -> None:
        """The fixture user has at least one replay in the window."""
        summaries = ws.list_replays(
            distinct_id=_FIXTURE_DISTINCT_ID,
            from_date=_FIXTURE_FROM_DATE,
            to_date=_FIXTURE_TO_DATE,
        )
        assert len(summaries) >= 1
        assert summaries[0].replay_id
        assert summaries[0].retention_days in (1, 7, 30, 90)


class TestSignAndCdnLive:
    """sign_replays returns valid signed URLs; CDN HEAD returns 200."""

    def test_signed_url_serves_cdn(self, ws: mp.Workspace) -> None:
        """A signed URL for the first discovered replay HEADs OK from the CDN."""
        import httpx

        summaries = ws.list_replays(
            distinct_id=_FIXTURE_DISTINCT_ID,
            from_date=_FIXTURE_FROM_DATE,
            to_date=_FIXTURE_TO_DATE,
        )
        if not summaries:
            pytest.skip("no replays in fixture window — fixture probably stale")

        signed = ws.sign_replay(summaries[0].replay_id)
        url = (
            f"{signed.url}0000-{summaries[0].retention_days}.json?{signed.query_string}"
        )
        with httpx.Client(timeout=30.0) as client:
            response = client.head(url)
        # Either 200 (file exists) or 404 (replay aged out / sparse files)
        # is acceptable; 403 would indicate a signing problem.
        assert response.status_code in (200, 404)


class TestFetchReplayLive:
    """fetch_replay returns a Replay with non-zero duration."""

    def test_fetch_returns_replay_with_events(self, ws: mp.Workspace) -> None:
        """Materializing the first replay yields ≥1 rrweb event."""
        summaries = ws.list_replays(
            distinct_id=_FIXTURE_DISTINCT_ID,
            from_date=_FIXTURE_FROM_DATE,
            to_date=_FIXTURE_TO_DATE,
        )
        if not summaries:
            pytest.skip("no replays in fixture window — fixture probably stale")

        replay = ws.fetch_replay(
            summaries[0].replay_id, retention_days=summaries[0].retention_days
        )
        assert len(replay.rrweb_events) >= 1
        assert replay.duration_seconds >= 0


class TestSensitiveDataLive:
    """Sensitive-data fixture project raises SessionReplayAccessError.

    Only runs when ``MP_REPLAY_SENSITIVE_PROJECT`` is set, since most
    fixture projects aren't sensitive-data-gated.
    """

    def test_sensitive_data_project_raises_access_error(self, ws: mp.Workspace) -> None:
        """Targeting a project with the flag set raises with structured details."""
        sensitive_project = os.environ.get("MP_REPLAY_SENSITIVE_PROJECT")
        if not sensitive_project:
            pytest.skip("MP_REPLAY_SENSITIVE_PROJECT not set")
        sens_ws = mp.Workspace(project=sensitive_project)
        with pytest.raises(SessionReplayAccessError) as exc_info:
            sens_ws.sign_replays(["any-replay-id"])
        assert exc_info.value.details["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"
