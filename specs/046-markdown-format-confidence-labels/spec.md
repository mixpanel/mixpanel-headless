# Feature Specification: Markdown Entry Format & Confidence Labels

**Feature Branch**: `msiebert-agent-memory` (slice `046-markdown-format-confidence-labels`; no per-feature branch)
**Created**: 2026-08-18
**Status**: Draft
**Linear**: AIE-604
**Input**: Define the Headless Memory entry format and the four confidence labels on top of the AIE-603 storage foundation.

## User Scenarios & Testing *(mandatory)*

The "user" of this slice is an AI agent (and the dreaming process that curates its
notes) reading and writing memory entries, plus the future CLI/`--jq` consumer that
renders them. The entry format is the contract those callers share.

### User Story 1 - Label a note with a confidence level and read it back (Priority: P1)

An agent records something it learned and stamps how much it trusts that knowledge —
`Confirmed`, `Inferred`, `Observed`, or `Predicted`. Later, the same agent (or the
dreaming curator) reads the note back and recovers both the label and the original
prose exactly as written.

**Why this priority**: The round-trip is the whole feature. Without a durable,
recoverable label the four-level confidence model does not exist, and every later
slice (size limits, PII, tool primitives) has nothing to serialize.

**Independent Test**: Construct an entry with each of the four labels and a body,
serialize it to text, parse the text back, and assert the recovered label and body
are identical to the originals. Fully testable with no filesystem or network.

**Acceptance Scenarios**:

1. **Given** an entry with label `Confirmed` and a markdown body, **When** it is
   serialized and then parsed, **Then** the parsed entry has label `Confirmed` and a
   byte-identical body.
2. **Given** each of the four labels in turn, **When** an entry carrying it is
   round-tripped, **Then** the label survives unchanged for all four.
3. **Given** a serialized entry, **When** it is inspected as text, **Then** it begins
   with a fenced front-matter block that names the confidence label and is followed by
   the unmodified body.

---

### User Story 2 - Free-form body, no schema imposed (Priority: P1)

The agent organizes the body however it wants — headings, lists, links, code fences,
even lines that happen to be `---`. The format layer must carry that prose verbatim
and never reinterpret, reformat, or truncate it.

**Why this priority**: The design commitment is "the agent self-directs organization;
no schema imposed up front." A format that mangles a body containing `---` or trailing
whitespace would silently corrupt memory.

**Independent Test**: Round-trip bodies containing `---` lines, leading/trailing blank
lines, unicode, and empty content, asserting the body is preserved exactly.

**Acceptance Scenarios**:

1. **Given** a body whose text contains one or more `---` lines, **When** the entry is
   round-tripped, **Then** the body — including those `---` lines — is preserved
   exactly and is not mistaken for a front-matter fence.
2. **Given** an empty body, **When** the entry is round-tripped, **Then** the parsed
   body is empty and the label is preserved.
3. **Given** a body with unicode and trailing whitespace, **When** round-tripped,
   **Then** the body is byte-identical.

---

### User Story 3 - Reject malformed or unlabeled input (Priority: P2)

When the dreaming curator or a hand-edit produces text that is missing the front-matter
block, missing the `confidence` key, or naming a label that is not one of the four,
parsing fails loudly rather than guessing a default.

**Why this priority**: "Explicit over implicit." A silently-defaulted label would let
untrusted `Predicted` research masquerade as `Confirmed` fact. The failure must be
unambiguous so callers can surface it.

**Independent Test**: Feed the parser text with no front-matter, an empty confidence
value, and an unknown label; assert each raises a clear, typed error naming the problem.

**Acceptance Scenarios**:

1. **Given** text with no front-matter fence, **When** parsed, **Then** parsing raises
   an error identifying the missing front-matter.
2. **Given** front-matter whose `confidence` value is not one of the four labels,
   **When** parsed, **Then** parsing raises an error naming the invalid label.
3. **Given** front-matter that omits the `confidence` key, **When** parsed, **Then**
   parsing raises an error identifying the missing label.

---

### User Story 4 - Serialize an entry for CLI / `--jq` consumption (Priority: P3)

A downstream renderer turns an entry into a JSON-serializable mapping so it can flow
through the existing CLI formatters and `--jq` filter, exactly as other result types do.

**Why this priority**: Enables later CLI surfacing without reopening this slice, but no
CLI command consumes it yet in this milestone.

**Independent Test**: Call the entry's dict conversion and assert the result is a plain
mapping of JSON-serializable values containing the label and body.

**Acceptance Scenarios**:

1. **Given** any entry, **When** converted to a dictionary, **Then** the result
   contains the confidence label and the body as JSON-serializable values.
2. **Given** the dictionary, **When** serialized as JSON, **Then** serialization
   succeeds without custom encoders.

---

### Edge Cases

- A body that itself starts with `---` on its first line must not be swallowed into the
  front-matter block — the front-matter is exactly the leading fenced region.
- A body containing the exact three-character line `---` in its interior is ordinary
  content, not a fence.
- Extra keys inside the front-matter block: rejected (the block carries only
  `confidence` in this slice) — surfaced explicitly rather than ignored.
- Confidence value with surrounding whitespace or differing case: see Assumptions for
  the canonicalization rule; anything not resolving to one of the four is rejected.
- An empty body is valid; a missing/blank confidence label is not.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The format MUST define exactly four confidence labels, ordered by
  descending trust: `Confirmed` (verified working result), `Inferred` (pattern from
  multiple observations), `Observed` (single raw data point), `Predicted` (proactive
  research, untested).
- **FR-002**: A memory entry MUST consist of exactly one confidence label plus a
  free-form markdown body on which no structural schema is imposed.
- **FR-003**: The system MUST serialize an entry to text as a leading front-matter block
  (delimited by `---` fences) carrying only the confidence label, followed by the
  verbatim body.
- **FR-004**: The system MUST parse serialized text back into an entry, recovering the
  label and the exact original body.
- **FR-005**: Serialize→parse MUST be a stable round-trip: parsing a serialized entry
  yields an entry equal to the original for every valid label and arbitrary body,
  including bodies that contain `---` lines, unicode, blank lines, and empty content.
- **FR-006**: Parsing MUST reject, with a clear typed error, text that lacks the
  front-matter block, omits the confidence key, or names a confidence value outside the
  four labels. No default label may be substituted.
- **FR-007**: The confidence label MUST be represented as a constrained value type so
  that an invalid label is a type-level and runtime error, not a free string.
- **FR-008**: The entry type MUST be immutable once constructed.
- **FR-009**: The entry MUST expose a conversion to a JSON-serializable mapping
  containing the label and body, consistent with the project's existing result-type
  convention.
- **FR-010**: The pure serialize/parse logic MUST perform no filesystem or network I/O,
  so it can be property- and mutation-tested in isolation (mirroring the foundation's
  pure/IO split).
- **FR-011**: The format layer MUST NOT read or write the backend byte store, enforce
  size limits, perform locking, or scan for PII — those belong to sibling slices.

### Key Entities *(include if feature involves data)*

- **Confidence Label**: A constrained enumeration of exactly four ordered values
  (`Confirmed`, `Inferred`, `Observed`, `Predicted`) expressing how much the agent
  trusts an entry.
- **Memory Entry**: An immutable pairing of one Confidence Label with a free-form
  markdown body. Serializes to front-matter-plus-body text and converts to a
  JSON-serializable mapping.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of valid (label, body) pairs survive a serialize→parse round-trip
  with byte-identical bodies and identical labels, verified across randomized inputs.
- **SC-002**: 100% of the four confidence labels are recoverable after round-trip;
  no other value is ever produced by a successful parse.
- **SC-003**: 100% of malformed inputs (missing front-matter, missing key, unknown
  label) produce an explicit error rather than a silently-defaulted or partial entry.
- **SC-004**: Bodies containing `---` lines round-trip without corruption in 100% of
  randomized cases.
- **SC-005**: The entry converts to a mapping that serializes to JSON with no custom
  encoder in 100% of cases.
- **SC-006**: Automated test coverage for the slice is ≥90%, and mutation score on the
  pure serialize/parse module is ≥80%.

## Assumptions

- The confidence value in front-matter is matched case-sensitively against the four
  canonical labels; leading/trailing whitespace around the value is trimmed before
  matching, but any value that does not then equal one of the four labels is rejected.
  (Chosen for determinism and to keep the parser stdlib-only and small.)
- The front-matter block carries only the `confidence` key in this slice; additional
  keys are rejected rather than ignored, keeping the surface minimal until a later slice
  needs more metadata.
- Both the label type and the entry type live in the internal memory package for now
  (not the public type surface); public exposure is deferred to the tool-primitives
  slice (AIE-608).
- The entry format is stdlib-only: no YAML library is introduced; a small constrained
  reader handles the label-only front-matter.
- The backend byte store from AIE-603 is unchanged and is not touched by this slice.
