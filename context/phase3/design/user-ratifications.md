# User ratifications (Phase 3)

## 2026-08-15 — B2 arbiter human-calls, both RATIFIED

1. **Playbook Discrepancy #8 (contract scope = declared annotation)** — RATIFIED.
   The cross-language contract covers only inputs within a validator's declared
   parameter annotation; out-of-annotation behavior (CPython accidental raises) is
   unspecified and NOT bug-compatible. Binding on all batches.
2. **Playbook Discrepancy #9 (S4 warning emission order)** — RATIFIED.
   Order-insensitive comparison accepted for the S4 chart-type warning pair on
   integer-like unknown keys (JS integer-key reordering); content equality still
   strict. Scoped to this warning pair only; no ordered-map API change.
