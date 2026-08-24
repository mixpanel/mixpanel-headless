# Internal Contract: Optimistic-Locking Concurrency for Memory Writes

**Feature**: 048-optimistic-locking-writes | **Date**: 2026-08-21

This is an `_internal` contract (not part of the public `mixpanel_headless`
API surface in this slice), analogous to
[`../../047-write-time-size-limits/contracts/memory_write_size_limit.md`](../../047-write-time-size-limits/contracts/memory_write_size_limit.md).
It is an internal Python-library primitive, not an HTTP API: the "contract"
is the behavioral guarantee `locking.py` and the two new `backend.py`
methods give every caller — current and future — once this slice lands.
Signatures are the intended shape; exact typing is finalized in code under
`mypy --strict`.

## `locking.py` (new module)

```python
Fingerprint = bytes | None

MAX_MEMORY_WRITE_ATTEMPTS: int = 5
RETRY_BACKOFF_BASE_SECONDS: float = 0.015

def fingerprint_of(data: bytes | None) -> Fingerprint:
    """sha256 digest of data, or None if data is None (absence sentinel)."""

def next_backoff_delay() -> float:
    """A jittered delay in [0, RETRY_BACKOFF_BASE_SECONDS)."""

class MemoryLockingError(Exception):
    """Common base for every typed error this module raises. Never raised
    directly; lets a caller catch any locking failure with one type while
    MemoryConflictError and MemoryConflictRetriesExhaustedError remain
    siblings."""

class MemoryConflictError(MemoryLockingError):
    """Raised when the current fingerprint at a key no longer matches
    the fingerprint captured at read time."""

    def __init__(self, key: str, expected: Fingerprint, actual: Fingerprint) -> None: ...

    key: str
    expected: Fingerprint
    actual: Fingerprint

class MemoryConflictRetriesExhaustedError(MemoryLockingError):
    """Raised when every attempt within MAX_MEMORY_WRITE_ATTEMPTS raised
    MemoryConflictError."""

    def __init__(self, key: str, attempts: int, last_conflict: MemoryConflictError) -> None: ...

    key: str
    attempts: int
    last_conflict: MemoryConflictError

def write_with_retry(
    backend: MemoryBackend,
    key: str,
    mutate: Callable[[bytes | None], bytes],
) -> None:
    """Read-mutate-write key with automatic conflict retry, bounded by
    MAX_MEMORY_WRITE_ATTEMPTS."""
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `fingerprint_of(None)` | key has no file | returns `None` |
| `fingerprint_of(b"")` | key has an existing, empty file | returns a 32-byte `sha256` digest; `!= fingerprint_of(None)` |
| `fingerprint_of(data)` | key has existing content `data` | returns `hashlib.sha256(data).digest()`; deterministic for identical `data` |
| `next_backoff_delay()` | any | returns a `float` in `[0, RETRY_BACKOFF_BASE_SECONDS)` |
| `MemoryConflictError(key, expected, actual)` | `expected != actual` | `isinstance(err, MemoryLockingError)` is `True`; `.key`, `.expected`, `.actual` set |
| `MemoryConflictRetriesExhaustedError(key, attempts, last_conflict)` | `attempts == MAX_MEMORY_WRITE_ATTEMPTS` | `isinstance(err, MemoryLockingError)` is `True`; NOT `isinstance(err, MemoryConflictError)`; `.key`, `.attempts`, `.last_conflict` set |

## `LocalFilesystemBackend.read_with_fingerprint` (backend.py) — new method

```python
def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
    """Return (current bytes or None, its fingerprint).

    Raises:
        ValueError: key is empty, absolute, or escapes the scope.
        CredentialPathError: the note path is a symlink.
        OSError: other I/O failure.
    """
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `read_with_fingerprint(key)` | no file at `key` | returns `(None, None)` |
| `read_with_fingerprint(key)` | file at `key` holds `data` | returns `(data, fingerprint_of(data))` |

## `LocalFilesystemBackend.write_if_match` (backend.py) — new method

```python
def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
    """Atomically store data at key iff its current fingerprint == expected.

    Raises:
        MemoryConflictError: the current fingerprint at key no longer
            equals expected.
        MemorySizeLimitError: len(data) exceeds MAX_MEMORY_WRITE_BYTES.
        ValueError: key is empty, absolute, or escapes the scope.
        OSError: I/O failure.
    """
```

### Preconditions

- `key` is a valid relative key (unchanged from the existing `write()`
  contract — validated by `_resolve`/`resolve_key`).
- `expected` is a `Fingerprint` the caller obtained from a prior
  `read_with_fingerprint(key)` call on the same backend instance (or `None`
  for a caller that believes the key does not yet exist and has not read
  it at all).
- `data` is the exact `bytes` payload the caller wants persisted at `key`
  if `expected` still matches. This contract does not care how those bytes
  were produced.

### New postcondition — fingerprint mismatch (conflict)

- **Given** the current fingerprint at `key` (recomputed at the start of
  this call) does not equal `expected`:
  - **When** `write_if_match(key, data, expected=expected)` is called,
  - **Then**:
    1. `MemoryConflictError(key, expected, actual)` is raised, where
       `actual` is the fingerprint observed at the start of this call.
    2. **The scope directory itself may now be created if it did not
       already exist** — this is the one documented exception to "no
       directory is created." Closing the cross-process TOCTOU race (two
       processes both passing the fingerprint check and both committing,
       silently losing one update — see the locking design note below)
       requires holding an OS-level lock across the re-read, the
       comparison, and the commit. The lock is an `flock` on the scope
       directory's own file descriptor (no separate lock file), and a
       directory must exist to be opened, so `write_if_match` now
       unconditionally ensures the scope directory exists as the very
       first step, before the fingerprint re-check runs — even on a call
       that goes on to conflict or fail the size guard. No directory
       *other than* the scope directory itself (e.g. no intermediate
       directory for a nested key) is created on a conflict or
       size-guard failure.
    3. No file is created at `key` if none existed before the call.
    4. If a file already existed at `key`, its on-disk bytes are
       byte-for-byte unchanged after the call.
    5. No tmp file is left behind — the underlying `atomic_write_bytes`
       (via `write()`) is never invoked when the fingerprint check fails.

### Locking design — closing the cross-process TOCTOU race

The original version of this contract described `write_if_match` as
"atomic" while actually performing three unsynchronized syscalls (read
fingerprint → compare → write). Two separate *processes* (e.g. a live
session and a background curator) could both read a matching fingerprint,
both pass the comparison, and both call `write()` — the second `os.replace`
silently discards the first, and neither process observes
`MemoryConflictError`. `write_with_retry`'s in-process retry loop cannot
detect this: the losing write lands from an entirely different process,
outside anything the retry loop reads.

The fix: `write_if_match` holds an exclusive `fcntl.flock` on the scope
directory's file descriptor for the full duration of the re-read +
compare + commit. This serializes every `write_if_match` call against
every other one that targets the same scope directory (coarser than
per-key — all keys within one scope share the lock — chosen for
simplicity and because it avoids creating any per-key lock file that
would otherwise show up in `list()`'s output). The lock is released
(and the directory fd closed) in a `finally`, on every exit path:
success, conflict, size-guard failure, or an unrelated `OSError`.

`fcntl` is POSIX-only. The import is guarded (`try`/`except ImportError`)
so the module still imports on Windows; there, `write_if_match` degrades
explicitly to no cross-process locking (single-process, single-attempt
fingerprint check only) rather than silently pretending to lock. This is
a documented gap, not a regression — no OS-level lock existed on any
platform before this fix.

### New postcondition — fingerprint match (no conflict)

- **Given** the current fingerprint at `key` equals `expected`:
  - **When** `write_if_match(key, data, expected=expected)` is called,
  - **Then** behavior is exactly the existing `write()` contract from
    AIE-605: `check_write_size(data)` runs first (may raise
    `MemorySizeLimitError`, in which case the same atomicity guarantees as
    above apply — this is not a conflict, it is the unrelated size guard),
    and on success the scope directory is created if needed and `data` is
    written atomically via `atomic_write_bytes(path, data, mode=0o600)`.

### Ordering guarantee (why atomicity holds without try/except)

Within one `write_if_match` call: the fingerprint re-check happens first,
strictly before `check_write_size` and strictly before any code path that
could call `atomic_write_bytes`. Both the fingerprint re-check and the size
check are synchronous, in-memory computations on data already read into
the process — there is no code path between "detect a conflict or an
oversized payload" and "raise" that touches the filesystem for a write, so
a raised `MemoryConflictError` or `MemorySizeLimitError` is by construction
a strict no-op with respect to disk state, exactly as AIE-605's D6
established for the size guard alone.

## `write_with_retry` (locking.py) — retrying helper

### Behavioral contract (tested)

| Scenario | Precondition | Postcondition |
|----------|--------------|---------------|
| Uncontested write | no intervening writer between the helper's read and its first `write_if_match` call | succeeds on attempt 1; `mutate` invoked exactly once; no `time.sleep` call occurs |
| Single conflict | exactly one intervening write lands between the helper's first read and its first `write_if_match` call | attempt 1 raises `MemoryConflictError` (caught internally); helper sleeps `next_backoff_delay()`; attempt 2 re-reads, re-invokes `mutate` against the fresh content, and succeeds |
| Persistent conflict | every attempt's `write_if_match` call raises `MemoryConflictError` | after `MAX_MEMORY_WRITE_ATTEMPTS` attempts, raises `MemoryConflictRetriesExhaustedError(key, MAX_MEMORY_WRITE_ATTEMPTS, last_conflict)`; no content is committed at any point |
| Oversized mutation on any attempt | `mutate`'s output exceeds `MAX_MEMORY_WRITE_BYTES` on some attempt | `MemorySizeLimitError` propagates immediately from that attempt; the helper does not catch it, does not retry it, and does not wrap it in `MemoryConflictRetriesExhaustedError` |
| Fresh key, racing create | two `write_with_retry` calls target the same key with no existing file | exactly one succeeds without a retry (the loser's first attempt detects the winner's create as a conflict and retries against the winner's committed content) |

### Every write primitive inherits the size guard unchanged (FR-010, FR-011)

`write_if_match` delegates its size check to the same `check_write_size`
from `limits.py` that `write()` already calls, and delegates its atomic
commit to the same `write()` method (or the equivalent inline sequence of
`_ensure_dir` + `atomic_write_bytes`) once both guards pass. No new size
policy is introduced, and no existing guarantee of `write()` (atomic
same-filesystem rename, symlink rejection on read, owner-only file mode) is
weakened or bypassed by either new method.
