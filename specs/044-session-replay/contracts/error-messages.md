# Contract: Error Messages

**Feature**: 044-session-replay
**Surface**: Stable error message catalog
**Audience**: Callers writing error-handling code; agents pattern-matching CLI stderr

Error messages are part of the API contract. Changes to wording in this catalog require a minor version bump and a CHANGELOG entry. Stable identifiers (exception class names, `details` dict keys, exit codes) are stricter — they require a major version bump to change.

---

## 1. `SessionReplayAccessError`

**When raised**: `POST /app/projects/<id>/replays/sign/bulk` returns 403 with a body indicating the `SESSION_RECORDING_SENSITIVE_DATA` flag is set on the project AND the calling account lacks sensitive-data access.

**Python**:
```python
raise SessionReplayAccessError(
    message=(
        f"Project {project_id} has SESSION_RECORDING_SENSITIVE_DATA enabled. "
        f"Your account lacks sensitive-data access. Contact the project owner "
        f"to grant the 'sensitive_data_replay' permission, or use a service "
        f"account that has it."
    ),
    details={
        "project_id": project_id,
        "flag": "SESSION_RECORDING_SENSITIVE_DATA",
        "permission_required": "sensitive_data_replay",
    },
    status_code=403,
)
```

**CLI**:
```
error: sensitive replay data — project 3713224 has SESSION_RECORDING_SENSITIVE_DATA
enabled and your account lacks access. Contact the project owner to grant the
'sensitive_data_replay' permission, or use a service account that has it.
```

**Exit code**: 2 (auth)

---

## 2. `SignedURLExpiredError`

**When raised**: A CDN fetch returns 403 with a body indicating signature expiration AND the caller opted out of automatic re-signing (`stream_replay(re_sign_on_expiry=False)`).

**Python**:
```python
raise SignedURLExpiredError(
    message=(
        f"Signed URL for replay {replay_id} expired (5-minute TTL). "
        f"Re-sign with sign_replay({replay_id!r}) or use the default "
        f"re_sign_on_expiry=True on stream_replay."
    ),
    details={
        "replay_id": replay_id,
        "signed_at": signed_at,
        "expired_at": expired_at,
    },
    status_code=403,
)
```

**CLI**:
```
error: signed URL expired (5-minute TTL) — re-run the command
```

**Exit code**: 1 (generic error)

---

## 3. `ReplayNotFoundError`

**When raised**: The CDN walker requested `0000-N.json` and got a 404. The replay either aged out of retention, was never recorded, or has been deleted.

**Python**:
```python
raise ReplayNotFoundError(
    message=(
        f"Replay {replay_id} not found on CDN. The replay may have aged out "
        f"of its retention window ({retention_days} days), never been recorded, "
        f"or been deleted."
    ),
    details={
        "replay_id": replay_id,
        "retention_days": retention_days,
        "cdn_url_prefix": url_prefix,
    },
    status_code=404,
)
```

**CLI**:
```
error: replay r-19221... not found — may have aged out of retention (30 days),
never been recorded, or been deleted.
```

**Exit code**: 4 (not found)

---

## 4. `ValueError` on bad `events_for_replay` group-by count

**When raised**: Caller passes more than 5 `event_properties` to `events_for_replay` or `events_for_replays`.

**Python**:
```python
raise ValueError(
    f"events_for_replay accepts at most 5 event_properties (Insights group-by "
    f"limit). Got {len(event_properties)}: {event_properties}"
)
```

**CLI** (mapped by `handle_errors` decorator):
```
error: too many event properties — got 7, max is 5 (Insights API limit).
Drop some properties or split into multiple queries.
```

**Exit code**: 3 (invalid args)

---

## 5. `ValueError` on `list_replays` argument validation

**When raised**: Neither or both of `distinct_id` and `replay_ids` provided; or `distinct_id` provided without `from_date`/`to_date`.

**Python**:
```python
# Neither
raise ValueError(
    "list_replays requires exactly one of distinct_id or replay_ids."
)

# Both
raise ValueError(
    "list_replays requires exactly one of distinct_id or replay_ids; both were given."
)

# distinct_id without window
raise ValueError(
    "list_replays(distinct_id=...) requires from_date and to_date."
)
```

**Exit code**: 3 (invalid args)

---

## 6. Optional-extra `ImportError` — not applicable

The replay feature has **no optional-extra-gated surface**, so it raises no
install-time `ImportError`. `networkx` and `anytree` (used by
`ReplayBundle.page_graph` / `element_graph` / `path_tree`) are declared in the
base `dependencies`, so those projections always work; there are no
`[replay-mining]` / `[replay-ml]` / `[replay-all]` extras.

(Section retained, not renumbered, so §7–§11 — and the code references to §9 /
§10 — keep their numbers.)

---

## 7. Mixpanel API errors (passed through)

Errors from the underlying Insights API or `/replays/sign[/bulk]` that do NOT match the sensitive-data 403 pattern are raised as the existing `QueryError` / `ServerError` / `APIError`. The library does not invent new error classes for these.

**Pattern**: existing `MixpanelAPIClient._handle_response()` maps HTTP status to exception, attaches the Mixpanel `error` field and request ID to `details`.

---

## 8. Bearer-credential warning (CLI, `--reveal-signed-urls`)

**When emitted**: Every invocation of `mp replays sign --reveal-signed-urls`, regardless of TTY / format / stdout destination.

**Destination**: stderr.

**Wording**:
```
warning: signed URLs are bearer credentials valid for ~5 minutes. Treat them
like session tokens — do not paste into chat, logs, or version control.
```

**Exit code impact**: none (the warning does not affect exit code).

---

## 9. Mobile-replay attempted (forward-compat marker)

**When raised**: `fetch_replay` is called against a replay_id whose CDN bytes are not in rrweb format (mobile, future formats).

**Python** (Phase 1 placeholder; Phase 2 may refine):
```python
raise NotImplementedError(
    f"Replay {replay_id} appears to be a mobile session (non-rrweb format). "
    f"Mobile session replays are not yet supported by mixpanel-headless. "
    f"Track upstream at SR-230."
)
```

**Exit code**: 1 (generic error)

---

## 10. Retention warning (structured log, not exception)

**When emitted**: `list_replays` encounters a `$mp_session_record` event with no `$mp_replay_retention_period` property.

**Destination**: structured warning via `warnings.warn()`; under default config emits to stderr.

**Wording**:
```
UserWarning: replay r-19221... is missing $mp_replay_retention_period; defaulting
to 30 days. Upgrade your Mixpanel SDK to stamp this property on new recordings.
```

**Category**: `UserWarning` (so it can be filtered with `warnings.filterwarnings("ignore", category=UserWarning)`).

---

## 11. Forward compatibility rules

- **Adding a new exception subclass** is backward-compatible. Existing `except SessionReplayError:` handlers continue to catch it.
- **Adding a new key to a `details` dict** is backward-compatible. Existing callers reading specific keys continue to work.
- **Changing a `message` string** is a minor-version change requiring a CHANGELOG entry. Callers MUST NOT pattern-match on message strings; they should use exception class + `details` keys.
- **Changing an exit code** is a major-version change.
- **Changing a `details` key name** is a major-version change.
