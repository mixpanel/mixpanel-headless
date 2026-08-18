# Research: Markdown Entry Format & Confidence Labels

**Feature**: 046-markdown-format-confidence-labels | **Date**: 2026-08-18

The two genuinely-forking decisions (label carrier; type placement) were resolved
before drafting. This document records every design decision and the rejected
alternatives so the sibling issues inherit the reasoning. No `NEEDS CLARIFICATION`
markers remain.

## D1 — Label carried in a leading `---` front-matter block

- **Decision**: Serialize an entry as a leading front-matter block delimited by `---`
  fences carrying only `confidence: <label>`, then the verbatim body:
  `---\nconfidence: <label>\n---\n<body>`.
- **Rationale**: The confidence label must be reliably parseable by both the agent and
  the dreaming curator while the body stays free-form ("no schema imposed"). A fenced
  front-matter block cleanly separates the one machine-readable field from arbitrary
  prose and matches the widely-understood markdown front-matter convention. It is
  robust against bodies that contain `---` because only the *leading* fenced region is
  interpreted.
- **Alternatives rejected**: An inline marker line (`**Confidence:** X`) — parseable but
  fragile and entangled with the body's own markdown; a label stored only off-disk on
  the result type — loses durability, a re-read cannot recover the label.

## D2 — Types live internal (`_internal/memory/`), not the public surface

- **Decision**: `ConfidenceLabel` and `MemoryEntry` live in `_internal/memory/entry.py`,
  not the public `_literal_types.py` / `types.py`.
- **Rationale**: Memory is still an internal system in this milestone. Public exposure of
  the label + entry types should land with the tool primitives (AIE-608) that actually
  give callers a reason to import them. Keeping them internal avoids committing a public
  surface before its consumers exist.
- **Alternatives rejected**: The ticket's literal anchor (`_literal_types.py` +
  `types.py`) — correct eventual home, but premature. The idioms from those files are
  still followed (Literal alias; frozen dataclass + `to_dict()`), just in the internal
  package.

## D3 — Stdlib-only front-matter reader (no PyYAML)

- **Decision**: Hand-roll a small, constrained front-matter reader in the pure `format`
  module. No YAML library is added; the project has no YAML dependency today and this
  slice does not justify one.
- **Rationale**: The front-matter surface is exactly one known key (`confidence`). A full
  YAML parser is far more machinery — and attack surface — than a single-key reader
  needs. Staying stdlib-only keeps the module a clean, fast PBT/mutmut target and matches
  045's "standard library only" ethos.
- **Alternatives rejected**: PyYAML / ruamel — a new core dependency for one label;
  `tomllib` — TOML front-matter is non-idiomatic for markdown and would still be
  over-general for a single key.

## D4 — Parse rejects missing/unknown labels; never defaults

- **Decision**: `parse` raises a typed `MemoryFormatError` when the text lacks the
  opening/closing fence, omits the `confidence` key, carries any extra front-matter key,
  or names a value outside the four labels. No default label is ever substituted.
- **Rationale**: "Explicit over implicit." A silently-defaulted label would let untested
  `Predicted` research masquerade as `Confirmed` fact — a correctness and trust hazard.
  Failing loudly lets the caller (dreaming, or a future CLI) surface the problem.
- **Alternatives rejected**: Defaulting an absent label to `Observed` (or any value) —
  hides corruption; tolerating unknown labels as free strings — defeats the constrained
  `Literal`.

## D5 — Round-trip contract: `parse(serialize(e)) == e`, body byte-exact

- **Decision**: Guarantee `parse(serialize(e)) == e` for every valid label and arbitrary
  body, with the body preserved byte-for-byte (including interior `---` lines, unicode,
  blank lines, trailing whitespace, and empty content). Full `serialize(parse(t)) == t`
  idempotence is NOT promised for arbitrary/non-canonical text — only the parse∘serialize
  direction the spec requires (FR-005).
- **Rationale**: The entry object is the source of truth; a lossless round-trip from it is
  what callers rely on. Demanding idempotence on arbitrary hand-written text would force
  canonicalization rules the "free-form body" principle forbids.
- **Implementation note**: `serialize` emits `---\nconfidence: {label}\n---\n{body}`.
  `parse` strips the opening `---\n`, consumes front-matter lines up to the first line
  equal to `---`, and takes everything after that closing fence's newline as the body via
  index arithmetic (not split/join) so trailing-newline fidelity is preserved.

## D6 — Label value canonicalization: trim, then case-sensitive exact match

- **Decision**: The `confidence` value is stripped of surrounding whitespace, then matched
  case-sensitively against the four canonical labels; anything that does not then equal a
  label is rejected. `MemoryEntry` also validates its label in `__post_init__` so an entry
  always carries a valid label regardless of how it was constructed.
- **Rationale**: Determinism with the smallest possible surface. Whitespace-trim tolerates
  benign formatting; case-sensitivity keeps the canonical forms (`Confirmed`, not
  `confirmed`) the single source of truth and keeps the validator trivial to reason about
  under mutation testing.
- **Alternatives rejected**: Case-insensitive / title-casing coercion — invites drift and
  ambiguous canonical forms; no trim — brittle against a stray trailing space.

## D7 — Testing strategy for the DoD

- **Decision**: `format.py` (serialize/parse) and `entry.py` (label set + frozen entry +
  `to_dict`) are pure and I/O-free. Hypothesis PBT (`test_memory_format_pbt.py`) asserts
  the round-trip on `(label, body)` pairs drawn from all four labels and adversarial
  bodies (containing `---`, empty, unicode, trailing whitespace), plus the invariant that
  malformed inputs always raise. mutmut targets both pure modules. Example-based unit
  tests cover the specific malformed-input branches and `to_dict` shape.
- **Rationale**: The ≥80% mutmut bar is tractable because the whole slice is I/O-free.
  Matches the project's `_pbt` convention and 045's pure-module discipline.
- **Alternatives rejected**: Relying on example-based tests alone — round-trip stability
  over arbitrary bodies is exactly the property Hypothesis is built to stress.

## Reused repo anchors (confirmed present)

- `types.py`: frozen `@dataclass` + `to_dict()` returning JSON-serializable values — the
  entry follows this idiom.
- `_literal_types.py`: `Literal` alias idiom (e.g. `TimeUnit`) — `ConfidenceLabel`
  mirrors it, in the internal package.
- 045 `paths.py` / `backend.py`: the pure-vs-IO split and `_pbt`/mutmut targeting pattern.
- Business Context (`get_business_context` / two-scope capped markdown): closest existing
  precedent for markdown-with-metadata, informing the front-matter choice.
