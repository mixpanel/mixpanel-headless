---
type: regex
pattern: 'retention_count'
match: not_contains
target: { source: file, path: retention_counts.py }
---
