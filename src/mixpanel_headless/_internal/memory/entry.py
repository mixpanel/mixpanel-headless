"""The Headless Memory entry record and its confidence labels (internal).

An entry pairs one confidence label with a free-form markdown body. This module
defines the constrained label set and the immutable ``MemoryEntry`` record; the
text serialization lives in the sibling
:mod:`~mixpanel_headless._internal.memory.format` module. Nothing here touches
the byte store, size limits, concurrency, or PII — those are separate layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["CONFIDENCE_LABELS", "ConfidenceLabel", "MemoryEntry"]

ConfidenceLabel = Literal["Confirmed", "Inferred", "Observed", "Predicted"]
"""How much an agent trusts a memory entry, ordered by descending trust.

+-----------+------------------------------------------------+
| Value     | Meaning                                        |
+===========+================================================+
| Confirmed | Verified working result                        |
+-----------+------------------------------------------------+
| Inferred  | Pattern from multiple observations             |
+-----------+------------------------------------------------+
| Observed  | Single raw data point                          |
+-----------+------------------------------------------------+
| Predicted | Proactive research (dreaming), untested        |
+-----------+------------------------------------------------+
"""

CONFIDENCE_LABELS: tuple[ConfidenceLabel, ...] = (
    "Confirmed",
    "Inferred",
    "Observed",
    "Predicted",
)
"""The four confidence labels in descending-trust order.

Single source of truth for validating and iterating labels; the parser and
``MemoryEntry`` both check membership against this tuple.
"""


@dataclass(frozen=True)
class MemoryEntry:
    """An immutable memory note: one confidence label plus a free-form body.

    The body is stored verbatim — no markdown schema is imposed. The label is
    validated at construction so a constructed entry always carries one of the
    four :data:`CONFIDENCE_LABELS`.

    Args:
        confidence: The entry's confidence label.
        body: Free-form markdown body. May be empty and may contain any content,
            including lines equal to ``---``.

    Raises:
        ValueError: ``confidence`` is not one of :data:`CONFIDENCE_LABELS`.

    Example:
        ```python
        entry = MemoryEntry(confidence="Confirmed", body="verified fact")
        entry.to_dict()  # {"confidence": "Confirmed", "body": "verified fact"}
        ```
    """

    confidence: ConfidenceLabel
    body: str

    def __post_init__(self) -> None:
        """Reject a confidence value outside the four labels.

        Raises:
            ValueError: ``confidence`` is not one of :data:`CONFIDENCE_LABELS`.
        """
        if self.confidence not in CONFIDENCE_LABELS:
            raise ValueError(
                f"invalid confidence label {self.confidence!r}; "
                f"expected one of {CONFIDENCE_LABELS}"
            )

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable mapping of the entry.

        Returns:
            ``{"confidence": <label>, "body": <body>}`` — both values are
            strings, so the mapping serializes to JSON with no custom encoder.

        Example:
            ```python
            MemoryEntry(confidence="Inferred", body="x").to_dict()
            # {"confidence": "Inferred", "body": "x"}
            ```
        """
        return {"confidence": self.confidence, "body": self.body}
