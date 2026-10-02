# ruff: noqa: ARG001, ARG005
"""Tests for the saved-behaviors CLI commands.

Tests cover all behaviors subcommands:
- list: List saved behaviors with local filters
- get: Get one saved behavior by ID
- create: Create a saved behavior from a definition file or stdin
- update: Update a saved behavior
- delete: Delete one or more saved behaviors
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer.testing

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.saved_definitions import find_server_skipped_keys
from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import QueryError, ServerError
from mixpanel_headless.types import RawBehaviorDefinition, SavedBehavior
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import (
    envelope,
    legacy_behavior_json,
    saved_behavior_json,
)

runner = typer.testing.CliRunner()

_UNKNOWN_BEHAVIOR_500 = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "saved_metrics"
    / "error_500_unknown_behavior.json"
)


def _behaviors() -> list[SavedBehavior]:
    """Return two typed saved behaviors: a funnel and a retention behavior.

    Returns:
        SavedBehavior objects built from the shared fixtures.
    """
    return [
        SavedBehavior.model_validate(saved_behavior_json(1, "Checkout")),
        SavedBehavior.model_validate(
            saved_behavior_json(2, "Return visits", behavior_type="retention")
        ),
    ]


class TestBehaviorsList:
    """Tests for mp behaviors list."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_returns_json_list(self, mock_get_ws: MagicMock) -> None:
        """A plain list prints every behavior as JSON with the default filters."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = _behaviors()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert [b["type"] for b in data] == ["funnel", "retention"]
        mock_ws.list_behaviors.assert_called_once_with(
            behavior_type=None, name_contains=None
        )

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_passes_filters(self, mock_get_ws: MagicMock) -> None:
        """--type and --name-contains map to their list_behaviors arguments."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app, ["behaviors", "list", "--type", "funnel", "--name-contains", "check"]
        )
        assert result.exit_code == 0, result.output
        mock_ws.list_behaviors.assert_called_once_with(
            behavior_type="funnel", name_contains="check"
        )

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_table_shows_can_view(self, mock_get_ws: MagicMock) -> None:
        """The table view has a CAN VIEW column and leaves out the definition."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = _behaviors()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "list", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "CAN VIEW" in result.stdout
        assert "Return visits" in result.stdout
        assert "DEFINITION" not in result.stdout


class TestBehaviorsGet:
    """Tests for mp behaviors get."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_returns_json(self, mock_get_ws: MagicMock) -> None:
        """get prints the full behavior, definition included."""
        mock_ws = MagicMock()
        mock_ws.get_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "get", "1"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["definition"]["behavior"]["type"] == "funnel"
        mock_ws.get_behavior.assert_called_once_with(1)

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_jq_filter(self, mock_get_ws: MagicMock) -> None:
        """--jq filters the JSON output."""
        mock_ws = MagicMock()
        mock_ws.get_behavior.return_value = _behaviors()[1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "get", "2", "--jq", ".name"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == "Return visits"

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_unknown_id_prints_server_message(self, mock_get_ws: MagicMock) -> None:
        """The recorded unknown-behavior 500 prints its support text and Error ID."""
        body = json.loads(_UNKNOWN_BEHAVIOR_500.read_text(encoding="utf-8"))
        session = make_session()
        client = MixpanelAPIClient(
            session=session,
            _transport=httpx.MockTransport(
                lambda request: httpx.Response(500, json=body)
            ),
        )
        mock_get_ws.return_value = Workspace(session=session, _api_client=client)

        result = runner.invoke(app, ["behaviors", "get", "999999999"])
        assert result.exit_code != 0
        stderr = " ".join(result.stderr.split())
        assert "Server error (500)" in stderr
        assert "https://mixpanel.com/get-support" in stderr
        assert "Error ID: 7f73afdc3d244d959af85fc10fa3e550" in stderr


class TestBehaviorsDelete:
    """Tests for mp behaviors delete."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_one_id_uses_checked_delete(self, mock_get_ws: MagicMock) -> None:
        """One ID goes through delete_behavior (existence check) with a stderr message."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behavior.assert_called_once_with(3001, force=False)
        mock_ws.delete_behaviors.assert_not_called()
        assert result.stdout == ""
        assert "Deleted saved behavior 3001" in result.stderr

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_several_ids_use_one_bulk_delete(self, mock_get_ws: MagicMock) -> None:
        """Several IDs go through one delete_behaviors call; stderr names the skip rule."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "7", "8"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behaviors.assert_called_once_with([7, 8], force=False)
        mock_ws.delete_behavior.assert_not_called()
        assert "7, 8" in result.stderr
        assert "skips" in result.stderr

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_unknown_id_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """The server error on the pre-read of an unknown ID exits non-zero."""
        mock_ws = MagicMock()
        mock_ws.delete_behavior.side_effect = ServerError(
            "Internal Server Error", status_code=500
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "999"])
        assert result.exit_code != 0
        assert "Server error (500)" in result.stderr


class TestBehaviorsDeleteForce:
    """Tests for the --force flag of mp behaviors delete."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_force_passes_through(self, mock_get_ws: MagicMock) -> None:
        """--force reaches both the single and the bulk delete."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behavior.assert_called_once_with(3001, force=True)

        result = runner.invoke(app, ["behaviors", "delete", "1", "2", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behaviors.assert_called_once_with([1, 2], force=True)

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_permission_refusal_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """A delete guard refusal exits non-zero with the message on stderr."""
        from mixpanel_headless.exceptions import ParamValidationError

        mock_ws = MagicMock()
        mock_ws.delete_behavior.side_effect = ParamValidationError(
            "This account cannot edit saved behavior 3001. Pass force=True "
            "(CLI: --force) to delete it anyway.",
            code="BH4_DELETE_NOT_PERMITTED",
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001"])
        assert result.exit_code != 0
        assert "--force" in result.stderr

    def test_help_explains_the_guard(self) -> None:
        """The delete help names --force and the superadmin hazard."""
        result = runner.invoke(app, ["behaviors", "delete", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.stdout
        assert "superadmin" in result.stdout


class TestBehaviorsCreate:
    """Tests for mp behaviors create."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_from_file(self, mock_get_ws: MagicMock, tmp_path: Path) -> None:
        """A definition file becomes a RawBehaviorDefinition."""
        definition = saved_behavior_json()["definition"]
        path = tmp_path / "behavior.json"
        path.write_text(json.dumps(definition), encoding="utf-8")
        mock_ws = MagicMock()
        mock_ws.create_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "behaviors",
                "create",
                "--name",
                "Checkout",
                "--definition-file",
                str(path),
                "--description",
                "Cart to purchase.",
            ],
        )
        assert result.exit_code == 0, result.output
        (params,) = mock_ws.create_behavior.call_args.args
        assert params.name == "Checkout"
        assert params.description == "Cart to purchase."
        assert params.behavior == RawBehaviorDefinition(definition)
        assert mock_ws.create_behavior.call_args.kwargs == {"validate": True}

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_from_stdin_no_validate(self, mock_get_ws: MagicMock) -> None:
        """``--definition-file -`` reads stdin; --no-validate passes through."""
        mock_ws = MagicMock()
        mock_ws.create_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws
        with patch(
            "mixpanel_headless.cli.validators._stdin_is_tty", return_value=False
        ):
            result = runner.invoke(
                app,
                [
                    "behaviors",
                    "create",
                    "--name",
                    "b",
                    "--definition-file",
                    "-",
                    "--no-validate",
                ],
                input='{"behavior": {"type": "simple"}}',
            )
        assert result.exit_code == 0, result.output
        (params,) = mock_ws.create_behavior.call_args.args
        assert params.behavior == RawBehaviorDefinition(
            {"behavior": {"type": "simple"}}
        )
        assert mock_ws.create_behavior.call_args.kwargs == {"validate": False}


class TestBehaviorsUpdate:
    """Tests for mp behaviors update."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_flags(self, mock_get_ws: MagicMock, tmp_path: Path) -> None:
        """Name, description, definition file, and --verified map to the params."""
        definition = saved_behavior_json()["definition"]
        path = tmp_path / "behavior.json"
        path.write_text(json.dumps(definition), encoding="utf-8")
        mock_ws = MagicMock()
        mock_ws.update_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "behaviors",
                "update",
                "3001",
                "--name",
                "New",
                "--definition-file",
                str(path),
                "--verified",
            ],
        )
        assert result.exit_code == 0, result.output
        behavior_id, params = mock_ws.update_behavior.call_args.args
        assert behavior_id == 3001
        assert params.name == "New"
        assert params.behavior == RawBehaviorDefinition(definition)
        assert params.verified is True

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_no_flags(self, mock_get_ws: MagicMock) -> None:
        """Without flags every field is None; --no-verified clears the flag."""
        mock_ws = MagicMock()
        mock_ws.update_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(app, ["behaviors", "update", "3001", "--no-verified"])
        assert result.exit_code == 0, result.output
        _behavior_id, params = mock_ws.update_behavior.call_args.args
        assert params.behavior is None
        assert params.name is None
        assert params.verified is False

    @pytest.mark.parametrize("extra", [[], ["--no-validate"]])
    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_no_change_option_exits_3(
        self, mock_get_ws: MagicMock, extra: list[str]
    ) -> None:
        """An update with no option to change is refused before any request.

        Args:
            mock_get_ws: Patched get_workspace.
            extra: Options that change nothing.
        """
        result = runner.invoke(app, ["behaviors", "update", "3001", *extra])
        assert result.exit_code == 3, result.output
        assert "Nothing to update" in result.stderr
        assert "--definition-file" in result.stderr
        mock_get_ws.assert_not_called()


class TestWriteErrorsHideTheRequest:
    """An error of a behaviors write command shows the message, never the request."""

    @pytest.mark.parametrize(
        ("args", "method"),
        [
            (["behaviors", "create", "--name", "b", "--definition-file", "-"], None),
            (["behaviors", "update", "3001", "--name", "n"], "update_behavior"),
            (["behaviors", "delete", "3001"], "delete_behavior"),
            (["behaviors", "delete", "1", "2"], "delete_behaviors"),
        ],
    )
    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_every_write_command_hides_the_request(
        self, mock_get_ws: MagicMock, args: list[str], method: str | None
    ) -> None:
        """create, update, and delete print no request params or body.

        Args:
            mock_get_ws: Patched get_workspace.
            args: The command line.
            method: The Workspace method that the command calls
                (``create_behavior`` when ``None``).
        """
        mock_ws = MagicMock()
        getattr(mock_ws, method or "create_behavior").side_effect = QueryError(
            "A behavior with that name already exists",
            status_code=409,
            request_params={"note": "secret-definition"},
            request_body={"definition": {"behavior": {"name": "secret-definition"}}},
        )
        mock_get_ws.return_value = mock_ws
        result = runner.invoke(
            app,
            args,
            input=json.dumps({"behavior": {"type": "funnel", "behaviors": []}}),
        )
        assert result.exit_code == 3, result.output
        assert "A behavior with that name already exists" in result.stderr
        assert "secret-definition" not in result.stderr
        assert "definition:" not in result.stderr


class TestCopyThroughStdin:
    """`mp behaviors get --jq .definition | mp behaviors create --definition-file -`."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_stored_definition_with_legacy_keys_copies(
        self, mock_get_ws: MagicMock
    ) -> None:
        """The printed definition of a stored behavior creates a copy without legacy keys."""
        row = legacy_behavior_json()
        bodies: list[Any] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the create body and accept it.

            Args:
                request: The create request.

            Returns:
                The created behavior.
            """
            assert request.method == "POST"
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=envelope(saved_behavior_json(9)))

        session = make_session(project_id="12345", region="us", oauth_token="t")
        client = MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(handler)
        )
        mock_get_ws.return_value = Workspace(session=session, _api_client=client)
        result = runner.invoke(
            app,
            ["behaviors", "create", "--name", "copy", "--definition-file", "-"],
            input=json.dumps(row["definition"]),
        )
        assert result.exit_code == 0, result.output
        (body,) = bodies
        assert body["type"] == "funnel"
        assert find_server_skipped_keys("behavior", body["definition"]) == []
        assert body["definition"]["behavior"]["exclusions"] == [
            {"event": "Refund", "steps": {"from": 0, "to": 1}}
        ]
