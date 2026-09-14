# Quickstart: alert-machine

**Feature**: 046-alert-machine
**Audience**: New users exploring the alert-machine skill; reviewers smoke-testing before merge.

This walkthrough exercises every user story (P1–P3) from spec.md. Treat it as the merge-gate recipe. The skill itself runs inside Claude Code; the artifacts it produces are standalone `.py` scripts you run yourself.

---

## Story 1 (P1) — Generate a working baseline anomaly detector

### 1.1 Ask in conversation

> "Watch daily signups in my project and page me when they drop abnormally."

The skill:
1. Grounds in context — `ws.get_business_context_chain()`, else a supplied `.md`, else asks.
2. Validates the metric — confirms the signup event exists via `ws.events()` / `ws.top_events()`; if the name is off, it offers the closest real event names.
3. Clarifies intent — confirms the alert shape is "drop" (baseline family fits a flat/non-seasonal series).
4. Profiles the series — pulls it via `Workspace.query(..., mode="timeseries")` and reads length / trend / seasonality / gaps.
5. Routes — flat, non-seasonal series → **baseline** recipe (IsolationForest or robust z-score).
6. Generates — writes a single `signups_drop_alert.py`.

### 1.2 Inspect the generated script

The file follows the canonical generated-script shape (spec.md § Canonical generated-script shape):

```python
"""Daily-signups drop alert — baseline IsolationForest. CI/agent-ready.

Why this recipe: the signup series is flat and non-seasonal over the window,
so a baseline outlier detector fits. (Seasonal series would route elsewhere.)

How to run:
  pip install mixpanel_headless scikit-learn
  python signups_drop_alert.py
  echo $?    # 0 = clean recently, 1 = recent anomaly, 2 = no data
"""
# === CREDENTIALS — env-first (shell env > sibling .env > inline placeholders) ===
# === WHAT TO WATCH ============================================================
METRIC = "Sign Up Completed"
MATH = "unique"
MATH_PROPERTY = None
FROM_DATE = "2026-01-01"
TO_DATE = "2026-06-28"
UNIT = "day"
# === DETECTOR KNOBS ===========================================================
RECENT_DAYS = 2
RANDOM_STATE = 42
```

### 1.3 Run it

```bash
pip install mixpanel_headless scikit-learn
python signups_drop_alert.py
echo $?
```

**Expected stdout** (excerpt):
```
================================================================
  Metric : Sign Up Completed (unique)
  Window : 2026-01-01 -> 2026-06-28  (179 days)
  Model  : IsolationForest(contamination=0.06)
  Found  : 4 anomalous day(s)
================================================================
  2026-06-27  DROP  value=    1,204.00  expected~    3,310.00  (-2,106.00, z=-3.2)
----------------------------------------------------------------
  *** RECENT ANOMALY in last 2 day(s): 2026-06-27 -> exit 1 ***
```

`echo $?` prints `1` (a recent drop fired). A clean window prints `0`; an empty query prints `2`.

### 1.4 Determinism check (merge gate)

```bash
python signups_drop_alert.py > /tmp/run1.txt; echo "exit=$?"
python signups_drop_alert.py > /tmp/run2.txt; echo "exit=$?"
diff /tmp/run1.txt /tmp/run2.txt && echo "DETERMINISTIC" || echo "NON-DETERMINISTIC"
```

Both runs must print the same exit code and `DETERMINISTIC`.

---

## Story 2 (P2) — Profile-driven recipe routing

### 2.1 A seasonal metric routes away from a naive z-score

> "Alert me when daily active users does something surprising — weekends are normally quiet."

The skill profiles the series, detects a weekly seasonal period, and routes to a **seasonality-aware** recipe (STL + residual outliers) rather than a baseline z-score. The generated docstring says so:

```python
"""DAU surprise alert — STL residual outliers. CI/agent-ready.

Why this recipe: the DAU series has a strong weekly seasonal component
(ACF peak at lag 7), so a naive z-score would fire every weekend. STL
decomposes trend + weekly seasonality and flags residual outliers, so a
normal Sunday dip is expected and a real surprise stands out.

  pip install mixpanel_headless statsmodels
"""
```

### 2.2 An "expected vs actual" intent routes to a forecasting band

> "Forecast next week's revenue and alert me when the actual leaves the expected band."

Routes to the **forecasting** family (Prophet or Holt-Winters). The report reads as expected-vs-actual with a prediction interval:

```
  2026-06-28  BAND_EXIT  expected 124,300 +/- 11,100  got 72,400  (DROP, below lower band)
```

### 2.3 A regime-shift intent routes to changepoint detection

> "I do not care about daily spikes — tell me when the metric permanently shifts level."

Routes to the **changepoint** family (ruptures PELT). The report names the changepoint date and the pre/post levels:

```
  changepoint: 2026-05-12  pre-level ~ 8,900  post-level ~ 5,400  (SHIFT -39%)
```

### 2.4 A causal intent routes to multivariate / CausalImpact

> "Did the May 12 release actually move conversion, or was it already trending?"

Routes to the **multivariate + causal** family (CausalImpact counterfactual). The report frames the effect against the counterfactual:

```
  effect of 2026-05-12 release: +6.2% conversion (95% CI +2.1% .. +10.4%) -> significant
```

### 2.5 A friction metric defaults to the right direction

> "Watch `Checkout Error` and tell me when it gets bad."

The skill recognizes the friction-shaped name (`*Error`) and defaults the intent to "a sustained rise is the alert" (more errors is bad), confirms that with you, then routes by the series profile (a slow worsening trend leans toward the seasonality-aware / forecasting families rather than a single-day spike). It frames the metric by users affected, not raw count:

```python
"""Checkout-error rise alert — STL residual outliers. CI/agent-ready.

Why this recipe: Checkout Error is a friction signal, so a sustained rise is
the alert (a drop is fine). The series has a weekly seasonal component, so STL
flags residual rises against the same-weekday expectation. Measured by unique
users affected, not raw hits.
"""
MATH = "unique"
```

### 2.6 Every routed script names its deps

Each generated script's install header names the exact deps for that recipe (`statsmodels`, `prophet`, `ruptures`, `causalimpact`), and importing a missing one fails fast:

```bash
python dau_surprise_alert.py
# statsmodels is required for this recipe and isn't installed.
#   pip install statsmodels
```

---

## Story 3 (P2/P3) — Deploy in cron / CI / an agent loop

### 3.1 Cron

```cron
# page on a recent anomaly; do nothing when clean
*/15 * * * * cd /opt/alerts && python signups_drop_alert.py || /usr/local/bin/page-oncall "signups anomaly"
```

`||` fires the pager only on a non-zero exit (`1` anomaly or `2` no data).

### 3.2 GitHub Actions (fail the build on a regression)

```yaml
- name: signup-regression-gate
  env:
    MP_USERNAME: ${{ secrets.MP_USERNAME }}
    MP_SECRET: ${{ secrets.MP_SECRET }}
    MP_PROJECT_ID: ${{ secrets.MP_PROJECT_ID }}
    MP_REGION: us
  run: |
    pip install mixpanel_headless scikit-learn
    python signups_drop_alert.py   # non-zero exit fails the job; report shows in the log
```

Credentials are supplied via environment variables only — no edit to the script's inline block.

### 3.3 Self-healing agent loop

```bash
python signups_drop_alert.py
case $? in
  0) echo "clean" ;;
  1) claude -p "signups dropped — investigate and open a ticket with the report above" ;;
  2) echo "no data — check the query/window" ;;
esac
```

### 3.4 Retarget with one edit

Change the single `METRIC` block to watch a different number — no changes to the model, report, or exit logic:

```python
METRIC = "Purchase"
MATH = "sum"
MATH_PROPERTY = "REVENUE"
```

---

## Reviewer checklist (merge gate)

For each recipe template under `scripts/recipes/`, verify:

- [ ] Honors the `0/1/2` exit-code contract (clean / recent anomaly / no data).
- [ ] Exposes `RECENT_DAYS` and a single retargetable `METRIC` block at the top of the file.
- [ ] Resolves credentials env-first (shell env > sibling `.env` > inline placeholders), never overwriting a set env var.
- [ ] Carries a bring-your-own-deps `pip`/`uv` install header naming the exact deps.
- [ ] Fails fast with a clear "pip install X" message on a missing recipe dep.
- [ ] Is deterministic (fixed `random_state` / seeds) — two runs on the same data agree.
- [ ] Guards degenerate math: zero-variance series, gaps (explicit fill policy), short series (down-select or exit `2`), naive-midnight date normalization.
- [ ] Prints an explainable report (value, expectation/forecast band, delta, score, direction).

For the skill itself, verify:

- [ ] `SKILL.md` frontmatter has `name`, `description` (the auto-trigger string from spec.md), and `allowed-tools`.
- [ ] `SKILL.md` is terse and routes into `references/` (no inlined `mixpanel_headless` API re-teaching).
- [ ] Bundled script paths use `${CLAUDE_SKILL_DIR}`.
- [ ] `help.py` is referenced via the plugin root, never copied into the skill.
- [ ] `git diff --stat` shows changes only under `mixpanel-plugin/skills/alert-machine/` (skill source) — no `src/` / `tests/` / `pyproject.toml` changes.

---

## Smoke-test script (merge gate)

The reduced version that runs against the public fixture project:

```bash
# Generate-and-run the baseline quickstart recipe against the fixture project,
# supplying credentials via env only.
export MP_USERNAME=... MP_SECRET=... MP_PROJECT_ID=... MP_REGION=us
pip install mixpanel_headless scikit-learn

python mixpanel-plugin/skills/alert-machine/scripts/recipes/baseline_isolation_forest.py
test $? -le 2 && echo "OK: exit code in {0,1,2}" || echo "FAIL: unexpected exit code"

# Determinism: same data -> same verdict
python .../baseline_isolation_forest.py > /tmp/a.txt; A=$?
python .../baseline_isolation_forest.py > /tmp/b.txt; B=$?
[ "$A" = "$B" ] && diff -q /tmp/a.txt /tmp/b.txt && echo "OK: deterministic"
```

---

## Security verification

```bash
# No real secret should be committed in a generated or template script.
grep -RInE 'secret|password|sa\.[0-9a-f]+\.mp-service-account' \
  mixpanel-plugin/skills/alert-machine/scripts/recipes/ \
  | grep -vE 'os\.environ|MP_SECRET|placeholder|# ' \
  && echo "REVIEW: possible inline secret" || echo "OK: no inline secrets in templates"
```

Templates must ship non-secret placeholders and default to env-first resolution.
