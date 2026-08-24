# Data Model: Optimistic-Locking Concurrency for Memory Writes

**Feature**: 048-optimistic-locking-writes | **Date**: 2026-08-21

This slice adds no new persisted record type and touches no existing
entry/format schema. It adds one fingerprint type, three error types (a
common base plus two concrete siblings), a small set of retry-policy
constants, and two functions/methods (all pure except the guarded-write
orchestration itself, which is additive on `LocalFilesystemBackend`) that
together implement optimistic-locking read-modify-write.

## Entities

### `Fingerprint` (type alias / small value type)

The whole-file content fingerprint captured at read time and re-verified at
commit time (FR-001, FR-008).

- **Module**: `src/mixpanel_headless/_internal/memory/locking.py`.
- **Shape**: `Fingerprint = bytes | None` — a `sha256` digest (`bytes`,
  32 bytes long) when content exists at the key, or the Python singleton
  `None` when no file exists at the key (the absence sentinel, D4). `None`
  can never be confused with a `bytes` digest at the type level, satisfying
  FR-009 without relying on a chosen-but-technically-producible digest
  value.
- **Construction**: Produced only by `fingerprint_of(data: bytes | None) ->
  Fingerprint`.
- **Equality**: Two fingerprints match iff they are `==`-equal — `None ==
  None` (both absent) or two equal 32-byte digests (identical content).
  Never persisted to disk; never serialized; exists only for the duration
  of one guarded-write attempt.

### `fingerprint_of` (pure function)

```python
def fingerprint_of(data: bytes | None) -> Fingerprint:
    """Return the content fingerprint for ``data``, or the absence sentinel."""
```

- **Module**: `locking.py`.
- **Behavior**:
  - `data is None` → returns `None` (absence sentinel).
  - `data is bytes` (including `b""`) → returns `hashlib.sha256(data).digest()`.
- **Purity**: No I/O; a pure function of its single argument.
- **Note**: `fingerprint_of(b"")` (an existing, empty file) is a valid
  32-byte digest, distinct from `fingerprint_of(None)` (no file) — this is
  the FR-009 guarantee made concrete.

### `MemoryLockingError` (error)

The common base exception for every typed error this slice raises
(Key Entities: "Locking error base").

- **Module**: `locking.py`.
- **Base class**: `Exception` — not `ValueError`, not `RuntimeError`, and
  not `MemorySizeLimitError` (D3). Kept independent of the AIE-605
  size-guard hierarchy (`MemorySizeLimitError` is a bare `ValueError` with
  no memory-specific base to align with) so a caller can never confuse "a
  locking failure" with "a size violation" through a shared ancestor.
- **Role**: Never raised directly. Exists so a caller can `except
  MemoryLockingError` to catch either concrete error below with one type,
  while the two concrete errors remain siblings — catching one never
  incidentally catches the other.

### `MemoryConflictError` (error)

The catchable, typed failure raised by a single guarded-write attempt when
the fingerprint captured at read time no longer matches the current on-disk
state at commit time (Key Entities: "Per-attempt conflict error").

- **Module**: `locking.py`.
- **Base class**: `MemoryLockingError` — a direct subclass, sibling to
  `MemoryConflictRetriesExhaustedError` (D3). Not `MemorySizeLimitError`,
  not `MemoryConflictRetriesExhaustedError`, and not (transitively)
  `ValueError` — a caller wanting `ValueError` semantics catches
  `MemorySizeLimitError` on its own merits, unrelated to this hierarchy.
- **Fields**:
  - `key: str` — the memory key the conflict occurred on.
  - `expected: Fingerprint` — the fingerprint the caller read at the start
    of the attempt.
  - `actual: Fingerprint` — the fingerprint observed at commit time.
- **Invariants**: Always constructed with `expected != actual` — the check
  that raises it never fires when they match.
- **Message**: Human-readable text naming the key (never the raw fingerprint
  bytes, to keep messages short); fields remain the structured source of
  truth for a caller that wants to log or branch on more than "a conflict
  happened."

### `MemoryConflictRetriesExhaustedError` (error)

The catchable, typed failure raised by the retrying helper when every
attempt within `MAX_MEMORY_WRITE_ATTEMPTS` raises `MemoryConflictError` (Key
Entities: "Retries-exhausted error").

- **Module**: `locking.py`.
- **Base class**: `MemoryLockingError` — a direct subclass, sibling to
  `MemoryConflictError` (D3), not a subclass of it. Exhaustion of a bounded
  retry budget is a distinct failure mode from a single collision, so the
  two concrete errors share only the common `MemoryLockingError` base, not
  each other; neither is a `ValueError` or a `RuntimeError` — the shared
  `MemoryLockingError` base itself subclasses plain `Exception`.
- **Fields**:
  - `key: str` — the memory key that could not be committed.
  - `attempts: int` — the total number of attempts made, equal to
    `MAX_MEMORY_WRITE_ATTEMPTS`.
  - `last_conflict: MemoryConflictError` — the final attempt's conflict,
    for a caller that wants the last observed `expected`/`actual`
    fingerprint pair without re-deriving it.
- **Invariants**: Always constructed with `attempts ==
  MAX_MEMORY_WRITE_ATTEMPTS`; `last_conflict` is always the exception
  raised by the final attempt.
- **Message**: Names the key and the attempt count.

### Retry-policy constants

The single named source of truth every caller of the retrying helper shares
(FR-005).

- **Module**: `locking.py`.
- **`MAX_MEMORY_WRITE_ATTEMPTS: Final[int] = 5`** — total attempts including
  the first (locked, D1). Not the number of *retries* (4) — the constant
  name and value both count total attempts to avoid an off-by-one between
  "attempts" and "retries" at call sites and in tests.
- **`RETRY_BACKOFF_BASE_SECONDS: Final[float] = 0.015`** — the upper bound
  of the full-jitter delay window (15 ms, within the locked 10-20 ms
  range); the actual delay for a given retry is drawn uniformly from
  `[0, RETRY_BACKOFF_BASE_SECONDS)`.
- **`next_backoff_delay() -> float`** — pure with respect to program state
  other than the process-global `random` source; returns a value in
  `[0, RETRY_BACKOFF_BASE_SECONDS)`. Isolated as its own function (rather
  than inlined at the `time.sleep` call site) so the *distribution* of
  delays it returns is unit- and property-testable without monkeypatching
  `time.sleep` itself.

## Guarded-write primitives (behavior, additive to `backend.py`)

### `LocalFilesystemBackend.write_if_match` (new method)

```python
def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
    """Write ``data`` at ``key`` iff its current fingerprint equals ``expected``.

    Raises:
        MemoryConflictError: the current fingerprint at ``key`` no longer
            equals ``expected``.
        MemorySizeLimitError: ``len(data)`` exceeds
            :data:`~mixpanel_headless._internal.memory.limits.MAX_MEMORY_WRITE_BYTES`.
        ValueError: ``key`` is empty, absolute, or escapes the scope.
        OSError: I/O failure.
    """
```

- **Precondition**: `expected` is the `Fingerprint` the caller obtained from
  a prior `read_with_fingerprint(key)` call (or `None` for a fresh key it
  believes does not exist yet).
- **Ordering (D6)**: (1) read current bytes at `key`, compute
  `fingerprint_of(current)`, compare to `expected` — raise
  `MemoryConflictError` on mismatch; (2) `check_write_size(data)` — raise
  `MemorySizeLimitError` on oversized content; (3) delegate to the existing
  `write(key, data)` for the unchanged atomic commit. No step performs
  `time.sleep`; this method makes exactly one attempt.
- **Does not retry.** This is the primitive User Story 2's "opt out of
  auto-retry" caller uses directly (FR-012).

### `LocalFilesystemBackend.read_with_fingerprint` (new method)

```python
def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
    """Return ``(current_bytes_or_None, fingerprint_of(current_bytes_or_None))``."""
```

- A convenience pairing of `read(key)` with `fingerprint_of` so a caller
  never computes a fingerprint from a value it did not just read (avoiding
  a caller-side TOCTOU between its own `read()` call and its own hashing).

### `write_with_retry` (new module-level function, `locking.py`)

```python
def write_with_retry(
    backend: MemoryBackend,
    key: str,
    mutate: Callable[[bytes | None], bytes],
) -> None:
    """Read, mutate, and write ``key`` with automatic conflict retry.

    Raises:
        MemoryConflictRetriesExhaustedError: every attempt within
            MAX_MEMORY_WRITE_ATTEMPTS raised MemoryConflictError.
        MemorySizeLimitError: any attempt's mutated content exceeds the
            AIE-605 per-file byte ceiling. Never retried.
        ValueError: key is empty, absolute, or escapes the scope.
        OSError: I/O failure.
    """
```

- **Behavior**: Loop up to `MAX_MEMORY_WRITE_ATTEMPTS` times. Each
  iteration: call `backend.read_with_fingerprint(key)`, compute
  `new_data = mutate(current)`, call
  `backend.write_if_match(key, new_data, expected=fingerprint)`. On success,
  return. On `MemoryConflictError`, if attempts remain, sleep
  `next_backoff_delay()` and loop again; if attempts are exhausted, raise
  `MemoryConflictRetriesExhaustedError` wrapping the final
  `MemoryConflictError`. On `MemorySizeLimitError` from any attempt,
  propagate immediately — never caught, never retried (FR-010).
- **`mutate`**: the caller-supplied transform, `bytes | None -> bytes` (see
  research.md D7 for the purity/re-invocation contract).
- **Depends on**: `MemoryBackend`'s protocol gaining `write_if_match` and
  `read_with_fingerprint` as part of this slice (additive protocol methods
  — existing implementations of the protocol that predate this slice do
  not exist outside `LocalFilesystemBackend`, so this is not a breaking
  change to any real caller).

## Non-goals (owned elsewhere)

- Entry format / confidence labels (`entry.py`, `format.py`) — unchanged;
  the fingerprint operates on already-serialized `bytes`, agnostic to what
  produced them.
- The AIE-605 size guard itself — unchanged, reused as-is via
  `check_write_size` inside `write_if_match`'s second step.
- Cross-key or cross-scope locking, lock files, or any coordination
  primitive that persists across process restarts — explicitly out of
  scope per the spec's Assumptions.
- PII detection/redaction of write content (AIE-607).
- Public exposure of `write_with_retry` / `write_if_match` /
  `MemoryLockingError` / `MemoryConflictError` /
  `MemoryConflictRetriesExhaustedError` and user-facing tool-verb shapes
  (AIE-608) — this slice stays `_internal`, matching 045/046/047's staging.
- Read-side behavior changes — plain `read()` is unaffected; only the two
  new guarded methods and the retrying helper are new.
