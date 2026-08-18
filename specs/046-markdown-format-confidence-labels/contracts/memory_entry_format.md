# Internal Contract: MemoryEntry, ConfidenceLabel & the format module

**Feature**: 046-markdown-format-confidence-labels | **Date**: 2026-08-18

These are `_internal` contracts (not part of the public `mixpanel_headless` API surface in
this slice). They define the entry format the sibling issues build on. Signatures are the
intended shape; exact typing is finalized in code under `mypy --strict`.

## `ConfidenceLabel` (entry.py)

```python
ConfidenceLabel = Literal["Confirmed", "Inferred", "Observed", "Predicted"]

CONFIDENCE_LABELS: tuple[ConfidenceLabel, ...] = (
    "Confirmed",   # verified working result
    "Inferred",    # pattern from multiple observations
    "Observed",    # single raw data point
    "Predicted",   # dreaming's proactive research, untested
)
```

- Ordered by descending trust. `CONFIDENCE_LABELS` is the single source of truth for
  validation and iteration.

## `MemoryEntry` (entry.py)

```python
@dataclass(frozen=True)
class MemoryEntry:
    """An immutable memory note: one confidence label + free-form markdown body."""

    confidence: ConfidenceLabel
    body: str

    def __post_init__(self) -> None:
        """Reject a confidence value outside the four labels.

        Raises:
            ValueError: ``confidence`` is not one of ``CONFIDENCE_LABELS``.
        """

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable mapping ``{"confidence": ..., "body": ...}``."""
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `MemoryEntry(label, body)` | label ∈ `CONFIDENCE_LABELS` | frozen instance; `body` stored verbatim |
| `MemoryEntry("Bogus", body)` | label ∉ labels | raises `ValueError` |
| `entry.body = x` | any | raises `FrozenInstanceError` (immutability) |
| `to_dict()` | any entry | `{"confidence": label, "body": body}`, JSON-serializable |

## The `format` module (format.py)

```python
class MemoryFormatError(ValueError):
    """Raised when text cannot be parsed into a MemoryEntry."""

def serialize(entry: MemoryEntry) -> str:
    """Render ``entry`` as front-matter + body text.

    Returns:
        ``"---\nconfidence: {confidence}\n---\n{body}"``.
    """

def parse(text: str) -> MemoryEntry:
    """Parse serialized text back into a MemoryEntry.

    Raises:
        MemoryFormatError: missing opening/closing fence, unterminated
            front-matter, missing/extra front-matter key, or a confidence
            value outside the four labels.
    """
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `serialize(e)` | any valid entry | text starts with `---\nconfidence: ` fence, body appended verbatim |
| `parse(t)` | `t = serialize(e)` | returns entry equal to `e`; body byte-identical |
| `parse(t)` | body contains `---` lines | interior `---` preserved, not treated as a fence |
| `parse(t)` | body empty | returns entry with `body == ""` |
| `parse(t)` | no opening `---` fence | raises `MemoryFormatError` |
| `parse(t)` | opening fence but no closing `---` | raises `MemoryFormatError` |
| `parse(t)` | front-matter omits `confidence` | raises `MemoryFormatError` |
| `parse(t)` | front-matter has an extra key | raises `MemoryFormatError` |
| `parse(t)` | `confidence` value ∉ labels | raises `MemoryFormatError` naming the value |

### Invariants to property-test (`test_memory_format_pbt.py`)

- **Round-trip**: for every `label ∈ CONFIDENCE_LABELS` and arbitrary `body`,
  `parse(serialize(MemoryEntry(label, body))) == MemoryEntry(label, body)`.
- **Body fidelity**: the round-tripped `body` is byte-identical, including bodies that
  contain `---` lines, unicode, leading/trailing blank lines, and empty strings.
- **Label totality**: a successful `parse` always yields a `confidence ∈ CONFIDENCE_LABELS`
  and never any other value.
- **Malformed totality**: text with a corrupted/absent front-matter always raises
  `MemoryFormatError` (never returns a partial or defaulted entry).
- **Determinism**: `serialize` and `parse` are deterministic for fixed inputs.
