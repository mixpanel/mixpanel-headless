# ruff: noqa: ARG001, ARG005
"""Tests for `mp replays` CLI commands (044-session-replay, Phase 1).

Coverage:
- ``mp replays list`` happy path + empty result + --help
- ``mp replays events`` happy path + --properties cap (exits 3)
- ``mp replays sign`` masking by default + --reveal-signed-urls full disclosure
  + stderr warning on every --reveal-signed-urls invocation
- ``mp replays fetch`` -o file output + one-line summary without -o
- Exit code mapping for SessionReplayAccessError (2) and ReplayNotFoundError (4)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import typer.testing

from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import (
    ReplayNotFoundError,
    SessionReplayAccessError,
)
from mixpanel_headless.types import Replay, ReplayEvent, ReplaySummary, SignedReplay

runner = typer.testing.CliRunner()


# =============================================================================
# Fixture helpers
# =============================================================================


def _summary(replay_id: str = "r-19221") -> ReplaySummary:
    """Build a ReplaySummary for mocking workspace.list_replays output."""
    return ReplaySummary(
        replay_id=replay_id,
        distinct_id="user-42",
        project_id=12345,
        start_time=1716810000000,
        retention_days=30,
    )


def _signed(replay_id: str = "r-19221") -> SignedReplay:
    """Build a SignedReplay for mocking workspace.sign_replays output."""
    return SignedReplay(
        replay_id=replay_id,
        url="https://cdn.test/srr-us/sha-12345/",
        query_string=("URLPrefix=ABCDEFGH&Expires=1716810300&KeyName=K&Signature=zzzz"),
        env="prod",
        signed_at=1716810000.0,
    )


def _replay_event(replay_id: str = "r-19221") -> ReplayEvent:
    """Build a ReplayEvent for mocking workspace.events_for_replay output."""
    return ReplayEvent(
        replay_id=replay_id,
        event_name="Login",
        event_time=1716810000,
        properties={"$browser": "Chrome"},
    )


def _replay(replay_id: str = "r-19221") -> Replay:
    """Build a Replay for mocking workspace.fetch_replay output."""
    return Replay(
        replay_id=replay_id,
        distinct_id="user-42",
        project_id=12345,
        start_time=1716810000000,
        end_time=1716810060000,  # 60s long
        retention_days=30,
        rrweb_events=[
            {"type": 4, "data": {"href": "/"}, "timestamp": 1716810000000},
            {"type": 3, "data": {}, "timestamp": 1716810030000},
            {"type": 4, "data": {"href": "/x"}, "timestamp": 1716810060000},
        ],
    )


# =============================================================================
# mp replays --help / list --help
# =============================================================================


class TestReplaysHelp:
    """The replays group and its subcommands are discoverable via --help."""

    def test_replays_group_help(self) -> None:
        """`mp replays --help` lists the four Phase 1 subcommands."""
        result = runner.invoke(app, ["replays", "--help"])
        assert result.exit_code == 0
        for sub in ("list", "events", "sign", "fetch"):
            assert sub in result.stdout

    def test_list_help_documents_flags(self) -> None:
        """`mp replays list --help` documents --user, --from, --to."""
        result = runner.invoke(app, ["replays", "list", "--help"])
        assert result.exit_code == 0
        for flag in ("--user", "--replay-id", "--from", "--to", "--limit"):
            assert flag in result.stdout

    def test_sign_help_documents_reveal_flag(self) -> None:
        """`mp replays sign --help` documents --reveal-signed-urls."""
        result = runner.invoke(app, ["replays", "sign", "--help"])
        assert result.exit_code == 0
        assert "--reveal-signed-urls" in result.stdout


# =============================================================================
# mp replays list
# =============================================================================


class TestReplaysList:
    """`mp replays list` happy path + empty result."""

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_list_returns_json_array(self, mock_get_ws: MagicMock) -> None:
        """Happy path returns a JSON array of summaries."""
        mock_ws = MagicMock()
        mock_ws.list_replays.return_value = [_summary("r-1"), _summary("r-2")]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "list",
                "--user",
                "user-42",
                "--from",
                "2026-05-20",
                "--to",
                "2026-05-27",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["replay_id"] == "r-1"

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_empty_result_exits_0(self, mock_get_ws: MagicMock) -> None:
        """Empty result is exit 0 with an empty JSON array (not an error)."""
        mock_ws = MagicMock()
        mock_ws.list_replays.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "list",
                "--user",
                "user-42",
                "--from",
                "2026-05-20",
                "--to",
                "2026-05-27",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == []


# =============================================================================
# mp replays events
# =============================================================================


class TestReplaysEvents:
    """`mp replays events` happy path + property cap (exit 3)."""

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_events_returns_json(self, mock_get_ws: MagicMock) -> None:
        """Happy path returns a JSON array of ReplayEvent dicts."""
        mock_ws = MagicMock()
        mock_ws.events_for_replay.return_value = [_replay_event()]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "events", "r-19221"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data[0]["event_name"] == "Login"

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_too_many_properties_exits_3(self, mock_get_ws: MagicMock) -> None:
        """Passing >5 properties raises ValueError → exit code 3."""
        # The real workspace would raise on its own; bypass discovery by
        # letting the mock's events_for_replay surface a ValueError as the
        # Workspace.events_for_replay implementation does.
        mock_ws = MagicMock()
        mock_ws.events_for_replay.side_effect = ValueError(
            "events_for_replay accepts at most 5 event_properties "
            "(Insights group-by limit). Got 6: ['a', 'b', 'c', 'd', 'e', 'f']"
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "events",
                "r-19221",
                "--properties",
                "a,b,c,d,e,f",
            ],
        )
        assert result.exit_code == 3
        assert "at most 5" in result.stderr


# =============================================================================
# mp replays sign — redaction + --reveal-signed-urls
# =============================================================================


class TestReplaysSignRedaction:
    """Default output masks; --reveal-signed-urls discloses + warns."""

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_default_masks_query_string(self, mock_get_ws: MagicMock) -> None:
        """Default JSON output has '<redacted N chars>' for query_string."""
        mock_ws = MagicMock()
        mock_ws.sign_replays.return_value = [_signed()]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "sign", "r-19221"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "<redacted" in data[0]["query_string"]
        assert "Signature=" not in result.stdout
        assert "URLPrefix=" not in result.stdout

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_reveal_includes_full_credential(self, mock_get_ws: MagicMock) -> None:
        """--reveal-signed-urls includes the bearer credential verbatim."""
        mock_ws = MagicMock()
        signed = _signed()
        mock_ws.sign_replays.return_value = [signed]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            ["replays", "sign", "r-19221", "--reveal-signed-urls"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data[0]["query_string"] == signed.query_string
        # to_dict() includes the _warning key per data-model.md §2.2.
        assert "_warning" in data[0]

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_reveal_emits_stderr_warning(self, mock_get_ws: MagicMock) -> None:
        """Every --reveal-signed-urls invocation prints the warning to stderr."""
        mock_ws = MagicMock()
        mock_ws.sign_replays.return_value = [_signed()]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            ["replays", "sign", "r-19221", "--reveal-signed-urls"],
        )
        assert result.exit_code == 0
        assert "bearer credentials" in result.stderr
        assert "5 minutes" in result.stderr


# =============================================================================
# mp replays fetch — file output + one-line summary
# =============================================================================


class TestReplaysFetch:
    """`-o file.json` writes JSON array; without -o prints one-line summary."""

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_fetch_with_output_writes_file(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """`-o file.json` writes a JSON array of timestamp-sorted rrweb events."""
        mock_ws = MagicMock()
        mock_ws.fetch_replay.return_value = _replay()
        mock_get_ws.return_value = mock_ws

        out_path = tmp_path / "replay.json"
        result = runner.invoke(
            app, ["replays", "fetch", "r-19221", "-o", str(out_path)]
        )
        assert result.exit_code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert isinstance(data, list)
        # Timestamps ascending.
        ts = [int(e["timestamp"]) for e in data]
        assert ts == sorted(ts)

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_fetch_without_output_prints_summary(self, mock_get_ws: MagicMock) -> None:
        """Without -o, prints a one-line summary to stdout."""
        mock_ws = MagicMock()
        mock_ws.fetch_replay.return_value = _replay()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "fetch", "r-19221"])
        assert result.exit_code == 0
        assert "fetched r-19221" in result.stdout
        assert "3 events" in result.stdout
        assert "30-day retention" in result.stdout


# =============================================================================
# Exit-code mapping for new exceptions
# =============================================================================


class TestExitCodeMapping:
    """SessionReplayAccessError → 2, ReplayNotFoundError → 4."""

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_sensitive_data_access_exits_2(self, mock_get_ws: MagicMock) -> None:
        """SessionReplayAccessError maps to exit code 2 (AUTH_ERROR)."""
        mock_ws = MagicMock()
        mock_ws.sign_replays.side_effect = SessionReplayAccessError(
            ("Project 3713224 has SESSION_RECORDING_SENSITIVE_DATA enabled."),
            details={
                "project_id": 3713224,
                "flag": "SESSION_RECORDING_SENSITIVE_DATA",
                "permission_required": "sensitive_data_replay",
            },
            status_code=403,
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "sign", "r-19221"])
        assert result.exit_code == 2
        assert "sensitive replay data" in result.stderr

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_analyze_prints_markdown(self, mock_get_ws: MagicMock) -> None:
        """`mp replays analyze` prints summary_markdown by default."""
        replay = _replay()
        mock_ws = MagicMock()
        mock_ws.fetch_replay.return_value = replay
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "analyze", "r-19221"])
        assert result.exit_code == 0
        assert "no actions extracted" in result.stdout

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_for_user_writes_to_out_dir(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """`mp replays for-user --out-dir DIR` writes index.json + per-replay md."""
        from mixpanel_headless.types import ReplayBundle

        bundle = ReplayBundle(
            replays=[_replay("r-1"), _replay("r-2")],
            computed_at="2026-05-27T00:00:00Z",
            project_id=12345,
        )
        mock_ws = MagicMock()
        mock_ws.replays_for_user.return_value = bundle
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "for-user",
                "user-42",
                "--from",
                "2026-05-20",
                "--to",
                "2026-05-27",
                "--include",
                "analyze",
                "--out-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert (tmp_path / "index.json").exists()
        assert (tmp_path / "r-1-summary.md").exists()
        assert (tmp_path / "r-2-summary.md").exists()
        assert "wrote 2 replays" in result.stdout

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_for_user_includes_mixpanel_events_by_default(
        self, mock_get_ws: MagicMock
    ) -> None:
        """Bare `for-user` mirrors the Python API default: events ON."""
        from mixpanel_headless.types import ReplayBundle

        bundle = ReplayBundle(
            replays=[_replay("r-1")],
            computed_at="2026-05-27T00:00:00Z",
            project_id=12345,
        )
        mock_ws = MagicMock()
        mock_ws.replays_for_user.return_value = bundle
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "for-user",
                "user-42",
                "--from",
                "2026-05-20",
                "--to",
                "2026-05-27",
            ],
        )
        assert result.exit_code == 0
        kwargs = mock_ws.replays_for_user.call_args.kwargs
        assert kwargs["include_mixpanel_events"] is True

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_for_user_no_mixpanel_events_opts_out(self, mock_get_ws: MagicMock) -> None:
        """`--no-mixpanel-events` turns the Mixpanel-events join off."""
        from mixpanel_headless.types import ReplayBundle

        bundle = ReplayBundle(
            replays=[_replay("r-1")],
            computed_at="2026-05-27T00:00:00Z",
            project_id=12345,
        )
        mock_ws = MagicMock()
        mock_ws.replays_for_user.return_value = bundle
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "replays",
                "for-user",
                "user-42",
                "--from",
                "2026-05-20",
                "--to",
                "2026-05-27",
                "--no-mixpanel-events",
            ],
        )
        assert result.exit_code == 0
        kwargs = mock_ws.replays_for_user.call_args.kwargs
        assert kwargs["include_mixpanel_events"] is False

    @patch("mixpanel_headless.cli.commands.replays.get_workspace")
    def test_replay_not_found_exits_4(self, mock_get_ws: MagicMock) -> None:
        """ReplayNotFoundError maps to exit code 4 (NOT_FOUND)."""
        mock_ws = MagicMock()
        mock_ws.fetch_replay.side_effect = ReplayNotFoundError(
            "Replay r-19221 not found on CDN.",
            details={
                "replay_id": "r-19221",
                "retention_days": 30,
                "cdn_url_prefix": "https://cdn.test/srr-us/sha/",
            },
            status_code=404,
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["replays", "fetch", "r-19221"])
        assert result.exit_code == 4
        assert "not found" in result.stderr
        assert "r-19221" in result.stderr
