# Data Model: Markdown Entry Format & Confidence Labels

**Feature**: 046-markdown-format-confidence-labels | **Date**: 2026-08-18

This slice defines a rich record — an entry — and its text serialization. It builds on
045's opaque byte addressing but does not touch it: the entry is pure text/data.

## Entities

### ConfidenceLabel (value)

A constrained enumeration of exactly four values, ordered by descending trust.

| Label | Meaning | Trust rank |
|-------|---------|-----------|
| `Confirmed` | Verified working result | 1 (highest) |
| `Inferred` | Pattern from multiple observations | 2 |
| `Observed` | Single raw data point | 3 |
| `Predicted` | Proactive research (dreaming), untested | 4 (lowest) |

- **Representation**: a `Literal["Confirmed", "Inferred", "Observed", "Predicted"]` alias
  plus a `CONFIDENCE_LABELS` tuple giving the canonical order for validation and iteration.
- **Validation**: any string not equal (after whitespace-trim, case-sensitive) to one of
  the four is invalid.

### MemoryEntry (record)

An immutable pairing of one `ConfidenceLabel` with a free-form markdown body.

- **Fields**:
  - `confidence: ConfidenceLabel` — how much the agent trusts the entry.
  - `body: str` — arbitrary markdown; no schema imposed. May be empty. May contain `---`
    lines, unicode, and arbitrary whitespace.
- **Invariants**:
  - Frozen (immutable after construction).
  - `confidence` MUST be one of the four labels — enforced in `__post_init__`, raising
    `ValueError` otherwise, so a constructed entry always carries a valid label.
  - `body` is stored verbatim; no normalization.
- **Behavior**:
  - `to_dict() -> dict[str, str]` — returns `{"confidence": <label>, "body": <body>}`,
    all JSON-serializable, matching the project's result-type convention so entries flow
    through CLI formatters and `--jq` later.

## Text serialization (pure)

Deterministic, I/O-free functions in `format.py`:

- `serialize(entry: MemoryEntry) -> str` — emits
  `"---\nconfidence: {confidence}\n---\n{body}"`.
- `parse(text: str) -> MemoryEntry` — inverse of `serialize` for canonical input; recovers
  the label and the exact body.

### On-disk shape

```markdown
---
confidence: Confirmed
---
The `mp login` SA path probes us→eu→in when --region is omitted.
Verified against prod on 2026-08-18.
```

### Parse rules

1. Text MUST begin with the opening fence line `---`. Otherwise → `MemoryFormatError`.
2. Front-matter is the region between the opening fence and the first subsequent line
   equal to `---` (the closing fence). An unterminated block → `MemoryFormatError`.
3. Front-matter MUST contain exactly the key `confidence` (one `key: value` line). A
   missing `confidence` key, or any additional key → `MemoryFormatError`.
4. The `confidence` value is whitespace-trimmed, then matched case-sensitively against
   `CONFIDENCE_LABELS`. A non-matching value → `MemoryFormatError`.
5. The body is everything after the closing fence's terminating newline, taken verbatim
   (including further `---` lines, blank lines, and trailing whitespace). An empty body is
   valid.

### Round-trip invariant

- `parse(serialize(e)) == e` for every valid label and arbitrary body (FR-005). The body
  is preserved byte-for-byte.
- Full `serialize(parse(t)) == t` idempotence is not promised for non-canonical text.

## Errors

- **MemoryFormatError(ValueError)**: raised by `parse` for any malformed input (missing
  fence, unterminated block, missing/extra key, unknown label). Subclasses `ValueError` so
  existing `ValueError`-based handling still catches it, while giving callers a precise
  type to match. The message names the specific defect.

## Non-goals (owned elsewhere)

- Byte encoding + persistence of the serialized text (AIE-603 backend / AIE-608 verbs).
- Write-time size limits on the body or serialized form (AIE-605).
- Concurrency / optimistic locking (AIE-606).
- PII detection/redaction of the body (AIE-607).
- Public exposure of the label/entry types and user-facing verb shapes (AIE-608).
- Additional front-matter keys / richer metadata (future slices).
