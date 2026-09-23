---
type: llm
focus: { source: file, path: march_logins.py }
---

The goal: count Login events in March 2026 for users with at least 3 Purchase events in March 2026 as a whole.
PASS if the "3 or more purchases" condition is evaluated over the whole month of March 2026. Two acceptable forms: (a) a `FrequencyFilter` on Purchase with a query `unit="month"` and `from_date="2026-03-01"`, `to_date="2026-03-31"`; or (b) a cohort or behavior criterion that requires at least 3 Purchase events between 2026-03-01 and 2026-03-31, used to filter a Login query over the same dates.
FAIL if it uses a `FrequencyFilter` with the default daily unit (no `unit="month"`), if it uses `last=` for the window, or if the March dates are missing.
