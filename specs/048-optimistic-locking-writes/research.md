# Research: Optimistic-Locking Concurrency for Memory Writes

**Feature**: 048-optimistic-locking-writes | **Date**: 2026-08-21

All decisions below are locked for this slice (AIE-606). No `NEEDS
CLARIFICATION` markers remain — the two open questions this slice started
with (retry policy, hashing granularity) are locked, not open to revision
here or later.

## D1 — Retry policy: bounded 5 total attempts, full-jitter backoff (locked)

- **Decision**: The retrying helper attempts a guarded write at most 5 times
  total (the first attempt plus up to 4 retries). Between a detected
  conflict and the next attempt it sleeps a randomized delay drawn uniformly
  from `[0, base)` ("full jitter"), with `base` on the order of 10-20 ms.
  Exhausting the budget raises `MemoryConflictRetriesExhaustedError`.
- **Rationale**: Memory writes are small, local, single-machine file
  operations contending only with other in-process or sibling-process
  writers on the same host — this is not a distributed system with
  unbounded contention, so a small fixed cap is enough to absorb realistic
  races (an agent session and a background curator landing within
  milliseconds of each other) without masking a genuinely stuck or
  misbehaving caller behind an unbounded retry loop. Full jitter (as
  opposed to fixed or linear backoff) is the standard fix for the
  "synchronized retry storm" failure mode: if two colliding writers both
  retried after a fixed delay, they would very likely collide again on the
  same cadence; randomizing the delay independently for each writer breaks
  that resonance with no coordination needed between them. A base of
  10-20 ms keeps the worst-case total retry latency (5 attempts x tens of
  ms) well under 100 ms, imperceptible against typical filesystem write
  latency and any tool-call round-trip that will eventually wrap this
  primitive (AIE-608).
- **Alternatives rejected**: Unbounded retry-until-success — violates
  SC-003's requirement that the helper never loop indefinitely, and would
  let a genuinely pathological contention pattern (e.g. a caller with a
  buggy mutation that always collides) hang a caller forever with no
  signal. A configurable-per-call attempt count — deferred; FR-005 locks
  this to a single shared constant for this slice so behavior cannot drift
  between callers, matching the AIE-605 precedent of one shared
  `MAX_MEMORY_WRITE_BYTES` rather than a per-call size limit. Exponential
  backoff — unnecessary complexity for a bound this small (5 attempts);
  full jitter around a constant base is simpler to reason about and to
  test (the PBT invariant only needs to assert "delay is drawn from
  `[0, base)`", not a growing sequence of ranges).

## D2 — Hashing granularity: whole-file `sha256`, with a distinct absence sentinel (locked)

- **Decision**: The content fingerprint of a key is `hashlib.sha256(data)`
  over the entire byte content read from (or about to be written to) that
  key. A key with no file at all is fingerprinted as a distinct sentinel
  value — not `sha256(b"")` — so "no file exists" and "a file exists and is
  empty" are never confused.
- **Rationale**: FR-008 requires the fingerprint be computed over the whole
  file, not a section or line range — a memory note produced by
  `format.serialize(...)` is a single small blob (bounded to 8 KiB by
  AIE-605) with no internally-addressable sections the write path needs to
  reason about independently; hashing the whole thing is both simpler and
  strictly more correct than any partial scheme, since a partial hash could
  miss a change outside the hashed region and silently permit a lost
  update. `hashlib.sha256` is standard library, already the project's
  posture of "no new third-party dependency" for pure logic modules
  (`limits.py`, `format.py`), and its 256-bit output makes an accidental
  collision between two different real note contents astronomically
  unlikely — collision resistance, not speed, is what a lock fingerprint
  needs. The distinct absence sentinel exists because FR-009 requires a
  create-vs-conflicting-create race (two writers both reading "no file
  yet") to be detected the same way as a modify-vs-conflicting-modify race;
  if absence fingerprinted to `sha256(b"")`, a writer that read an actually
  *existing* empty file would be indistinguishable from a writer that read
  *no file at all*, silently defeating FR-009's detection requirement for
  a real (if unusual) edge case (a key holding a legitimately empty note).
- **Alternatives rejected**: `mtime`/`st_size`-based change detection
  (stat-based optimistic concurrency, as some databases use) — coarser and
  platform-dependent (mtime resolution varies by filesystem; two writes
  within the same tick can be indistinguishable), and it would require a
  second filesystem `stat` call the whole-file hash does not need since the
  bytes are already resident in memory on both the read and write sides.
  Section- or line-level hashing — no such internal structure exists in a
  memory note's serialized form (`format.py`'s output is front-matter plus
  an opaque verbatim body); inventing one purely to make the lock finer-
  grained would add complexity with no caller-visible benefit at today's
  8 KiB scale. Using `sha256(b"")` for absence (no sentinel) — collapses
  two distinguishable states into one, defeating FR-009 as above.

## D3 — Error taxonomy: a common base, `MemoryLockingError`, with two sibling concrete errors

- **Decision**: Introduce a common base exception, `MemoryLockingError`,
  and two concrete errors that both subclass it directly:
  `MemoryConflictError` (raised by the single-attempt guarded write on a
  fingerprint mismatch) and `MemoryConflictRetriesExhaustedError` (raised
  by the retrying helper when every attempt in the budget raises
  `MemoryConflictError`). Neither concrete error subclasses the other.
  `MemoryLockingError` itself subclasses `Exception` directly — not
  `ValueError`, not `RuntimeError`, and not `MemorySizeLimitError` — so the
  locking hierarchy is independent of AIE-605's size-guard hierarchy at
  every level. All three live in the new `locking.py` module, mirroring
  `MemorySizeLimitError`'s home in `limits.py`.
- **Rationale**: FR-003, FR-007, and FR-010 each require type-level
  distinguishability with no string-matching: a caller must be able to
  `except MemoryConflictError` alone (opting out of retry, FR-012),
  `except MemoryConflictRetriesExhaustedError` alone (the retrying helper's
  terminal failure), or `except MemorySizeLimitError` alone (an orthogonal,
  AIE-605 failure mode that must never be conflated with either concurrency
  error per FR-010). Making the two concrete errors direct siblings under
  `MemoryLockingError` — rather than one subclassing the other — satisfies
  the spec's User Story 2 Scenario 3 requirement that a caller be able to
  catch *only* the per-attempt error without incidentally also matching the
  retries-exhausted error via a shared parent in a broad `except`. The
  common base earns its place because it gives a library consumer who
  wants "any locking failure" (as opposed to a size violation) a single
  type to catch — `except MemoryLockingError` — without having to
  enumerate both concrete types or fall back to a bare `except Exception`.
  `MemoryLockingError` subclasses plain `Exception` (not `ValueError`) so
  that catching it can never be confused with the unrelated
  `MemorySizeLimitError`/`ValueError` hierarchy AIE-605 established;
  checking `src/mixpanel_headless/_internal/memory/limits.py` confirms
  `MemorySizeLimitError` has no memory-specific base of its own to align
  with — it is a bare `ValueError` — so there is no existing base class for
  `MemoryLockingError` to join instead of `Exception`.
- **Alternatives rejected**: A single error type distinguished only by a
  field (e.g. `MemoryConflictError(exhausted: bool)`) — reintroduces exactly
  the "inspect a field instead of the type" pattern FR-007 explicitly rules
  out ("distinguishable ... by type alone, without string-matching a
  message" — the spirit of that requirement extends to not requiring field
  inspection either, since the whole point is a caller can `except` the
  specific failure it cares about). Subclassing `MemoryConflictError` under
  `MemoryConflictRetriesExhaustedError` — would make `except
  MemoryConflictError` accidentally also catch the exhaustion case,
  defeating FR-012's "without ever encountering the retries-exhausted
  error" guarantee for a caller that opts into the single-attempt primitive
  and later composes it with its own retry loop that only expects the
  per-attempt error. No common base at all (two fully independent types) —
  rejected because it leaves a consumer who wants "any locking failure"
  with no single type to catch, forcing either a tuple `except
  (MemoryConflictError, MemoryConflictRetriesExhaustedError)` at every call
  site that wants the umbrella behavior, or a bare `except Exception` that
  over-catches; a lightweight shared base removes that friction at zero
  cost to the sibling-separation guarantee FR-012 requires.

## D4 — Absence sentinel: a private, non-`bytes` fingerprint value

- **Decision**: The fingerprint type is a small internal value that is
  either "a sha256 digest of existing content" or a single shared "absent"
  sentinel, represented as a value that cannot collide with any possible
  digest output (e.g. a distinguished sentinel object or an `Optional`-style
  `None`-for-absent convention over an otherwise-`bytes`-typed digest).
  The exact representation is finalized in `data-model.md`; the constraint
  locked here is only the *property* — absence must be representable and
  provably distinct from every possible content digest, by construction
  (typed, not by convention over the same type as a digest that happens
  never to collide).
- **Rationale**: A sentinel implemented as "a probably-never-produced
  digest string" (e.g. an all-zero hash) is a latent bug: `sha256` is a
  total function over the input space and nothing prevents a byte string
  from someday hashing to that specific chosen sentinel value in a
  future audit, an adversarial input, or (unlikely but non-zero) an
  accidental collision. Using a distinguishable type-level sentinel removes
  the question entirely rather than relying on the sentinel's practical
  improbability.
- **Alternatives rejected**: Sentinel as a special digest value — rejected
  for the reason above (D2 also touches this from the "why a sentinel at
  all" angle; D4 fixes *how* it must be represented).

## D5 — Module split: `locking.py` separate from `backend.py`, mirroring `limits.py`

- **Decision**: All pure logic — the fingerprint computation, the fingerprint
  comparison, the two error types, the retry-policy constants, and the
  backoff-delay computation — lives in a new module,
  `src/mixpanel_headless/_internal/memory/locking.py`, with zero filesystem
  or network I/O. `backend.py` gains only the code that reads/writes bytes
  and calls into `locking.py`'s pure functions around those I/O calls.
- **Rationale**: This is the exact discipline `limits.py` established for
  AIE-605 and the plan explicitly mirrors it: a small, I/O-free module is
  independently unit-, property-, and mutation-testable (≥80% mutmut bar)
  in complete isolation from any real filesystem, while the I/O-bearing
  orchestration in `backend.py` stays a thin, easily-read composition of
  already-tested pure pieces (per-file size check, then fingerprint check,
  then atomic write). Following the established split also means a future
  reader who has already internalized `limits.py`'s shape (constant +
  typed error + pure check function) recognizes `locking.py`'s shape
  immediately.
- **Alternatives rejected**: Extending `limits.py` itself with locking
  logic — conflates two independently-evolving, independently-testable
  concerns (a static byte-count ceiling vs. a stateful-per-attempt
  fingerprint comparison and retry/backoff policy) in one module and one
  `__all__`, the same reasoning `limits.py`'s own research.md (047, D5)
  used to keep the exception out of `format.py`. Putting the retry loop
  directly in `backend.py` — would mix the pure jittered-delay computation
  (a unit/PBT/mutmut target) into the same method as real `time.sleep`
  calls and real file I/O, losing the isolated testability the constitution
  check in 047 called out as a reason to split.

## D6 — Guard ordering per attempt: fingerprint check, then size check, then atomic write

- **Decision**: Within a single guarded-write attempt, the order is: (1)
  compute the current fingerprint at the target key and compare it against
  the fingerprint captured at read time — raise `MemoryConflictError` on
  mismatch; (2) run the unchanged AIE-605 `check_write_size(data)` guard —
  raise `MemorySizeLimitError` on an oversized payload; (3) call
  `atomic_write_bytes` (via the existing `write()` path) to commit. All
  three steps for one attempt happen without any intervening `time.sleep`;
  jittered backoff only happens *between* attempts, after a conflict is
  detected and before the next attempt's fingerprint re-check begins.
- **Rationale**: FR-010 requires the size guard "apply, unchanged and
  independently, to every attempt" and never be "treated as, retried as, or
  reported as a lock conflict" — checking the fingerprint first means a
  stale-but-correctly-sized write is correctly identified as a conflict
  (not a size problem) and a fresh-but-oversized write is correctly
  identified as a size problem (not a conflict), because each guard only
  ever sees the failure mode it is responsible for. Running both checks
  before any byte is committed preserves the same atomicity-by-construction
  property AIE-605's D6 established for the size guard alone: a raised
  error at either checkpoint is a strict no-op with respect to disk state,
  since neither checkpoint performs I/O beyond the read already required to
  compute the current fingerprint.
- **Alternatives rejected**: Size check before fingerprint check — would
  mean an oversized *and* stale write raises `MemorySizeLimitError` even
  though the more fundamental problem (the caller's premise about current
  content is already wrong) is the conflict; ordering fingerprint-first
  means the conflict is surfaced whenever one exists, regardless of the
  new content's size, which is the more actionable signal for a caller
  deciding how to react (re-read-and-retry is only useful information once
  you know whether staleness, not size, was the failure). Checking size and
  fingerprint in a single combined pass — no benefit; they are independent,
  cheap, in-memory checks with no shared computation to fuse.

## D7 — Caller-mutation purity: a documented contract, not a runtime-enforced one

- **Decision**: The retrying helper's contract requires the caller-supplied
  mutation function be safe to invoke more than once against different
  "current content" inputs, producing only its return value as an effect
  (no side effects that would be wrong to repeat, such as sending a
  network request or mutating shared external state). This is documented
  in the helper's docstring and in `quickstart.md`; the helper does not
  attempt to detect or enforce it at runtime.
- **Rationale**: Enforcing purity at runtime is not mechanically possible in
  Python without an intrusive sandboxing scheme wildly disproportionate to
  this slice's scope, and the project's own precedent (`ConfigManager._mutate`
  in `config.py`) already relies on a documented convention — "the body
  mutates the yielded dict in place" — rather than a runtime check, for an
  analogous read-modify-write contract. A mutation function for memory
  writes is expected to be a small, pure transform over the note's text
  (add a line, update a confidence label, append a fact) — exactly the
  shape that is naturally idempotent-to-recompute and safe to re-run.
- **Alternatives rejected**: Requiring the mutation to be provided as
  serializable data plus a pure combinator applied by the helper (making
  re-invocation trivially safe by construction) — over-engineered for this
  slice's scope and inconsistent with how the rest of the codebase expresses
  read-modify-write callbacks (`ConfigManager._mutate`'s
  `Generator[dict[str, Any], None, None]` contextmanager also trusts its
  caller's body). Detecting side effects via monkeypatching or tracing in
  tests only — worth having as a test-hygiene practice, but not a
  substitute for stating the contract plainly, so it is not treated as a
  design decision in its own right here.
