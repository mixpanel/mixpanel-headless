# Research: Write-Time Size-Limit Enforcement

**Feature**: 047-write-time-size-limits | **Date**: 2026-08-20

All decisions below are locked for this slice (AIE-605). No `NEEDS CLARIFICATION`
markers remain — the ceiling value is a locked decision (8 KiB / 8,192 bytes),
not open to revision here or later.

## D1 — Unit: bytes of the serialized content, not characters or code points

- **Decision**: The ceiling is measured in `len(data)` where `data: bytes` is
  the already-serialized payload handed to the write primitive — the exact
  bytes that will land on disk.
- **Rationale**: FR-001 requires the measurement be "bytes of the serialized
  content (not characters, not on-disk size after any future compression)".
  A multi-byte UTF-8 body can be short in characters but large in bytes (Edge
  Cases in spec.md); checking the encoded `bytes` object is the only measure
  that matches what actually gets written and later read back. It also mirrors
  the existing read-side precedent (`MAX_CREDENTIAL_BYTES` in `io_utils.py`),
  which caps `st.st_size` — bytes on disk — not a character count.
- **Alternatives rejected**: Counting `len(text)` on a `str` before encoding —
  wrong unit for multi-byte UTF-8 and would let a body that encodes over the
  ceiling slip through; capping post-write on-disk size — impossible to check
  before the write commits, which violates the atomic-rejection requirement
  (FR-003).

## D2 — Scope: per-file, not per-tree or per-scope

- **Decision**: The guard compares one write call's byte length against the
  ceiling and nothing else — no summing across files, no tracking of a scope's
  total on-disk footprint.
- **Rationale**: This is locked by the spec's own "Unit and scope (locked)"
  assumption and FR-009 ("MUST NOT aggregate or compare against the total size
  of a memory tree"). A per-tree quota would require the backend to enumerate
  and sum sibling files on every write — extra I/O, extra failure modes, and a
  cross-cutting concern the spec explicitly defers.
- **Alternatives rejected**: A per-scope quota (sum of all files under one
  `memory/` dir) — out of scope per FR-009 and would need a `list()` + stat
  pass before every `write()`, changing the big-O of a currently O(1) call.

## D3 — The 8 KiB (8,192 bytes) ceiling value

- **Decision**: `MAX_MEMORY_WRITE_BYTES = 8_192` (8 KiB), defined once as an
  `int` constant. Locked — not a placeholder for later revision.
- **Rationale**: A memory note is one concise fact, not a pasted document.
  8 KiB is roughly 1,300 words — 4-8x more than a dense, well-written note
  occupies in practice — so the ceiling rejects accidental dumps (a pasted
  transcript, a copied file) while leaving generous headroom for a real note.
  It sits **far below** both existing size precedents in the codebase, and
  deliberately so, because a memory note has a tighter, purpose-built ceiling
  than either:
  - `MAX_CREDENTIAL_BYTES` (1 MiB, `io_utils.py`) guards against OOM on
    secrets that are never expected to be large but are still allowed a wide
    margin; a memory note is expected to be short *by construction*, not
    merely bounded, so its ceiling is over 100x smaller.
  - `BUSINESS_CONTEXT_MAX_CHARS` (~50,000 characters, ~50-200 KB) is a
    project-level reference document meant to hold many sections; a single
    memory note is one fact and has no business approaching that size, so its
    ceiling sits far below it too, not just "comfortably above" some fraction
    of it.
  8 KiB × many notes accumulating in a scope's `memory/` tree remains a small,
  predictable disk footprint.
- **Alternatives rejected**: 256 KiB (the spec's original placeholder) — sized
  for a "keep prose notes bounded" posture borrowed from document-sized
  budgets, when a memory note is fact-sized, not document-sized; accepting
  256 KiB would let a single runaway note occupy as much space as an entire
  `BUSINESS_CONTEXT_MAX_CHARS` document several times over, which is exactly
  the un-bounded-growth risk this slice exists to prevent. Reusing
  `MAX_CREDENTIAL_BYTES` (1 MiB) directly — conflates a "reject implausible
  secrets" cap with a "keep one fact concise" cap. A cap near 1 KiB — too
  tight; would reject legitimate multi-paragraph curated notes in normal use,
  which the spec's Success Criteria (SC-001) require to succeed unmodified.

## D4 — Enforcement point: `LocalFilesystemBackend.write`, before `atomic_write_bytes`

- **Decision**: The guard runs as the first statement inside
  `LocalFilesystemBackend.write(key, data)` in `backend.py`, checking
  `len(data)` and raising before `self._resolve(key)`'s directory-creation
  side effect and before `atomic_write_bytes` is called at all.
- **Rationale**: `write()` is the single choke point every current write path
  funnels through (per `MemoryBackend`'s protocol contract and the package
  docstring: "a thin, content-agnostic protocol"). Every current call site
  (and, per FR-008/User Story 3, every future write primitive — tool-verb
  wrappers land in a later slice) calls this one method rather than
  `atomic_write_bytes` or `os.open` directly. Placing the check here means a
  future primitive inherits the guard automatically by delegating to
  `write()`, with no re-implementation and no way to bypass it by choosing a
  different internal helper.
- **Alternatives rejected**: Checking inside `atomic_write_bytes` in
  `io_utils.py` — that helper is shared with credential/config writes that
  have their own, unrelated size discipline (`MAX_CREDENTIAL_BYTES` governs
  reads, not writes, today); overloading it with a memory-specific ceiling
  would leak a memory-domain constant into a generic I/O utility. Checking at
  each higher-level call site individually — exactly the "trivially bypassed
  by the next caller that goes through a different path" failure User Story 3
  warns against.

## D5 — New exception: `MemorySizeLimitError(ValueError)` in a new pure module

- **Decision**: Add `MemorySizeLimitError`, subclassing `ValueError`, in a new
  module `src/mixpanel_headless/_internal/memory/limits.py` (repo-relative:
  `src/mixpanel_headless/_internal/memory/limits.py`), alongside the
  `MAX_MEMORY_WRITE_BYTES` constant and the pure size-check function
  (`check_write_size`). Exported from `_internal/memory/__init__.py` next to
  `MemoryFormatError`.
- **Rationale**: Follows the exact precedent `MemoryFormatError(ValueError)`
  set in `format.py` — subclassing `ValueError` keeps it catchable by any
  existing broad `except ValueError` handling while still being a precise,
  named type callers can `except MemorySizeLimitError` specifically (FR-006).
  A new `limits.py` module — rather than adding the exception to `backend.py`
  or `format.py` — keeps the constant, the exception, and the pure
  byte-length comparison in one small, I/O-free module that mirrors 046's
  pure/IO split (`format.py` pure vs. `backend.py` I/O): the size check itself
  never touches the filesystem, so it can be unit-tested and mutation-tested
  in complete isolation from `LocalFilesystemBackend`, exactly like `format.py`
  is tested in isolation from `backend.py` today.
- **Alternatives rejected**: Subclassing `OSError` (matching
  `CredentialPathError`) — `CredentialPathError` intentionally mirrors
  `OSError`-based call sites that already `except OSError` for I/O failures;
  a size-limit rejection is a content-validation failure, not an I/O failure,
  and callers reacting to it (splitting a note, summarizing, surfacing to the
  user) want a `ValueError`-shaped "your input was invalid" signal, consistent
  with `MemoryFormatError`. Defining the exception directly in `backend.py` —
  would mix pure validation logic into the I/O-bearing module and lose the
  isolated mutmut target. Defining it in `format.py` — conflates two unrelated
  concerns (entry serialization vs. write-size policy) in one module and one
  `__all__`.

## D6 — Atomicity: check `len(data)` before any I/O, not a try/except around the write

- **Decision**: `write()` computes `len(data)` and calls
  `check_write_size(data)` — which raises `MemorySizeLimitError` synchronously
  — as the very first operation, strictly before `self._ensure_dir(...)` and
  `atomic_write_bytes(...)`. No directory is created, no tmp file is opened,
  and no byte reaches the filesystem when the check fails.
- **Rationale**: FR-003 requires rejection "before any byte of the new content
  is committed to storage" and FR-004 requires the existing file (if any) be
  left "completely unmodified — no partial write, no truncation." Because
  `len(data)` is an in-memory, allocation-free operation on the `bytes` object
  already held by the caller, there is no way for a partial write to occur
  before the check completes — the check and the first filesystem syscall are
  strictly ordered, so a raised `MemorySizeLimitError` is by construction a
  no-op with respect to disk state. This requires no `try`/`except`/rollback
  logic: atomicity here is a matter of statement ordering, not a compensating
  action after a failed write.
- **Alternatives rejected**: Writing to a tmp file first and checking its size
  before the atomic rename — `atomic_write_bytes` already receives `data` as
  an in-memory `bytes` object, so its size is knowable without ever opening a
  tmp file; adding that indirection would create exactly the disk I/O the
  atomic-rejection requirement is designed to avoid, and would leave a
  same-pid/tid stale tmp file to clean up on the rejection path for no benefit.
