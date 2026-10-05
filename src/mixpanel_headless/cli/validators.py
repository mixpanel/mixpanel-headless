"""CLI parameter validators for Literal types.

Validates string inputs from Typer against Literal types before
passing to Workspace methods, providing early error feedback.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TypeVar, cast, get_args

import typer

from mixpanel_headless._literal_types import CountType, HourDayUnit, TimeUnit
from mixpanel_headless.cli.utils import ExitCode, err_console
from mixpanel_headless.types import EntityType

T = TypeVar("T")


def validate_literal(value: str, literal_type: Any, param_name: str) -> Any:
    """Validate a CLI string against a Literal type.

    Args:
        value: String value from CLI.
        literal_type: The Literal type to validate against.
        param_name: Parameter name for error message.

    Returns:
        The validated value, cast to the Literal type.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if invalid.
    """
    valid_values = get_args(literal_type)
    if value not in valid_values:
        err_console.print(
            f"[red]Error:[/red] Invalid value for {param_name}: '{value}'"
        )
        err_console.print(f"Valid options: {', '.join(valid_values)}")
        raise typer.Exit(ExitCode.INVALID_ARGS)
    return value


def validate_time_unit(value: str, param_name: str = "--unit") -> TimeUnit:
    """Validate time unit for aggregation.

    Args:
        value: String value from CLI (should be "day", "week", or "month").
        param_name: Parameter name for error message. Default: "--unit".

    Returns:
        Validated value as TimeUnit literal type.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if value is invalid.
    """
    validate_literal(value, TimeUnit, param_name)
    return cast(TimeUnit, value)


def validate_hour_day_unit(value: str, param_name: str = "--unit") -> HourDayUnit:
    """Validate hour/day unit for numeric queries.

    Args:
        value: String value from CLI (should be "hour" or "day").
        param_name: Parameter name for error message. Default: "--unit".

    Returns:
        Validated value as HourDayUnit literal type.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if value is invalid.
    """
    validate_literal(value, HourDayUnit, param_name)
    return cast(HourDayUnit, value)


def validate_count_type(value: str, param_name: str = "--type") -> CountType:
    """Validate count type for event counting.

    Args:
        value: String value from CLI (should be "general", "unique", or "average").
        param_name: Parameter name for error message. Default: "--type".

    Returns:
        Validated value as CountType literal type.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if value is invalid.
    """
    validate_literal(value, CountType, param_name)
    return cast(CountType, value)


def validate_json_object(value: str, param_name: str) -> dict[str, Any]:
    """Parse a CLI string as a JSON object.

    Used for opaque structured inputs supplied on the command line, such as the
    activity-feed pagination cursor (``--sentinel-event``).

    Args:
        value: Raw JSON string from the CLI.
        param_name: Parameter name for error messages.

    Returns:
        The parsed JSON object as a dict.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if the value is not valid JSON,
            or parses to something other than a JSON object.
    """
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        err_console.print(f"[red]Error:[/red] Invalid JSON for {param_name}: {exc}")
        raise typer.Exit(ExitCode.INVALID_ARGS) from exc
    if not isinstance(parsed, dict):
        err_console.print(f"[red]Error:[/red] {param_name} must be a JSON object.")
        raise typer.Exit(ExitCode.INVALID_ARGS)
    return parsed


def _stdin_is_tty() -> bool:
    """Return whether stdin is an interactive terminal.

    A seam for tests: ``CliRunner`` swaps ``sys.stdin``, so the check is
    read through this function rather than at import time.

    Returns:
        ``True`` when stdin is a terminal.
    """
    return sys.stdin.isatty()


def read_json_object_file(path: Path, param_name: str) -> dict[str, Any]:
    """Read a JSON object from a file, or from stdin when the path is ``-``.

    Used by options that take a whole JSON document, such as the
    ``--definition-file`` of ``mp metrics create``. Stdin on an interactive
    terminal is refused, so the command never blocks and waits for typed
    input.

    Args:
        path: The file path, or ``-`` for stdin.
        param_name: Parameter name for error messages.

    Returns:
        The parsed JSON object as a dict.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if the file cannot be read,
            stdin is a terminal, or the text is not a JSON object.
    """
    if str(path) == "-":
        if _stdin_is_tty():
            err_console.print(
                f"[red]Error:[/red] {param_name} - reads stdin, but stdin is a "
                f"terminal. Pipe a JSON object or pass a file path."
            )
            raise typer.Exit(ExitCode.INVALID_ARGS)
        text = sys.stdin.read()
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            err_console.print(f"[red]Error:[/red] Cannot read {param_name}: {exc}")
            raise typer.Exit(ExitCode.INVALID_ARGS) from exc
    return validate_json_object(text, param_name)


def validate_entity_type(value: str, param_name: str = "--type") -> EntityType:
    """Validate Lexicon entity type.

    Args:
        value: String value from CLI. Valid types: "event", "profile".
        param_name: Parameter name for error message. Default: "--type".

    Returns:
        Validated value as EntityType literal type.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) if value is invalid.
    """
    validate_literal(value, EntityType, param_name)
    return cast(EntityType, value)
