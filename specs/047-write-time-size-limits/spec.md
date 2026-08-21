# Feature Specification: Write-Time Size-Limit Enforcement

**Feature Branch**: `msiebert-agent-memory` (slice `047-write-time-size-limits`; no per-feature branch)
**Created**: 2026-08-20
**Status**: Draft
**Linear**: AIE-605
**Input**: Enforce a per-file byte ceiling on every Headless Memory write primitive, on top of the AIE-603 storage foundation and the AIE-604 entry format.

## User Scenarios & Testing *(mandatory)*

The "user" of this slice is an AI agent (and the dreaming curator that rewrites
notes on its behalf) writing a memory note through any write primitive. The
size guard is a contract those callers share: it protects the memory tree from
unbounded growth without ever taking the risk of silently mutilating a note.

### User Story 1 - A write at or under the limit succeeds unchanged (Priority: P1)

An agent writes a note whose serialized size is at or under the defined
per-file byte ceiling. The write succeeds and the stored bytes are exactly
what was submitted — nothing trimmed, nothing altered.

**Why this priority**: The guard must never interfere with legitimate writes.
If normal-sized notes were rejected or altered, the memory system would be
unusable; this is the baseline the rejection behavior in User Story 2 is
built against.

**Independent Test**: Write a note whose byte size is under the ceiling, then
at exactly the ceiling, and confirm both succeed and read back byte-identical
to what was written. Fully testable with no real filesystem beyond a
temporary directory.

**Acceptance Scenarios**:

1. **Given** a note whose serialized size is below the per-file ceiling,
   **When** it is written through a write primitive, **Then** the write
   succeeds and reading the same key back returns byte-identical content.
2. **Given** a note whose serialized size is exactly the per-file ceiling,
   **When** it is written, **Then** the write succeeds — the ceiling is
   inclusive, not an exclusive bound.
3. **Given** a zero-byte note, **When** it is written, **Then** the write
   succeeds (an empty note is valid content, not a size violation).

---

### User Story 2 - A write over the limit is rejected, atomically (Priority: P1)

An agent (or the dreaming curator) attempts to write a note whose serialized
size exceeds the per-file ceiling — for example a runaway curation pass or an
agent that pastes in a large document. The write primitive refuses the write
before any byte reaches disk and raises a clear, catchable error naming the
offending size and the ceiling.

**Why this priority**: This is the feature. Without it, nothing bounds how
large a single memory file can grow, and an oversized note could exhaust disk
space or blow out read-side assumptions elsewhere in the system. The error
must be catchable so a calling agent or the dreaming curator can recover
(e.g., split the note, summarize it, or surface the failure) rather than
crash uncontrolled.

**Independent Test**: Attempt to write a note one byte over the ceiling
against a backend with no pre-existing file at that key, and against a
backend with an existing file at that key; assert both raise the same typed,
catchable error and that no file is created or modified in either case.

**Acceptance Scenarios**:

1. **Given** a note whose serialized size is one byte over the per-file
   ceiling, **When** it is written to a key with no existing file, **Then**
   the write raises a typed, catchable error and no file is created at that
   key.
2. **Given** an existing note stored under a key, **When** a caller attempts
   to overwrite it with content that exceeds the per-file ceiling, **Then**
   the write raises the same typed error and the existing note on disk is
   left completely unmodified — no partial write, no truncation.
3. **Given** a rejected write, **When** the raised error is inspected, **Then**
   it names both the size of the rejected content and the ceiling it exceeded,
   so a caller can log or react to the specific numbers.

---

### User Story 3 - The ceiling is enforced consistently across every write primitive (Priority: P2)

Whichever memory write primitive an agent or a future tool surface calls —
whether it stores a fresh note, overwrites an existing one, or is invoked
through a not-yet-built higher-level helper — the same byte ceiling applies
with the same rejection behavior. No primitive gets a silent exemption.

**Why this priority**: Memory has more than one write entry point already
(direct backend writes today; tool-primitive wrappers land in a later slice).
A guard placed on only one of them would be trivially bypassed by the next
caller that goes through a different path, defeating the purpose of a
size limit.

**Independent Test**: Exercise every write primitive exposed by the memory
write path with an oversized payload and confirm each one rejects it the
same way, with the same error type and the same ceiling constant.

**Acceptance Scenarios**:

1. **Given** the set of all memory write primitives, **When** each is called
   with content exceeding the ceiling, **Then** each raises the same typed
   error referencing the same ceiling value.
2. **Given** a future write primitive built on top of the existing write
   path, **When** it delegates to that path, **Then** it inherits the size
   guard automatically rather than needing to re-implement it.

---

### Edge Cases

- **Exactly at the limit**: succeeds (inclusive ceiling — see User Story 1,
  Scenario 2).
- **One byte over the limit**: rejected (see User Story 2, Scenario 1).
- **Zero-byte content**: valid and accepted; "empty" is not "oversized."
- **Multi-byte UTF-8 where character count differs from byte count**: the
  ceiling is measured in bytes of the serialized content, not characters or
  code points, so a note that looks short in an editor can still be rejected
  if its encoded byte size exceeds the ceiling (e.g., a body dense with
  multi-byte characters).
- **Overwrite of an existing file that would exceed the cap**: rejected before
  any byte of the new content is written; the previously stored note is left
  exactly as it was (see User Story 2, Scenario 2).
- **A write whose content is already on disk unchanged** (a no-op rewrite of
  a file at or under the ceiling): succeeds, since it is not oversized.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every memory write primitive MUST enforce a per-file byte
  ceiling on the content being written, measured in bytes of the serialized
  content (not characters, not on-disk size after any future compression).
- **FR-002**: The ceiling MUST be inclusive: content whose size is exactly the
  ceiling MUST be accepted; content one byte over MUST be rejected.
- **FR-003**: A write that would exceed the ceiling MUST be rejected before
  any byte of the new content is committed to storage. No partial or
  truncated write may occur.
- **FR-004**: Rejecting an oversized write MUST NOT modify, truncate, or
  otherwise alter any content already stored at the target key. An oversized
  overwrite attempt leaves the existing file exactly as it was.
- **FR-005**: The system MUST NEVER silently truncate oversized content to fit
  the ceiling under any circumstance.
- **FR-006**: A rejected write MUST raise a distinct, catchable error type
  (not a bare generic exception) that a calling agent or curator can detect
  and handle without string-matching an error message.
- **FR-007**: The raised error MUST report both the size of the rejected
  content and the ceiling value it exceeded, so callers can log or react to
  the specific numbers.
- **FR-008**: The per-file byte ceiling MUST be a single defined constant
  shared by every write primitive, so the limit cannot drift between
  primitives or be silently exempted by a new one.
- **FR-009**: The size guard MUST apply per individual memory file — it MUST
  NOT aggregate or compare against the total size of a memory tree, other
  files in the same scope, or any cross-file quota.
- **FR-010**: A write of zero-byte content MUST be accepted; the guard rejects
  content that is too large, never content that is empty.
- **FR-011**: The guard MUST apply uniformly regardless of whether the target
  key already has stored content (fresh write) or is being overwritten
  (existing content present).

### Key Entities *(include if feature involves data)*

- **Per-file byte ceiling**: A single constant naming the maximum number of
  bytes a memory write primitive will accept for one file's content in one
  write call. Applies identically to every write primitive; not a per-tree or
  per-scope quota.
- **Oversized-write error**: The catchable, typed failure raised when a write
  attempt's content size exceeds the per-file byte ceiling. Carries the
  rejected size and the ceiling for caller inspection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of writes at or under the per-file ceiling succeed and
  read back byte-identical to what was submitted, verified across randomized
  boundary sizes (zero, one byte under, exactly at the ceiling).
- **SC-002**: 100% of writes exceeding the per-file ceiling by any amount
  (one byte to arbitrarily large) are rejected with a catchable, typed error
  — never silently truncated, never partially committed.
- **SC-003**: 100% of rejected overwrite attempts against an existing file
  leave that file's stored bytes unchanged, verified by reading the key
  before and after the rejected write and comparing.
- **SC-004**: Every write primitive exposed by the memory write path enforces
  the identical ceiling constant — a single source-of-truth check confirms no
  primitive defines its own, divergent limit.
- **SC-005**: Automated test coverage for the slice is ≥90%, and mutation
  score on the pure size-check logic is ≥80%.

## Assumptions

- **Unit and scope (locked)**: The ceiling is measured in bytes and enforced
  per individual file, not per memory tree. This mirrors the existing
  read-side cap (`MAX_CREDENTIAL_BYTES`, 1 MiB, enforced per credential file
  in `io_utils.py`) and deliberately does not introduce a cross-file quota,
  which would require tracking total tree size and is out of scope for this
  slice.
- **Default ceiling value (locked)**: This spec fixes **8 KiB (8,192 bytes)**
  as the per-file write ceiling for memory notes. The number is a locked
  decision, not open to revision in the plan phase:
  - A memory note is a single concise fact, not a pasted document. 8 KiB is
    roughly 1,300 words — far more than one note should ever need — so the
    ceiling rejects accidental dumps (a pasted transcript, a copied file)
    while giving a dense, well-written note 4-8x headroom over what it
    typically occupies in practice.
  - It sits far below `MAX_CREDENTIAL_BYTES` (1 MiB): credential files guard
    against OOM on secrets that are never expected to be large, but a memory
    note has an even tighter, purpose-built ceiling because it is expected to
    be short by construction, not merely bounded.
  - It sits far below `BUSINESS_CONTEXT_MAX_CHARS` (roughly 50,000 characters,
    ~50 KB-200 KB depending on encoding): a business-context document is a
    project-level reference meant to hold many sections, whereas a single
    memory note is one fact and has no business being anywhere near that
    size.
  - It is small enough that many such files accumulating in a scope's memory
    tree remain a bounded, predictable disk footprint, while still leaving
    generous headroom over a typical dense note.
  - The constant is finalized and named during the plan phase; this spec
    fixes both the literal number and the *behavior* (inclusive per-file
    byte ceiling, atomic rejection, catchable typed error).
- **Write-path scope**: "Every memory write primitive" refers to the write
  path that exists today (the backend's single write entry point that all
  higher-level memory operations funnel through) plus any write primitive
  built in a later slice on top of it. This slice does not enumerate future
  tool-primitive names; it requires that whatever is built inherits the same
  guard rather than re-implementing or bypassing it.
- **Read path unaffected**: This slice covers only the write path. It does
  not change, add, or remove any read-side size behavior (memory reads
  intentionally do not enforce the credential-style size cap, per the
  existing backend's documented posture) and does not revisit that decision.
- **No PII or content-quality scanning**: This slice enforces size only. It
  does not inspect, redact, or validate the content's meaning — that remains
  a sibling concern for other slices.
