---
name: setup
description: Installs or upgrades mixpanel_headless (0.3.0 or newer) with pandas, numpy, matplotlib, seaborn, networkx, anytree, scipy, and pyarrow (Python 3.11+ only) on Python 3.10+, then checks the imports, mp help, and the credentials. Use when setting up Mixpanel analysis, or when the library is missing or older than 0.3.0. Do not use for login or account changes (use auth).
disable-model-invocation: true
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh) Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py *)
---

# mixpanel-headless setup

Install the library and its analysis stack, then confirm that the plugin works.

## 1. Run the setup script

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh
```

The script does these steps:

1. Finds Python 3.10 or newer.
2. Installs `mixpanel-headless>=0.3.0` and the analysis packages with `uv`, or with `pip` when `uv` is not available. The version floor upgrades an older install, because the skills depend on `mp help`, which first shipped in 0.3.0.
3. Imports every package and prints its version.
4. Runs `mp help` once, offline, to confirm that the built-in API reference works.
5. Checks that the `mp` command is on `PATH`.
6. Reports which credentials it finds.

The script is safe to run again. It does not prompt for input.

## 2. Read the result

Read these lines in the output:

| Line | Meaning |
| --- | --- |
| `✓ mixpanel-headless INSTALLED <version>` | The library was not present. The script installed it. |
| `✓ mixpanel-headless UPGRADED <old> → <new>` | An older library was present. The script upgraded it. |
| `✓ mixpanel-headless OK <version>` | The library already met the 0.3.0 floor. |
| `✓ built-in help (mp help)` | The API reference works. The skills can look up API names. |
| `✓ mp on PATH` | The `mp` command runs directly. |
| `⚠ mp not on PATH; ...` | Not an error. The skills fall back to `python3 -m mixpanel_headless`. To get `mp`, add the Python scripts directory to `PATH`. |
| `✗ Python 3.10+ required` | Tell the user to install Python 3.10 or newer. |
| `✗ No package manager found` | Tell the user to install `uv` (https://docs.astral.sh/uv/) or `pip`. |
| `✗ Import verification failed` | Show the error. A partial install or a wrong interpreter is the usual cause. |
| `✗ built-in help (mp help) failed` | The installed library is older than 0.3.0. Show the install output. A pinned version or a second Python is the usual cause. |

If the script printed `UPGRADED`, tell the user to restart any Python kernel or
notebook that imported the old version.

## 3. Check the credentials

Run the auth helper. It prints one JSON object:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session
```

Switch on the `state` field:

- **`ok`** — show "`account.name` → project `project.id`". Go to step 4.
- **`needs_account`**, **`needs_project`**, or **`error`** — hand the problem to the `auth` skill. Tell the user to run `/mixpanel-headless:auth`. That skill owns the login, account, project, and security flows. Do not repeat those flows here.

## 4. Verify the connection

Test the active account. Use `account.name` from step 3, because the script needs a name:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account test <account.name>
```

The subcommand does not raise. Read `result.ok`:

- `result.ok: true` — setup is complete. The user can ask analytics questions. The `mixpanelyst` skill loads automatically for them.
- `result.ok: false` — show `result.error`. Hand the problem to the `auth` skill (`/mixpanel-headless:auth account test <name>`).
