# mixpanel-headless plugin

Analyze Mixpanel data with Python. Ask a question in plain language. Claude writes and runs Python with the [`mixpanel_headless`](https://mixpanel.github.io/mixpanel-headless/) library and pandas, then answers from the result.

The plugin has five skills: analysis, session replay, dashboards, authentication, and setup. The skills teach judgment: which query engine fits a question, which defaults mislead, and how to read a result. The library documents its own API. Claude looks up signatures, types, and allowed values with `mp help` (shell) or `mp.help()` (Python), so the answers always match the installed version.

## Quick start

```text
/mixpanel-headless:setup                 # create the plugin's Python environment, check credentials
"How many signups last week?"            # insights query
"Where do users drop off in checkout?"   # funnel
"Do users come back after onboarding?"   # retention
"What do users do after signup?"         # flows
"Watch the last session for user 123"    # session replay
"Build a KPI dashboard for growth"       # dashboards
```

## Skills

| Skill | Invocation | Use |
|-------|------------|-----|
| `mixpanelyst` | Automatic on analytics questions | Insights, funnels, retention, flows, and user queries; schema exploration; entity management; business context |
| `session-replay` | Automatic on session replay questions | Find, fetch, and analyze session recordings for web and mobile (rage clicks, rage taps, dead clicks, errors, action timelines) |
| `dashboard-expert` | Automatic on dashboard requests | Read, explain, build, and change dashboards, text cards, and layouts |
| `auth` | `/mixpanel-headless:auth` | Show the session; add, log in, and switch accounts, projects, workspaces, and targets |
| `setup` | `/mixpanel-headless:setup` | Create or upgrade the plugin's private Python environment with `mixpanel_headless` (0.3.0 or later), verify it, and check for credentials |

`setup` runs only when you call it. The other skills also load when your request matches their description.

## API reference: `mp help`

The library ships its own reference. It needs no credentials and makes no network call.

```bash
mp help                                  # overview and the list of Workspace domains
mp help search cohort                    # find names by keyword
mp help Workspace.query_funnel           # signature, docstring, and referenced types
mp help Workspace.query_funnel.math      # one parameter and its allowed values
mp help Filter                           # fields and constructors of a type
mp help Workspace --domain "feature flags"   # every method in one area
mp help Filter -f json                   # machine-readable output
```

The skills run these commands with the `mp` from the plugin's Python environment (see below). In Python, `mp.help("Workspace.query")` prints the same text, and `mp.reference.search("cohort")` returns structured results. The [hosted documentation](https://mixpanel.github.io/mixpanel-headless/) has guides and tutorials.

## Query engines

| Engine | Method | Question |
|--------|--------|----------|
| Insights | `ws.query()` | How much? How many? What is the trend? |
| Funnels | `ws.query_funnel()` | Do users convert through a sequence of steps? |
| Retention | `ws.query_retention()` | Do users come back? |
| Flows | `ws.query_flow()` | What paths do users take? |
| Users | `ws.query_user()` | Who are the users, and what do their profiles show? |

```python
import mixpanel_headless as mp

ws = mp.Workspace()
signups = ws.query("Signup", last=30, unit="day", group_by="platform")
print(signups.df)

funnel = ws.query_funnel(["Signup", "Onboarding Complete", "First Purchase"])
print(funnel.overall_conversion_rate)
```

Each result has a `.df` property that returns a pandas DataFrame. Run `mp help <ResultType>` for the other fields of a result.

## Beyond queries

The library also creates, reads, updates, and deletes Mixpanel entities through the App API:

- Dashboards, reports (bookmarks), and cohorts
- Feature flags and experiments
- Alerts, annotations, and webhooks
- Data governance: Lexicon definitions, drop filters, custom properties, custom events, lookup tables, and schemas
- Business context: the markdown documentation that grounds AI assistants, at organization and project scope

Entity methods need a workspace ID. The library resolves it on the first call that needs it (`ws.resolve_workspace_id()`). Business context belongs to the project and the organization, so it needs a project only.

## Authentication

The library supports three account types:

- `service_account`: username and secret (Basic Auth)
- `oauth_browser`: browser login with PKCE; tokens refresh automatically
- `oauth_token`: a static bearer token for CI and agents

Each account gives access to projects, and each project has workspaces. The recommended first command is `mp login`. It detects the account type from the environment, finds the region, names the account, and selects a default project. For the browser login, the region defaults to `us`; pass `--region eu` or `--region in` for other data centers.

Run `/mixpanel-headless:auth` to see the session or to switch accounts, projects, workspaces, or saved targets.

## Installation

From GitHub:

```bash
/plugin marketplace add mixpanel/mixpanel-headless
/plugin install mixpanel-headless@mixpanel-headless-marketplace
```

Then run `/mixpanel-headless:setup`. The skills need `mixpanel_headless` 0.3.0 or later, because `mp help` first shipped in 0.3.0.

### The plugin's Python environment

Setup creates a private Python environment at `~/.claude/plugins/data/mixpanel-headless-<source>/venv`. It uses `uv venv` when uv is installed, and `python3 -m venv` otherwise. With uv, a Python 3.10 or later on your `PATH` is optional, because uv can supply one. Setup installs `mixpanel-headless` 0.3.0 or later and the analysis packages into that environment only. It never installs into your system or user Python. Run setup again at any time; it reuses the environment and upgrades the packages.

- The skills run that environment's `python` and `mp`, not the ones on your `PATH`.
- The environment survives plugin updates, because its folder name has no version.
- To run your own scripts with it, run `<venv>/bin/python your_script.py`, where `<venv>` is the path setup prints at the end.
- `mp` from this environment is often not on your `PATH`. Run it as `<venv>/bin/mp` (for example, `<venv>/bin/mp login`).
- Alternatively, install `mixpanel-headless` in your own project (for example, `uv add mixpanel-headless`).

### Local development

```bash
claude --plugin-dir /path/to/mixpanel-headless/mixpanel-plugin
```

Run `/reload-plugins` to load changes without a restart.

## Permissions

When `mixpanelyst`, `session-replay`, or `dashboard-expert` runs, Claude Code pre-approves these tools for that turn, so analysis code runs without a prompt for each command:

- The plugin environment's `python` and `mp` (full paths under `~/.claude/plugins/data/mixpanel-headless-<source>/venv/bin/`)
- `uv run` commands
- File reads, writes, and edits
- Fetches from the documentation site (`mixpanel.github.io`)

The pre-approval also covers `mp` commands and Python code that change or delete Mixpanel objects. The skills tell Claude to list the objects and get your confirmation before any delete. Your own permission rules take precedence over the pre-approval. To get a prompt for each command, add ask rules for these tools (for example, a `Bash(...)` rule for the environment's `mp` path) to your Claude Code permission settings. To block a command, add a deny rule.

`setup` and `auth` pre-approve only their own scripts: `setup` runs its install script, and `auth` runs its script with the environment's `python`.

## Prerequisites

- Python 3.10 or later, or `uv` (setup builds the plugin environment with one of them)
- A Mixpanel account: a service account, a browser login, or an OAuth token
- Claude Code with plugins enabled

## Directory structure

```text
mixpanel-plugin/
├── .claude-plugin/
│   └── plugin.json                  # plugin manifest
├── skills/
│   ├── mixpanelyst/
│   │   ├── SKILL.md                 # analysis workflow, gotchas, look-up loop
│   │   └── references/              # one file per query engine and topic
│   ├── session-replay/
│   │   ├── SKILL.md                 # replay discovery and analysis
│   │   └── references/              # mobile capture, wireframes, rage taps
│   ├── dashboard-expert/
│   │   ├── SKILL.md                 # analyze, build, modify, explain
│   │   └── references/              # layout, text cards, report pipeline, chart types, templates
│   ├── auth/
│   │   ├── SKILL.md                 # /mixpanel-headless:auth
│   │   └── scripts/auth_manager.py  # auth status and management (JSON output)
│   └── setup/
│       ├── SKILL.md                 # /mixpanel-headless:setup
│       └── scripts/setup.sh         # creates the Python environment and installs the library
├── evals/                           # behavior evals (claude plugin eval)
├── docs/
│   ├── quickstart-claude-code.md    # getting started in Claude Code
│   └── getting-started-guide.md     # full guide
└── README.md
```

## Links

- [Library documentation](https://mixpanel.github.io/mixpanel-headless/)
- [Source repository](https://github.com/mixpanel/mixpanel-headless)

## License

MIT
