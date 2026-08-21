# Data Model: Write-Time Size-Limit Enforcement

**Feature**: 047-write-time-size-limits | **Date**: 2026-08-20

This slice adds no new record types and touches no existing entry/format
schema. It adds one constant and one error type, both pure (no I/O), that
`LocalFilesystemBackend.write` consults before it commits bytes.

## Entities

### `MAX_MEMORY_WRITE_BYTES` (constant)

The single defined per-file byte ceiling every memory write primitive
enforces (FR-008).

- **Value**: `8_192` (8 KiB — 8 × 1024 bytes). Locked — a memory note is a
  single concise fact, not a pasted document, so the ceiling is far below
  both `MAX_CREDENTIAL_BYTES` (1 MiB) and `BUSINESS_CONTEXT_MAX_CHARS`
  (~50,000 chars), not merely below one and above the other.
- **Module**: `src/mixpanel_headless/_internal/memory/limits.py`.
- **Type**: `int`.
- **Meaning**: The maximum number of bytes a memory write primitive will
  accept for one file's content in one `write()` call. Inclusive — a payload
  of exactly this many bytes succeeds (FR-002).
- **Scope**: Per individual memory file. Never summed across files, scopes,
  or an entire `memory/` tree (FR-009).

### `MemorySizeLimitError` (error)

The catchable, typed failure raised when a write's content size exceeds
`MAX_MEMORY_WRITE_BYTES` (Key Entities: "Oversized-write error").

- **Module**: `src/mixpanel_headless/_internal/memory/limits.py`.
- **Base class**: `ValueError` — matches the `MemoryFormatError(ValueError)`
  precedent in `format.py` so existing `except ValueError` handling still
  catches it, while giving callers a precise type to match without
  string-matching a message (FR-006).
- **Fields**:
  - `size: int` — the rejected content's length in bytes (the value that
    failed the check).
  - `limit: int` — the ceiling it exceeded, i.e. `MAX_MEMORY_WRITE_BYTES` at
    the time of the raise.
- **Invariants**:
  - Always constructed with `size > limit` — the check that raises it never
    fires when `size <= limit` (the ceiling is inclusive; see the
    `check_write_size` contract below).
  - Both fields are plain `int`s, so a caller can log or react to the exact
    numbers without parsing the message string (FR-007).
- **Message**: Human-readable text naming both `size` and `limit` (e.g.
  `"Memory write of 8193 bytes exceeds the 8192-byte per-file limit."`),
  generated in `__init__` from the two fields — the fields remain the
  structured source of truth; the message is a convenience for logs.

### `check_write_size` (pure function)

The size-check logic itself — the unit that must clear the ≥80% mutmut bar
called out in the spec's Success Criteria (SC-005).

- **Module**: `src/mixpanel_headless/_internal/memory/limits.py`.
- **Signature**: `check_write_size(data: bytes) -> None`.
- **Behavior**: Compares `len(data)` against `MAX_MEMORY_WRITE_BYTES`.
  - `len(data) <= MAX_MEMORY_WRITE_BYTES` → returns `None` (no-op, including
    for `len(data) == 0`, per FR-010).
  - `len(data) > MAX_MEMORY_WRITE_BYTES` → raises
    `MemorySizeLimitError(size=len(data), limit=MAX_MEMORY_WRITE_BYTES)`.
- **Purity**: No filesystem, no network, no mutation of `data` — a single
  in-memory comparison, matching `format.py`'s "deliberately I/O-free" design
  so it is independently unit-, property-, and mutation-testable in isolation
  from `LocalFilesystemBackend`.

## Enforcement point (behavior change, no new entity)

`LocalFilesystemBackend.write(key, data)` in `backend.py` gains one line —
a call to `check_write_size(data)` — as its first statement, before
`self._resolve(key)`'s side effects and before `atomic_write_bytes`. See
[`contracts/memory_write_size_limit.md`](contracts/memory_write_size_limit.md)
for the precise pre/postcondition contract.

## Non-goals (owned elsewhere)

- Entry format / confidence labels (`entry.py`, `format.py`) — unchanged;
  the size guard operates on already-serialized `bytes`, agnostic to what
  produced them (AIE-604, done).
- Concurrency / optimistic locking on writes (AIE-606).
- PII detection/redaction of write content (AIE-607).
- Public exposure of `MAX_MEMORY_WRITE_BYTES` / `MemorySizeLimitError` and
  user-facing verb shapes (AIE-608) — this slice stays `_internal`, matching
  045/046's staging.
- Any per-tree or per-scope quota (explicitly out of scope per FR-009).
- Read-side size behavior — unchanged; memory reads still do not enforce the
  credential-style cap, per the existing backend's documented posture.
