"""Unit tests for ReplaysService (044-session-replay).

Locks the documented behavior of the CDN walker: parallel batches, 404
sentinel, 403 re-sign retry, max_files bound, timestamp ordering, and
forward-compat mobile-replay detection. ``MixpanelAPIClient.sign_replays``
is mocked at the method level; CDN GETs use ``httpx.MockTransport`` so
``httpx.AsyncClient`` traffic stays in-process.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlparse

import httpx
import pytest

from mixpanel_headless._internal.services.replays import ReplaysService
from mixpanel_headless.exceptions import (
    MixpanelHeadlessError,
    ReplayNotFoundError,
    SignedURLExpiredError,
    UnsupportedReplayFormatError,
)
from mixpanel_headless.types import SignedReplay

# =============================================================================
# Helpers
# =============================================================================


def _mock_api_client(project_id: str = "12345") -> MagicMock:
    """Build a stand-in for MixpanelAPIClient with the minimum surface used."""
    api = MagicMock()
    api.project_id = project_id
    api.sign_replays = MagicMock(return_value=[])
    return api


def _signed(replay_id: str = "r-1", *, env: str = "prod") -> SignedReplay:
    """Build a SignedReplay pointing at the fake CDN host used in fixtures."""
    return SignedReplay(
        replay_id=replay_id,
        url=f"https://cdn.test/srr-us/sha-{replay_id}/",
        query_string="URLPrefix=A&Expires=1&KeyName=K&Signature=S",
        env=env,  # type: ignore[arg-type]
        signed_at=1716810000.0,
    )


def _rrweb_event(timestamp: int, type_: int = 3) -> dict[str, Any]:
    """Build a minimal rrweb-shaped event."""
    return {"type": type_, "data": {}, "timestamp": timestamp}


def _parse_file_num(url: str) -> int:
    """Pull the NNNN file index out of a CDN URL like '...0007-30.json?...'."""
    path = urlparse(url).path
    last = path.rsplit("/", 1)[-1]
    # last looks like '0007-30.json'
    num_part = last.split("-", 1)[0]
    return int(num_part)


# =============================================================================
# sign()
# =============================================================================


class TestSignWrapping:
    """ReplaysService.sign wraps api_client.sign_replays in SignedReplay objects."""

    def test_sign_returns_list_of_signed_replay(self) -> None:
        """Each raw dict from the API becomes one SignedReplay in input order."""
        api = _mock_api_client()
        api.sign_replays.return_value = [
            {
                "replay_id": "r-1",
                "url": "https://cdn.test/srr-us/sha-1/",
                "query_string": "URLPrefix=A&Signature=X",
            },
            {
                "replay_id": "r-2",
                "url": "https://cdn.test/srr-us/sha-2/",
                "query_string": "URLPrefix=B&Signature=Y",
            },
        ]
        service = ReplaysService(api)

        result = service.sign(["r-1", "r-2"], env="prod")

        assert len(result) == 2
        assert all(isinstance(r, SignedReplay) for r in result)
        assert result[0].replay_id == "r-1"
        assert result[1].replay_id == "r-2"
        assert result[0].env == "prod"
        assert result[0].signed_at > 0
        api.sign_replays.assert_called_once_with(["r-1", "r-2"], env="prod")

    def test_sign_missing_key_raises_schema_error(self) -> None:
        """A dict item missing url/query_string raises the structured error."""
        api = _mock_api_client()
        api.sign_replays.return_value = [
            {"replay_id": "r-1", "query_string": "URLPrefix=A&Signature=X"}
        ]
        service = ReplaysService(api)

        with pytest.raises(MixpanelHeadlessError, match="missing key") as exc_info:
            service.sign(["r-1"])
        assert exc_info.value.code == "SIGN_RESPONSE_SCHEMA"

    @pytest.mark.parametrize(
        "bad_item",
        [
            pytest.param(None, id="none"),
            pytest.param("r-1-just-a-string", id="string"),
            pytest.param(["r-1"], id="list"),
        ],
    )
    def test_sign_non_dict_item_raises_schema_error(self, bad_item: object) -> None:
        """Non-dict items raise the structured schema error, not TypeError."""
        api = _mock_api_client()
        api.sign_replays.return_value = [bad_item]
        service = ReplaysService(api)

        with pytest.raises(
            MixpanelHeadlessError, match="expected an object"
        ) as exc_info:
            service.sign(["r-1"])
        assert exc_info.value.code == "SIGN_RESPONSE_SCHEMA"
        assert type(bad_item).__name__ in str(exc_info.value)


# =============================================================================
# fetch_files() — the CDN walker
# =============================================================================


def _make_cdn_handler(
    *,
    file_contents: dict[int, list[dict[str, Any]] | None] | None = None,
    files_403: set[int] | None = None,
    call_log: list[int] | None = None,
) -> Any:
    """Build an httpx.MockTransport handler that serves CDN file fixtures.

    Args:
        file_contents: Maps file number → events to return (200), or None
            to return 404. Numbers absent from this dict 404 by default.
        files_403: File numbers that should return 403 (overrides
            file_contents).
        call_log: Optional list to append every requested file number to.

    Returns:
        Callable suitable for ``httpx.MockTransport(handler)``.
    """
    file_contents = file_contents or {}
    files_403 = files_403 or set()

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve one CDN file based on the file number parsed from the URL."""
        file_num = _parse_file_num(str(request.url))
        if call_log is not None:
            call_log.append(file_num)
        if file_num in files_403:
            return httpx.Response(403, text="signature expired")
        if file_num not in file_contents or file_contents[file_num] is None:
            return httpx.Response(404)
        return httpx.Response(200, json=file_contents[file_num])

    return handler


class TestFetchFilesHappyPath:
    """Buffered fetch concatenates all files and sorts by timestamp."""

    def test_returns_timestamp_sorted_events(self) -> None:
        """Events from all CDN files are concatenated in timestamp order."""
        # Out-of-order timestamps within a file, plus files served in
        # arbitrary order, should all come back sorted.
        file_contents: dict[int, list[dict[str, Any]] | None] = {
            0: [_rrweb_event(20), _rrweb_event(10)],
            1: [_rrweb_event(40), _rrweb_event(30)],
            2: None,  # 404 → end of replay
        }
        api = _mock_api_client()
        transport = httpx.MockTransport(_make_cdn_handler(file_contents=file_contents))
        service = ReplaysService(api, _async_transport=transport)

        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=500,
            concurrency=50,
        )

        timestamps = [e["timestamp"] for e in events]
        assert timestamps == [10, 20, 30, 40]

    def test_uses_correct_file_naming(self) -> None:
        """File URLs use the {NNNN:04d}-{retention_days}.json pattern (FR-013).

        With concurrency=1 the walker fetches one file at a time, so the
        404 sentinel at file 2 terminates the walk before file 3 is hit.
        Wider batches issue the whole batch in parallel and inspect 404s
        after the gather; that case is exercised by test_respects_max_files_bound.
        """
        call_log: list[int] = []
        file_contents: dict[int, list[dict[str, Any]] | None] = {
            0: [_rrweb_event(10)],
            1: [_rrweb_event(20)],
            2: None,
        }
        api = _mock_api_client()
        transport = httpx.MockTransport(
            _make_cdn_handler(file_contents=file_contents, call_log=call_log)
        )
        service = ReplaysService(api, _async_transport=transport)

        service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=500,
            concurrency=1,
        )
        # Sequential walk stops the moment file 2 returns 404.
        assert sorted(call_log) == [0, 1, 2]

    def test_respects_max_files_bound(self) -> None:
        """max_files caps the walk even when no 404 ever appears."""
        # Every file returns one event; no 404 would naturally stop us.
        file_contents: dict[int, list[dict[str, Any]] | None] = {
            n: [_rrweb_event(n * 10)] for n in range(200)
        }
        call_log: list[int] = []
        api = _mock_api_client()
        transport = httpx.MockTransport(
            _make_cdn_handler(file_contents=file_contents, call_log=call_log)
        )
        service = ReplaysService(api, _async_transport=transport)

        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=10,
            concurrency=4,
        )

        assert len(events) == 10
        assert max(call_log) == 9


class TestFetchFilesTermination:
    """404 handling: first-file → ReplayNotFoundError; mid-walk → clean stop."""

    def test_first_file_404_raises_replay_not_found(self) -> None:
        """A 404 on file 0000-N.json means the replay doesn't exist on CDN."""
        # Empty file_contents → every file 404s.
        api = _mock_api_client()
        transport = httpx.MockTransport(_make_cdn_handler())
        service = ReplaysService(api, _async_transport=transport)

        with pytest.raises(ReplayNotFoundError) as exc_info:
            service.fetch_files(
                _signed(),
                retention_days=30,
                max_files=500,
                concurrency=50,
            )

        exc = exc_info.value
        assert exc.details["replay_id"] == "r-1"
        assert exc.details["retention_days"] == 30
        assert exc.details["cdn_url_prefix"].endswith("/")

    def test_mid_walk_404_terminates_cleanly(self) -> None:
        """A 404 on a non-first file is the end-of-replay sentinel (no raise)."""
        file_contents: dict[int, list[dict[str, Any]] | None] = {
            0: [_rrweb_event(10)],
            1: [_rrweb_event(20)],
            2: [_rrweb_event(30)],
            # file 3 absent → 404
        }
        api = _mock_api_client()
        transport = httpx.MockTransport(_make_cdn_handler(file_contents=file_contents))
        service = ReplaysService(api, _async_transport=transport)

        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=500,
            concurrency=50,
        )
        assert [e["timestamp"] for e in events] == [10, 20, 30]


class TestFetchFiles403Retry:
    """403 mid-walk: re-sign once when allowed, raise when disabled."""

    def test_403_with_re_sign_succeeds_after_resign(self) -> None:
        """403 mid-walk triggers one re-sign + retry when re_sign_on_expiry=True."""
        # Simulate: first request to file 0 returns 403; after re-sign,
        # everything is fine. Use a stateful handler that flips behavior
        # after the re-sign call shows up in api.sign_replays.
        state = {"resigned": False}

        def handler(request: httpx.Request) -> httpx.Response:
            """Return 403 until we've re-signed; then serve the file normally."""
            file_num = _parse_file_num(str(request.url))
            if file_num >= 2:
                return httpx.Response(404)
            if not state["resigned"]:
                return httpx.Response(403, text="signature expired")
            return httpx.Response(200, json=[_rrweb_event(file_num * 10)])

        api = _mock_api_client()

        def _sign_replays(_ids: list[str], env: str = "prod") -> list[dict[str, Any]]:
            """Mark re-signed and return a fresh credential dict."""
            state["resigned"] = True
            return [
                {
                    "replay_id": "r-1",
                    "url": "https://cdn.test/srr-us/sha-1/",
                    "query_string": "URLPrefix=Z&Signature=NEW",
                }
            ]

        api.sign_replays.side_effect = _sign_replays
        transport = httpx.MockTransport(handler)
        service = ReplaysService(api, _async_transport=transport)

        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=500,
            concurrency=50,
            re_sign_on_expiry=True,
        )
        # Re-sign was called exactly once.
        assert api.sign_replays.call_count == 1
        # After re-sign we got the events for files 0 and 1.
        assert [e["timestamp"] for e in events] == [0, 10]

    def test_403_without_re_sign_raises_expired(self) -> None:
        """re_sign_on_expiry=False propagates the expiry as SignedURLExpiredError."""
        api = _mock_api_client()
        transport = httpx.MockTransport(_make_cdn_handler(files_403={0}))
        service = ReplaysService(api, _async_transport=transport)

        with pytest.raises(SignedURLExpiredError) as exc_info:
            service.fetch_files(
                _signed(),
                retention_days=30,
                max_files=500,
                concurrency=50,
                re_sign_on_expiry=False,
            )

        exc = exc_info.value
        assert exc.details["replay_id"] == "r-1"
        assert "signed_at" in exc.details
        assert "expired_at" in exc.details
        assert api.sign_replays.call_count == 0


class TestFetchFilesCredentialRedaction:
    """Transport errors must never leak the signed query_string credential."""

    def test_transport_error_redacts_signed_credential(self) -> None:
        """An httpx error whose str() embeds the URL is scrubbed before raising."""
        signed = _signed()

        def handler(request: httpx.Request) -> httpx.Response:
            """Raise a transport error whose message embeds the credentialed URL."""
            raise httpx.ConnectError(f"connection failed for {request.url}")

        api = _mock_api_client()
        transport = httpx.MockTransport(handler)
        service = ReplaysService(api, _async_transport=transport)

        with pytest.raises(MixpanelHeadlessError) as exc_info:
            service.fetch_files(
                signed, retention_days=30, max_files=500, concurrency=50
            )

        message = str(exc_info.value)
        assert signed.query_string not in message
        assert "<redacted>" in message


# =============================================================================
# Mobile-replay detection (forward-compat marker)
# =============================================================================


class TestMobileReplayDetection:
    """First event missing rrweb keys → UnsupportedReplayFormatError per §9."""

    def test_non_rrweb_first_event_raises_unsupported_format(self) -> None:
        """Mobile replays use a different recording format; fail with a typed error."""
        # First file's first event lacks 'type', 'data', and 'timestamp'.
        file_contents: dict[int, list[dict[str, Any]] | None] = {
            0: [{"mobile_event": "tap", "ts": 1716810000}],
            1: None,
        }
        api = _mock_api_client()
        transport = httpx.MockTransport(_make_cdn_handler(file_contents=file_contents))
        service = ReplaysService(api, _async_transport=transport)

        with pytest.raises(UnsupportedReplayFormatError, match="mobile session") as ei:
            service.fetch_files(
                _signed(),
                retention_days=30,
                max_files=500,
                concurrency=50,
            )
        # Typed so the CLI maps it to a clean exit code, and callers can branch.
        assert ei.value.details["replay_id"] == _signed().replay_id
        assert ei.value.details["format"] == "non-rrweb"


# =============================================================================
# discover() (with mocked query_fn)
# =============================================================================


class TestDiscoverNoQueryFn:
    """Without query_fn, discover raises a clear RuntimeError."""

    def test_raises_without_query_fn(self) -> None:
        """discover delegates to query_fn; missing dependency must fail loudly."""
        api = _mock_api_client()
        service = ReplaysService(api)  # no query_fn
        with pytest.raises(RuntimeError, match="query_fn"):
            service.discover(
                distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
            )

    def test_empty_replay_ids_returns_empty(self) -> None:
        """No distinct_id and empty replay_ids returns [] without calling query_fn."""
        api = _mock_api_client()
        query_fn = MagicMock()
        service = ReplaysService(api, query_fn=query_fn)
        result = service.discover(replay_ids=[])
        assert result == []
        query_fn.assert_not_called()


# =============================================================================
# discover() / events_for() parsing — against the REAL Insights `series` shape
#
# These mock `result.series` with the nested-dict structure the live Insights
# API actually returns (captured from project 3), NOT a hand-built `.df`. The
# old tests mocked a `.df` with property-named columns — a shape the API never
# produces — which is exactly why the silent-empty bug shipped green.
# =============================================================================


def _series_result(series: dict[str, Any]) -> MagicMock:
    """A stand-in Workspace.query() result exposing only `.series`."""
    result = MagicMock()
    result.series = series
    return result


# Discovery: $mp_session_record grouped by [replay_id, retention] with
# math="min", math_property="time". Leaf `all` is the min event-time in unix
# SECONDS. Each replay carries an `$overall` rollup sibling that must be skipped.
_DISCOVERY_SERIES: dict[str, Any] = {
    "Session Recording Checkpoint [Minimum Time]": {
        "$overall": {"all": 1779319127},
        "rid-aaa": {
            "$overall": {"all": 1779322882},
            "30": {"all": 1779322882},
        },
        "rid-bbb": {
            "$overall": {"all": 1779332317},
            "7": {"all": 1779332317},
        },
    }
}

# Older SDK: the replay has no `$mp_replay_retention_period`, so its only child
# is the `$overall` rollup. Parser must default retention to 30 + warn, and
# still recover start_time from the `$overall` branch.
_DISCOVERY_SERIES_NO_RETENTION: dict[str, Any] = {
    "Session Recording Checkpoint [Minimum Time]": {
        "$overall": {"all": 1779319127},
        "rid-old": {"$overall": {"all": 1779319127}},
    }
}

# events_for: $all_events grouped by [$time, $event_name, $mp_replay_id]. $time
# keys are second-precision ISO strings; leaf `all` is the event count.
_EVENTS_SERIES: dict[str, Any] = {
    "All Events [Total Events]": {
        "$overall": {"all": 13},
        "2026-05-21T16:31:31": {
            "$overall": {"all": 1},
            "$mp_dead_click": {
                "$overall": {"all": 1},
                "rid-bab": {"all": 1},
            },
        },
        "2026-05-21T16:31:25": {
            "$overall": {"all": 12},
            "Browser API fetch": {
                "$overall": {"all": 12},
                "rid-bab": {"all": 12},
            },
        },
    }
}

# events_for with one extra group key ($browser) → one deeper nesting level.
_EVENTS_SERIES_WITH_PROP: dict[str, Any] = {
    "All Events [Total Events]": {
        "$overall": {"all": 1},
        "2026-05-21T16:31:25": {
            "$overall": {"all": 1},
            "Browser API fetch": {
                "$overall": {"all": 1},
                "rid-bab": {
                    "$overall": {"all": 1},
                    "Chrome": {"all": 1},
                },
            },
        },
    }
}


class TestDiscoverParsing:
    """discover() parses the real min-time `series` into ReplaySummary rows."""

    def test_one_summary_per_replay(self) -> None:
        """Two replays in the series → two summaries, correct retention + start_time."""
        api = _mock_api_client(project_id="3")
        query_fn = MagicMock(return_value=_series_result(_DISCOVERY_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        out = service.discover(
            distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
        )
        by_id = {s.replay_id: s for s in out}
        assert set(by_id) == {"rid-aaa", "rid-bbb"}
        assert by_id["rid-aaa"].retention_days == 30
        assert by_id["rid-bbb"].retention_days == 7
        # Leaf is unix seconds; start_time is unix ms.
        assert by_id["rid-aaa"].start_time == 1779322882 * 1000
        assert by_id["rid-aaa"].distinct_id == "u-1"
        assert by_id["rid-aaa"].project_id == 3

    def test_query_uses_min_time_aggregation(self) -> None:
        """discover asks Insights for min(time) grouped by replay_id + retention."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_DISCOVERY_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        service.discover(
            distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
        )
        q = query_fn.call_args[0][0]
        assert q.math == "min"
        assert q.math_property == "$time"
        assert q.group_by == [
            "$mp_replay_id",
            "$mp_replay_retention_period",
        ]

    def test_missing_retention_defaults_30_with_warning(self) -> None:
        """A replay whose only child is `$overall` → retention 30 + UserWarning."""
        api = _mock_api_client()
        query_fn = MagicMock(
            return_value=_series_result(_DISCOVERY_SERIES_NO_RETENTION)
        )
        service = ReplaysService(api, query_fn=query_fn)
        with pytest.warns(UserWarning, match=r"\$mp_replay_retention_period"):
            out = service.discover(
                distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
            )
        assert len(out) == 1
        assert out[0].retention_days == 30
        assert out[0].start_time == 1779319127 * 1000

    def test_empty_series_returns_empty(self) -> None:
        """An empty series yields no summaries and does not raise."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result({}))
        service = ReplaysService(api, query_fn=query_fn)
        assert (
            service.discover(
                distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
            )
            == []
        )

    def test_nonstandard_retention_defaults_30_with_warning(self) -> None:
        """A retention key outside {1,7,30,90} → default 30 + warn, time kept."""
        api = _mock_api_client()
        series: dict[str, Any] = {
            "Session Recording Checkpoint [Minimum Time]": {
                "$overall": {"all": 1779319127},
                "rid-weird": {
                    "$overall": {"all": 1779322882},
                    "15": {"all": 1779322882},
                },
            }
        }
        query_fn = MagicMock(return_value=_series_result(series))
        service = ReplaysService(api, query_fn=query_fn)
        with pytest.warns(UserWarning, match=r"\$mp_replay_retention_period"):
            out = service.discover(
                distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
            )
        assert len(out) == 1
        assert out[0].retention_days == 30
        assert out[0].start_time == 1779322882 * 1000

    def test_limit_caps_summaries(self) -> None:
        """limit truncates the returned summaries."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_DISCOVERY_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        out = service.discover(
            distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27", limit=1
        )
        assert len(out) == 1

    def test_default_window_is_90_day_lookback(self) -> None:
        """Dateless replay_ids discovery uses last=90 (covers max retention).

        The _resolve_retention path hydrates explicit IDs with no window;
        Workspace.query's last=30 default would silently miss replays 31–90
        days old, defaulting their retention to 30 and breaking the CDN walk.
        """
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result({}))
        service = ReplaysService(api, query_fn=query_fn)
        service.discover(replay_ids=["rid-aaa"])
        q = query_fn.call_args[0][0]
        assert q.last == 90
        assert q.from_date is None
        assert q.to_date is None

    def test_explicit_window_overrides_lookback(self) -> None:
        """An explicit from/to is passed through; last is not sent."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_DISCOVERY_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        service.discover(
            distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
        )
        q = query_fn.call_args[0][0]
        assert q.from_date == "2026-05-20"
        assert q.to_date == "2026-05-27"

    def test_missing_retention_warning_has_no_doubled_prefix(self) -> None:
        """The warning text must not carry a literal 'UserWarning:' prefix.

        warnings.warn(..., UserWarning) prepends the category name itself;
        embedding it in the message too renders 'UserWarning: UserWarning: …'.
        """
        api = _mock_api_client()
        query_fn = MagicMock(
            return_value=_series_result(_DISCOVERY_SERIES_NO_RETENTION)
        )
        service = ReplaysService(api, query_fn=query_fn)
        with pytest.warns(UserWarning) as record:
            service.discover(
                distinct_id="u-1", from_date="2026-05-20", to_date="2026-05-27"
            )
        message = str(record[0].message)
        assert not message.startswith("UserWarning:")
        assert message.startswith("replay ")


class TestEventsForParsing:
    """events_for() parses the real $all_events `series` into ReplayEvent rows."""

    def test_returns_time_sorted_events_per_replay(self) -> None:
        """Two events for one replay come back time-sorted."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_EVENTS_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        out = service.events_for(["rid-bab"])
        assert set(out) == {"rid-bab"}
        events = out["rid-bab"]
        assert [e.event_name for e in events] == ["Browser API fetch", "$mp_dead_click"]
        assert events[0].event_time < events[1].event_time

    def test_event_properties_surface(self) -> None:
        """An extra group key lands in ReplayEvent.properties."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_EVENTS_SERIES_WITH_PROP))
        service = ReplaysService(api, query_fn=query_fn)
        out = service.events_for(["rid-bab"], event_properties=["$browser"])
        assert out["rid-bab"][0].properties == {"$browser": "Chrome"}

    def test_issues_all_events_query_shape(self) -> None:
        """events_for queries $all_events grouped by time/event_name/replay_id."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result(_EVENTS_SERIES))
        service = ReplaysService(api, query_fn=query_fn)
        service.events_for(["rid-bab"])
        q = query_fn.call_args[0][0]
        assert q.events == ["$all_events"]
        assert q.group_by[:3] == ["$time", "$event_name", "$mp_replay_id"]

    def test_empty_series_returns_empty_dict(self) -> None:
        """An empty series yields an empty dict, no raise."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result({}))
        service = ReplaysService(api, query_fn=query_fn)
        assert service.events_for(["rid-bab"]) == {}

    def test_default_window_is_90_day_lookback(self) -> None:
        """Without an explicit window, the query uses last=90 (max retention).

        The underlying Workspace.query default is last=30, which would silently
        miss events for replays 31–90 days old.
        """
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result({}))
        service = ReplaysService(api, query_fn=query_fn)
        service.events_for(["rid-bab"])
        q = query_fn.call_args[0][0]
        assert q.last == 90
        assert q.from_date is None
        assert q.to_date is None

    def test_explicit_window_overrides_lookback(self) -> None:
        """An explicit from/to is passed through; last is not sent."""
        api = _mock_api_client()
        query_fn = MagicMock(return_value=_series_result({}))
        service = ReplaysService(api, query_fn=query_fn)
        service.events_for(["rid-bab"], from_date="2026-05-20", to_date="2026-05-21")
        q = query_fn.call_args[0][0]
        assert q.from_date == "2026-05-20"
        assert q.to_date == "2026-05-21"


# Ensure the module is importable as a package for pytest collection.
_ = json


class TestFetchFilesNonListPayload:
    """CDN files with non-list JSON are logged and treated as empty."""

    def test_non_list_json_warns_and_treats_as_empty(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A dict payload logs a warning and contributes zero events."""
        import logging

        def handler(request: httpx.Request) -> httpx.Response:
            """Serve a dict payload for file 0, then 404."""
            file_num = _parse_file_num(str(request.url))
            if file_num == 0:
                return httpx.Response(200, json={"error": "oops"})
            return httpx.Response(404)

        api = _mock_api_client()
        transport = httpx.MockTransport(handler)
        service = ReplaysService(api, _async_transport=transport)

        with caplog.at_level(logging.WARNING):
            events = service.fetch_files(
                _signed(),
                retention_days=30,
                max_files=500,
                concurrency=1,
            )

        assert events == []
        assert any("instead of list" in r.getMessage() for r in caplog.records)


class TestToUnixMs:
    """_to_unix_ms coercion edge cases."""

    def test_unparseable_timestamp_warns_and_returns_zero(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Garbage $time values log a warning and coerce to 0."""
        import logging

        from mixpanel_headless._internal.services.replays import _to_unix_ms

        with caplog.at_level(logging.WARNING):
            assert _to_unix_ms("not-a-timestamp") == 0
        assert any("unparseable timestamp" in r.getMessage() for r in caplog.records)
