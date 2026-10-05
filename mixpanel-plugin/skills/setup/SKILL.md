---
name: setup
description: Creates the plugin's own Python environment and installs or upgrades mixpanel_headless (0.3.0 or newer) with pandas, numpy, matplotlib, seaborn, networkx, anytree, scipy, and pyarrow (Python 3.11+ only) on Python 3.10+, then checks the imports, mp help, and the credentials. Use when setting up Mixpanel analysis, or when the plugin environment is missing or older than 0.3.0. Do not use for login or account changes (use auth).
disable-model-invocation: true
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh ${CLAUDE_PLUGIN_DATA}/venv) Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py *)
---

# mixpanel-headless setup

Create the plugin environment, install the library and its analysis stack into
it, then confirm that the plugin works.

The plugin environment is a virtual environment at `${CLAUDE_PLUGIN_DATA}/venv`.
The script installs nothing outside it, so it never changes the user's global
or system Python. The environment stays in place when the plugin updates. All
skills run Python as `${CLAUDE_PLUGIN_DATA}/venv/bin/python` and the CLI as
`${CLAUDE_PLUGIN_DATA}/venv/bin/mp`.

## 1. Run the setup script

Run this command exactly as written, because the pre-approved pattern matches
this text:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh ${CLAUDE_PLUGIN_DATA}/venv
```

The script does these steps:

1. Creates the environment with `uv venv`, or with `python3 -m venv` when `uv` is not available. It reuses an environment that already works.
2. Installs `mixpanel-headless>=0.3.0` and the analysis packages into it. The version floor upgrades an older install, because the skills depend on `mp help`, which first shipped in 0.3.0.
3. Imports every package and prints its version.
4. Runs `mp help` once, offline, to confirm that the built-in API reference works.
5. Checks the `mp` command inside the environment.
6. Reports which credentials it finds.
7. Prints the environment path.

The script is safe to run again. It does not prompt for input.

## 2. Read the result

Read these lines in the output:

| Line | Meaning |
| --- | --- |
| `✓ Plugin environment created` or `found` | The environment exists at the printed path. |
| `✓ mixpanel-headless INSTALLED <version>` | The library was not present. The script installed it. |
| `✓ mixpanel-headless UPGRADED <old> → <new>` | An older library was present. The script upgraded it. |
| `✓ mixpanel-headless OK <version>` | The library already met the 0.3.0 floor. |
| `✓ built-in help (mp help)` | The API reference works. The skills can look up API names. |
| `✓ mp CLI: <path>` | The `mp` command exists in the environment. |
| `✗ Usage: setup.sh <absolute-venv-path>` | The plugin data path was not filled in. Run `/mixpanel-headless:setup` again. |
| `✗ Python 3.10+ required but not found` | Tell the user to install Python 3.10 or newer, or `uv` (https://docs.astral.sh/uv/). |
| `✗ Could not create the virtual environment` | Show the explanation the script printed. On Debian and Ubuntu, the usual fix is `uv` or the `python3-venv` package. |
| `✗ ... is not a virtual environment` | Something else uses that path. Tell the user to move it away. |
| `✗ Package install failed` | Show the installer output. A network or package-index problem is the usual cause. |
| `✗ Import verification failed` | Show the error. A partial install is the usual cause. Run setup again. |
| `✗ built-in help (mp help) failed` | The installed library is older than 0.3.0. Show the install output. |

If the script printed `UPGRADED`, tell the user to restart any Python kernel or
notebook that imported the old version.

Tell the user the environment path from the last lines. They can run their own
scripts with `${CLAUDE_PLUGIN_DATA}/venv/bin/python`.

## 3. Check the credentials

Run the auth helper. It prints one JSON object:

```bash
${CLAUDE_PLUGIN_DATA}/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py session
```

Switch on the `state` field:

- **`ok`** — show "`account.name` → project `project.id`". Go to step 4.
- **`needs_account`**, **`needs_project`**, or **`error`** — hand the problem to the `auth` skill. Tell the user to run `/mixpanel-headless:auth`. That skill owns the login, account, project, and security flows. Do not repeat those flows here.

## 4. Verify the connection

Test the active account. Use `account.name` from step 3, because the script needs a name:

```bash
${CLAUDE_PLUGIN_DATA}/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py account test <account.name>
```

The subcommand does not raise. Read `result.ok`:

- `result.ok: true` — setup is complete. The user can ask analytics questions. The `mixpanelyst` skill loads automatically for them.
- `result.ok: false` — show `result.error`. Hand the problem to the `auth` skill (`/mixpanel-headless:auth account test <name>`).
