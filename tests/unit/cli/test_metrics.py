# ruff: noqa: ARG001, ARG005
"""Tests for the saved-metrics CLI commands.

Tests cover all metrics subcommands:
- list: List saved metrics with local filters
- get: Get one saved metric by ID
- create: Create a saved metric from a definition file or stdin
- update: Update a saved metric
- verify: Verify or unverify saved metrics in one request
- delete: Delete one or more saved metrics
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer.testing

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.saved_definitions import (
    find_server_skipped_keys,
    strip_server_skipped_keys,
)
from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import ParamValidationError, QueryError
from mixpanel_headless.types import RawMetricDefinition, SavedMetric
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    envelope,
    formula_metric_json,
    legacy_formula_metric_json,
    legacy_funnel_metric_json,
    warehouse_metric_json,
)

runner = typer.testing.CliRunner()


def _metrics() -> list[SavedMetric]:
    """Return three typed saved metrics: a behavior metric, a formula, a warehouse metric.

    Returns:
        SavedMetric objects built from the shared fixtures.
    """
    return [
        SavedMetric.model_validate(behavior_metric_json(1, "Weekly signups")),
        SavedMetric.model_validate(formula_metric_json(2, "Signup conversion")),
        SavedMetric.model_validate(warehouse_metric_json(3, "Warehouse revenue")),
    ]


class TestMetricsList:
    """Tests for mp metrics list."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_returns_json_list(self, mock_get_ws: MagicMock) -> None:
        """A plain list prints every metric as JSON with the default filters."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert [m["id"] for m in data] == [1, 2, 3]
        assert data[0]["definition"]["measurement"] == {"math": "unique"}
        assert data[0]["created"] == "2026-03-01T12:00:00"
        mock_ws.list_metrics.assert_called_once_with(
            metric_type=None, verified=None, name_contains=None, viewable_only=False
        )

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_passes_filters(self, mock_get_ws: MagicMock) -> None:
        """Each list option maps to its list_metrics argument."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "list",
                "--type",
                "formula",
                "--verified",
                "--name-contains",
                "rate",
                "--viewable-only",
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == []
        mock_ws.list_metrics.assert_called_once_with(
            metric_type="formula",
            verified=True,
            name_contains="rate",
            viewable_only=True,
        )

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_no_verified_flag(self, mock_get_ws: MagicMock) -> None:
        """--no-verified asks for unverified metrics only."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list", "--no-verified"])
        assert result.exit_code == 0, result.output
        assert mock_ws.list_metrics.call_args.kwargs["verified"] is False

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_table_shows_can_view(self, mock_get_ws: MagicMock) -> None:
        """The table view has a CAN VIEW column and leaves out the definition."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "CAN VIEW" in result.stdout
        assert "Warehouse revenue" in result.stdout
        assert "DEFINITION" not in result.stdout
        assert "measurement" not in result.stdout

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_jq_filter(self, mock_get_ws: MagicMock) -> None:
        """--jq filters the JSON output."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app, ["metrics", "list", "--jq", "[.[] | select(.can_view == false) | .id]"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == [3]


class TestMetricsGet:
    """Tests for mp metrics get."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_returns_json(self, mock_get_ws: MagicMock) -> None:
        """get prints the full metric, definition included."""
        mock_ws = MagicMock()
        mock_ws.get_metric.return_value = _metrics()[1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "get", "2"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["definition"]["formula"]["definition"] == "A / B * 100"
        mock_ws.get_metric.assert_called_once_with(2)

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_jq_prints_the_bare_warehouse_source(self, mock_get_ws: MagicMock) -> None:
        """--jq .warehouse_source_id prints a bare id for --warehouse-source-id."""
        mock_ws = MagicMock()
        mock_ws.get_metric.return_value = SavedMetric.model_validate(
            warehouse_metric_json()
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app, ["metrics", "get", "120001", "--jq", ".warehouse_source_id"]
        )
        assert result.exit_code == 0, result.output
        assert result.stdout == "55\n"

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_not_found_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """A 404 from the server exits with a non-zero code and an error on stderr."""
        mock_ws = MagicMock()
        mock_ws.get_metric.side_effect = QueryError(
            "Metric not found for id 9", status_code=404
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "get", "9"])
        assert result.exit_code != 0
        assert "Metric not found" in result.stderr

    def test_rejects_non_integer_id(self) -> None:
        """A non-integer ID is a usage error."""
        result = runner.invoke(app, ["metrics", "get", "abc"])
        assert result.exit_code == 2


class TestMetricsDelete:
    """Tests for mp metrics delete."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_one_id_uses_checked_delete(self, mock_get_ws: MagicMock) -> None:
        """One ID goes through delete_metric (existence check) with a stderr message."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "104700"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metric.assert_called_once_with(104700, force=False)
        mock_ws.delete_metrics.assert_not_called()
        assert result.stdout == ""
        assert "Deleted saved metric 104700" in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_several_ids_use_one_bulk_delete(self, mock_get_ws: MagicMock) -> None:
        """Several IDs go through one delete_metrics call; stderr names the skip rule."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "1", "2", "3"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metrics.assert_called_once_with([1, 2, 3], force=False)
        mock_ws.delete_metric.assert_not_called()
        assert "1, 2, 3" in result.stderr
        assert "skips" in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_not_found_refusal_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """The SM5 refusal of delete_metric exits non-zero with the message."""
        mock_ws = MagicMock()
        mock_ws.delete_metric.side_effect = ParamValidationError(
            "Saved metric 5 was not found in project 12345; nothing was deleted.",
            code="SM5_NOT_FOUND_FOR_DELETE",
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "5"])
        assert result.exit_code != 0
        assert "nothing was deleted" in result.stderr

    def test_requires_an_id(self) -> None:
        """delete with no ID is a usage error."""
        result = runner.invoke(app, ["metrics", "delete"])
        assert result.exit_code == 2


class TestMetricsDeleteForce:
    """Tests for the --force flag of mp metrics delete."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_force_passes_through(self, mock_get_ws: MagicMock) -> None:
        """--force reaches both the single and the bulk delete."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "104700", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metric.assert_called_once_with(104700, force=True)

        result = runner.invoke(app, ["metrics", "delete", "1", "2", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metrics.assert_called_once_with([1, 2], force=True)

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_permission_refusal_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """A delete guard refusal exits non-zero with the message on stderr."""
        from mixpanel_headless.exceptions import ParamValidationError

        mock_ws = MagicMock()
        mock_ws.delete_metric.side_effect = ParamValidationError(
            "This account cannot edit saved metric 104700. Pass force=True "
            "(CLI: --force) to delete it anyway.",
            code="SM6_DELETE_NOT_PERMITTED",
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "104700"])
        assert result.exit_code != 0
        assert "--force" in result.stderr

    def test_help_explains_the_guard(self) -> None:
        """The delete help names --force and the superadmin hazard."""
        result = runner.invoke(app, ["metrics", "delete", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.stdout
        assert "superadmin" in result.stdout


def _write_definition(tmp_path: Path, definition: dict[str, Any]) -> str:
    """Write a definition JSON file and return its path as a string.

    Args:
        tmp_path: Pytest temporary directory.
        definition: The definition dict.

    Returns:
        The file path.
    """
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    return str(path)


class TestMetricsCreate:
    """Tests for mp metrics create."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_behavior_metric_from_file(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """A definition file becomes a RawMetricDefinition of the inferred kind."""
        definition = behavior_metric_json()["definition"]
        mock_ws = MagicMock()
        mock_ws.create_metric.return_value = _metrics()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "Weekly signups",
                "--definition-file",
                _write_definition(tmp_path, definition),
                "--description",
                "Signups.",
                "--owner-id",
                "8",
                "--verified",
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["id"] == 1
        (params,) = mock_ws.create_metric.call_args.args
        assert params.name == "Weekly signups"
        assert params.description == "Signups."
        assert params.owned_by == 8
        assert params.verified is True
        assert params.definition == RawMetricDefinition("metric", definition)
        assert mock_ws.create_metric.call_args.kwargs == {"validate": True}

    @pytest.mark.parametrize(
        ("definition", "kind"),
        [
            ({"formula": {"definition": "A", "referencedMetrics": []}}, "formula"),
            ({"query": "SELECT 1", "metricType": "numeric"}, "warehouse"),
        ],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_kind_is_inferred(
        self,
        mock_get_ws: MagicMock,
        tmp_path: Path,
        definition: dict[str, Any],
        kind: str,
    ) -> None:
        """A formula block gives kind formula; a query gives kind warehouse.

        Args:
            mock_get_ws: Patched get_workspace.
            tmp_path: Pytest temporary directory.
            definition: The definition dict.
            kind: The expected kind.
        """
        mock_ws = MagicMock()
        mock_ws.create_metric.return_value = _metrics()[0]
        mock_get_ws.return_value = mock_ws
        args = [
            "metrics",
            "create",
            "--name",
            "m",
            "--definition-file",
            _write_definition(tmp_path, definition),
        ]
        if kind == "warehouse":
            args += ["--warehouse-source-id", "55"]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        (params,) = mock_ws.create_metric.call_args.args
        assert params.definition.type == kind
        if kind == "warehouse":
            assert params.definition.warehouse_source_id == 55

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_definition_from_stdin_with_kind_and_no_validate(
        self, mock_get_ws: MagicMock
    ) -> None:
        """``--definition-file -`` reads stdin; --kind and --no-validate pass through."""
        mock_ws = MagicMock()
        mock_ws.create_metric.return_value = _metrics()[0]
        mock_get_ws.return_value = mock_ws
        with patch(
            "mixpanel_headless.cli.validators._stdin_is_tty", return_value=False
        ):
            result = runner.invoke(
                app,
                [
                    "metrics",
                    "create",
                    "--name",
                    "m",
                    "--definition-file",
                    "-",
                    "--kind",
                    "metric",
                    "--no-validate",
                ],
                input='{"behavior": {"type": "people"}, "measurement": {}}',
            )
        assert result.exit_code == 0, result.output
        (params,) = mock_ws.create_metric.call_args.args
        assert params.definition == RawMetricDefinition(
            "metric", {"behavior": {"type": "people"}, "measurement": {}}
        )
        assert mock_ws.create_metric.call_args.kwargs == {"validate": False}

    def test_bad_kind_exits_3(self, tmp_path: Path) -> None:
        """A --kind outside metric, formula, warehouse is a usage error."""
        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "m",
                "--definition-file",
                _write_definition(tmp_path, {}),
                "--kind",
                "behavior",
            ],
        )
        assert result.exit_code == 3

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_coded_refusal_exits_nonzero(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """A ParamValidationError from the Workspace exits non-zero with its message."""
        mock_ws = MagicMock()
        mock_ws.create_metric.side_effect = ParamValidationError(
            "The saved metric definition does not match the server schema at "
            "definition.behavior.x: Extra inputs are not permitted.",
            code="SM4_SCHEMA",
        )
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "m",
                "--definition-file",
                _write_definition(tmp_path, {"behavior": {"x": 1}}),
            ],
        )
        assert result.exit_code != 0
        assert "definition.behavior.x" in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_server_schema_refusal_prints_no_request_echo(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """A 400 from the server schema prints the short message, not the SQL.

        The server's error text ends with an HTML-escaped copy of the whole
        request, so it holds the warehouse SQL.
        """
        sql = "SELECT secret_column FROM warehouse.revenue"

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the create with the server's schema 400 body.

            Args:
                request: The create request.

            Returns:
                The 400 response, whose error echoes the request.
            """
            echo = html.escape(repr(json.loads(request.content)))
            return httpx.Response(
                400,
                json={
                    "details": {
                        "data": None,
                        "path": ["root", "definition"],
                        "schema": {},
                    },
                    "error": f"Additional properties are not allowed {echo}",
                    "status": "error",
                },
            )

        session = make_session(project_id="12345", region="us", oauth_token="t")
        client = MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(handler)
        )
        mock_get_ws.return_value = Workspace(session=session, _api_client=client)
        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "Revenue",
                "--warehouse-source-id",
                "5",
                "--no-validate",
                "--definition-file",
                _write_definition(
                    tmp_path, {"query": sql, "metricType": "numeric", "bogus": 1}
                ),
            ],
        )
        assert result.exit_code == 3, result.output
        assert "The server refused the request body" in result.stderr
        assert "secret_column" not in result.stderr
        assert "secret_column" not in result.stdout


class TestMetricsUpdate:
    """Tests for mp metrics update."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_metadata_flags(self, mock_get_ws: MagicMock) -> None:
        """Name, description, owner, and --no-verified map to UpdateMetricParams."""
        mock_ws = MagicMock()
        mock_ws.update_metric.return_value = _metrics()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "update",
                "1",
                "--name",
                "New",
                "--description",
                "",
                "--owner-id",
                "8",
                "--no-verified",
            ],
        )
        assert result.exit_code == 0, result.output
        metric_id, params = mock_ws.update_metric.call_args.args
        assert metric_id == 1
        assert params.name == "New"
        assert params.description == ""
        assert params.owned_by == 8
        assert params.verified is False
        assert params.definition is None

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_definition_round_trip(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """The definition of `get --format json` goes back through --definition-file."""
        definition = formula_metric_json()["definition"]
        mock_ws = MagicMock()
        mock_ws.update_metric.return_value = _metrics()[1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "update",
                "2",
                "--definition-file",
                _write_definition(tmp_path, definition),
                "--verified",
            ],
        )
        assert result.exit_code == 0, result.output
        _metric_id, params = mock_ws.update_metric.call_args.args
        assert params.definition == RawMetricDefinition("formula", definition)
        assert params.verified is True
        assert mock_ws.update_metric.call_args.kwargs == {"validate": True}

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_one_flag_leaves_the_other_fields(self, mock_get_ws: MagicMock) -> None:
        """With only --verified, every other field is None."""
        mock_ws = MagicMock()
        mock_ws.update_metric.return_value = _metrics()[0]
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(app, ["metrics", "update", "1", "--verified"])
        assert result.exit_code == 0, result.output
        _metric_id, params = mock_ws.update_metric.call_args.args
        assert params.verified is True
        assert params.name is None
        assert params.definition is None

    @pytest.mark.parametrize(
        "extra",
        [[], ["--no-validate"], ["--format", "table"]],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_no_change_option_exits_3(
        self, mock_get_ws: MagicMock, extra: list[str]
    ) -> None:
        """An update with no option to change is refused before any request.

        Args:
            mock_get_ws: Patched get_workspace.
            extra: Options that change nothing.
        """
        result = runner.invoke(app, ["metrics", "update", "1", *extra])
        assert result.exit_code == 3, result.output
        assert "Nothing to update" in result.stderr
        assert "--definition-file" in result.stderr
        mock_get_ws.assert_not_called()

    @pytest.mark.parametrize(
        "extra",
        [
            ["--kind", "formula"],
            ["--warehouse-source-id", "7"],
            ["--name", "New", "--kind", "metric"],
            ["--verified", "--warehouse-source-id", "7"],
        ],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_definition_options_without_a_file_exit_3(
        self, mock_get_ws: MagicMock, extra: list[str]
    ) -> None:
        """--kind or --warehouse-source-id without --definition-file is refused.

        Args:
            mock_get_ws: Patched get_workspace.
            extra: The options of the command line.
        """
        result = runner.invoke(app, ["metrics", "update", "1", *extra])
        assert result.exit_code == 3, result.output
        assert (
            "--kind and --warehouse-source-id require --definition-file"
            in result.stderr
        )
        mock_get_ws.assert_not_called()


class TestMetricsVerify:
    """Tests for mp metrics verify."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_verify_many(self, mock_get_ws: MagicMock) -> None:
        """verify sends one bulk update with verified=True for each id."""
        mock_ws = MagicMock()
        mock_ws.bulk_update_metrics.return_value = _metrics()[:2]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "verify", "1", "2"])
        assert result.exit_code == 0, result.output
        (entries,) = mock_ws.bulk_update_metrics.call_args.args
        assert [(e.id, e.verified) for e in entries] == [(1, True), (2, True)]
        assert [m["id"] for m in json.loads(result.stdout)] == [1, 2]
        assert "skipped" not in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_unverify_and_skipped_ids(self, mock_get_ws: MagicMock) -> None:
        """--unverify clears the flag; ids missing from the result are named on stderr."""
        mock_ws = MagicMock()
        mock_ws.bulk_update_metrics.return_value = _metrics()[:1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "verify", "1", "99", "--unverify"])
        assert result.exit_code == 0, result.output
        (entries,) = mock_ws.bulk_update_metrics.call_args.args
        assert [(e.id, e.verified) for e in entries] == [(1, False), (99, False)]
        assert "99" in result.stderr
        assert "skipped" in result.stderr


class TestMetricsQuery:
    """Tests for mp metrics query."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_queries_the_saved_metric_by_reference(
        self, mock_get_ws: MagicMock
    ) -> None:
        """query reads the metric, then runs Workspace.query on its reference."""
        saved = _metrics()[1]
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {"series": {"Signup conversion": {}}}
        mock_ws = MagicMock()
        mock_ws.get_metric.return_value = saved
        mock_ws.query.return_value = result_obj
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "query",
                "2",
                "--from",
                "2024-09-01",
                "--to",
                "2024-09-07",
                "--unit",
                "week",
                "--group-by",
                "$os",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_ws.get_metric.assert_called_once_with(2)
        (ref,), kwargs = mock_ws.query.call_args
        assert ref == saved.to_ref()
        assert ref.type == "formula"
        assert kwargs == {
            "from_date": "2024-09-01",
            "to_date": "2024-09-07",
            "last": 30,
            "unit": "week",
            "group_by": "$os",
        }
        assert json.loads(result.stdout) == {"series": {"Signup conversion": {}}}

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_defaults_and_table(self, mock_get_ws: MagicMock) -> None:
        """Without options the query runs the last 30 days by day; table uses rows."""
        result_obj = MagicMock()
        result_obj.to_table_dict.return_value = [{"date": "2024-09-01", "value": 3}]
        mock_ws = MagicMock()
        mock_ws.get_metric.return_value = _metrics()[0]
        mock_ws.query.return_value = result_obj
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "query", "1", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert mock_ws.query.call_args.kwargs == {
            "from_date": None,
            "to_date": None,
            "last": 30,
            "unit": "day",
            "group_by": None,
        }
        assert "2024-09-01" in result.stdout

    def test_bad_unit_exits_3(self) -> None:
        """A --unit outside day, week, month is a usage error."""
        result = runner.invoke(app, ["metrics", "query", "1", "--unit", "year"])
        assert result.exit_code == 3


_SECRET_SQL = "SELECT secret_column FROM warehouse.revenue"
"""Warehouse SQL that no error output may show."""

_METRICS_PATH = "/api/app/projects/12345/metrics"
"""App API path of the saved metrics of the test project."""


def _workspace_on(handler: Any) -> Workspace:
    """Build a Workspace whose API client answers with a mock transport.

    Args:
        handler: The ``httpx.MockTransport`` handler.

    Returns:
        A Workspace on project 12345.
    """
    session = make_session(project_id="12345", region="us", oauth_token="t")
    client = MixpanelAPIClient(session=session, _transport=httpx.MockTransport(handler))
    return Workspace(session=session, _api_client=client)


class TestWriteErrorsHideTheRequest:
    """An error of a write command shows the message, never the request."""

    @pytest.mark.parametrize(
        ("status", "message"),
        [
            (409, "A metric with that name already exists"),
            (403, "Cannot save metric with your current plan"),
        ],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_create_error_prints_no_sql(
        self, mock_get_ws: MagicMock, tmp_path: Path, status: int, message: str
    ) -> None:
        """A 409 or 403 on a warehouse create prints the message, not the SQL.

        Args:
            mock_get_ws: Patched get_workspace.
            tmp_path: Pytest temporary directory.
            status: The HTTP status of the server error.
            message: The server's error text.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Refuse the create.

            Args:
                request: The create request.

            Returns:
                The error response.
            """
            assert (request.method, request.url.path) == ("POST", _METRICS_PATH)
            return httpx.Response(status, json={"error": message, "status": "error"})

        mock_get_ws.return_value = _workspace_on(handler)
        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "Revenue",
                "--warehouse-source-id",
                "55",
                "--definition-file",
                _write_definition(
                    tmp_path, {"query": _SECRET_SQL, "metricType": "numeric"}
                ),
            ],
        )
        assert result.exit_code == 3, result.output
        assert message in result.stderr
        assert "secret_column" not in result.stderr
        assert "secret_column" not in result.stdout
        assert "definition:" not in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_update_error_prints_no_sql(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """A 409 on a warehouse update prints the message, not the new or stored SQL."""
        stored = warehouse_metric_json()

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the read, then refuse the update.

            Args:
                request: The read or the update request.

            Returns:
                The stored metric, or the 409 response.
            """
            assert request.url.path == f"{_METRICS_PATH}/{stored['id']}"
            if request.method == "GET":
                return httpx.Response(200, json=envelope(stored))
            return httpx.Response(
                409,
                json={"error": "A metric with that name already exists"},
            )

        mock_get_ws.return_value = _workspace_on(handler)
        result = runner.invoke(
            app,
            [
                "metrics",
                "update",
                str(stored["id"]),
                "--name",
                "Taken name",
                "--definition-file",
                _write_definition(
                    tmp_path, {"query": _SECRET_SQL, "metricType": "timeseries"}
                ),
            ],
        )
        assert result.exit_code == 3, result.output
        assert "A metric with that name already exists" in result.stderr
        output = result.stderr + result.stdout
        assert "secret_column" not in output
        assert stored["definition"]["query"] not in output

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_failed_follow_up_names_the_created_metric(
        self, mock_get_ws: MagicMock, tmp_path: Path
    ) -> None:
        """A create whose verified update fails prints the new id, not the SQL."""
        created = warehouse_metric_json(41)

        def handler(request: httpx.Request) -> httpx.Response:
            """Accept the create, then refuse the follow-up update.

            Args:
                request: The create or the follow-up request.

            Returns:
                The created metric, or the 403 response.
            """
            if request.method == "POST":
                return httpx.Response(200, json=envelope(created))
            assert (request.method, request.url.path) == (
                "PATCH",
                f"{_METRICS_PATH}/41",
            )
            return httpx.Response(403, json={"error": "Permission denied"})

        mock_get_ws.return_value = _workspace_on(handler)
        result = runner.invoke(
            app,
            [
                "metrics",
                "create",
                "--name",
                "Revenue",
                "--warehouse-source-id",
                "55",
                "--verified",
                "--definition-file",
                _write_definition(
                    tmp_path, {"query": _SECRET_SQL, "metricType": "numeric"}
                ),
            ],
        )
        assert result.exit_code == 1, result.output
        assert "created saved metric 41" in result.stderr
        assert "Permission denied" in result.stderr
        output = result.stderr + result.stdout
        assert "secret_column" not in output
        assert created["definition"]["query"] not in output

    @pytest.mark.parametrize(
        ("args", "method"),
        [
            (["metrics", "update", "1", "--name", "n"], "update_metric"),
            (["metrics", "verify", "1", "2"], "bulk_update_metrics"),
            (["metrics", "delete", "1"], "delete_metric"),
            (["metrics", "delete", "1", "2"], "delete_metrics"),
        ],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_every_write_command_hides_the_request(
        self, mock_get_ws: MagicMock, args: list[str], method: str
    ) -> None:
        """update, verify, and delete print no request params or body either.

        Args:
            mock_get_ws: Patched get_workspace.
            args: The command line.
            method: The Workspace method that the command calls.
        """
        mock_ws = MagicMock()
        getattr(mock_ws, method).side_effect = QueryError(
            "Permission denied",
            status_code=403,
            request_params={"note": _SECRET_SQL},
            request_body={"definition": {"query": _SECRET_SQL}},
        )
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(app, args)
        assert result.exit_code == 3, result.output
        assert "Permission denied" in result.stderr
        assert "secret_column" not in result.stderr

    @patch("mixpanel_headless.cli.commands.dashboards.get_workspace")
    def test_other_command_groups_keep_their_debug_lines(
        self, mock_get_ws: MagicMock
    ) -> None:
        """Another command group still prints the request lines of a QueryError."""
        mock_ws = MagicMock()
        mock_ws.create_dashboard.side_effect = QueryError(
            "A dashboard with that title already exists",
            status_code=409,
            request_params={"source": "debug-param"},
            request_body={"title": "Revenue", "description": "debug-body"},
        )
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(app, ["dashboards", "create", "--title", "Revenue"])
        assert result.exit_code == 3, result.output
        assert "A dashboard with that title already exists" in result.stderr
        assert "source:" in result.stderr
        assert "debug-param" in result.stderr
        assert "title:" in result.stderr
        assert "debug-body" in result.stderr


class TestCopyThroughStdin:
    """`mp metrics get --jq .definition | mp metrics create --definition-file -`."""

    @pytest.mark.parametrize(
        ("row", "kind"),
        [
            (legacy_funnel_metric_json(), "metric"),
            (legacy_formula_metric_json(), "formula"),
        ],
    )
    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_stored_definition_with_legacy_keys_copies(
        self, mock_get_ws: MagicMock, row: dict[str, Any], kind: str
    ) -> None:
        """The printed definition of a stored metric creates a copy without legacy keys.

        Args:
            mock_get_ws: Patched get_workspace.
            row: A stored metric whose definition has legacy keys.
            kind: The metric kind of the row.
        """
        bodies: list[Any] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the create body and accept it.

            Args:
                request: The create request.

            Returns:
                The created metric.
            """
            assert (request.method, request.url.path) == ("POST", _METRICS_PATH)
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=envelope(behavior_metric_json(7)))

        mock_get_ws.return_value = _workspace_on(handler)
        result = runner.invoke(
            app,
            ["metrics", "create", "--name", "copy", "--definition-file", "-"],
            input=json.dumps(row["definition"]),
        )
        assert result.exit_code == 0, result.output
        (body,) = bodies
        assert body["type"] == kind
        assert find_server_skipped_keys(kind, body["definition"]) == []
        expected = json.loads(json.dumps(row["definition"]))
        strip_server_skipped_keys(kind, expected)
        assert body["definition"] == expected
