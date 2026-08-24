"""Real multi-process concurrency test for the ``write_if_match`` lock.

Threads sharing one process's memory cannot prove cross-process mutual
exclusion: ``flock`` locks are associated with an open file description,
and two threads in the same process that each ``os.open`` their own fd
for the same path get *independent* lock instances that do not contend
with each other the way the kernel's per-inode ``flock`` state actually
does across processes. Only real, separate OS processes can catch the
TOCTOU bug this module closes -- so this test uses ``multiprocessing``
(real processes), not threads.
"""

from __future__ import annotations

import multiprocessing
import platform
from pathlib import Path

import pytest

from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend
from mixpanel_headless._internal.memory.locking import write_with_retry

_WORKER_COUNT = 8
_KEY = "shared_notes.md"
_JOIN_TIMEOUT_SECONDS = 30.0


def _run_worker(scope_dir: str, worker_id: int) -> None:
    """Append this worker's unique line to the shared note via ``write_with_retry``.

    Runs in a separate OS process (spawned by
    ``test_concurrent_processes_never_lose_an_update``). Each worker reads
    the note's current content, appends its own line, and commits through
    the optimistic-locking retry loop -- exactly the pattern a live
    session and a background curator would both use against the same
    memory note.

    Args:
        scope_dir: String path to the shared scope directory (a
            ``Path`` is passed as ``str`` for uneventful pickling across
            the process boundary).
        worker_id: This worker's unique index, embedded in the line it
            appends so the parent test can verify every worker's write
            survived.
    """
    backend = LocalFilesystemBackend(Path(scope_dir))
    line = f"worker-{worker_id}\n".encode()

    def mutate(current: bytes | None) -> bytes:
        """Append this worker's line to whatever content currently exists."""
        return (current or b"") + line

    write_with_retry(backend, _KEY, mutate)


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="flock-based cross-process locking is POSIX-only",
)
def test_concurrent_processes_never_lose_an_update(tmp_path: Path) -> None:
    """N real OS processes racing on one key must not silently lose an update.

    Without the ``flock``-guarded critical section in
    ``LocalFilesystemBackend.write_if_match``, two processes can both
    read a matching fingerprint, both pass the compare, and both commit
    via ``os.replace`` -- the second write silently discards the first
    with no ``MemoryConflictError`` raised anywhere, because the losing
    write happens entirely in a different process's memory, outside
    anything this process's retry loop ever reads. ``write_with_retry``'s
    in-process retry cannot detect a conflict it never sees.

    Every one of ``_WORKER_COUNT`` worker processes appends its own
    uniquely-identified line via ``write_with_retry``. After all workers
    complete, every single line must be present in the final file --
    proving no update was lost to the race -- and the file must contain
    exactly ``_WORKER_COUNT`` lines (well-formed, no partial/corrupted
    write and no duplicate).
    """
    scope_dir = tmp_path / "projects" / "1" / "memory"
    backend = LocalFilesystemBackend(scope_dir)
    backend.write(_KEY, b"")  # seed a defined starting point

    ctx = multiprocessing.get_context("spawn")
    processes = [
        ctx.Process(target=_run_worker, args=(str(scope_dir), worker_id))
        for worker_id in range(_WORKER_COUNT)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=_JOIN_TIMEOUT_SECONDS)

    still_alive = [p for p in processes if p.is_alive()]
    for p in still_alive:
        p.terminate()
    assert not still_alive, "one or more worker processes did not finish in time"
    assert all(p.exitcode == 0 for p in processes), (
        f"a worker process failed: exit codes {[p.exitcode for p in processes]}"
    )

    final_content = backend.read(_KEY)
    assert final_content is not None
    lines = final_content.decode().splitlines()

    expected_lines = {f"worker-{i}" for i in range(_WORKER_COUNT)}
    assert set(lines) == expected_lines, (
        "lost update detected: not every worker's line survived the race"
    )
    assert len(lines) == _WORKER_COUNT, (
        "unexpected line count -- possible corruption or duplicate commit"
    )
