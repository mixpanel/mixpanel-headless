"""Integration tests for the report-link CLI surface (045-report-links).

Covers the ``handle_errors`` exit-code branches for the report-link exception
family, ``mp reports link``, ``mp reports resolve``, and the ``--link`` flags
on ``mp query``. Fixtures follow ``tests/integration/cli/test_bookmark_commands.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from click.testing import Result
from typer.testing import CliRunner

from mixpanel_headless._internal.report_links import parse_report_link
from mixpanel_headless.cli.main import app
from mixpanel_headless.cli.utils import handle_errors
from mixpanel_headless.exceptions import (
    AuthenticationError,
    BookmarkValidationError,
    MixpanelHeadlessError,
    ParamValidationError,
    ReportLinkNotFoundError,
    ReportLinkParseError,
    ReportLinkScopeMismatchError,
    ShortLinkResolutionError,
    UnsupportedReportLinkError,
    ValidationError,
)
from mixpanel_headless.types import (
    FlowsResult,
    FunnelResult,
    QueryResult,
    ReportLink,
    ResolvedReport,
    SavedReportResult,
)


def _app_raising(exc: Exception) -> typer.Typer:
    """Build a one-command Typer app whose command raises ``exc``.

    Args:
        exc: The exception instance the command raises.

    Returns:
        A Typer app with a single ``handle_errors``-decorated command.
    """
    app = typer.Typer()

    @app.command()
    @handle_errors
    def boom() -> None:
        """Raise the injected exception."""
        raise exc

    return app


def _combined(result: object) -> str:
    """Return stdout plus stderr for a CliRunner result.

    Args:
        result: The ``click.testing.Result``.

    Returns:
        The combined output text.
    """
    output = str(getattr(result, "output", "") or "")
    try:
        stderr = str(getattr(result, "stderr", "") or "")
    except ValueError:  # pragma: no cover - older click without stderr capture
        stderr = ""
    return output + stderr


class TestHandleErrorsExitCodes:
    """contracts/cli-commands.md §4: exit codes for the report-link family."""

    def test_not_found_exits_4(self, cli_runner: CliRunner) -> None:
        """ReportLinkNotFoundError maps to NOT_FOUND (4) and prints the message."""
        exc = ReportLinkNotFoundError(
            "No unsaved report found for slug EBrV5bW2u9Mw in project 3 (us).",
            code="REPORT_LINK_SLUG_NOT_FOUND",
            details={"slug": "EBrV5bW2u9Mw"},
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 4
        assert "error:" in _combined(result)
        assert "EBrV5bW2u9Mw" in _combined(result)

    def test_not_found_prints_hint_when_present(self, cli_runner: CliRunner) -> None:
        """A ``hint`` in a not-found error is printed on its own line."""
        exc = ReportLinkNotFoundError(
            "No saved report found with id 123 in project 3 (us).",
            code="REPORT_LINK_BOOKMARK_NOT_FOUND",
            details={"bookmark_id": 123, "hint": "Check the saved report id."},
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 4
        out = _combined(result)
        assert "hint:" in out
        assert "Check the saved report id." in out

    def test_parse_error_exits_3_with_hint(self, cli_runner: CliRunner) -> None:
        """ReportLinkParseError maps to INVALID_ARGS (3) and prints the hint."""
        exc = ReportLinkParseError(
            "Could not parse report link: 'nope'",
            details={"raw": "nope", "hint": "Pass a full Mixpanel report URL."},
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 3
        out = _combined(result)
        assert "error:" in out
        assert "Could not parse" in out
        assert "hint:" in out
        assert "Pass a full Mixpanel" in out

    def test_parse_error_without_hint_prints_no_hint_line(
        self, cli_runner: CliRunner
    ) -> None:
        """No ``hint`` in details means no ``hint:`` line."""
        exc = ReportLinkParseError("Could not parse report link: 'nope'")
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 3
        assert "hint:" not in _combined(result)

    def test_unsupported_exits_3(self, cli_runner: CliRunner) -> None:
        """UnsupportedReportLinkError maps to INVALID_ARGS (3) with the hint."""
        exc = UnsupportedReportLinkError(
            "This link uses the legacy JSURL hash format.",
            code="UNSUPPORTED_LEGACY_HASH",
            details={"hint": "Open it in a browser and copy the new URL."},
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 3
        out = _combined(result)
        assert "legacy JSURL" in out
        assert "Open it in a browser" in out

    def test_scope_mismatch_exits_3(self, cli_runner: CliRunner) -> None:
        """ReportLinkScopeMismatchError maps to INVALID_ARGS (3)."""
        exc = ReportLinkScopeMismatchError(
            "Report link belongs to project 3 but the active session is project 12345.",
            code="REPORT_LINK_PROJECT_MISMATCH",
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 3
        out = _combined(result)
        assert "project 3" in out
        assert "12345" in out

    def test_short_link_resolution_exits_1(self, cli_runner: CliRunner) -> None:
        """ShortLinkResolutionError maps to GENERAL_ERROR (1)."""
        exc = ShortLinkResolutionError(
            "Shortlink /s/AbC returned HTTP 302 without a Location header.",
            code="SHORT_LINK_NO_LOCATION",
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 1
        assert "Location header" in _combined(result)

    def test_bookmark_validation_exits_3_one_line_per_error(
        self, cli_runner: CliRunner
    ) -> None:
        """BookmarkValidationError maps to INVALID_ARGS (3), one line per error."""
        exc = BookmarkValidationError(
            [
                ValidationError(path="sections.show", message="missing", code="V1"),
                ValidationError(
                    path="displayOptions.chartType",
                    message="unknown chart",
                    code="V2",
                ),
                ValidationError(
                    path="sorting", message="soft", code="S4", severity="warning"
                ),
            ]
        )
        result = cli_runner.invoke(_app_raising(exc), [])
        assert result.exit_code == 3
        out = _combined(result)
        assert "params failed schema validation" in out
        assert "sections.show: missing" in out
        assert "displayOptions.chartType: unknown chart" in out
        assert "sorting: soft" not in out


# =============================================================================
# mp reports link (US1)
# =============================================================================

_SLUG = "EBrV5bW2u9Mw"
_PARAMS = {"sections": {"show": []}, "displayOptions": {"chartType": "line"}}
_LINK = ReportLink(
    url=f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}",
    slug=_SLUG,
    report_type="insights",
    project_id=12345,
    workspace_id=75,
    name="Logins",
    created_at="2026-09-02T10:00:00",
)


def _invoke_reports(
    cli_runner: CliRunner,
    mock_workspace: MagicMock,
    args: list[str],
    *,
    input_text: str | None = None,
) -> Result:
    """Invoke ``mp reports ...`` with the workspace patched.

    Args:
        cli_runner: The Typer CLI runner.
        mock_workspace: The mocked Workspace returned by ``get_workspace``.
        args: Arguments after ``reports``.
        input_text: Optional stdin text.

    Returns:
        The click result.
    """
    with patch(
        "mixpanel_headless.cli.commands.reports.get_workspace",
        return_value=mock_workspace,
    ):
        return cli_runner.invoke(app, ["reports", *args], input=input_text)


class TestReportsLink:
    """contracts/cli-commands.md §1: ``mp reports link``."""

    def test_params_option_prints_link_dict(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--params JSON`` calls create_report_link and prints to_dict()."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner, mock_workspace, ["link", "--params", json.dumps(_PARAMS)]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == _LINK.to_dict()
        mock_workspace.create_report_link.assert_called_once_with(
            _PARAMS,
            report_type=None,
            name="",
            description="",
            workspace_id=None,
            bookmark_id=None,
            validate=True,
        )

    def test_params_file(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, tmp_path: Path
    ) -> None:
        """``--params-file PATH`` reads the JSON object from the file."""
        mock_workspace.create_report_link.return_value = _LINK
        path = tmp_path / "params.json"
        path.write_text(json.dumps(_PARAMS))

        result = _invoke_reports(
            cli_runner, mock_workspace, ["link", "--params-file", str(path)]
        )

        assert result.exit_code == 0, result.output
        assert mock_workspace.create_report_link.call_args.args[0] == _PARAMS

    def test_dash_reads_stdin(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A positional ``-`` reads the JSON object from stdin."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner, mock_workspace, ["link", "-"], input_text=json.dumps(_PARAMS)
        )

        assert result.exit_code == 0, result.output
        assert mock_workspace.create_report_link.call_args.args[0] == _PARAMS

    def test_non_tty_stdin_without_option(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """With no option and a piped stdin, the JSON object is read from stdin."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner, mock_workspace, ["link"], input_text=json.dumps(_PARAMS)
        )

        assert result.exit_code == 0, result.output
        assert mock_workspace.create_report_link.call_args.args[0] == _PARAMS

    def test_params_dash_reads_stdin(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--params -`` reads the JSON object from stdin."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["link", "--params", "-"],
            input_text=json.dumps(_PARAMS),
        )

        assert result.exit_code == 0, result.output
        assert mock_workspace.create_report_link.call_args.args[0] == _PARAMS

    @pytest.mark.parametrize(
        "args", [[], ["-"], ["--params", "-"], ["--params-file", "-"]]
    )
    def test_stdin_on_a_terminal_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, args: list[str]
    ) -> None:
        """Every stdin form refuses to block on a terminal."""
        with patch(
            "mixpanel_headless.cli.commands.reports._stdin_is_tty", return_value=True
        ):
            result = _invoke_reports(cli_runner, mock_workspace, ["link", *args])

        assert result.exit_code == 3
        assert "stdin is a terminal" in _combined(result)
        mock_workspace.create_report_link.assert_not_called()

    def test_plain_prints_only_the_url(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``-f plain`` prints the bare URL so a shell can capture it."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["link", "--params", json.dumps(_PARAMS), "-f", "plain"],
        )

        assert result.exit_code == 0, result.output
        assert result.stdout == _LINK.url + "\n"

    def test_options_reach_create_report_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """type, name, description, workspace, bookmark, no-validate are forwarded."""
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            [
                "link",
                "--params",
                json.dumps(_PARAMS),
                "--type",
                "funnels",
                "--name",
                "Logins",
                "--description",
                "last 7 days",
                "--workspace-id",
                "5",
                "--bookmark-id",
                "9",
                "--no-validate",
            ],
        )

        assert result.exit_code == 0, result.output
        mock_workspace.create_report_link.assert_called_once_with(
            _PARAMS,
            report_type="funnels",
            name="Logins",
            description="last 7 days",
            workspace_id=5,
            bookmark_id=9,
            validate=False,
        )

    def test_invalid_json_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Invalid JSON is a local input error: exit 3, no workspace call."""
        result = _invoke_reports(
            cli_runner, mock_workspace, ["link", "--params", '{"bad": ']
        )

        assert result.exit_code == 3
        assert "Invalid JSON" in _combined(result)
        mock_workspace.create_report_link.assert_not_called()

    def test_non_object_json_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A JSON array is not a params object: exit 3."""
        result = _invoke_reports(
            cli_runner, mock_workspace, ["link", "--params", "[1]"]
        )

        assert result.exit_code == 3
        mock_workspace.create_report_link.assert_not_called()

    def test_two_sources_exit_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, tmp_path: Path
    ) -> None:
        """``--params`` and ``--params-file`` together is an error: exit 3."""
        path = tmp_path / "params.json"
        path.write_text("{}")

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["link", "--params", "{}", "--params-file", str(path)],
        )

        assert result.exit_code == 3
        assert "one of" in _combined(result)
        mock_workspace.create_report_link.assert_not_called()

    def test_missing_file_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, tmp_path: Path
    ) -> None:
        """A missing ``--params-file`` is a local input error: exit 3."""
        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["link", "--params-file", str(tmp_path / "nope.json")],
        )

        assert result.exit_code == 3
        mock_workspace.create_report_link.assert_not_called()

    def test_unknown_type_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--type boards`` is rejected before the workspace call."""
        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["link", "--params", json.dumps(_PARAMS), "--type", "boards"],
        )

        assert result.exit_code == 3
        mock_workspace.create_report_link.assert_not_called()

    def test_positional_other_than_dash_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Only ``-`` is accepted as the positional source."""
        result = _invoke_reports(cli_runner, mock_workspace, ["link", "params.json"])

        assert result.exit_code == 3
        mock_workspace.create_report_link.assert_not_called()

    def test_help_has_example(self, cli_runner: CliRunner) -> None:
        """``--help`` shows at least one example invocation."""
        result = cli_runner.invoke(app, ["reports", "link", "--help"])

        assert result.exit_code == 0
        assert "mp reports link" in result.stdout


# =============================================================================
# mp reports resolve (US2)
# =============================================================================

_RESOLVED = ResolvedReport(
    source="slug",
    report_type="insights",
    params=_PARAMS,
    project_id=12345,
    workspace_id=75,
    region="us",
    url=f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}",
    input=_SLUG,
    slug=_SLUG,
    name="Logins",
)
_QUERY_RESULT = QueryResult(
    computed_at="2026-09-02T10:00:00",
    from_date="2026-08-26",
    to_date="2026-09-02",
    headers=["$event"],
    series={"Login": {"2026-08-26": 10}},
    params=_PARAMS,
)


class TestReportsResolve:
    """contracts/cli-commands.md §2: ``mp reports resolve``."""

    def test_prints_resolved_report_dict(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``mp reports resolve LINK`` prints ResolvedReport.to_dict()."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", _SLUG])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == _RESOLVED.to_dict()
        mock_workspace.resolve_report_link.assert_called_once_with(_SLUG)
        mock_workspace.query_report_link.assert_not_called()

    def test_jq_params(self, cli_runner: CliRunner, mock_workspace: MagicMock) -> None:
        """``--jq .params`` prints only the params."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", _SLUG, "--jq", ".params"]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == _PARAMS

    def test_run_calls_query_report_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--run`` resolves once, runs the ResolvedReport, prints the result."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED
        mock_workspace.query_report_link.return_value = _QUERY_RESULT
        link = f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", link, "--run"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == _QUERY_RESULT.to_dict()
        mock_workspace.resolve_report_link.assert_called_once_with(link)
        mock_workspace.query_report_link.assert_called_once_with(_RESOLVED, mode=None)

    def test_run_with_mode_forwards_mode(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--run --mode paths`` forwards the flows mode."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED
        mock_workspace.query_report_link.return_value = _QUERY_RESULT

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", _SLUG, "--run", "--mode", "paths"]
        )

        assert result.exit_code == 0, result.output
        mock_workspace.query_report_link.assert_called_once_with(
            _RESOLVED, mode="paths"
        )

    def test_run_with_invalid_mode_exits_3(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--mode bogus`` is rejected before any workspace call."""
        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", _SLUG, "--run", "--mode", "bogus"]
        )

        assert result.exit_code == 3
        mock_workspace.resolve_report_link.assert_not_called()
        mock_workspace.query_report_link.assert_not_called()

    def test_run_table_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--run -f table`` goes through present_result's table path."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED
        mock_workspace.query_report_link.return_value = _QUERY_RESULT

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", _SLUG, "--run", "-f", "table"]
        )

        assert result.exit_code == 0, result.output
        assert "Login" in result.stdout

    def test_mode_without_run_is_ignored(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--mode`` without ``--run`` is accepted and ignored."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", _SLUG, "--mode", "paths"]
        )

        assert result.exit_code == 0, result.output
        mock_workspace.resolve_report_link.assert_called_once_with(_SLUG)

    def test_overrides_tail_prints_warning(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A bookmark URL with a ``~(...)`` tail prints the §7 warning to stderr."""
        mock_workspace.resolve_report_link.return_value = _RESOLVED
        link = "https://mixpanel.com/project/12345/app/insights#report/123/~(a~1)"

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", link])

        assert result.exit_code == 0, result.output
        assert "ignoring URL overrides" in _combined(result)
        assert json.loads(result.stdout) == _RESOLVED.to_dict()

    def test_run_resolves_once_and_warns_from_expanded_short_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--run`` resolves in the command, warns on ``~(...)``, runs the report."""
        short = "https://mixpanel.com/s/AbC"
        expanded = "https://mixpanel.com/project/12345/app/funnels#view/123/~(a~1)"
        resolved = ResolvedReport(
            **{
                **_RESOLVED.__dict__,
                "input": short,
                "expanded_url": expanded,
                "source": "bookmark",
                "slug": None,
                "bookmark_id": 123,
            }
        )
        mock_workspace.resolve_report_link.return_value = resolved
        mock_workspace.query_report_link.return_value = _QUERY_RESULT

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", short, "--run"]
        )

        assert result.exit_code == 0, result.output
        assert "ignoring URL overrides '~(a~1)'" in _combined(result)
        mock_workspace.resolve_report_link.assert_called_once_with(short)
        mock_workspace.query_report_link.assert_called_once_with(resolved, mode=None)

    def test_scope_mismatch_exits_3_with_both_projects(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A project mismatch from the workspace exits 3 and names both ids."""
        mock_workspace.resolve_report_link.side_effect = ReportLinkScopeMismatchError(
            "Report link belongs to project 3 but the active session is project 12345.",
            code="REPORT_LINK_PROJECT_MISMATCH",
            details={
                "hint": 'Switch with ws.use(project="3") (CLI: mp --project 3 ...) '
                "and retry."
            },
        )

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["resolve", f"https://mixpanel.com/project/3/app/insights#{_SLUG}"],
        )

        assert result.exit_code == 3
        out = _combined(result)
        assert "project 3" in out
        assert "12345" in out
        assert "hint:" in out
        assert "mp --project 3" in out

    @pytest.mark.parametrize(
        ("link", "code"),
        [
            ("nope", "REPORT_LINK_UNPARSEABLE"),
            (
                "https://example.com/project/3/app/insights#x",
                "REPORT_LINK_NOT_MIXPANEL_HOST",
            ),
            ("https://mixpanel.com/project/3/app/insights", "REPORT_LINK_EMPTY_HASH"),
        ],
    )
    def test_real_parse_error_exits_3_with_hint(
        self,
        cli_runner: CliRunner,
        mock_workspace: MagicMock,
        link: str,
        code: str,
    ) -> None:
        """A real parser error travels through the command to exit 3 and a hint."""
        mock_workspace.resolve_report_link.side_effect = parse_report_link

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", link])

        assert result.exit_code == 3, result.output
        out = _combined(result)
        assert "error:" in out
        assert "hint:" in out
        assert code not in out  # the message is prose, not the code

    def test_overrides_tail_behind_short_link_prints_warning(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A shortlink that expands to a saved-report link with ``~(...)`` warns."""
        short = "https://mixpanel.com/s/AbC"
        expanded = "https://mixpanel.com/project/12345/app/funnels#view/123/~(a~1)"
        mock_workspace.resolve_report_link.return_value = ResolvedReport(
            **{
                **_RESOLVED.__dict__,
                "input": short,
                "expanded_url": expanded,
                "source": "bookmark",
                "slug": None,
                "bookmark_id": 123,
            }
        )

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", short])

        assert result.exit_code == 0, result.output
        assert "ignoring URL overrides '~(a~1)'" in _combined(result)

    def test_not_found_exits_4(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """An unknown slug exits 4."""
        mock_workspace.resolve_report_link.side_effect = ReportLinkNotFoundError(
            f"No unsaved report found for slug {_SLUG} in project 12345 (us).",
            code="REPORT_LINK_SLUG_NOT_FOUND",
        )

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", _SLUG])

        assert result.exit_code == 4
        assert "No unsaved report" in _combined(result)

    def test_legacy_hash_exits_3_with_browser_hint(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A legacy hash exits 3 and prints the browser hint."""
        mock_workspace.resolve_report_link.side_effect = UnsupportedReportLinkError(
            "This link uses the legacy JSURL hash format, which mixpanel-headless "
            "cannot decode.",
            code="UNSUPPORTED_LEGACY_HASH",
            details={
                "hint": (
                    "Open it in a browser (the app re-mints a shareable link on "
                    "load) and copy the new URL."
                )
            },
        )

        result = _invoke_reports(
            cli_runner,
            mock_workspace,
            ["resolve", "https://mixpanel.com/project/12345/app/insights#~(x)"],
        )

        assert result.exit_code == 3
        out = _combined(result)
        assert "legacy JSURL" in out
        assert "Open it in a browser" in out

    def test_help_has_quoted_example(self, cli_runner: CliRunner) -> None:
        """``--help`` shows an example that quotes the URL because of ``#``."""
        result = cli_runner.invoke(app, ["reports", "resolve", "--help"])

        assert result.exit_code == 0
        assert "mp reports resolve" in result.stdout
        assert "'https://" in result.stdout


# =============================================================================
# shortlinks (US3)
# =============================================================================


class TestReportsResolveShortLink:
    """``mp reports resolve`` with a shortlink input."""

    def test_short_link_prints_expanded_url(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """The resolved report carries ``expanded_url`` and the shortlink ``input``."""
        short = "https://mixpanel.com/s/AbC"
        resolved = ResolvedReport(
            **{
                **_RESOLVED.__dict__,
                "input": short,
                "expanded_url": _RESOLVED.url,
            }
        )
        mock_workspace.resolve_report_link.return_value = resolved

        result = _invoke_reports(cli_runner, mock_workspace, ["resolve", short])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["expanded_url"] == _RESOLVED.url
        assert data["input"] == short
        mock_workspace.resolve_report_link.assert_called_once_with(short)

    def test_login_redirect_exits_2(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """An AuthenticationError from a login redirect exits 2."""
        mock_workspace.resolve_report_link.side_effect = AuthenticationError(
            "Shortlink /s/AbC requires authentication; the server redirected to "
            "the login page.",
            status_code=302,
        )

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", "https://mixpanel.com/s/AbC"]
        )

        assert result.exit_code == 2
        assert "requires authentication" in _combined(result)

    def test_short_link_resolution_error_exits_1(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A ShortLinkResolutionError exits 1 with its hint."""
        mock_workspace.resolve_report_link.side_effect = ShortLinkResolutionError(
            "Shortlink /s/AbC redirects to another shortlink "
            "(https://mixpanel.com/s/XyZ). mixpanel-headless follows one redirect "
            "only.",
            code="SHORT_LINK_CHAIN",
            details={"hint": "Resolve the target shortlink directly."},
        )

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", "https://mixpanel.com/s/AbC"]
        )

        assert result.exit_code == 1
        out = _combined(result)
        assert "another shortlink" in out
        assert "Resolve the target shortlink directly" in out

    def test_short_link_not_found_exits_4(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A missing shortlink exits 4."""
        mock_workspace.resolve_report_link.side_effect = ReportLinkNotFoundError(
            "Shortlink /s/AbC does not exist on mixpanel.com.",
            code="SHORT_LINK_NOT_FOUND",
        )

        result = _invoke_reports(
            cli_runner, mock_workspace, ["resolve", "https://mixpanel.com/s/AbC"]
        )

        assert result.exit_code == 4


# =============================================================================
# --link on mp query (US4)
# =============================================================================

_REPORT_URL = f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}"
_SEG_ARGS = [
    "query",
    "segmentation",
    "-e",
    "Login",
    "--from",
    "2026-08-01",
    "--to",
    "2026-08-31",
]


def _invoke_query(
    cli_runner: CliRunner, mock_workspace: MagicMock, args: list[str]
) -> Result:
    """Invoke ``mp query ...`` with the workspace patched.

    Args:
        cli_runner: The Typer CLI runner.
        mock_workspace: The mocked Workspace returned by ``get_workspace``.
        args: The full argument list starting with ``query``.

    Returns:
        The click result.
    """
    with patch(
        "mixpanel_headless.cli.commands.query.get_workspace",
        return_value=mock_workspace,
    ):
        return cli_runner.invoke(app, args)


class TestSegmentationLink:
    """contracts/cli-commands.md §3: ``mp query segmentation --link``."""

    def test_link_builds_params_and_creates_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--link`` calls build_params + create_report_link and adds report_url."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(
            cli_runner,
            mock_workspace,
            [*_SEG_ARGS, "-u", "week", "--on", "country", "--link"],
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["report_url"] == _LINK.url
        assert data["event"] == "Signup"  # the conftest SegmentationResult still prints
        mock_workspace.build_params.assert_called_once_with(
            "Login",
            from_date="2026-08-01",
            to_date="2026-08-31",
            unit="week",
            group_by="country",
        )
        mock_workspace.create_report_link.assert_called_once_with(_PARAMS)

    def test_link_without_on_has_no_group_by(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Without ``--on`` the params carry no breakdown."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(cli_runner, mock_workspace, [*_SEG_ARGS, "--link"])

        assert result.exit_code == 0, result.output
        mock_workspace.build_params.assert_called_once_with(
            "Login",
            from_date="2026-08-01",
            to_date="2026-08-31",
            unit="day",
            group_by=None,
        )

    def test_where_warns_and_omits_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``--where`` prints the §7 warning and omits report_url; exit 0."""
        result = _invoke_query(
            cli_runner,
            mock_workspace,
            [*_SEG_ARGS, "--where", 'properties["x"] == 1', "--link"],
        )

        assert result.exit_code == 0, result.output
        assert "--link is not supported with --where; link omitted" in _combined(result)
        data = json.loads(result.stdout)
        assert data["report_url"] is None
        assert data["report_url_error"] == "--link is not supported with --where"
        mock_workspace.create_report_link.assert_not_called()
        mock_workspace.segmentation.assert_called_once()

    @pytest.mark.parametrize(
        "on",
        [
            'defined(properties["x"])',
            'properties["x"] > 1',
            "number(x)",
            "string(x) == 'y'",
            'user["Country"]',
            'event["Plan"]',
            "a != b",
            "a < b",
        ],
    )
    def test_non_bare_on_warns_and_omits_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, on: str
    ) -> None:
        """An expression in ``--on`` prints the warning and nulls report_url."""
        result = _invoke_query(
            cli_runner, mock_workspace, [*_SEG_ARGS, "--on", on, "--link"]
        )

        assert result.exit_code == 0, result.output
        assert "bare property name for --on only; link omitted" in _combined(result)
        data = json.loads(result.stdout)
        assert data["report_url"] is None
        assert data["report_url_error"] == (
            "--link supports a bare property name for --on only"
        )
        mock_workspace.create_report_link.assert_not_called()

    @pytest.mark.parametrize(
        "on",
        [
            "Plan Type",
            "$city",
            "country",
            "Ünïcode prop",
            "Terms and Conditions",
            "Sign In or Up",
            "Undefined Reason",
            "Price (USD)",
        ],
    )
    def test_bare_on_produces_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, on: str
    ) -> None:
        """Spaces, ``$``, Unicode, words like ``and``, and parentheses are bare."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(
            cli_runner, mock_workspace, [*_SEG_ARGS, "--on", on, "--link"]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["report_url"] == _LINK.url
        assert mock_workspace.build_params.call_args.kwargs["group_by"] == on

    def test_create_failure_warns_and_still_prints_result(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A MixpanelHeadlessError from create_report_link never fails the query."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.side_effect = MixpanelHeadlessError(
            "server said no"
        )

        result = _invoke_query(cli_runner, mock_workspace, [*_SEG_ARGS, "--link"])

        assert result.exit_code == 0, result.output
        assert "could not create report link: server said no" in _combined(result)
        data = json.loads(result.stdout)
        assert data["report_url"] is None
        assert data["report_url_error"] == "server said no"
        assert data["event"] == "Signup"

    def test_auth_failure_on_link_is_isolated_too(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Even an AuthenticationError from the link step leaves the query intact."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.side_effect = AuthenticationError(
            "Invalid credentials.", status_code=401
        )

        result = _invoke_query(cli_runner, mock_workspace, [*_SEG_ARGS, "--link"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["report_url"] is None
        assert "Invalid credentials" in data["report_url_error"]

    def test_jq_report_url_prints_the_url(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """The documented ``--link --jq .report_url`` prints the URL string."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(
            cli_runner, mock_workspace, [*_SEG_ARGS, "--link", "--jq", ".report_url"]
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.strip().strip('"') == _LINK.url

    @pytest.mark.parametrize("fmt", ["jsonl", "csv", "plain"])
    def test_link_with_other_formats(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, fmt: str
    ) -> None:
        """``--link`` with jsonl, csv, or plain output still shows the URL."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(
            cli_runner, mock_workspace, [*_SEG_ARGS, "--link", "-f", fmt]
        )

        assert result.exit_code == 0, result.output
        assert _LINK.url in result.stdout

    def test_build_params_failure_warns_and_still_prints_result(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A ParamValidationError from build_params is also isolated."""
        mock_workspace.build_params.side_effect = ParamValidationError(
            "bad unit", code="TC1B_INVALID_UNIT"
        )

        result = _invoke_query(cli_runner, mock_workspace, [*_SEG_ARGS, "--link"])

        assert result.exit_code == 0, result.output
        assert "could not create report link" in _combined(result)
        mock_workspace.create_report_link.assert_not_called()

    def test_without_link_output_unchanged(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Without ``--link`` there is no report_url key and no link call."""
        result = _invoke_query(cli_runner, mock_workspace, _SEG_ARGS)

        assert result.exit_code == 0, result.output
        assert "report_url" not in json.loads(result.stdout)
        mock_workspace.build_params.assert_not_called()
        mock_workspace.create_report_link.assert_not_called()

    def test_link_table_format_prints_url_line(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """With ``-f table`` the URL is printed on its own line after the table."""
        mock_workspace.build_params.return_value = _PARAMS
        mock_workspace.create_report_link.return_value = _LINK

        result = _invoke_query(
            cli_runner, mock_workspace, [*_SEG_ARGS, "--link", "-f", "table"]
        )

        assert result.exit_code == 0, result.output
        assert _LINK.url in result.stdout.replace("\n", "")

    def test_token_list_is_importable(self) -> None:
        """The bare-``--on`` token list is one module-level tuple of symbols."""
        from mixpanel_headless.cli.commands.query import NON_BARE_ON_TOKENS

        assert isinstance(NON_BARE_ON_TOKENS, tuple)
        for token in ("[", "]", '"', "'", "==", "!=", "<", ">", "&&", "||"):
            assert token in NON_BARE_ON_TOKENS
        for call in ("boolean(", "number(", "string(", "defined("):
            assert call in NON_BARE_ON_TOKENS
        for word in (" and ", " or ", "defined", "(", ")"):
            assert word not in NON_BARE_ON_TOKENS

    def test_help_states_approximation(self, cli_runner: CliRunner) -> None:
        """``--help`` explains that the link reproduces a subset of the query."""
        result = cli_runner.invoke(app, ["query", "segmentation", "--help"])

        assert result.exit_code == 0
        assert "--link" in result.stdout
        assert "bare" in result.stdout


class TestSavedReportLinks:
    """contracts/cli-commands.md §3: ``--link`` on funnel, saved-report, flows."""

    def test_funnel_link(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """``query funnel 456 --link`` adds saved_report_link(456, funnels)."""
        mock_workspace.funnel.return_value = FunnelResult(
            funnel_id=456,
            funnel_name="Onboarding",
            from_date="2026-08-01",
            to_date="2026-08-31",
            conversion_rate=0.5,
            steps=[],
        )
        mock_workspace.saved_report_link.return_value = _REPORT_URL

        result = _invoke_query(
            cli_runner,
            mock_workspace,
            [
                "query",
                "funnel",
                "456",
                "--from",
                "2026-08-01",
                "--to",
                "2026-08-31",
                "--link",
            ],
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["report_url"] == _REPORT_URL
        mock_workspace.saved_report_link.assert_called_once_with(
            456, report_type="funnels"
        )
        mock_workspace.create_report_link.assert_not_called()

    @pytest.mark.parametrize(
        ("headers", "expected_type"),
        [
            (["$event"], "insights"),
            (["$funnel"], "funnel"),
            (["$retention"], "retention"),
            (["$flows"], "flows"),
        ],
    )
    def test_saved_report_link_passes_detected_type(
        self,
        cli_runner: CliRunner,
        mock_workspace: MagicMock,
        headers: list[str],
        expected_type: str,
    ) -> None:
        """``query saved-report 123 --link`` passes result.report_type through."""
        mock_workspace.query_saved_report.return_value = SavedReportResult(
            bookmark_id=123,
            computed_at="2026-09-02T10:00:00",
            from_date="2026-08-01",
            to_date="2026-08-31",
            headers=headers,
            series={},
        )
        mock_workspace.saved_report_link.return_value = _REPORT_URL

        result = _invoke_query(
            cli_runner, mock_workspace, ["query", "saved-report", "123", "--link"]
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["report_url"] == _REPORT_URL
        assert data["report_type"] == expected_type
        mock_workspace.saved_report_link.assert_called_once_with(
            123, report_type=expected_type
        )
        mock_workspace.create_report_link.assert_not_called()

    def test_flows_link(self, cli_runner: CliRunner, mock_workspace: MagicMock) -> None:
        """``query flows 8 --link`` adds saved_report_link(8, flows)."""
        mock_workspace.query_saved_flows.return_value = FlowsResult(
            bookmark_id=8, computed_at="2026-09-02T10:00:00"
        )
        mock_workspace.saved_report_link.return_value = _REPORT_URL

        result = _invoke_query(
            cli_runner, mock_workspace, ["query", "flows", "8", "--link"]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["report_url"] == _REPORT_URL
        mock_workspace.saved_report_link.assert_called_once_with(8, report_type="flows")
        mock_workspace.create_report_link.assert_not_called()

    @pytest.mark.parametrize(
        "args",
        [
            ["query", "funnel", "456", "--from", "2026-08-01", "--to", "2026-08-31"],
            ["query", "saved-report", "123"],
            ["query", "flows", "8"],
        ],
    )
    def test_saved_link_failure_never_fails_the_query(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, args: list[str]
    ) -> None:
        """A raise from saved_report_link keeps the result and exit 0."""
        mock_workspace.funnel.return_value = FunnelResult(
            funnel_id=456,
            funnel_name="Onboarding",
            from_date="2026-08-01",
            to_date="2026-08-31",
            conversion_rate=0.5,
            steps=[],
        )
        mock_workspace.query_saved_report.return_value = SavedReportResult(
            bookmark_id=123,
            computed_at="t",
            from_date="d",
            to_date="d",
            headers=["$event"],
            series={},
        )
        mock_workspace.query_saved_flows.return_value = FlowsResult(
            bookmark_id=8, computed_at="2026-09-02T10:00:00"
        )
        mock_workspace.saved_report_link.side_effect = ParamValidationError(
            "Unknown region 'xx'.", code="RL3_UNKNOWN_REGION"
        )

        result = _invoke_query(cli_runner, mock_workspace, [*args, "--link"])

        assert result.exit_code == 0, result.output
        assert "could not create report link: Unknown region" in _combined(result)
        data = json.loads(result.stdout)
        assert data["report_url"] is None
        assert data["report_url_error"] == "Unknown region 'xx'."

    @pytest.mark.parametrize("fmt", ["table", "plain"])
    def test_saved_report_link_table_and_plain_print_a_separate_line(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, fmt: str
    ) -> None:
        """Like the other ``--link`` commands: unchanged result, then a URL line."""
        mock_workspace.query_saved_report.return_value = SavedReportResult(
            bookmark_id=123,
            computed_at="t",
            from_date="d",
            to_date="d",
            headers=["$event"],
            series={},
        )
        mock_workspace.saved_report_link.return_value = _REPORT_URL

        result = _invoke_query(
            cli_runner,
            mock_workspace,
            ["query", "saved-report", "123", "--link", "-f", fmt],
        )

        assert result.exit_code == 0, result.output
        lines = result.stdout.rstrip("\n").split("\n")
        assert lines[-1] == f"report_url: {_REPORT_URL}"
        assert "report_url=" not in result.stdout
        # The URL is not embedded in the formatted result itself.
        assert _REPORT_URL not in "\n".join(lines[:-1]).replace("\n", "")

    def test_saved_report_without_link_unchanged(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Without ``--link`` the saved-report output has no report_url."""
        mock_workspace.query_saved_report.return_value = SavedReportResult(
            bookmark_id=123,
            computed_at="t",
            from_date="d",
            to_date="d",
            headers=["$event"],
            series={},
        )

        result = _invoke_query(
            cli_runner, mock_workspace, ["query", "saved-report", "123"]
        )

        assert result.exit_code == 0, result.output
        assert "report_url" not in json.loads(result.stdout)
        mock_workspace.saved_report_link.assert_not_called()
