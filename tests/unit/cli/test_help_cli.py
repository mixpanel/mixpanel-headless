"""CliRunner tests for ``mp help``.

Covers the documented command-line examples, the exit-code contract
(0 found, 4 miss, 3 invalid flags), the three output formats, ``--jq``
gating, ``--domain`` filtering, ``--no-hints``, variadic query tokens, the
literal ``[property]`` tag, and isolation from the config file and the
auth flags.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

from mixpanel_headless.cli.main import app
from mixpanel_headless.cli.utils import ExitCode, handle_errors
from mixpanel_headless.exceptions import HelpLookupError


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin ``HOME`` and ``MP_CONFIG_PATH`` to an empty dir and drop ``MP_*`` vars.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The empty home directory used for the isolation assertions.
    """
    home = tmp_path / "home"
    home.mkdir()
    for key in list(os.environ):
        if key.startswith("MP_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MP_CONFIG_PATH", str(home / "config.toml"))
    return home


@pytest.fixture
def runner() -> CliRunner:
    """Return a Typer ``CliRunner``.

    Returns:
        A fresh ``CliRunner`` instance.
    """
    return CliRunner()


class TestDocumentedExamples:
    """Every documented command line exits 0 with the expected shape."""

    def test_overview(self, runner: CliRunner) -> None:
        """``mp help`` prints the overview with the version and llms.txt link."""
        result = runner.invoke(app, ["help"])
        assert result.exit_code == 0, result.output
        assert "mixpanel_headless" in result.output
        assert "llms.txt" in result.output
        assert len(result.output.splitlines()) < 60

    def test_workspace_listing(self, runner: CliRunner) -> None:
        """``mp help Workspace`` prints grouped methods and the literal property tag."""
        result = runner.invoke(app, ["help", "Workspace"])
        assert result.exit_code == 0, result.output
        assert "[property]" in result.output
        assert "dashboards (" in result.output
        assert "session replay (" in result.output

    def test_workspace_domain_filter(self, runner: CliRunner) -> None:
        """``--domain`` keeps only the named group."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "session replay"])
        assert result.exit_code == 0, result.output
        assert "session replay (" in result.output
        assert "dashboards (" not in result.output

    def test_workspace_method(self, runner: CliRunner) -> None:
        """``mp help Workspace.query`` prints the signature block and a tip."""
        result = runner.invoke(app, ["help", "Workspace.query"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("Workspace.query(")
        assert "Referenced types (" in result.output
        assert "Tip:" in result.output

    def test_json_with_jq(self, runner: CliRunner) -> None:
        """``-f json --jq`` applies the filter to the JSON payload."""
        result = runner.invoke(
            app, ["help", "Filter", "-f", "json", "--jq", ".construction[].name"]
        )
        assert result.exit_code == 0, result.output
        assert "equals" in result.output

    def test_markdown(self, runner: CliRunner) -> None:
        """``-f markdown`` emits a fenced code block."""
        result = runner.invoke(app, ["help", "MathType", "-f", "markdown"])
        assert result.exit_code == 0, result.output
        assert "```" in result.output
        assert "MathType" in result.output

    def test_search(self, runner: CliRunner) -> None:
        """``mp help search cohort`` prints search hits."""
        result = runner.invoke(app, ["help", "search", "cohort"])
        assert result.exit_code == 0, result.output
        assert "CohortAggregationType" in result.output

    def test_exceptions_no_hints(self, runner: CliRunner) -> None:
        """``mp help exceptions --no-hints`` prints the tree without a tip."""
        result = runner.invoke(app, ["help", "exceptions", "--no-hints"])
        assert result.exit_code == 0, result.output
        assert "MixpanelHeadlessError" in result.output
        assert "HelpLookupError" in result.output
        assert "Tip:" not in result.output

    def test_types_listing(self, runner: CliRunner) -> None:
        """``mp help types`` prints the grouped type listing."""
        result = runner.invoke(app, ["help", "types"])
        assert result.exit_code == 0, result.output
        assert "literal aliases (" in result.output


class TestExitCodes:
    """Exit codes: 0 found, 4 miss, 3 flag misuse."""

    def test_miss_exits_4_with_suggestions_on_stdout(self, runner: CliRunner) -> None:
        """An unknown query exits 4 and prints suggestions on stdout."""
        result = runner.invoke(app, ["help", "Workspace.query_funel"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert "No help entry for 'Workspace.query_funel'." in result.output
        assert "Did you mean?" in result.output
        assert "Workspace.query_funnel" in result.output

    def test_miss_json(self, runner: CliRunner) -> None:
        """A miss with ``-f json`` prints a JSON error object and exits 4."""
        result = runner.invoke(app, ["help", "nonesuch_thing", "-f", "json"])
        assert result.exit_code == ExitCode.NOT_FOUND
        payload = json.loads(result.output)
        assert payload["query"] == "nonesuch_thing"
        assert "suggestions" in payload
        assert "hits" in payload

    def test_jq_without_json_exits_3(self, runner: CliRunner) -> None:
        """``--jq`` requires ``-f json``."""
        result = runner.invoke(app, ["help", "Filter", "--jq", ".kind"])
        assert result.exit_code == ExitCode.INVALID_ARGS

    def test_search_without_term_exits_3(self, runner: CliRunner) -> None:
        """A bare ``search`` prints usage and exits 3."""
        result = runner.invoke(app, ["help", "search"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert "search" in result.output

    def test_unknown_domain_exits_3(self, runner: CliRunner) -> None:
        """An unknown ``--domain`` exits 3 and lists the titles."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "nope"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert "dashboards" in result.output

    def test_domain_on_non_workspace_exits_3(self, runner: CliRunner) -> None:
        """``--domain`` with a non-``Workspace`` query exits 3."""
        result = runner.invoke(app, ["help", "Filter", "--domain", "dashboards"])
        assert result.exit_code == ExitCode.INVALID_ARGS

    def test_handle_errors_maps_help_lookup_error_to_4(self) -> None:
        """``handle_errors`` maps ``HelpLookupError`` to exit code 4."""

        @handle_errors
        def _miss() -> None:
            """Raise a lookup miss for the decorator to map."""
            raise HelpLookupError("nope", suggestions=("Filter",))

        with pytest.raises(click.exceptions.Exit) as exc:
            _miss()
        assert exc.value.exit_code == ExitCode.NOT_FOUND


class TestFlags:
    """Format, hints, domain, and token handling."""

    def test_no_hints_removes_tip(self, runner: CliRunner) -> None:
        """``--no-hints`` suppresses the ``Tip:`` block."""
        with_hints = runner.invoke(app, ["help", "Workspace.create_dashboard"])
        without = runner.invoke(
            app, ["help", "Workspace.create_dashboard", "--no-hints"]
        )
        assert "Tip:" in with_hints.output
        assert "Tip:" not in without.output

    def test_domain_prefix(self, runner: CliRunner) -> None:
        """A unique case-insensitive prefix selects the domain."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "FUNNEL"])
        assert result.exit_code == 0, result.output
        assert "funnel query (" in result.output
        assert "retention query (" not in result.output

    def test_variadic_tokens_equal_quoted_form(self, runner: CliRunner) -> None:
        """Separate tokens and one quoted string produce identical output."""
        split = runner.invoke(app, ["help", "search", "cohort"])
        quoted = runner.invoke(app, ["help", "search cohort"])
        assert split.exit_code == 0
        assert split.output == quoted.output

    def test_json_parses(self, runner: CliRunner) -> None:
        """``-f json`` output is a JSON object with the entry kind."""
        result = runner.invoke(app, ["help", "FeatureFlagStatus", "-f", "json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["kind"] == "enum"

    def test_search_json(self, runner: CliRunner) -> None:
        """``search`` with ``-f json`` emits the search payload."""
        result = runner.invoke(app, ["help", "search", "cohort", "-f", "json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["term"] == "cohort"
        assert payload["hits"]

    def test_invalid_format_rejected(self, runner: CliRunner) -> None:
        """An unsupported format is rejected by the option parser."""
        result = runner.invoke(app, ["help", "Filter", "-f", "table"])
        assert result.exit_code != 0

    def test_command_help(self, runner: CliRunner) -> None:
        """``mp help --help`` documents the flags."""
        result = runner.invoke(app, ["help", "--help"])
        assert result.exit_code == 0, result.output
        assert "--domain" in result.output
        assert "--no-hints" in result.output
        assert "--jq" in result.output


class TestIsolation:
    """The command reads no config and ignores the auth flags."""

    def test_empty_home_stays_empty(
        self, runner: CliRunner, _isolated_env: Path
    ) -> None:
        """Running the command creates no file under the isolated home."""
        result = runner.invoke(app, ["help", "Workspace.query"])
        assert result.exit_code == 0, result.output
        assert list(_isolated_env.iterdir()) == []

    def test_global_account_flag_is_ignored(self, runner: CliRunner) -> None:
        """``-a`` before the command does not stop an offline lookup."""
        result = runner.invoke(app, ["-a", "nonexistent", "help", "Filter"])
        assert result.exit_code == 0, result.output
        assert "class Filter" in result.output

    def test_property_tag_survives(self, runner: CliRunner) -> None:
        """The literal ``[property]`` tag is not eaten as Rich markup."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "dashboards"])
        assert result.exit_code == 0
        listing = runner.invoke(app, ["help", "Workspace"])
        assert "[property]" in listing.output
