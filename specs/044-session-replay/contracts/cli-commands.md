# Contract: CLI Commands

**Feature**: 044-session-replay
**Surface**: `mp replays` command group
**Audience**: Operators, support engineers, agents invoking the CLI

A new Typer command group `mp replays` registered in `cli/main.py::_register_commands()`. All commands follow the existing pattern: `@handle_errors`, `get_workspace(ctx)`, `output_result(ctx, ..., format=format)`.

---

## 1. Command surface

| Command | Phase | Purpose |
|---------|-------|---------|
| `mp replays list` | 1 | Discover a user's replays |
| `mp replays events` | 1 | Mixpanel events in a replay's window |
| `mp replays sign` | 1 | Get signed CDN URL(s) |
| `mp replays fetch` | 1 | Pull raw rrweb bytes |
| `mp replays analyze` | 2 | Print markdown timeline |
| `mp replays for-user` | 2 | Discovery + fetch + analyze in one command |

---

## 2. `mp replays list`

```bash
mp replays list --user USER --from DATE --to DATE [--limit N] [--format FMT]
mp replays list --replay-id ID [--replay-id ID ...] [--format FMT]
```

**Options**:
- `--user TEXT`: distinct_id. Mutually exclusive with `--replay-id`.
- `--replay-id TEXT` (repeatable): explicit IDs to hydrate. Mutually exclusive with `--user`.
- `--from TEXT`: ISO date (YYYY-MM-DD). Required with `--user`.
- `--to TEXT`: ISO date (YYYY-MM-DD). Required with `--user`.
- `--limit INT`: default 100.
- `--format [table|json|jsonl|csv|plain]`: default `table`.

**Default columns** (table format): `replay_id`, `distinct_id`, `started`, `retention_days`.

**Examples**:
```bash
mp replays list --user user-42 --from 2026-05-20 --to 2026-05-27
mp replays list --user user-42 --from 2026-05-20 --to 2026-05-27 --format jsonl
mp replays list --replay-id r-19221... --replay-id r-19222... --format json
```

**Exit codes**: 0 success (incl. empty result); 2 auth; 3 invalid args.

---

## 3. `mp replays events`

```bash
mp replays events REPLAY_ID [--properties PROP[,PROP...]] [--format FMT]
```

**Options**:
- `REPLAY_ID`: positional, required.
- `--properties TEXT`: comma-separated event properties to include as group keys. Max 5.
- `--format [json|jsonl|csv|plain]`: default `json`.

**Examples**:
```bash
mp replays events r-19221... --properties '$browser,$current_url'
mp replays events r-19221... --format jsonl
```

**Exit codes**: 0 success; 2 auth; 3 invalid args (e.g. >5 properties); 4 replay not found.

---

## 4. `mp replays sign`

```bash
mp replays sign REPLAY_ID [REPLAY_ID ...] [--env ENV] [--reveal-signed-urls] [--format FMT]
```

**Options**:
- `REPLAY_ID` (variadic): one or more IDs.
- `--env [prod|dev]`: default `prod`.
- `--reveal-signed-urls`: opt into full bearer-credential disclosure. **Emits a stderr warning every time used.**
- `--format [json|jsonl|table|plain]`: default `json`.

**Output (default, redacted)**:
```json
[
  {
    "replay_id": "r-19221...",
    "url": "https://cdn.mxpnl.com/srr-us/<sha>-<pid>/",
    "query_string": "<redacted 256 chars>",
    "env": "prod",
    "signed_at": 1730000000.0,
    "expires_at": 1730000300.0
  }
]
```

**Output with `--reveal-signed-urls`** (full):
```json
[
  {
    "_warning": "query_string is a bearer credential valid for ~5 minutes",
    "replay_id": "r-19221...",
    "url": "https://cdn.mxpnl.com/srr-us/<sha>-<pid>/",
    "query_string": "URLPrefix=...&Expires=...&KeyName=...&Signature=...",
    "env": "prod",
    "signed_at": 1730000000.0,
    "expires_at": 1730000300.0
  }
]
```

**Stderr on `--reveal-signed-urls`** (every invocation):
```
warning: signed URLs are bearer credentials valid for ~5 minutes. Treat them
like session tokens — do not paste into chat, logs, or version control.
```

**Exit codes**: 0 success; 2 auth (incl. sensitive-data 403); 3 invalid args; 4 replay not found.

---

## 5. `mp replays fetch`

```bash
mp replays fetch REPLAY_ID [-o FILE] [--env ENV] [--include-events] [--max-files N]
```

**Options**:
- `REPLAY_ID`: positional, required.
- `-o`, `--output PATH`: write to file. When omitted, prints a one-line summary to stdout.
- `--env [prod|dev]`: default `prod`.
- `--include-events`: trigger the Mixpanel-events join.
- `--max-files INT`: default 500.

**File output** (`-o file.json`): JSON array of rrweb events, timestamp-sorted. Directly compatible with the rrweb JS player:

```javascript
import rrwebPlayer from 'rrweb-player';
const events = await (await fetch('file.json')).json();
new rrwebPlayer({ target: document.body, props: { events } });
```

**Stdout output** (no `-o`):
```
fetched r-19221... — 4823 events, 8m 12s, 30-day retention
```

**Exit codes**: 0 success; 2 auth; 4 replay not found.

---

## 6. `mp replays analyze`

```bash
mp replays analyze REPLAY_ID [--format FMT]
```

**Options**:
- `REPLAY_ID`: positional, required.
- `--format [plain|json|markdown]`: default `plain` (= markdown timeline). `json` emits the structured action list.

**Default output** (markdown timeline to stdout):
```markdown
# Session r-19221... — 8m 12s — alice@acme.com

## Timeline

- 14:32:01 navigate to `https://acme.com/login`
- 14:32:04 click `button "Sign in"`
- 14:32:06 input `input[type=email]` (12 chars)
- 14:32:09 input `input[type=password]` (16 chars)
- 14:32:11 click `button "Submit"`
- 14:32:14 navigate to `https://acme.com/dashboard`
...
```

**JSON output** (`--format json`): array of normalized `UserAction` records.

**Exit codes**: 0 success; 2 auth; 4 replay not found.

**Phase note**: requires Phase 2 (vendored analyzer). In Phase 1, this command does not exist.

---

## 7. `mp replays for-user`

```bash
mp replays for-user USER --from DATE --to DATE \
    [--include analyze] [--include events] \
    [--out-dir DIR] [--limit N]
```

**Options**:
- `USER`: positional distinct_id, required.
- `--from TEXT`, `--to TEXT`: ISO date window, required.
- `--include [analyze|events]` (repeatable): which extras to fetch.
- `--out-dir PATH`: directory to write per-replay output. When omitted, writes to stdout (markdown summaries concatenated).
- `--limit INT`: default 100.

**Output with `--out-dir DIR --include analyze`**:
```
DIR/
├── r-19221...-summary.md
├── r-19222...-summary.md
├── r-19223...-summary.md
└── index.json    # bundle.sessions_df.to_json(orient="records")
```

**Stdout** (after writing the files):
```
wrote 3 replays to ./replays/
total: 24m activity, 12 navigations, 47 clicks, 3 errors
```

**Exit codes**: 0 success (incl. empty result); 2 auth; 3 invalid args.

**Phase note**: requires Phase 2.

---

## 8. Global behaviors

### Authentication

All commands use the standard `get_workspace(ctx)` resolution: env → param → target → bridge → config. Auth failures exit with code 2 and a structured error.

### Error mapping

| Exception | Exit code | CLI message format |
|-----------|-----------|--------------------|
| `SessionReplayAccessError` | 2 | `error: sensitive replay data — project N has SESSION_RECORDING_SENSITIVE_DATA enabled and your account lacks access` |
| `SignedURLExpiredError` | 1 | `error: signed URL expired (5-minute TTL) — re-run the command` |
| `ReplayNotFoundError` | 4 | `error: replay R not found — may have aged out of retention, never been recorded, or been deleted` |
| `QueryError` (Insights) | 1 | passed through with HTTP status and Mixpanel error message |
| Other `APIError` | 1 | passed through |

### Output formatting

All commands honor `--format` per the existing `FormatOption` enum: `json`, `jsonl`, `table`, `csv`, `plain`. Where `--format` is omitted, each command picks the most useful default (see per-command sections).

### Logging

- Default: silent on success, structured errors on stderr.
- `-v` (verbose, existing global): progress lines on stderr (e.g. "fetching CDN file 0042-30.json").
- `-vv` (debug, existing global): URL prefixes (NEVER query strings) on stderr.
- Bearer credentials NEVER logged at any level.
