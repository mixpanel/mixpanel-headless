"""CliRunner tests for ``mp help``.

Covers the documented command-line examples, the exit-code contract
(0 found, 4 miss or empty search, 3 flag misuse, 2 bad option value), the
stdout / stderr split (results and misses on stdout, flag misuse on
stderr), the three output formats, ``--jq`` gating, ``--domain``
filtering and its error cases, ``--no-hints``, variadic query tokens, the
literal ``[property]`` tag, and isolation from the config file and the
auth flags.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

from mixpanel_headless import reference as ref
from mixpanel_headless._internal.help.models import HELP_FORMATS
from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS
from mixpanel_headless.cli.main import app
from mixpanel_headless.cli.utils import ExitCode, handle_errors
from mixpanel_headless.exceptions import HelpDomainError, HelpLookupError

DOMAIN_TITLES = tuple(title for title, _ in WORKSPACE_DOMAINS)
"""Every registered ``Workspace`` domain title, in registry order."""


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
        """``-f json --jq`` applies the filter: one JSON string per line."""
        result = runner.invoke(
            app, ["help", "Filter", "-f", "json", "--jq", ".construction[].name"]
        )
        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert lines
        values = [json.loads(line) for line in lines]
        assert all(isinstance(value, str) for value in values)
        assert "equals" in values
        assert "kind" not in result.stdout

    def test_json_with_jq_single_value(self, runner: CliRunner) -> None:
        """A filter that yields one value prints that value alone."""
        result = runner.invoke(app, ["help", "Filter", "-f", "json", "--jq", ".kind"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == "dataclass"
        assert result.stdout == '"dataclass"\n'

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

    def test_help_entry_describes_itself(self, runner: CliRunner) -> None:
        """``mp help HelpEntry`` renders the help system's own result type."""
        result = runner.invoke(app, ["help", "HelpEntry"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("class HelpEntry\n")
        assert "Fields (public):" in result.output
        assert "  kind: " in result.output

    def test_search_finds_help_entry(self, runner: CliRunner) -> None:
        """``mp help search HelpEntry`` lists the root export as a dataclass hit."""
        result = runner.invoke(app, ["help", "search", "HelpEntry"])
        assert result.exit_code == 0, result.output
        assert "[dataclass] HelpEntry " in result.output

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
    """Exit codes: 0 found, 4 miss or empty search, 3 flag misuse."""

    def test_miss_exits_4_with_suggestions_on_stdout(self, runner: CliRunner) -> None:
        """An unknown query exits 4 and prints suggestions on stdout only."""
        result = runner.invoke(app, ["help", "Workspace.query_funel"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert result.stdout.startswith("No help entry for 'Workspace.query_funel'.")
        assert "Did you mean: " in result.stdout
        assert "Workspace.query_funnel" in result.stdout
        assert result.stderr == ""

    def test_miss_with_hits_exits_4(self, runner: CliRunner) -> None:
        """A near miss prints the suggestions and the search view, exits 4."""
        result = runner.invoke(app, ["help", "Cohor"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert result.stdout.startswith(
            "No help entry for 'Cohor'. Did you mean: Cohort, "
        )
        assert '# Search: "Cohor"' in result.stdout
        assert any(
            line.startswith("  [dataclass] Cohort")
            for line in result.stdout.splitlines()
        )

    @pytest.mark.parametrize("fmt", HELP_FORMATS)
    def test_miss_output_equals_python_help(self, runner: CliRunner, fmt: str) -> None:
        """The CLI miss text is exactly what ``mp.help()`` prints for the query.

        Args:
            fmt: One of the help output formats.
        """
        result = runner.invoke(app, ["help", "Cohor", "-f", fmt])
        assert result.exit_code == ExitCode.NOT_FOUND
        buffer = io.StringIO()
        ref.help("Cohor", format=fmt, file=buffer)  # type: ignore[arg-type]
        assert result.stdout == buffer.getvalue()

    def test_miss_json(self, runner: CliRunner) -> None:
        """A miss with ``-f json`` prints a JSON error object and exits 4."""
        result = runner.invoke(app, ["help", "nonesuch_thing", "-f", "json"])
        assert result.exit_code == ExitCode.NOT_FOUND
        payload = json.loads(result.stdout)
        assert payload["query"] == "nonesuch_thing"
        assert "suggestions" in payload
        assert "hits" in payload

    def test_miss_with_domain_takes_miss_path(self, runner: CliRunner) -> None:
        """A name miss exits 4 with the normal miss text even with ``--domain``."""
        result = runner.invoke(app, ["help", "Filtr", "--domain", "dashboards"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert result.stdout.startswith("No help entry for 'Filtr'. Did you mean: ")
        assert "Filter" in result.stdout
        assert "Domains:" not in result.output
        assert result.stderr == ""

    def test_uninspectable_builtin_member_exits_4(self, runner: CliRunner) -> None:
        """An inherited builtin without a signature is a plain miss, exit 4."""
        result = runner.invoke(app, ["help", "FeatureFlagStatus.maketrans"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert result.stdout.startswith(
            "No help entry for 'FeatureFlagStatus.maketrans'."
        )
        assert "Invalid argument" not in result.output
        assert result.stderr == ""

    def test_jq_without_json_exits_3(self, runner: CliRunner) -> None:
        """``--jq`` requires ``-f json``."""
        result = runner.invoke(app, ["help", "Filter", "--jq", ".kind"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        assert "--jq requires --format json" in result.stderr

    def test_search_without_term_exits_3(self, runner: CliRunner) -> None:
        """A bare ``search`` prints one usage line on stderr and exits 3."""
        result = runner.invoke(app, ["help", "search"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        assert result.stderr == (
            "Error: search needs a term. Usage: mp help search <term>\n"
        )

    def test_search_without_hits_exits_4(self, runner: CliRunner) -> None:
        """A search that matches nothing still prints its view, then exits 4."""
        result = runner.invoke(app, ["help", "search", "zzzzqqqq"])
        assert result.exit_code == ExitCode.NOT_FOUND
        assert result.stdout == 'No matches for "zzzzqqqq"\n'
        assert result.stderr == ""

    def test_search_without_hits_json_exits_4(self, runner: CliRunner) -> None:
        """Under ``-f json`` an empty search prints the JSON object and exits 4."""
        result = runner.invoke(app, ["help", "search", "zzzzqqqq", "-f", "json"])
        assert result.exit_code == ExitCode.NOT_FOUND
        payload = json.loads(result.stdout)
        assert payload["term"] == "zzzzqqqq"
        assert payload["hits"] == []

    def test_unknown_domain_exits_3(self, runner: CliRunner) -> None:
        """An unknown ``--domain`` exits 3; stderr has the message and one list."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "nope"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines == [
            "Error: Unknown domain 'nope'.",
            "Domains: " + ", ".join(DOMAIN_TITLES),
        ]
        assert result.stderr.count("dashboards") == 1

    def test_ambiguous_domain_exits_3(self, runner: CliRunner) -> None:
        """An ambiguous ``--domain`` prefix exits 3 and lists the candidates."""
        result = runner.invoke(app, ["help", "Workspace", "--domain", "se"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        assert result.stderr.splitlines() == [
            "Error: Ambiguous domain 'se': session and switching, session replay.",
            "Domains: session and switching, session replay",
        ]

    def test_domain_on_non_workspace_exits_3(self, runner: CliRunner) -> None:
        """``--domain`` with a non-``Workspace`` query exits 3 and says why."""
        result = runner.invoke(app, ["help", "Filter", "--domain", "dashboards"])
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        assert result.stderr == (
            "Error: --domain applies only to the Workspace listing; "
            "'Filter' is not the Workspace class.\n"
        )
        assert "No help entry" not in result.output

    def test_domain_error_keeps_json_stdout_clean(self, runner: CliRunner) -> None:
        """Under ``-f json`` a domain error writes nothing to stdout."""
        result = runner.invoke(
            app, ["help", "Workspace", "--domain", "nope", "-f", "json"]
        )
        assert result.exit_code == ExitCode.INVALID_ARGS
        assert result.stdout == ""
        assert "Unknown domain 'nope'." in result.stderr

    def test_handle_errors_maps_help_domain_error_to_4_as_safety_net(self) -> None:
        """``handle_errors`` still maps an escaped ``HelpDomainError`` to exit 4."""

        @handle_errors
        def _escaped() -> None:
            """Raise a domain error that bypassed the command's own handler."""
            raise HelpDomainError("Workspace", domain="nope", domains=("a",))

        with pytest.raises(click.exceptions.Exit) as exc:
            _escaped()
        assert exc.value.exit_code == ExitCode.NOT_FOUND

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
        """An unsupported format is rejected by the option parser (exit 2)."""
        result = runner.invoke(app, ["help", "Filter", "-f", "table"])
        assert result.exit_code == 2
        assert "table" in result.stderr

    def test_format_choices_come_from_help_formats(self) -> None:
        """The ``--format`` choices are exactly the library's ``HELP_FORMATS``."""
        command = typer.main.get_command(app)
        assert isinstance(command, click.Group)
        help_cmd = command.get_command(click.Context(command), "help")
        assert help_cmd is not None
        option = next(p for p in help_cmd.params if "--format" in p.opts)
        assert isinstance(option.type, click.Choice)
        assert list(option.type.choices) == list(HELP_FORMATS)

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
