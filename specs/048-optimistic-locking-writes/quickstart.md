# Quickstart: Optimistic-Locking Concurrency for Memory Writes

**Feature**: 048-optimistic-locking-writes | **Date**: 2026-08-21

Internal-only in this slice — there is no public API or CLI yet (memory tool
verbs land in AIE-608). This shows the guarded read-modify-write cycle, a
conflict being auto-retried, and catching the retries-exhausted error.

## An uncontested guarded write behaves like today's write, plus one check

```python
from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend
from mixpanel_headless._internal.memory.locking import write_with_retry

backend = LocalFilesystemBackend(scope_dir)
backend.write("notes.md", b"# context\n")

def append_line(current: bytes | None) -> bytes:
    """Append a line to the note, treating no-file as an empty note."""
    base = current or b""
    return base + b"another fact\n"

write_with_retry(backend, "notes.md", append_line)
assert backend.read("notes.md") == b"# context\nanother fact\n"
```

## A single intervening write is retried automatically

```python
calls = []

def mutate(current: bytes | None) -> bytes:
    """Simulate a second writer landing in between the first two attempts."""
    calls.append(current)
    if len(calls) == 1:
        # A different writer commits behind our back before we can land.
        backend.write("shared.md", b"someone else's update\n")
    return (current or b"") + b"\nmy update"

write_with_retry(backend, "shared.md", mutate)

# attempt 1 read b"" (or None), then the intervening write landed, so
# attempt 1's write_if_match conflicted; attempt 2 re-read the intervening
# writer's content and committed on top of it.
assert len(calls) == 2
assert backend.read("shared.md") == b"someone else's update\n\nmy update"
```

## Opting out of auto-retry: catching a single conflict directly

```python
from mixpanel_headless._internal.memory.locking import MemoryConflictError

current, fingerprint = backend.read_with_fingerprint("shared.md")
new_data = (current or b"") + b"\none more line"

# Another writer lands here, in between our read and our write.
backend.write("shared.md", b"raced ahead\n")

try:
    backend.write_if_match("shared.md", new_data, expected=fingerprint)
except MemoryConflictError as exc:
    print(exc.key, exc.expected, exc.actual)
    # "shared.md" <old fingerprint> <the racing writer's fingerprint>
    # No retry happened -- write_if_match makes exactly one attempt.
```

## Catching the retries-exhausted error

```python
from mixpanel_headless._internal.memory.locking import (
    MAX_MEMORY_WRITE_ATTEMPTS,
    MemoryConflictRetriesExhaustedError,
)

def always_races(current: bytes | None) -> bytes:
    """A pathological mutation that always loses the race, for illustration."""
    backend.write("contended.md", (current or b"") + b"!")  # someone else always wins
    return (current or b"") + b"?"

try:
    write_with_retry(backend, "contended.md", always_races)
except MemoryConflictRetriesExhaustedError as exc:
    print(exc.key, exc.attempts)  # "contended.md" 5
    assert exc.attempts == MAX_MEMORY_WRITE_ATTEMPTS
    # exc.last_conflict is the final MemoryConflictError, if more detail is needed.
```

`MemoryConflictError` and `MemoryConflictRetriesExhaustedError` both
subclass the common `MemoryLockingError` base; neither subclasses the
other, so a caller can `except` either one specifically without
accidentally catching the other. `MemoryLockingError` itself is
independent of AIE-605's `MemorySizeLimitError` — an oversized mutation
output propagates immediately, uncaught by the retry loop and never
confused with a locking failure. A caller that wants to catch either
locking failure with one type can `except MemoryLockingError` instead:

```python
from mixpanel_headless._internal.memory.locking import MemoryLockingError

try:
    write_with_retry(backend, "contended.md", always_races)
except MemoryLockingError as exc:
    # Catches both MemoryConflictError and
    # MemoryConflictRetriesExhaustedError without pulling in
    # MemorySizeLimitError.
    print(type(exc).__name__, exc)
```

## Verify the DoD locally

```bash
just test -k "memory_locking or memory_backend"   # unit tests for this slice
just test-pbt                                      # Hypothesis boundary/backoff PBT
just typecheck                                     # mypy --strict
just check                                         # full gate (lint + fmt + typecheck + cov + build)
just mutate-check                                  # mutmut >= 80% on locking.py's pure logic
```
