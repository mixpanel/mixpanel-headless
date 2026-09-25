# Request Pacing

Mixpanel limits how many queries each project can run per hour. The library keeps a shared record of the queries that count against that limit, and it paces requests so that they stay inside it. All `mp` commands and Python sessions on one machine share this record, called the **query ledger**.

!!! tip "Nothing to configure"
    Pacing is on by default. Under the budget it does nothing you can see. It acts only when the project is near its limit.

## What it does

Before a request that counts against a limit, the library reads the ledger and computes the time of the next free slot. Then it does one of three things:

1. **The budget has room.** The request goes out at once. This is the normal case.
2. **A slot opens within a short wait** (30 seconds by default). The library waits, then sends. The query looks slightly slower.
3. **The next slot is further away.** The library sends nothing. It raises `RateLimitError` at once. The message gives the exact time of the next slot and how much of the budget is used.

Without pacing, the 61st query of the hour goes to the server, gets an HTTP 429, and the client sleeps and retries blindly. With pacing, a short wait is absorbed, and a long wait fails fast with an exact answer and no wasted request.

A wait of 5 seconds or more logs one line at `WARNING` level on the `mixpanel_headless._internal.pacer` logger. With no logging configuration, Python prints it to stderr, never to stdout:

```text
Mixpanel query budget for project 3713224: 60 of 60 used in the last hour; waiting 23s for the next slot.
```

Shorter waits log at `DEBUG` level.

!!! note "Pacing does not add quota"
    No client can run more queries than the project's limit. Pacing removes wasted requests and blind sleeps, and it gives exact answers. To spend less of the budget, ask fewer, larger questions: one insights query with several metrics costs 1, the same as a query with one metric.

## Which requests count

The ledger follows the server's own counting rules.

| Requests | Budget | Paced |
|---|---|---|
| Query API endpoints the server counts: `insights`, `segmentation`, `funnels`, `retention`, `arb_funnels`, `stream`, `events`, `engage`, `jql`, `cohorts`, and the others on the server's list. This covers `query()`, `query_funnel()`, `query_retention()`, `query_flow()`, `activity_feed()`, `query_saved_report()`, and the `segmentation` family. | Query API budget per project (60 per hour by default) | Yes |
| The first page of a profile query (`engage`) | Query API budget | Yes |
| Later profile pages (`engage` with a `session_id`) and `engage/aliases` | None; the server does not count them | No |
| Raw event export (`/api/2.0/export`, used by `stream_events`) | A separate server system with its own limits | No; its 429 handling is the same as before pacing |
| App API (`/api/app/...`: dashboards, cohorts CRUD, Lexicon, `/me`, and so on) | Per-user limits that the ledger does not track | No |
| Any request without a `project_id` in its URL or its body | – | No |

Like the server, the library reads the `project_id` from the request body as well as from the URL. So the typed queries (`query()`, `query_funnel()`, `query_retention()`, `query_flow()`, and `activity_feed()`), which send the project in a POST body, are paced.

Some rules follow from how the server counts:

- **Discovery calls count too.** `events()`, `properties()`, `property_values()`, `funnels()`, and `cohorts()` read counted Query API endpoints (`events/...`, `funnels/list`, `cohorts/list`). A loop over many properties can use a large part of the budget.
- **A cached server result still counts.** The server counts a query when it arrives, before it looks in its cache.
- **A query that fails during execution counts.** Authentication and plan errors (HTTP 401 and 402) do not count, and the ledger gives their slot back.
- **A Query API request that the server rejects with a 429 does not count.** The ledger gives its slot back.
- **A request that never reaches the server does not count.** When the connection fails (the connection never opens), the ledger gives the slot back. A read timeout keeps the slot, because the server can count the request.
- **The account does not matter.** The server keeps one budget per project. Two local accounts that use one project share its budget, and they share one ledger.

## How processes share the budget

The ledger is a small JSON file for each host and project:

```text
~/.mp/pacer/{host}/{project_id}-query.json
```

The storage directory follows `MP_STORAGE_DIR` when it is set (`$MP_STORAGE_DIR/pacer/...`). Each process locks the file while it reads and writes it, and no process waits while it holds the lock. So five agents that run at once on one machine each get their own exact slot. They do not race each other into a burst of 429s.

The host is part of the key, so each region and each [alternate API host](../getting-started/configuration.md#alternate-api-host-mp_api_base_url) has its own ledger.

If the ledger cannot be used, the library sends requests without pacing and logs one warning per process (see [Troubleshooting](#troubleshooting)). A damaged ledger file is treated as empty and rewritten. The server stays the final check.

## Raised limits

Many projects have a limit higher than 60 queries per hour. The library learns the real limit, so it does not pace a project below it unless you set a lower limit.

**Learned from the server.** Until the library knows the limit, a full ledger does not block. The next query goes out as a probe:

- If the server accepts it, the limit is higher, and queries continue.
- If the server rejects it, the `RateLimit-Policy` header of the 429 response states the project's limit. The ledger stores that value and blocks from then on. The rejected probe does not count against the budget, so the probe is free.

A 429 without a `RateLimit` header that names a limit (for example, from a proxy, or when the server sheds load) teaches the ledger nothing. The library handles it as it did before pacing existed: the normal retry, which waits for the `Retry-After` value or backs off.

A learned limit expires after 7 days, because a project's limit can change. The cost is one probe per project per week.

**Set a known limit.** If you know your project's limit, set it, and the ledger uses it from the first query:

```bash
export MP_PACER_QUERY_LIMIT=240        # every project in this process
```

```toml
# ~/.mp/config.toml
[settings.pacer_query_limits]
"3713224" = 240                        # per project ID
```

`MP_PACER_QUERY_LIMIT` wins over the per-project value in `config.toml`.

A configured limit is a ceiling. When the library also knows the limit from the server (learned within the last 7 days), the lower of the two applies. With neither, the default of 60 applies.

- **A value set too high** (for example, an expired grant) is replaced by the server's limit after the first 429 that states it. The library logs one warning that names both values.
- **A value set too low is never raised automatically**, not even after a 429 states a higher limit. You can use this on purpose. All API users of a project share one budget, so a limit of 40 on a 60-per-hour project leaves room for teammates and other scripts.

!!! warning "`config.toml` must be private"
    The library refuses to read a `config.toml` that the group or others can read (the file mode must be `0600`). The pacer then logs one warning, `Ignoring pacer settings in the config file: ...`, and applies none of the pacer settings in the file, including `[settings.pacer_query_limits]`. Environment variables still apply. Fix the mode with `chmod 600 ~/.mp/config.toml`.

## Settings

| Setting | Values | Default | Purpose |
|---|---|---|---|
| `MP_PACER` | `on` / `true` / `1` / `yes`, or `off` / `false` / `0` / `no` (any case) | `on` | `off` turns pacing off. The library then reads and writes no ledger files and behaves exactly as it did before pacing existed. |
| `MP_PACER_MAX_WAIT` | seconds, or `inf` | `30` | The longest wait the library absorbs before it raises `RateLimitError`. In Python it applies to each request. Inside an `mp` command it is a budget for the whole command: the total of all pacer waits across the command's requests. Unattended jobs can set a large value or `inf`, so the job waits for each slot and never fails on the budget. |
| `MP_PACER_QUERY_LIMIT` | positive integer | unset | A known Query API limit (queries per hour) for every project in the process. |

The same settings can live in `~/.mp/config.toml` (or the file at `MP_CONFIG_PATH`):

```toml
[settings]
pacer = "on"                 # or "off"; true / false also work
pacer_max_wait = 120         # seconds

[settings.pacer_query_limits]
"3713224" = 240              # project ID = queries per hour
```

For each setting, the environment variable wins over `config.toml`, and `config.toml` wins over the default. An invalid value logs one warning and is ignored, and the next source applies. For example, `MP_PACER_QUERY_LIMIT=0`, `MP_PACER=maybe`, or an environment variable set to an empty string is ignored, and the value in `config.toml` (or the default) is used. An invalid `MP_PACER` value leaves pacing on; its warning ends with "request pacing stays on". An invalid value never fails a request. With `MP_PACER=off`, the library does not read the pacer settings in `config.toml`.

A long wait is safe with OAuth. After a pacer wait, the library resolves the `Authorization` header again, so a request that waited (for example, with `MP_PACER_MAX_WAIT=inf`) does not send an expired OAuth token.

There are no `Workspace` arguments for pacing. The environment variables work for both the CLI and Python.

!!! warning "Agent tool calls time out"
    Agent runtimes often stop a tool call after about two minutes, and a query itself can take tens of seconds. Keep `MP_PACER_MAX_WAIT` short for interactive and agent use. Raise it for scheduled jobs.

## The error

When the next slot is further away than `MP_PACER_MAX_WAIT`, the library raises `RateLimitError` without sending the request. The message has one of two forms.

**This machine's own requests fill the budget** (`details["reason"] == "ledger"`):

```text
Mixpanel query budget exhausted for project 3713224: 60 of 60 queries used in the last hour (Query API limit). The next slot opens at 14:32:10 UTC (in 7m 12s). No request was sent. To wait instead of failing, set MP_PACER_MAX_WAIT (seconds). Retry after 432 seconds.
```

**The server reported the budget full, and the ledger cannot explain it** (`details["reason"] == "server"`). Other clients probably use the same project:

```text
Mixpanel query budget exhausted for project 3713224: the server reported the hourly limit (60) reached, likely from other clients sharing this project. The next attempt opens at 14:26:10 UTC (in 1m 0s). No request was sent. To wait instead of failing, set MP_PACER_MAX_WAIT (seconds). Retry after 60 seconds.
```

When the library does not know the project's limit (the 429 named the hourly limit but did not state its size), the message leaves out the number: "the server reported the hourly limit reached, likely from other clients sharing this project".

The error carries structured data:

| Field | Meaning |
|---|---|
| `retry_after` | Seconds until the next slot, rounded up |
| `details["limit"]` | The limit the ledger used |
| `details["used"]` | Requests counted in the current window |
| `details["window_seconds"]` | The window length (3600) |
| `details["next_slot_at"]` | The next slot as an ISO 8601 UTC timestamp |
| `details["limit_source"]` | `"server"`, `"configured"`, or `"default"` |
| `details["sent"]` | `False`: the request never left the machine |
| `details["bucket"]` | `"query"` |
| `details["blocked_streak"]` | Only when `reason` is `"server"`: the number of 429s in a row that the ledger could not explain. Each one doubles the pause, up to one hour. |
| `details["reason"]` | `"ledger"`: this machine's own recent requests fill the budget. `"server"`: the server reported the budget full, and other clients probably share the project. |

A `RateLimitError` from the server (an HTTP 429 that the retries could not get past) has no `sent` key.

### In Python

```python
import mixpanel_headless as mp

ws = mp.Workspace()

try:
    result = ws.query("Login", last=7)
except mp.RateLimitError as e:
    if e.details.get("sent") is False:
        # Raised by the pacer: nothing was sent.
        if e.details["reason"] == "ledger":
            print(f"Budget full until {e.details['next_slot_at']} "
                  f"({e.details['used']} of {e.details['limit']} used)")
        else:
            print(f"Other clients use this project's budget; "
                  f"next attempt at {e.details['next_slot_at']}")
    else:
        print(f"Server rate limit; retry after {e.retry_after}s")
```

Do not retry a `RateLimitError` in a loop. Each attempt fails the same way until the slot opens. To wait instead, set `MP_PACER_MAX_WAIT`, or schedule the work for `next_slot_at`.

### In the CLI

The `mp` CLI prints the message to stderr and exits with code `5`, the same code as for every other rate-limit error (see [Exit Codes](../cli/index.md#exit-codes)):

```bash
mp query segmentation -e Login --from 2025-01-01
# Rate limited: Mixpanel query budget exhausted for project 3713224: 60 of 60 ...
# Wait 432 seconds before retrying.
echo $?
# 5
```

Inside one `mp` command, `MP_PACER_MAX_WAIT` limits the total of all pacer waits, not each wait. A command that pages through many counted requests therefore fails fast once its waits add up to the limit. A scheduled job can wait instead of failing:

```bash
MP_PACER_MAX_WAIT=inf mp query segmentation -e Login --from 2025-01-01
```

## Troubleshooting

**Turn pacing off.** Set `MP_PACER=off` to rule the pacer out. The library then sends every request directly, as it did before pacing existed, and the server's 429 responses reach the normal retry logic.

```bash
MP_PACER=off mp query segmentation -e Login --from 2025-01-01
```

**429s from other machines** (`details["reason"] == "server"`). The ledger knows only the requests from this machine. Other machines, CI jobs, and teammates can use the same project's budget. The library pauses a project's queries when a 429's `RateLimit` header says that the hourly limit tripped and the ledger cannot explain it. This happens in two cases:

- The ledger knows the limit, but it counts fewer requests than that limit.
- The ledger does not know the limit, because the 429 did not state its size.

A 429 without such a header (for example, from a proxy) causes no pause. It gets the normal retry.

The first pause lasts one window divided by the limit: 60 seconds at a limit of 60, 15 seconds at a limit of 240. After the pause, the next query goes out as a probe. Rejected Query API probes are free. When the probe also gets a 429 that the ledger cannot explain, the pause doubles (60, 120, 240 seconds, and so on) up to one hour. The first successful query resets the pause. In real traffic, such an episode lasts a median of about 20 minutes. The error's `details["blocked_streak"]` gives the number of these 429s in a row. If this error happens often, set a lower [configured limit](#raised-limits) to leave room for the other users.

**A warning says that pacing is off or partial.** The pacer never fails a request because of its own problems. When it cannot work, it logs one warning per process and requests go out unpaced:

- `Request pacing is off for this process: cannot use the ledger under ... Requests go out unpaced.` The ledger directory cannot be used, for example because the storage directory is read-only, or because another process held the ledger's file lock for more than 1 second. Check the permissions of `~/.mp/pacer` (or `$MP_STORAGE_DIR/pacer`).
- `Request pacing uses a thread lock only: processes on this machine are not paced together.` The file system or the platform does not support the file lock (for example, some network file systems). Threads in one process are still paced, but separate processes do not share the budget.
- `Request pacer internal error; requests go out unpaced; please report.` An unexpected error in the pacer. Please report it with the `DEBUG` log.
- `Request pacer: ignoring ledger entries in the future; the system clock stepped back.` The ledger holds send times too far in the future to be real reservations, so the library ignores them. Pacing continues.

**Too many concurrent queries.** The server also allows only 5 Query API requests at the same time per project. The ledger does not track this. A concurrency 429 is free, and the normal retry logic waits a few seconds and tries again.

**The first full hour sends one extra request.** Until the library knows a project's limit, the first query past 60 goes to the server as a probe. For a project at the default limit, that probe gets a 429 (which does not count), and the library then waits or raises as described above. Set `MP_PACER_QUERY_LIMIT` or `[settings.pacer_query_limits]` to skip the probe.
