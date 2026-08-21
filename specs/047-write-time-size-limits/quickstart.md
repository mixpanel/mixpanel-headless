# Quickstart: Write-Time Size-Limit Enforcement

**Feature**: 047-write-time-size-limits | **Date**: 2026-08-20

Internal-only in this slice — there is no public API or CLI yet (memory tool
verbs land in AIE-608). This shows how a sibling feature or a test triggers
the guard and catches the new error, and how a normal write at or under the
ceiling is unaffected.

## Writing at or under the ceiling succeeds unchanged

```python
from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend

backend = LocalFilesystemBackend(scope_dir)

backend.write("notes.md", b"# context\n")     # tiny — always fine
backend.write("empty.md", b"")                 # zero bytes — fine (FR-010)

at_ceiling = b"x" * 8_192                      # exactly 8 KiB
backend.write("large.md", at_ceiling)          # succeeds — inclusive ceiling
assert backend.read("large.md") == at_ceiling  # byte-identical
```

## Writing over the ceiling is rejected, atomically

```python
from mixpanel_headless._internal.memory.limits import MemorySizeLimitError

too_big = b"x" * 8_193                         # one byte over

try:
    backend.write("oversized.md", too_big)
except MemorySizeLimitError as exc:
    print(exc.size, exc.limit)                 # 8193 8192
    # No file was created at "oversized.md".
    assert backend.read("oversized.md") is None
```

## Rejecting an overwrite leaves the existing file untouched

```python
backend.write("note.md", b"original content")

try:
    backend.write("note.md", b"x" * 8_193)
except MemorySizeLimitError:
    pass

assert backend.read("note.md") == b"original content"  # unchanged, not truncated
```

## Catching the error without string-matching

```python
from mixpanel_headless._internal.memory.limits import (
    MAX_MEMORY_WRITE_BYTES,
    MemorySizeLimitError,
)

def write_note_or_summarize(backend, key: str, data: bytes) -> None:
    """Write, or fall back to a caller-provided summarization strategy."""
    try:
        backend.write(key, data)
    except MemorySizeLimitError as exc:
        raise RuntimeError(
            f"Note too large ({exc.size}B > {exc.limit}B); "
            "split or summarize before retrying."
        ) from exc
```

`MemorySizeLimitError` subclasses `ValueError`, so existing broad
`except ValueError` handling still catches it — but `except MemorySizeLimitError`
lets a caller (or the dreaming curator) react specifically, without parsing
the message string.

## Verify the DoD locally

```bash
just test -k "memory_limits or memory_backend"   # unit tests for this slice
just test-pbt                                     # Hypothesis boundary-size PBT
just typecheck                                    # mypy --strict
just check                                        # full gate (lint + fmt + typecheck + cov + build)
just mutate-check                                 # mutmut >= 80% on check_write_size
```
