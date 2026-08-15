"""Differential fuzz harness over the JSON-RPC oracle bridges (design D14).

Spawns two oracle bridges as subprocesses (oracle-py vs oracle-py for the
Phase-1 SELF-PARITY done-criterion; oracle-py vs oracle-ts once TS-7
lands), generates Hypothesis inputs per registered fuzz target — the
Phase-1 priority targets plus the Phase-2 `types.*` api families and the
protocol-1.1 ``codec.roundtrip`` surface
(``conformance/differential/strategies.py``) — calls both bridges with the
SAME codec-encoded input, canonicalizes both responses with the D6
implementation, and diffs. A divergence is shrunk by Hypothesis and the
minimal repro is written to ``conformance/differential/repros/``.

Skip semantics (oracle-protocol.md §4.2): a response whose ``error.code``
is ``UNPORTED`` or ``WIRE_OUT_OF_SCOPE`` from EITHER side counts as skip,
never divergence — this is how compat-only oracle-ts coexists with the
full oracle-py surface.

CLI:
    ```bash
    uv run python -m conformance.differential.fuzz_harness \\
        --examples 200 --report json
    # defaults: both sides = in-repo oracle-py (self-parity), all targets
    ```

Exit codes: ``0`` zero divergences, ``1`` >=1 divergence, ``2`` harness
crash (a bridge died, protocol error, canonicalization bug).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from hypothesis import HealthCheck, example, given, settings

from conformance.differential.strategies import (
    ALL_TARGETS,
    CODEC_ROUNDTRIP_API,
    TARGETS_BY_NAME,
    FuzzCall,
    FuzzTarget,
)
from conformance.record.codecs import encode_input_kwargs
from conformance.runner.canonical import canonicalize, canonicalize_error

SKIP_ERROR_CODES = frozenset({"UNPORTED", "WIRE_OUT_OF_SCOPE"})
"""``error.code`` values counted as skip, never divergence (protocol §4.2)."""

_REPO_ROOT = Path(__file__).resolve().parents[2]
"""Python repo root — cwd for the default oracle-py subprocesses."""

DEFAULT_REPRO_DIR = _REPO_ROOT / "conformance" / "differential" / "repros"
"""Where shrunken divergence reproductions are written (design D14)."""

OracleCall = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
"""A bridge's call surface: ``(api, encoded_input) -> {ok, ...}`` payload."""


class OracleBridgeError(Exception):
    """A bridge failed at the PROTOCOL level (harness crash, never data).

    Raised when a bridge process dies, answers with a JSON-RPC ``error``
    object, or returns a payload the D6 canonicalizer rejects — all
    infrastructure failures, reported distinctly from divergences
    (mirroring the D9.3 crash-is-never-a-catch discipline).
    """


class _DivergenceFound(Exception):
    """Internal signal: one probe produced differing canonical outcomes.

    Raised inside the Hypothesis-driven check so the engine shrinks the
    probe; the harness records the minimal example from the final replay.
    """


@dataclass
class Divergence:
    """One minimal (shrunk) divergence record.

    Attributes:
        api: The probed api name.
        encoded_input: The codec-encoded input both bridges received.
        left: The left bridge's result payload.
        right: The right bridge's result payload.
    """

    api: str
    encoded_input: dict[str, Any]
    left: Mapping[str, Any]
    right: Mapping[str, Any]


@dataclass
class TargetReport:
    """Per-target outcome for the harness report.

    Attributes:
        name: The target name.
        examples: Total probes executed (edge examples + generated;
            includes shrink replays when a divergence was found).
        skipped: Probes where either side answered a skip payload.
        divergences: 0 or 1 — Hypothesis reports the single minimal
            counterexample per target run.
        repro_path: Path of the written repro file, when diverged.
        error: Bridge/protocol failure description (harness crash), if any.
    """

    name: str
    examples: int = 0
    skipped: int = 0
    divergences: int = 0
    repro_path: str | None = None
    error: str | None = None


class OracleProcess:
    """One oracle bridge subprocess speaking the D14 line protocol.

    Example:
        ```python
        with OracleProcess([sys.executable, "-m", "conformance.oracle_py"]) as oracle:
            oracle.info()["language"]
            # "python"
        ```
    """

    def __init__(self, argv: Sequence[str], cwd: Path | None = None) -> None:
        """Configure the bridge command line.

        Args:
            argv: The subprocess argument vector.
            cwd: Working directory (defaults to the Python repo root so
                ``python -m conformance.oracle_py`` resolves).
        """
        self._argv = list(argv)
        self._cwd = cwd or _REPO_ROOT
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0

    def __enter__(self) -> OracleProcess:
        """Start the bridge process.

        Returns:
            This instance, started.

        Raises:
            OracleBridgeError: If the process cannot be spawned.
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Shut the bridge down (best-effort) and reap the process.

        Args:
            exc_type: Exception type leaving the ``with`` block, if any.
            exc: Exception instance, if any.
            tb: Traceback, if any.
        """
        self.close()

    def start(self) -> None:
        """Spawn the bridge with line-buffered text pipes.

        Raises:
            OracleBridgeError: If the executable cannot be spawned.
        """
        try:
            self._process = subprocess.Popen(  # noqa: S603 - harness-owned argv
                self._argv,
                cwd=self._cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,  # inherit: bridge logs stay visible, never parsed
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise OracleBridgeError(
                f"cannot spawn oracle {self._argv!r}: {exc}"
            ) from exc

    def close(self) -> None:
        """Send ``oracle.shutdown`` (best-effort) and terminate the process."""
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                with contextlib.suppress(OracleBridgeError):
                    self._request("oracle.shutdown", None)
                process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        finally:
            self._process = None

    def info(self) -> Mapping[str, Any]:
        """Fetch the bridge's ``oracle.info`` identity block.

        Returns:
            The info result object.

        Raises:
            OracleBridgeError: On any protocol failure.
        """
        return self._request("oracle.info", None)

    def call(self, api: str, encoded_input: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute one ``oracle.call`` and return its result payload.

        The sentinel api :data:`CODEC_ROUNDTRIP_API` routes to the
        protocol-1.1 ``codec.roundtrip`` METHOD (oracle-protocol.md §8)
        with ``params.value`` = the probe's encoded ``value`` kwarg;
        every other api goes through ``oracle.call``.

        Args:
            api: The dotted registry api name (or the roundtrip sentinel).
            encoded_input: The codec-encoded kwargs.

        Returns:
            The ``{ok, output|error}`` payload.

        Raises:
            OracleBridgeError: On any protocol failure (JSON-RPC ``error``
                response, dead pipe, malformed response line).
        """
        if api == CODEC_ROUNDTRIP_API:
            return self._request(
                "codec.roundtrip", {"value": encoded_input.get("value")}
            )
        return self._request("oracle.call", {"api": api, "input": dict(encoded_input)})

    def _request(
        self, method: str, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        """Send one request line and read its response line.

        Args:
            method: The JSON-RPC method.
            params: The params object, or None to omit.

        Returns:
            The response's ``result`` member (always an object for the
            three oracle methods).

        Raises:
            OracleBridgeError: If the process is not running, the pipe
                closed, the response is malformed, or the bridge answered
                a JSON-RPC ``error`` object.
        """
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise OracleBridgeError("oracle process is not running")
        self._next_id += 1
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            request["params"] = dict(params)
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, ValueError) as exc:
            raise OracleBridgeError(f"oracle pipe failed: {exc}") from exc
        if not line:
            raise OracleBridgeError(f"oracle closed the pipe (exit={process.poll()!r})")
        try:
            response = json.loads(line)
        except ValueError as exc:
            raise OracleBridgeError(
                f"oracle response is not valid JSON: {line!r}"
            ) from exc
        if not isinstance(response, Mapping):
            raise OracleBridgeError(f"oracle response is not an object: {line!r}")
        if "error" in response:
            raise OracleBridgeError(
                f"oracle protocol error for {method}: {response['error']!r}"
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise OracleBridgeError(f"oracle result is not an object: {line!r}")
        return result


def _is_skip(result: Mapping[str, Any]) -> bool:
    """Detect a skip payload (protocol §4.2).

    Args:
        result: A bridge's call result payload.

    Returns:
        True when ``ok`` is false and ``error.code`` is a skip code.
    """
    if result.get("ok"):
        return False
    error = result.get("error")
    return isinstance(error, Mapping) and error.get("code") in SKIP_ERROR_CODES


def _canonical_outcome(result: Mapping[str, Any]) -> str:
    """Reduce one call payload to its canonical comparison string (D6).

    Args:
        result: A bridge's call result payload.

    Returns:
        ``"ok:" + canonicalize(output)`` or ``"error:" +
        canonicalize_error(error)`` — the ok/error axis is part of the
        comparison so a return on one side and a raise on the other always
        diverges.

    Raises:
        OracleBridgeError: If the payload shape is malformed or fails
            canonicalization (a bridge bug, not a divergence).
    """
    try:
        if result.get("ok"):
            return "ok:" + canonicalize(result.get("output"))
        error = result.get("error")
        if not isinstance(error, Mapping):
            raise OracleBridgeError(f"malformed ok:false payload: {result!r}")
        return "error:" + canonicalize_error(error)
    except OracleBridgeError:
        raise
    except Exception as exc:  # CanonicalizationError and shape surprises
        raise OracleBridgeError(
            f"cannot canonicalize oracle payload {result!r}: {exc}"
        ) from exc


def compare_call(
    left: OracleCall, right: OracleCall, api: str, kwargs: Mapping[str, Any]
) -> Divergence | None | str:
    """Probe both bridges with one call and diff the canonical outcomes.

    Args:
        left: The left bridge's call surface.
        right: The right bridge's call surface.
        api: The dotted registry api name.
        kwargs: RAW Python kwargs (encoded here via the shared codec table
            so both bridges receive the identical wire value).

    Returns:
        ``None`` on a match, the string ``"skip"`` when either side
        answered a skip payload, or a :class:`Divergence` record.

    Raises:
        OracleBridgeError: On protocol-level failures from either bridge.
    """
    encoded = encode_input_kwargs(kwargs)
    # Round-trip through JSON text so both bridges (and the in-process
    # test doubles) see exactly the value a real pipe would deliver.
    encoded = json.loads(json.dumps(encoded, ensure_ascii=True))
    left_result = left(api, encoded)
    right_result = right(api, encoded)
    if _is_skip(left_result) or _is_skip(right_result):
        return "skip"
    if _canonical_outcome(left_result) != _canonical_outcome(right_result):
        return Divergence(
            api=api, encoded_input=encoded, left=left_result, right=right_result
        )
    return None


@dataclass
class _RunState:
    """Mutable per-target state shared with the Hypothesis check function.

    Attributes:
        examples: Probes executed so far.
        skipped: Probes skipped so far.
        last_divergence: The most recent divergence — after the Hypothesis
            run raises, this holds the MINIMAL example (the engine replays
            the shrunk counterexample last).
    """

    examples: int = 0
    skipped: int = 0
    last_divergence: Divergence | None = None


def _build_property(
    target: FuzzTarget,
    left: OracleCall,
    right: OracleCall,
    state: _RunState,
    max_examples: int,
) -> Callable[[], None]:
    """Assemble the Hypothesis property for one target.

    Attaches every R10.9 edge call as an explicit ``@example`` (design
    D14), then the target strategy via ``@given``, then deterministic
    settings (``derandomize=True``, no database, no deadline — bridge
    round-trips are I/O bound).

    Args:
        target: The fuzz target.
        left: Left bridge call surface.
        right: Right bridge call surface.
        state: Shared run state (counters + minimal divergence).
        max_examples: Generated-example budget per target.

    Returns:
        A zero-arg callable running the property (raises
        :class:`_DivergenceFound` with the minimal example in ``state``).
    """

    def check(call: FuzzCall) -> None:
        """Probe both bridges with one generated call.

        Args:
            call: The ``(api, kwargs)`` probe.

        Raises:
            _DivergenceFound: When the canonical outcomes differ.
            OracleBridgeError: On protocol-level bridge failures.
        """
        api, kwargs = call
        state.examples += 1
        outcome = compare_call(left, right, api, kwargs)
        if outcome == "skip":
            state.skipped += 1
            return
        if isinstance(outcome, Divergence):
            state.last_divergence = outcome
            raise _DivergenceFound(api)

    # Hypothesis decorators erase precise callable types; the single Any
    # below is confined to decorator plumbing (justification: hypothesis'
    # own decorator signatures return loosely-typed wrappers).
    decorated: Any = check
    for edge in reversed(target.edge_calls):
        decorated = example(call=edge)(decorated)
    decorated = given(call=target.calls)(decorated)
    decorated = settings(
        max_examples=max_examples,
        derandomize=True,
        database=None,
        deadline=None,
        suppress_health_check=(
            HealthCheck.too_slow,
            HealthCheck.filter_too_much,
            HealthCheck.data_too_large,
        ),
    )(decorated)
    result: Callable[[], None] = decorated
    return result


def _write_repro(repro_dir: Path, target: FuzzTarget, divergence: Divergence) -> Path:
    """Write one shrunken divergence repro file (design D14).

    Args:
        repro_dir: The repro output directory (created if missing).
        target: The diverging target.
        divergence: The minimal divergence record.

    Returns:
        The written file path
        (``<repro_dir>/<date>-<api-with-dashes>.json``).
    """
    repro_dir.mkdir(parents=True, exist_ok=True)
    date = _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat()
    path = repro_dir / f"{date}-{divergence.api.replace('.', '-')}.json"
    payload = {
        "date": date,
        "target": target.name,
        "api": divergence.api,
        "input": divergence.encoded_input,
        "left": divergence.left,
        "right": divergence.right,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_target(
    target: FuzzTarget,
    left: OracleCall,
    right: OracleCall,
    *,
    max_examples: int,
    repro_dir: Path,
) -> TargetReport:
    """Fuzz one target across both bridges and report the outcome.

    Args:
        target: The fuzz target.
        left: Left bridge call surface.
        right: Right bridge call surface.
        max_examples: Generated-example budget.
        repro_dir: Where to write a minimal repro on divergence.

    Returns:
        The per-target report (never raises for divergences; bridge
        failures land in ``report.error``).
    """
    state = _RunState()
    report = TargetReport(name=target.name)
    prop = _build_property(target, left, right, state, max_examples)
    try:
        prop()
    except _DivergenceFound:
        report.divergences = 1
        if state.last_divergence is not None:
            report.repro_path = str(
                _write_repro(repro_dir, target, state.last_divergence)
            )
    except OracleBridgeError as exc:
        report.error = str(exc)
    report.examples = state.examples
    report.skipped = state.skipped
    return report


@dataclass
class HarnessResult:
    """Aggregate result of one harness run.

    Attributes:
        status: ``ok`` / ``divergence`` / ``harness_crashed``.
        left_info: Left bridge identity (``oracle.info``).
        right_info: Right bridge identity.
        targets: Per-target reports in run order.
    """

    status: str
    left_info: Mapping[str, Any]
    right_info: Mapping[str, Any]
    targets: list[TargetReport] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Serialize the result for the ``--report json`` output.

        Returns:
            A JSON-ready report object with per-target example counts.
        """
        return {
            "status": self.status,
            "left_info": dict(self.left_info),
            "right_info": dict(self.right_info),
            "examples_per_target": {t.name: t.examples for t in self.targets},
            "skipped_per_target": {t.name: t.skipped for t in self.targets},
            "total_examples": sum(t.examples for t in self.targets),
            "total_divergences": sum(t.divergences for t in self.targets),
            "targets": [
                {
                    "name": t.name,
                    "examples": t.examples,
                    "skipped": t.skipped,
                    "divergences": t.divergences,
                    "repro_path": t.repro_path,
                    "error": t.error,
                }
                for t in self.targets
            ],
        }


def run_harness(
    left: OracleProcess,
    right: OracleProcess,
    targets: Sequence[FuzzTarget],
    *,
    max_examples: int,
    repro_dir: Path,
) -> HarnessResult:
    """Run the full differential pass over started bridges.

    Args:
        left: Started left bridge.
        right: Started right bridge.
        targets: Targets to fuzz, in order.
        max_examples: Generated-example budget per target.
        repro_dir: Repro output directory.

    Returns:
        The aggregate result (``harness_crashed`` when any target hit a
        bridge/protocol failure — crashes are never divergences, mirroring
        D9.3).

    Raises:
        OracleBridgeError: If either bridge fails ``oracle.info`` before
            any target runs.
    """
    result = HarnessResult(status="ok", left_info=left.info(), right_info=right.info())
    for target in targets:
        report = run_target(
            target,
            left.call,
            right.call,
            max_examples=max_examples,
            repro_dir=repro_dir,
        )
        result.targets.append(report)
    if any(t.error for t in result.targets):
        result.status = "harness_crashed"
    elif any(t.divergences for t in result.targets):
        result.status = "divergence"
    return result


def _print_report(result: HarnessResult, as_json: bool) -> None:
    """Write the final report to stdout.

    Args:
        result: The aggregate result.
        as_json: True for machine-readable JSON output.
    """
    payload = result.to_payload()
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return
    print(
        f"[fuzz_harness] status={payload['status']} "
        f"examples={payload['total_examples']} "
        f"divergences={payload['total_divergences']}"
    )
    for target in payload["targets"]:
        line = (
            f"  {target['name']}: examples={target['examples']} "
            f"skipped={target['skipped']} divergences={target['divergences']}"
        )
        if target["repro_path"]:
            line += f" repro={target['repro_path']}"
        if target["error"]:
            line += f" ERROR={target['error']}"
        print(line)


def _default_oracle_argv() -> list[str]:
    """Build the default (in-repo oracle-py) bridge argument vector.

    Returns:
        ``[<current interpreter>, "-m", "conformance.oracle_py"]``.
    """
    return [sys.executable, "-m", "conformance.oracle_py"]


def _select_targets(spec: str) -> list[FuzzTarget]:
    """Resolve the ``--targets`` selector.

    Args:
        spec: ``"all"`` or a comma-separated list of target names.

    Returns:
        The selected targets in table order.

    Raises:
        SystemExit: Via ``argparse``-style error for unknown names.
    """
    if spec == "all":
        return list(ALL_TARGETS)
    selected: list[FuzzTarget] = []
    for name in spec.split(","):
        name = name.strip()
        if name not in TARGETS_BY_NAME:
            known = ", ".join(sorted(TARGETS_BY_NAME))
            raise SystemExit(f"unknown target {name!r} (known: {known})")
        selected.append(TARGETS_BY_NAME[name])
    return selected


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (see module docstring for usage).

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 ok / 1 divergence / 2 harness crash).
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.differential.fuzz_harness",
        description="Differential fuzzing over the D14 oracle bridges.",
    )
    parser.add_argument(
        "--left",
        default=None,
        help="Left bridge command line (shlex-split); default: in-repo oracle-py.",
    )
    parser.add_argument(
        "--right",
        default=None,
        help="Right bridge command line; default: in-repo oracle-py (self-parity).",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=200,
        help="Generated examples per target (default 200 — the D14 self-parity bar).",
    )
    parser.add_argument(
        "--targets",
        default="all",
        help="Comma-separated target names, or 'all' (default).",
    )
    parser.add_argument(
        "--repro-dir",
        type=Path,
        default=DEFAULT_REPRO_DIR,
        help="Directory for shrunken divergence repros.",
    )
    parser.add_argument(
        "--report",
        choices=("json", "text"),
        default="text",
        help="Report format.",
    )
    args = parser.parse_args(argv)
    targets = _select_targets(args.targets)
    left_argv = shlex.split(args.left) if args.left else _default_oracle_argv()
    right_argv = shlex.split(args.right) if args.right else _default_oracle_argv()
    try:
        with OracleProcess(left_argv) as left, OracleProcess(right_argv) as right:
            result = run_harness(
                left,
                right,
                targets,
                max_examples=args.examples,
                repro_dir=args.repro_dir,
            )
    except OracleBridgeError as exc:
        print(f"[fuzz_harness] harness_crashed: {exc}", file=sys.stderr)
        return 2
    _print_report(result, args.report == "json")
    if result.status == "harness_crashed":
        return 2
    return 1 if result.status == "divergence" else 0


if __name__ == "__main__":
    sys.exit(main())
