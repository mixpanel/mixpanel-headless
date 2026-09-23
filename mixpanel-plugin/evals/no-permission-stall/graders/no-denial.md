---
type: regex
pattern: 'Permission to use \w+[^\n]{0,2000}?has been denied|permission check failed'
flags: i
match: not_contains
target: trace
---
