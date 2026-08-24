# Feature Specification: Optimistic-Locking Concurrency for Memory Writes

**Feature Branch**: `msiebert-agent-memory` (slice `048-optimistic-locking-writes`; no per-feature branch)
**Created**: 2026-08-21
**Status**: Draft
**Linear**: AIE-606
**Input**: Guard the Headless Memory read-modify-write cycle against concurrent
writers, on top of the AIE-603 storage foundation, the AIE-604 entry format,
and the AIE-605 write-time size guard.

## User Scenarios & Testing *(mandatory)*

The "user" of this slice is the same actor as 045/046/047: an AI agent (and
the dreaming curator that rewrites notes on its behalf) reading a note,
deciding how to change it, and writing the result back. Today that
read-modify-write cycle is not guarded — two concurrent writers (an agent
session and a background curator, or two agent sessions sharing a scope) can
each read the same content, each compute a different mutation, and the second
`write()` silently clobbers the first writer's update with no signal to
either side. This slice closes that gap with an optimistic-locking primitive:
detect the conflict before it is committed, retry automatically within a
bounded budget, and raise a typed, catchable error when the budget is
exhausted.

### User Story 1 - An uncontested write succeeds exactly as it does today (Priority: P1)

An agent reads a note, computes a new value, and writes it back with no other
writer touching the same key in between. The guarded write behaves exactly
like the AIE-605 write path today — one size check, one atomic write, no
retry — plus one additional hash computation to confirm nothing changed
underneath it.

**Why this priority**: The guard must never punish the common case. Nearly
every memory write in practice is uncontested; if the guard added retries,
latency, or altered behavior for the ordinary path, the memory system would
be slower and less predictable for no benefit. This is the baseline User
Story 2 and User Story 3 are built against.

**Independent Test**: Perform a guarded write against a backend with no
concurrent writer, both for a fresh key and for an existing key, and confirm
each succeeds on the first attempt, applies the AIE-605 size guard unchanged,
and reads back byte-identical to what the caller's mutation produced.

**Acceptance Scenarios**:

1. **Given** a key with no existing file, **When** a caller performs a
   guarded read-modify-write with no concurrent writer, **Then** the write
   succeeds on the first attempt and a subsequent read returns the mutated
   content byte-identical.
2. **Given** a key with existing content, **When** a caller performs a
   guarded read-modify-write with no concurrent writer, **Then** the write
   succeeds on the first attempt, the prior content is fully replaced, and no
   retry occurs.
3. **Given** a guarded write whose caller-produced content exceeds the
   AIE-605 per-file byte ceiling, **When** the write is attempted, **Then**
   `MemorySizeLimitError` is raised exactly as it is today — the size guard
   is unaffected by, and not retried as, a concurrency conflict.

---

### User Story 2 - A conflicting concurrent write is detected before any byte reaches disk (Priority: P1)

Two writers read the same key's content, each computes a mutation, and one
commits first. When the second writer's guarded write attempts to commit, it
must detect that the on-disk content it read is no longer current, refuse to
overwrite it blindly, and give the caller a typed signal distinguishable from
every other failure mode.

**Why this priority**: This is the feature. Without conflict detection, the
second writer's mutation silently destroys the first writer's committed
change with no error, no log line, and no way for either side to know it
happened. A typed per-attempt conflict error is also the seam a caller uses
to opt out of automatic retry (User Story 3) when it wants to react
differently — for example, abandoning a stale in-flight curation pass rather
than recomputing it.

**Independent Test**: Read a key's content, have a second writer commit a
different value to the same key, then attempt to commit the first writer's
(now-stale) content; assert a typed conflict error is raised, that the
second writer's committed content is completely unmodified on disk, and that
no partial or interleaved bytes ever appear at the key.

**Acceptance Scenarios**:

1. **Given** a caller has read a key's current content and computed a
   mutation, **When** another writer commits different content to that same
   key before the caller's write lands, **Then** the caller's write raises a
   typed conflict error rather than silently overwriting the intervening
   commit.
2. **Given** a raised conflict error, **When** the on-disk content is read
   immediately afterward, **Then** it is exactly what the intervening writer
   committed — never truncated, never interleaved with the losing writer's
   bytes.
3. **Given** a caller that wants to handle a conflict itself rather than
   auto-retry, **When** it calls the single-attempt guarded write primitive
   directly, **Then** it can catch the per-attempt conflict error distinctly
   from the retries-exhausted error described in User Story 3.

---

### User Story 3 - A detected conflict is retried automatically within a bounded budget (Priority: P1)

When the default guarded read-modify-write helper detects a conflict, it
reloads the key's current content, re-invokes the caller's mutation against
that fresh content, and attempts to commit again — up to a fixed, bounded
number of total attempts, with a small randomized delay between attempts so
repeatedly-colliding writers do not lock into a tight retry loop against each
other. If every attempt in the budget conflicts, the helper raises a
dedicated, typed exhaustion error distinct from a single per-attempt
conflict.

**Why this priority**: Auto-retry is what makes the guard usable without
every caller hand-rolling a retry loop. A caller that just wants "make this
change happen, resolving races automatically" should not need to know the
guard exists under normal contention. The bound and the distinct exhaustion
error keep this from becoming an unbounded or silent hang under sustained
contention.

**Independent Test**: Arrange for a key to receive exactly one intervening
write between the helper's first read and its first commit attempt, and
confirm the helper succeeds within the retry budget by re-reading, re-running
the caller's mutation, and committing the second time. Separately, arrange
for every attempt in the budget to collide and confirm the helper raises the
dedicated exhaustion error rather than looping indefinitely or silently
giving up.

**Acceptance Scenarios**:

1. **Given** exactly one intervening write lands between the helper's read
   and its first write attempt, **When** the helper detects the resulting
   conflict, **Then** it reloads the current content, re-invokes the
   caller's mutation against that fresh content, and its retried write
   succeeds — all within the bounded attempt budget.
2. **Given** every attempt within the bounded budget collides with an
   intervening write, **When** the budget is exhausted, **Then** the helper
   raises a dedicated, typed retries-exhausted error distinct from the
   per-attempt conflict error, and no content is committed.
3. **Given** a retry occurs, **When** the delay between attempts is
   inspected across repeated runs, **Then** it is a small, randomized
   ("jittered") interval rather than a fixed delay, so multiple colliding
   writers do not resynchronize onto the same retry cadence.

---

### Edge Cases

- **File created by another writer between read and write**: the caller
  read "absent" (no file); another writer creates the file before the
  caller's commit. Treated as a conflict — the caller's fingerprint captured
  "absent" and the current state is no longer absent.
- **File deleted by another writer between read and write**: the caller read
  existing content; another writer deletes the file before the caller's
  commit. Treated as a conflict — the caller's fingerprint captured the
  prior content and the current state is now absent, which does not match.
- **A retry whose re-run mutation is itself oversized**: if the caller's
  mutation, re-invoked against fresh content during a retry, produces
  content exceeding the AIE-605 per-file byte ceiling, the write fails with
  `MemorySizeLimitError` immediately — this is never treated as a lock
  conflict and is never itself retried by the concurrency guard.
- **Two writers racing to create the same brand-new key**: both read
  "absent"; the first commit wins; the second's commit detects the file now
  exists where it expected absence and is treated as a conflict, subject to
  the same retry/exhaustion behavior as any other conflict.
- **Plain `read()` is unaffected**: this slice adds no guard, fingerprint, or
  behavior change to reading a key outside a guarded write. Only the guarded
  write path is new.
- **A retry that reloads content identical to what the caller already had**:
  possible if the intervening writer wrote back the same bytes (a no-op
  race). Still treated as a conflict on the fingerprint mismatch pass if the
  digest differs at any point in the race window; the retry's fresh read
  simply produces an unchanged mutation input, which is not itself an error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a guarded write primitive that captures
  a content fingerprint of a key at read time and re-verifies that
  fingerprint immediately before committing new content to that key.
- **FR-002**: When the fingerprint captured at read time still matches the
  current on-disk state at commit time, the guarded write MUST proceed
  exactly as the unguarded AIE-605 write path does today — including its
  size guard — with no retry.
- **FR-003**: When the fingerprint captured at read time no longer matches
  the current on-disk state at commit time, the guarded write MUST NOT
  commit any byte of the caller's stale content, and MUST raise a typed,
  catchable per-attempt conflict error distinct from any other exception the
  write path raises.
- **FR-004**: The system MUST provide a higher-level helper that, on
  detecting a conflict, reloads the current content at the key, re-invokes
  the caller-supplied mutation against that fresh content, and re-attempts
  the guarded write, up to a single bounded maximum number of total attempts.
- **FR-005**: The maximum attempt count MUST be a single named constant
  shared by every caller of the retrying helper — not configurable per call
  in this slice.
- **FR-006**: The retrying helper MUST insert a small, randomized ("jittered")
  delay between a detected conflict and the next attempt, rather than
  retrying immediately or on a fixed cadence.
- **FR-007**: When the retrying helper exhausts its bounded attempt budget
  without a successful commit, it MUST raise a dedicated, typed
  retries-exhausted error that is distinguishable from both the per-attempt
  conflict error (FR-003) and `MemorySizeLimitError` (AIE-605) by type alone,
  without string-matching a message.
- **FR-008**: The content fingerprint MUST be computed over the whole byte
  content of a key, not over a section, line range, or any partial view of
  it.
- **FR-009**: The fingerprint MUST have a value distinct from the fingerprint
  of any actual file content — including empty (zero-byte) content — that
  represents "no file exists at this key," so a create-vs-conflicting-create
  race is detected the same way as a modify-vs-conflicting-modify race.
- **FR-010**: The AIE-605 per-file size guard MUST continue to apply,
  unchanged and independently, to every attempt of a guarded write. A
  rejection from the size guard MUST NEVER be treated as, retried as, or
  reported as a lock conflict, and MUST NEVER be silently swallowed by the
  retrying helper.
- **FR-011**: The guarded write path MUST NOT weaken any existing guarantee
  of `LocalFilesystemBackend.write` — atomic same-filesystem rename, no
  partial writes, symlink rejection on the read side, owner-only file mode —
  it composes with those guarantees rather than replacing any of them.
- **FR-012**: A caller MUST be able to opt out of automatic retry and invoke
  the single-attempt guarded write directly, catching only the per-attempt
  conflict error (FR-003) without ever encountering the retries-exhausted
  error (FR-007), which only the retrying helper can raise.
- **FR-013**: The guarded write behavior MUST be defined identically whether
  the target key has no existing file (fresh write) or has existing content
  (overwrite) — "absent" is a valid, well-defined fingerprint state, not a
  special case requiring different handling.

### Key Entities *(include if feature involves data)*

- **Content fingerprint**: A whole-file digest of a key's current bytes, or a
  distinct absence sentinel when no file exists at that key. Computed at
  read time and re-verified at commit time; never persisted to disk.
- **Locking error base**: `MemoryLockingError`, the common base both of the
  slice's typed errors subclass. Lets a caller catch "any locking failure"
  with one type while the two concrete errors remain siblings — catching
  one never incidentally catches the other. Independent of
  `MemorySizeLimitError` (AIE-605); neither hierarchy subclasses the other.
- **Per-attempt conflict error**: `MemoryConflictError`, the catchable,
  typed failure raised by the single-attempt guarded write when the
  fingerprint no longer matches at commit time. Subclasses
  `MemoryLockingError`. Distinct from the retries-exhausted error so a
  caller can opt out of auto-retry and react to a single collision
  directly.
- **Retries-exhausted error**: `MemoryConflictRetriesExhaustedError`, the
  catchable, typed failure raised by the retrying helper when every attempt
  within the bounded budget collides. Subclasses `MemoryLockingError`.
  Distinct from the per-attempt conflict error and from
  `MemorySizeLimitError`.
- **Retry policy**: The named constants governing the retrying helper's
  behavior — the maximum total attempt count and the jittered backoff
  parameters between attempts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of uncontested guarded writes succeed on the first
  attempt and read back byte-identical to the caller's mutation output, with
  no behavior change versus the unguarded AIE-605 write path beyond the
  fingerprint check.
- **SC-002**: 100% of single-conflict scenarios (exactly one intervening
  write between read and commit) succeed within the bounded retry budget,
  verified across randomized intervening-write timing via a Hypothesis
  property-based / concurrency test.
- **SC-003**: 100% of persistent-conflict scenarios (every attempt in the
  budget collides) raise the dedicated retries-exhausted error — the helper
  never loops indefinitely, never silently gives up without raising, and
  never commits stale content.
- **SC-004**: 100% of conflict and retries-exhausted outcomes leave on-disk
  bytes at the key as either the pre-conflict content or one complete
  writer's committed content — never truncated, never interleaved, verified
  by reading the key before and after every conflict/exhaustion scenario.
- **SC-005**: Automated test coverage for the slice is ≥90%, mutation score
  on the pure fingerprint/retry-decision logic is ≥80%, and a Hypothesis
  property-based/concurrency test locks the invariant "a guarded write
  eventually succeeds within budget or raises the retries-exhausted error —
  it never hangs."

## Assumptions

- **Retry policy (locked)**: The retrying helper is bounded to a maximum of
  5 total attempts, with a small randomized ("full jitter") backoff between
  attempts — base delay on the order of 10-20 ms. Exhausting the budget
  raises a dedicated typed exception, `MemoryConflictRetriesExhaustedError`.
  A single attempt's conflict signal is a separate typed error,
  `MemoryConflictError`. Both subclass a common base, `MemoryLockingError`,
  introduced for this slice; neither subclasses the other. Neither
  subclasses AIE-605's `MemorySizeLimitError` (which is a `ValueError`) —
  the locking hierarchy and the size-guard hierarchy are independent. A
  caller can `except MemoryConflictError` alone (opt out of retry),
  `except MemoryConflictRetriesExhaustedError` alone (a terminal retry
  failure), or `except MemoryLockingError` to catch either locking failure
  with one type. Neither number is configurable per call in this slice.
- **Hashing granularity (locked)**: The content fingerprint is computed over
  the whole byte content of a key — `hashlib.sha256` over the raw bytes, not
  a section- or line-level digest — with a distinct sentinel value
  representing "no file exists at this key" (not the hash of empty bytes,
  which must remain distinguishable from absence). Standard library only; no
  new third-party dependency.
- **Caller-mutation purity contract**: The caller-supplied mutation passed to
  the retrying helper may be invoked more than once (once per attempt) and
  must therefore be safe to re-run against fresh content without
  side-effects beyond producing its return value. This is a documented
  contract on the helper's caller, not something the helper enforces at
  runtime.
- **Write-path scope**: This slice touches only `backend.py` (an additive
  change — the existing unguarded `write()` method and its guarantees are
  untouched) and a new pure module, `_internal/memory/locking.py`, mirroring
  the `limits.py` split introduced in AIE-605. It does not add a public API
  surface; tool-primitive wrappers that will call the guarded write path are
  a later slice (AIE-608).
- **Read path unaffected**: Plain `read()` gains no fingerprint, guard, or
  behavior change in this slice. Only the new guarded-write primitives
  compute or consult a fingerprint.
- **No cross-key or cross-scope coordination**: The guard operates on one key
  at a time, exactly like the AIE-605 size guard operates on one file at a
  time. It does not introduce a lock file, a lock directory, or any
  coordination primitive that spans multiple keys or persists across process
  restarts.
- **Not a replacement for a database**: This is optimistic, not pessimistic,
  concurrency control — there is no blocking lock, no lock acquisition wait,
  and no fairness guarantee across writers. Under sustained heavy contention
  a writer can still exhaust its retry budget by design (SC-003); that is
  the intended failure mode, not a defect to be engineered away by widening
  the budget in this slice.
