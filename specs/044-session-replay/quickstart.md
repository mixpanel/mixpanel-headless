# Quickstart: Session Replay

**Feature**: 044-session-replay
**Audience**: New users exploring the session-replay surface; reviewers smoke-testing before merge.

This walkthrough exercises every documented user story (P1–P3) from spec.md. Treat it as the merge-gate recipe.

---

## Story 1 (P1) — Discover and pull a user's recent replays

### 1.1 Discover

```python
import mixpanel_headless as mp

ws = mp.Workspace.use(account="acme-corp", project=3713224)

summaries = ws.list_replays(
    distinct_id="user-42",
    from_date="2026-05-20",
    to_date="2026-05-27",
)
print(f"Found {len(summaries)} replays")
for s in summaries:
    print(f"  {s.replay_id}  started {s.start_time}  retention {s.retention_days}d")
```

**Expected output** (when user-42 has 3 sessions in the window):
```
Found 3 replays
  r-19221397401184  started 1716192721000  retention 30d
  r-19222483017720  started 1716279127000  retention 30d
  r-19223568634256  started 1716365533000  retention 30d
```

### 1.2 Sign

```python
signed = ws.sign_replays([s.replay_id for s in summaries])
print(signed[0])     # __repr__ masks the bearer credential
```

**Expected output**:
```
SignedReplay(replay_id='r-19221397401184', url='https://cdn.mxpnl.com/srr-us/abc.../', query_string='<redacted 256 chars>', env='prod', signed_at=1716365822.7)
```

### 1.3 Fetch raw bytes

```python
replay = ws.fetch_replay("r-19221397401184")
print(f"{len(replay.rrweb_events)} events, duration {replay.duration_seconds:.1f}s")

# Write rrweb-player-compatible JSON
import json
from pathlib import Path

Path("recording.json").write_text(
    json.dumps(replay.to_rrweb_player_json())
)
```

**Expected output**:
```
4823 events, duration 492.1s
```

### 1.4 Stream (for large replays)

```python
for i, event in enumerate(ws.stream_replay("r-19221397401184")):
    if i == 0:
        print(f"first event at t={event['timestamp']}")
    if i >= 99:
        print("...stopping after 100 events")
        break
```

### 1.5 CLI equivalent

```bash
# Discover
mp replays list --user user-42 --from 2026-05-20 --to 2026-05-27

# Pull bytes
mp replays fetch r-19221397401184 -o recording.json

# Play in a browser
# (open an HTML page that imports rrweb-player and loads recording.json)
```

---

## Story 2 (P2) — Behavioral analysis across many replays

### 2.1 Build a bundle

```python
bundle = ws.replays_for_user(
    distinct_id="user-42",
    from_date="2026-05-20",
    to_date="2026-05-27",
    include_mixpanel_events=True,
)
print(bundle.df.head())   # default projection: sessions_df
```

**Expected**: a `pandas.DataFrame` with one row per replay and the documented session-level columns (`replay_id`, `duration_s`, `n_events`, `n_actions`, ...).

### 2.2 Top-N aggregations

```python
print("Top 5 most-clicked elements:")
print(bundle.top_clicks(n=5))

print("\nRage-click sessions:")
print(bundle.rage_clicks(threshold=3, window_ms=1000))

print("\nDead clicks (no DOM response within 200ms):")
print(bundle.dead_clicks(window_ms=200))

print("\nSessions with console errors:")
print(bundle.error_sessions().sessions_df[["replay_id", "n_errors"]])
```

### 2.3 Chainable filters

```python
# Funnel-like: sessions that hit /checkout AND took longer than 60s
checkout_sessions = (
    bundle
    .where(contains_url="/checkout")
    .filter(lambda r: r.duration_seconds > 60)
)
print(f"{len(checkout_sessions.replays)} long checkout sessions")

# Deterministic sample for manual review
sample = checkout_sessions.sample(n=3, seed=42)
for r in sample.replays:
    print(r.summary_markdown[:200], "...")
```

### 2.4 Graph and tree projections

```python
import networkx as nx   # requires pip install 'mixpanel-headless[replay-all]'

g = bundle.page_graph
print(f"Page graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

# Most-visited pages, weighted by transitions
pr = nx.pagerank(g, weight="count")
for url, score in sorted(pr.items(), key=lambda kv: -kv[1])[:5]:
    print(f"  {score:.3f}  {url}")
```

```python
from anytree import RenderTree

tree = bundle.path_tree
print(RenderTree(tree))   # ASCII rendering of action sequences
```

### 2.5 Two-bundle comparison

```python
# Build a second bundle for users who converted
converters = ws.replays_for_user(distinct_id="user-99", from_date="2026-05-20", to_date="2026-05-27")

diff = bundle.compare(converters)
print(diff.head(10))      # action-frequency diff
```

---

## Story 3 (P2) — CLI walkthrough

### 3.1 Markdown timeline for a single replay

```bash
mp replays analyze r-19221397401184
```

**Expected stdout** (excerpt):
```markdown
# Session r-19221397401184 — 8m 12s — user-42

## Timeline

- 14:32:01 navigate to `https://acme.com/login`
- 14:32:04 click `button "Sign in"`
- 14:32:06 input `input[type=email]` (12 chars)
...
```

### 3.2 Full bundle for a user, written to disk

```bash
mp replays for-user user-42 --from 2026-05-20 --to 2026-05-27 \
    --include analyze --include events \
    --out-dir ./replays/

ls ./replays/
# r-19221397401184-summary.md
# r-19222483017720-summary.md
# r-19223568634256-summary.md
# index.json
```

### 3.3 Bearer-credential handling

```bash
# Redacted by default
mp replays sign r-19221397401184
# {"replay_id": "r-19221397401184", "url": "...", "query_string": "<redacted 256 chars>", ...}

# Opt into disclosure (with warning)
mp replays sign r-19221397401184 --reveal-signed-urls 2>/tmp/warning.txt
cat /tmp/warning.txt
# warning: signed URLs are bearer credentials valid for ~5 minutes. Treat them
# like session tokens — do not paste into chat, logs, or version control.
```

---

## Story 4 (P3) — Process mining and ML clustering

### 4.1 Process discovery (requires `[replay-mining]` extra)

```bash
pip install 'mixpanel-headless[replay-mining]'
```

```python
import pm4py

# Without pm4py installed, event_log returns a DataFrame.
# With pm4py installed, it returns an EventLog.
log = bundle.event_log()

# Inductive miner produces a Petri net
net, im, fm = pm4py.discover_petri_net_inductive(log)
pm4py.view_petri_net(net, im, fm, format="png")

# Or a BPMN diagram
bpmn = pm4py.discover_bpmn_inductive(log)
pm4py.view_bpmn(bpmn)

# Or directly-follows graph
dfg, sa, ea = pm4py.discover_dfg(log)
pm4py.view_dfg(dfg, sa, ea)
```

### 4.2 Custom labeling for stable activities

```python
from mixpanel_headless.types import selector_label_fn

# Use data-testid attributes from your SDK markup
log = bundle.event_log(label_fn=selector_label_fn("data-testid"))
```

### 4.3 Session clustering (requires `[replay-ml]` extra)

```bash
pip install 'mixpanel-headless[replay-ml]'
```

```python
clustered = bundle.cluster(n=5, features="actions")
for r in clustered.replays:
    print(f"{r.replay_id}  cluster={r.cluster_label}")

# Then drill into one cluster
cluster_0 = clustered.filter(lambda r: r.cluster_label == 0)
print(cluster_0.summary_markdown)
```

---

## Smoke-test script (merge gate)

The full quickstart above is the manual smoke test. The reduced version that lives in CI:

```bash
# Phase 1 smoke test (after Phase 1 PR merges)
uv run python -c "
import mixpanel_headless as mp
ws = mp.Workspace.use()
s = ws.list_replays(distinct_id='$KNOWN_USER', from_date='2026-05-20', to_date='2026-05-27')
assert len(s) > 0, 'no replays found for known user'
r = ws.fetch_replay(s[0].replay_id)
assert len(r.rrweb_events) > 0, 'replay had no events'
print(f'OK: fetched {len(r.rrweb_events)} events for {r.replay_id}')
"

# Phase 2 smoke test (after Phase 2 PR merges)
uv run python -c "
import mixpanel_headless as mp
ws = mp.Workspace.use()
b = ws.replays_for_user('$KNOWN_USER', from_date='2026-05-20', to_date='2026-05-27')
assert len(b.replays) > 0
assert len(b.sessions_df) == len(b.replays)
assert len(b.actions_df) > 0
print(f'OK: bundle of {len(b.replays)} replays, {len(b.actions_df)} actions')
"

# CLI smoke test
mp replays list --user "$KNOWN_USER" --from 2026-05-20 --to 2026-05-27 --format json | jq length
mp replays sign "$KNOWN_REPLAY_ID" --format json | jq -r '.[0].query_string'
# expected: <redacted N chars>
```

---

## Performance verification

The following targets must hold on a typical broadband connection. Failing any of these indicates a regression:

| Operation | Target | Measurement |
|-----------|--------|-------------|
| `list_replays(7-day window)` | ≤ 2 s | Wall-clock from call to return |
| `sign_replays(100 IDs)` | ≤ 2 s | Single round-trip |
| `fetch_replay(30 MB replay)` | ≤ 5 s | Includes sign + walk + parse |
| `stream_replay` first event | ≤ 1 s | Time-to-first-yield |
| `ReplayBundle.actions_df` (100 replays) | ≤ 10 s | End-to-end from `replays_for_user` |

---

## Security verification

Before each merge, audit the transcript for credential leaks:

```bash
# Grep your test output for any unredacted signed URLs
mp replays list --user "$KNOWN_USER" --from 2026-05-20 --to 2026-05-27 -v 2>&1 \
    | grep -E 'Signature=|URLPrefix=|Expires=' && echo "LEAK DETECTED" || echo "OK"

mp replays fetch "$KNOWN_REPLAY_ID" -o /tmp/r.json -v 2>&1 \
    | grep -E 'Signature=|URLPrefix=|Expires=' && echo "LEAK DETECTED" || echo "OK"
```

Both commands must report `OK`.
