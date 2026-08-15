"""oracle-py entry point: ``python -m conformance.oracle_py`` (design D14).

Runs the newline-delimited JSON-RPC 2.0 oracle loop over stdin/stdout under
the SAME frozen clock/UUID/virtual-sleep environment as the corpus runner
(design D1.4/D7): ``RECORD_EPOCH`` freeze, deterministic UUID stream, and
per-call determinism reset. stdout carries ONLY protocol response lines
(ASCII-safe); stderr is free-form logs and is never parsed (design D14).

Exit codes:

- ``0`` — clean exit (``oracle.shutdown`` served, or EOF on stdin).
- ``2`` — environment failure before the loop started (missing
  ``freezegun`` — bootstrap with ``uv sync --all-extras``, design D9.2).
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run the oracle read loop until shutdown or EOF.

    Returns:
        Process exit code (0 clean, 2 environment failure).
    """
    try:
        import freezegun  # noqa: F401
    except ImportError:
        print(
            "oracle-py: freezegun is not installed — the D1.4 clock shim "
            "cannot run. Bootstrap the environment with `uv sync "
            "--all-extras` (design D9.2 step 2).",
            file=sys.stderr,
        )
        return 2
    from conformance.oracle_py.server import OracleServer
    from conformance.record.clock import RecordClock

    clock = RecordClock()
    clock.start()
    server = OracleServer(reset=clock.reset_test_state)
    try:
        for raw_line in sys.stdin:
            response = server.handle_line(raw_line.rstrip("\r\n"))
            if response is not None:
                print(response, flush=True)
            if server.shutdown_requested:
                break
    finally:
        clock.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
