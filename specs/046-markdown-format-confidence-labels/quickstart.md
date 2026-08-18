# Quickstart: Markdown Entry Format & Confidence Labels

**Feature**: 046-markdown-format-confidence-labels | **Date**: 2026-08-18

Internal-only in this slice — there is no public API or CLI yet (that is AIE-608). This
shows how a sibling feature or a test builds, serializes, and parses an entry. The format
layer is pure text: encoding to bytes and persistence belong to the backend (AIE-603).

## Build, serialize, and parse an entry

```python
from mixpanel_headless._internal.memory.entry import MemoryEntry
from mixpanel_headless._internal.memory.format import serialize, parse

entry = MemoryEntry(
    confidence="Confirmed",
    body="The `mp login` SA path probes us→eu→in when --region is omitted.\n",
)

text = serialize(entry)
# ---
# confidence: Confirmed
# ---
# The `mp login` SA path probes us→eu→in when --region is omitted.

assert parse(text) == entry          # stable round-trip
assert parse(text).body == entry.body  # byte-identical body
```

## Confidence labels

```python
from mixpanel_headless._internal.memory.entry import CONFIDENCE_LABELS

CONFIDENCE_LABELS
# ("Confirmed", "Inferred", "Observed", "Predicted")  # descending trust

MemoryEntry(confidence="Predicted", body="untested hunch")  # ok
```

## Bodies that contain `---` survive

```python
entry = MemoryEntry(confidence="Observed", body="before\n---\nafter")
assert parse(serialize(entry)).body == "before\n---\nafter"
```

## Malformed input is rejected loudly

```python
from mixpanel_headless._internal.memory.format import parse, MemoryFormatError
import pytest

with pytest.raises(MemoryFormatError):
    parse("no front matter here")               # missing opening fence

with pytest.raises(MemoryFormatError):
    parse("---\ntitle: x\n---\nbody")           # missing `confidence` key

with pytest.raises(MemoryFormatError):
    parse("---\nconfidence: Certain\n---\nbody") # unknown label
```

## Convert to a dict for CLI / `--jq`

```python
MemoryEntry(confidence="Inferred", body="pattern across runs").to_dict()
# {"confidence": "Inferred", "body": "pattern across runs"}
```

## Verify the DoD locally

```bash
just test -k "memory_entry or memory_format"   # unit tests for this slice
just test-pbt                                   # Hypothesis property tests (incl. format round-trip)
just typecheck                                  # mypy --strict
just check                                       # full gate (lint + fmt + typecheck + cov + build)
just mutate-check                                # mutmut >= 80% on the new pure modules
```
