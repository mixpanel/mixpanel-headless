---
type: regex
pattern: '\blast\s*=\s*[0-9]'
match: not_contains
target: { source: file, path: march_logins.py }
---
