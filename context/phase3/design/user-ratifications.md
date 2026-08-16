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

## 2026-08-16 — B7 arbiter escalation (Caution #13), user ruling: FIX

**default_account_name org-ordering (result-affecting site)** — user REJECTED the
exclusion ruling and directed the proper fix: `MeResponse.organizations` parses into an
insertion-order-preserving Map sourced from the lossless JSON layer, so the first-org
pick matches Python dict insertion order exactly. Executed as an early B8 task
(supersedes the B7-ARB-A R2 exclusion; the fuzz exclusion is removed once the fix
lands). Rationale: unlike Discrepancy #9 (diagnostic ordering), this site changes a
user-visible output.
