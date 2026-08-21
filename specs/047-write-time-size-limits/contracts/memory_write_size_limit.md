# Internal Contract: Write-Time Size-Limit Enforcement

**Feature**: 047-write-time-size-limits | **Date**: 2026-08-20

This is an `_internal` contract (not part of the public `mixpanel_headless`
API surface in this slice), analogous to
[`../../046-markdown-format-confidence-labels/contracts/memory_entry_format.md`](../../046-markdown-format-confidence-labels/contracts/memory_entry_format.md).
It is an internal Python-library primitive, not an HTTP API: the "contract" is
the behavioral guarantee `LocalFilesystemBackend.write` gives every caller —
current and future — once this slice lands. Signatures are the intended
shape; exact typing is finalized in code under `mypy --strict`.

## `limits.py` (new module)

```python
MAX_MEMORY_WRITE_BYTES: int = 8_192  # 8 KiB

class MemorySizeLimitError(ValueError):
    """Raised when write content exceeds MAX_MEMORY_WRITE_BYTES."""

    def __init__(self, size: int, limit: int) -> None:
        ...

    size: int
    limit: int

def check_write_size(data: bytes) -> None:
    """Raise MemorySizeLimitError if len(data) > MAX_MEMORY_WRITE_BYTES."""
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `check_write_size(data)` | `len(data) <= MAX_MEMORY_WRITE_BYTES` | returns `None`; no exception |
| `check_write_size(b"")` | zero-byte content | returns `None` (FR-010 — empty is not oversized) |
| `check_write_size(data)` | `len(data) == MAX_MEMORY_WRITE_BYTES` | returns `None` (FR-002 — inclusive ceiling) |
| `check_write_size(data)` | `len(data) == MAX_MEMORY_WRITE_BYTES + 1` | raises `MemorySizeLimitError(size=MAX_MEMORY_WRITE_BYTES + 1, limit=MAX_MEMORY_WRITE_BYTES)` |
| `check_write_size(data)` | `len(data) > MAX_MEMORY_WRITE_BYTES` (any excess) | raises `MemorySizeLimitError` with `.size == len(data)`, `.limit == MAX_MEMORY_WRITE_BYTES` |
| `MemorySizeLimitError(size, limit)` | any | `isinstance(err, ValueError)` is `True`; `err.size`, `err.limit` set; `str(err)` names both numbers |

## `LocalFilesystemBackend.write` (backend.py) — new raising behavior

```python
def write(self, key: str, data: bytes) -> None:
    """Atomically store ``data`` at ``key``, creating dirs on demand.

    Raises:
        MemorySizeLimitError: len(data) exceeds MAX_MEMORY_WRITE_BYTES.
        ValueError: key is empty, absolute, or escapes the scope.
        OSError: I/O failure.
    """
```

### Preconditions

- `key` is a valid relative key (unchanged from the existing contract —
  validated by `_resolve`/`resolve_key`).
- `data` is the exact `bytes` payload the caller wants persisted at `key`.
  This slice does not care how those bytes were produced (raw notes,
  `format.serialize(...)` output, or anything else) — the check is on the
  final byte length only.

### New postcondition — oversized content

- **Given** `len(data) > MAX_MEMORY_WRITE_BYTES`:
  - **When** `write(key, data)` is called, **regardless of whether a file
    already exists at `key`**,
  - **Then**:
    1. `MemorySizeLimitError` is raised, carrying the rejected `size` and the
       `limit` it exceeded.
    2. No directory is created that did not already exist
       (`self._ensure_dir` is never reached).
    3. No file is created at `key` if none existed before the call.
    4. If a file already existed at `key`, its on-disk bytes are byte-for-byte
       unchanged after the call — no truncation, no partial write (FR-004).
    5. No tmp file (`<name>.tmp.<pid>.<tid>`) is left behind —
       `atomic_write_bytes` is never invoked, so it never creates one.

### Unchanged postcondition — content at or under the ceiling

- **Given** `len(data) <= MAX_MEMORY_WRITE_BYTES` (including `len(data) == 0`):
  - **When** `write(key, data)` is called,
  - **Then** behavior is exactly as before this slice: the scope directory is
    created if needed, `data` is written atomically via
    `atomic_write_bytes(path, data, mode=0o600)`, and a subsequent
    `read(key)` returns `data` byte-identical (SC-001).

### Ordering guarantee (why atomicity holds without try/except)

`check_write_size(data)` is the first statement in `write()`, executed before
`self._resolve(key)`'s directory side effects and before
`atomic_write_bytes` is ever called. `len(data)` is a synchronous, in-memory,
allocation-free computation on a `bytes` object the caller already holds —
there is no code path between "check the length" and "raise" that touches the
filesystem, so a raised `MemorySizeLimitError` is by construction a strict
no-op with respect to disk state.

### Every write primitive inherits this (User Story 3 / FR-008)

Any current or future write primitive that funnels through
`LocalFilesystemBackend.write` — the sole implementation of the
`MemoryBackend.write` protocol method in this slice — gets this exact
behavior automatically. A future higher-level helper (e.g. a tool-verb
wrapper landing in a later slice) that calls `backend.write(...)` internally
does not need to re-implement or re-check the ceiling; it cannot bypass the
guard without avoiding `write()` entirely, which would mean not persisting
through the `MemoryBackend` seam at all.
