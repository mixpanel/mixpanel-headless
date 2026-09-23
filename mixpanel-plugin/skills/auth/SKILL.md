---
name: auth
description: Manages Mixpanel credentials for the mixpanel_headless library and the mp CLI — checks the active session, lists, adds, and switches accounts, runs OAuth login (one-shot `mp login` or the two-step flow), switches projects and workspaces, and manages saved targets. Use when Mixpanel credentials are missing or failing, when code raises AuthenticationError or reports no account or no project, when the user wants to log in, switch account, project, or workspace, or save or use a target. With no arguments it prints a one-line session summary. Do not use for installing or upgrading the library (use setup) or for analytics questions once credentials work (use mixpanelyst).
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py *)
argument-hint: [session|login|account|project|workspace|target] [...]
---

# Mixpanel authentication

Manage Mixpanel credentials through `auth_manager.py`. Each subcommand prints
exactly one JSON object to stdout. Parse it and present the result in plain
words.

Run each command below exactly as written. Keep the path unquoted, because the
pre-approved command pattern in `allowed-tools` matches the unquoted form.

**Schema:** every response has `schema_version: 1` and a `state` of `ok`,
`needs_account`, `needs_project`, or `error`. Errors are also JSON on stdout
with exit code 0, so you can parse the output without a try/except.

## Security rules (firm)

- Do not ask for secrets (passwords, API secrets) in the conversation. They stay visible in the history.
- Do not pass secrets as command-line arguments. They are visible in the process list.
- For a service account, tell the user to run `! mp account add <name> --type service_account --username <username> --project <project_id> --region <region>` themselves. The command prompts for the secret with hidden input.

## Routing

Parse `$ARGUMENTS` and route to the matching subcommand. With no arguments,
run `session`.

### "login"

For first-time setup, the one-shot path is `mp login`. It picks the auth flow
from the environment, derives the account name from `/me`, and pins a default
project. Tell the user to run:

```text
! mp login
```

The region behavior depends on the auth type:
- `service_account` and `oauth_token` paths probe `us → eu → in` and use the first region that answers.
- The `oauth_browser` path (the default for a bare `mp login`) uses `us`. EU and India users must pass `--region eu` or `--region in`.

Optional flags:
- `--name NAME` — override the derived account name
- `--region us|eu|in` — set the region explicitly (required for EU and India browser users)
- `--project ID` — skip the project picker
- `--service-account` — force the service-account path (needs `MP_USERNAME` and `MP_SECRET` in the environment)
- `--token-env VAR` — force the static-bearer path (reads the token from `$VAR`)
- `--no-browser` — print the authorization URL instead of opening a browser

After the user confirms, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session` to get `account.name`. Then run
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account test <account.name>`.

### No arguments or "session"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session`. Switch on `state`:
- **`ok`** — show one line: "Active: `account.name` → project `project.id`". Add workspace `workspace.id` if it is not null. Mention `/mixpanel-headless:auth account list` and `/mixpanel-headless:auth project list` for a switch.
- **`needs_account`** — no account is configured. Show `next[0].command` (the one-shot `mp login`) as the recommended step. List the alternatives: `next[1]` (explicit account add) and `next[2]` (the `MP_OAUTH_TOKEN` environment variables, best for CI and agents).
- **`needs_project`** — an account exists but no project is pinned. Tell the user to run `mp project list`, then `mp project use <id>`.
- **`error`** — show `error.message`. If `error.actionable` is true, the message names the next command.

### "account list"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account list`. Show `items` as a table: `name`, `type`, `region`,
`is_active`. Mark the active account with a star. If `referenced_by_targets`
is not empty for an account, say so ("`team` is referenced by targets: `ecom`").

If `items` is empty, show the `next` onboarding hints (as for `needs_account`).

### "account add"

This is a guided wizard. Do not run any script that handles secrets.

1. Ask for the **account name** (for example "personal", "team", "ci").
2. Ask for the **type**: `oauth_browser` (recommended for laptops), `service_account` (long-lived), or `oauth_token` (CI and agents).
3. Ask for the **region**: us, eu, or in (default us).
4. For `service_account`, ask for the username and the numeric project ID. For `oauth_token`, ask for the project ID and the name of the environment variable that holds the bearer token. For `oauth_browser`, the project ID is optional, because `mp account login` fills it in after the browser flow.
5. Tell the user to run the matching command. For a service account:

```text
Now run this command. It prompts for your service account secret with hidden input:

! mp account add <NAME> --type service_account --username <USERNAME> --project <PROJECT_ID> --region <REGION>
```

For OAuth browser, prefer the one-shot `mp login` (see "login" above):

```text
! mp login --name <NAME> --region <REGION>
```

For full control over registration before the browser flow, the two-step path
still works:

```text
! mp account add <NAME> --type oauth_browser --region <REGION>
! mp account login <NAME>      # opens a browser for the PKCE flow
```

Replace the placeholders with the values you collected. The `!` prefix runs the
command in the user's terminal session.

6. After the user confirms, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account test <NAME>`.
7. Report success or failure from the `result.ok` field.

### "account use" or "account use <name>"

If a name is given, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account use <name>`.

If no name is given:
1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account list` to show the accounts.
2. Ask which one to use.
3. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account use <name>` with the chosen name.

On `state: ok`, show one line: "Switched to `active.account` (project `active.project`)".
On `state: error`, show `error.message`.

### "account login <name>"

The name is required. If it is missing, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account list` and ask.
Then run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account login <name>`.

Tell the user that a browser window opens for Mixpanel authentication. Wait for
the JSON response.

On `state: ok`: "OAuth login successful. `logged_in_as.user.email`, token
valid until `logged_in_as.expires_at`."
On `state: error`: show `error.message` and suggest a retry.

### "account test" or "account test <name>"

The script needs a name. If none is given, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session` and use
`account.name`. Then run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account test <name>`.

The subcommand does not raise, so `state` is always `ok`. Read `result.ok`:
- `result.ok: true` → "Connected as `result.user.email` · `result.accessible_project_count` accessible projects."
- `result.ok: false` → "Test failed: `result.error`."

### "project list"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py project list`. Show `items` as a table: organization, project name,
project ID. Mark the active project (`is_active: true`) with a star. Suggest
`/mixpanel-headless:auth project use <id>` for a switch.

### "project use <id>"

If no ID is given, run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py project list` first and ask which one to use.

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py project use <PROJECT_ID>`.

On `state: ok`: "Switched to project `active.project`."
On `state: error`: show `error.message`.

### "workspace list"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py workspace list`. Show `items` as a table: workspace ID, name,
`is_default`. Mark the active workspace with a star. Name the parent project
from `project.name` (`project.id`).

### "workspace use <id>"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py workspace use <WORKSPACE_ID>`.

On `state: ok`: "Pinned workspace `active.workspace`."

### "target list"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py target list`. A target is a saved (account, project, workspace?)
triple, a named cursor position. Show a table: name, account, project,
workspace.

### "target add"

This is a guided wizard. Collect the target name, the account name, the
project ID, and an optional workspace ID. Then run:

```text
python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py target add <NAME> --account <ACCT> --project <PROJ> [--workspace <WS>]
```

Or tell the user to run `! mp target add <NAME> --account <ACCT> --project <PROJ> [--workspace <WS>]`.

### "target use <name>"

Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py target use <name>`. It applies all three axes (`account`,
`project`, `workspace`) to `[active]` in one atomic config write.

## Bearer-token environment variables (`MP_OAUTH_TOKEN`)

For non-interactive contexts (CI, agents, short-lived environments), the
browser flow does not work. Set these instead:

```text
export MP_OAUTH_TOKEN=<bearer-token>
export MP_PROJECT_ID=<project-id>
export MP_REGION=<us|eu|in>
```

The library sends an `Authorization: Bearer <token>` header to every Mixpanel
endpoint. The full service-account set (`MP_USERNAME` + `MP_SECRET` +
`MP_PROJECT_ID` + `MP_REGION`) wins when both sets are complete. So it is safe
to add these to a shell that already exports the service-account variables.

## Presentation

- Show status in one or two lines, not a wall of JSON.
- Use tables for lists of accounts, projects, workspaces, and targets.
- When something is missing, suggest the next action.
- On an error, show `error.message` verbatim, because it names the fix.
