---
name: mixpanelyst
description: Analyzes Mixpanel data with Python, the mixpanel_headless library, and pandas. Use when the user asks about their Mixpanel data, such as event trends, DAU/WAU/MAU, funnels, retention and churn, user paths, user profiles, cohorts, a user's tracked event history (activity feed), segment comparisons, revenue, feature adoption, or experiment results. Also use to explore a project's events and properties, build a custom property or cohort, share a query as a report link, read or write business context, or manage entities such as cohorts, feature flags, experiments, alerts, annotations, webhooks, Lexicon definitions, and other governance objects, or when code runs mixpanel_headless queries or `mp query` / `mp inspect`. Do not use for adding tracking to an app's source code, for what a specific user did on screen (use session-replay), for building or editing dashboards (use dashboard-expert), for logging in, credentials, or switching accounts (use auth), or for installing the library (run /mixpanel-headless:setup).
allowed-tools: Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/python *) Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/mp *) Bash(uv run *) Read Write Edit WebFetch(domain:mixpanel.github.io)
---

# Mixpanel analysis with mixpanel_headless

Answer questions about Mixpanel data. Write and run Python that uses the `mixpanel_headless` library and pandas. This skill teaches judgment: which query answers the question, which defaults mislead, and how to check a result. The library itself is the API reference.

Installed in the plugin environment: !`${CLAUDE_PLUGIN_DATA}/venv/bin/python -m mixpanel_headless --version 2>/dev/null || echo "plugin environment not set up; run /mixpanel-headless:setup"`

!`${CLAUDE_PLUGIN_DATA}/venv/bin/mp help 2>/dev/null | grep -A 30 "^Workspace domains" || echo "Domain list unavailable (needs mixpanel_headless 0.3.0 or later); run /mixpanel-headless:setup"`

## Run code in the plugin environment

The plugin keeps its own Python environment. Run Python with `${CLAUDE_PLUGIN_DATA}/venv/bin/python`: add `-c "..."` for a quick look, or a script path for multi-step work. In this skill, `mp` means `${CLAUDE_PLUGIN_DATA}/venv/bin/mp`. Run it with that full path. The examples keep the short form `mp help <query>`.

If that interpreter does not exist, or the version above is older than 0.3.0, ask the user to run `/mixpanel-headless:setup`. When the user's project already has mixpanel_headless (for example, a uv project), `uv run python` also works.

## Mental model

`ws = mp.Workspace()` is the one entry point. It holds the session: account, project, and workspace. It resolves credentials from the environment and `~/.mp/config.toml`. Five query engines answer five kinds of question:

| Question | Method |
| --- | --- |
| How much, how many, what trend? | `ws.query()` |
| Do users complete a sequence of steps? | `ws.query_funnel()` |
| Do users come back? | `ws.query_retention()` |
| What paths do users take? | `ws.query_flow()` |
| Who are the users, and how many match? | `ws.query_user()` |

Every result has `.df` (a pandas DataFrame) and `.params` (the report definition that Mixpanel ran). A flow result also has `.graph` (a networkx graph). Each engine has a `build_*_params` twin that returns params without a network call, and a `run_*_params` twin that runs edited params. Beyond queries, `ws` also covers discovery, streaming, entity management (dashboards, reports, cohorts, flags, experiments, Lexicon, and more), business context, and session replay. The domain list above names every area.

## Workflow

1. **Ground in the schema.** Confirm that each event carries each property that you plan to filter or break down. Reason: a filter on a property that the event does not carry returns zeros, not an error. When the question names one or two known events, use `ws.properties("<event>")`. For an unfamiliar project, run `ws.schema_graph(include_density=True)` once, then `schema.properties_for_event("<event>")`. Use `ws.events()` and `ws.property_values("<property>", event="<event>")` to confirm exact names and values.
2. **Look up the API.** Use the look-up loop below for each method or type that you did not look up in this session.
3. **Write and run.** Use `-c "..."` with the plugin interpreter for one quick look. Write a `.py` file for multi-step work and run it with the same interpreter, so that you can edit and run it again.
4. **Check before you present.** Look at the row count and the date range. Treat an empty or all-zero result as a question, not an answer. Compare the magnitude with a simple total (`ws.query("<event>", mode="total")`). Look for gaps in a time series.
5. **Share when asked.** When the user wants to share or open the result in Mixpanel, pass the result to `ws.create_report_link(result, name="...")` and give them `link.url`. Each call stores a new record on the server, so do not create links that nobody asked for.

## The look-up loop: check the API before you write code

The installed library documents itself. Its answers match the installed version, so trust them over memory and over any example in this skill. Do not guess API names: a wrong parameter name costs a failed run, and a look-up costs one call of about one second, with no credentials and no network.

1. Find the name: `mp help search <term>` (for example `mp help search retention`).
2. Read the signature: `mp help Workspace.query_funnel`.
3. For the allowed values of a parameter, run `mp help Workspace.<method>.<param>` first, for example `mp help Workspace.query_funnel.math`. Do this before you read a reference file or fetch a guide, because it lists every value for the installed version.
4. Read a type before you build it. `mp help Filter` lists its constructors. `mp help MathType` lists its values.
5. List a whole area: `mp help Workspace --domain "feature flags"`. `mp help` alone prints the domains.
6. Write the code and run it. If it fails, read the error. The error text often names the fix.

Look up each name once per session and reuse the answer. Add `-f json` only when you want to extract fields, for example `mp help Filter -f json --jq '.construction[].name'`. Inside Python, `mp.help("Workspace.query")` prints the same text. `mp help types` and `mp help exceptions` list all public types and exceptions.

A "Tip" line at the end of `mp help` output points to a hosted guide. Fetch it with WebFetch when you need a tutorial rather than a signature.

If `mp help` reports `No such command`, the library in the plugin environment is older than 0.3.0, so ask the user to run `/mixpanel-headless:setup`.

## Choose the parameters on purpose

Each engine has a "master dial": one setting that changes every number downstream. Choose it to match the product's natural usage cadence. Do not accept the default without a reason. When you are not sure, run two or three values and compare. A result that holds across values is a signal. A result that flips is an artifact of the setting.

- **Insights:** `math` (with `math_property` and `per_user`) decides what you count: people, events, or a property value. Read [insights.md](references/insights.md).
- **Funnels:** `conversion_window` and `conversion_window_unit` decide who converts. Also choose `order` on purpose. Read [funnels.md](references/funnels.md).
- **Retention:** `retention_unit` and `bucket_sizes` decide what "came back" means. Read [retention.md](references/retention.md).
- **Flows:** `forward`, `reverse`, and `count_type` decide the shape of the paths. Read [flows.md](references/flows.md).
- **Users:** `mode` decides between a count and profile rows. Read [users.md](references/users.md).

Prefer a median to a mean for money and other property values, because one outlier moves a mean. If the mean and the median differ a lot, the distribution is skewed, so report the median.

## Gotchas

Each of these returns a plausible but wrong answer, or fails in a way that looks like a data problem.

- **`last=` is always days, on every engine.** `last=4, unit="week"` covers 4 days, not 4 weeks. `unit` sets the bucket size only. Use `last=28` or `from_date`/`to_date`.
- **`math` decides what `math_property` means.** Count math such as `"unique"` or `"dau"` with a `math_property` raises a validation error. There is no `"sum"` value: to sum a property, use `math="total"` with `math_property`.
- **`per_user` needs `math_property`.** Without it, or with count math, the query raises a validation error. Per-user math aggregates a property value per user first.
- **`mode="total"` returns one value for the whole range.** A change to `unit` does not change a plain count in this mode. Use `mode="timeseries"` for a trend.
- **`rolling` reduces the number of points.** A 30-day rolling window over 59 days gives about 30 points, not 59, because the early periods have no full window.
- **A `FrequencyFilter` counts per `unit` bucket, not over the whole range.** With the default `unit="day"`, "at least 3 times" means 3 times in one day. An empty series can be the correct answer. Choose the `unit` that matches the period that the user means.
- **A missing property gives zeros, not an error.** A filter or breakdown on a property that the event does not carry returns an empty or zero result. Check the schema first (workflow step 1).
- **In event queries, a filter on a user profile property needs `resource_type="people"`.** The default is `"events"`, which looks for an event property of the same name and usually matches nothing. `ws.query_user()` filters are profile filters already.
- **`ws.query_user()` returns a count by default.** Its default `mode` is `"aggregate"` and its default `limit` is 1. For profile rows, pass `mode="profiles"` and a `limit`.
- **`ws.top_events()` shows today only.** It is not a ranking over a period. For volume over a period, run `ws.query()` in `mode="total"`.
- **Funnel `math="median"` is not time to convert.** Property math on a funnel aggregates the numeric `math_property`. Funnel times come only as means (`avg_time`, `avg_time_from_start`, in seconds), so say that they are means.
- **Entity methods act on one workspace.** The library picks a workspace automatically on the first App API call, and raises `WorkspaceScopeError` if it cannot. When the project has several workspaces and the user means a specific one, list them with `ws.workspaces()` and pin one with `ws.use(workspace=<id>)`.
- **A report link from another project or region raises `ReportLinkScopeMismatchError`.** The check runs before the record fetch. The message names the `ws.use(...)` call that fixes it.
- **A shortlink (`/s/<code>`) can fail with `AuthenticationError`.** The shortlink can redirect to the login page, so the API cannot expand it. Ask the user for the full URL from the browser address bar.
- **Demo and test projects can have old data.** When a result is empty, widen the date range with `from_date` before you conclude that nothing happened.
- **`ws.schema_graph()` can take minutes on a very large project.** Its cache lasts only inside one Python process. Separate `-c` runs fetch it again, so do multi-step work in one `.py` file, or save the schema to a file.
- **Sweeps multiply queries and can hit the rate limit.** Cap each loop at a few values, and run the queries one after another, not in parallel. On `RateLimitError`, wait `e.retry_after` seconds (when it is set) before you retry.

## Reading guide

Read a reference file only when its condition applies. Each file holds judgment and examples that this file leaves out.

| Read | When |
| --- | --- |
| [insights.md](references/insights.md) | Before any `ws.query()` that uses non-default math, `per_user`, a property sum, formulas, or rolling windows |
| [funnels.md](references/funnels.md) | Before any funnel query |
| [retention.md](references/retention.md) | Before any retention query |
| [flows.md](references/flows.md) | Before any flow query |
| [users.md](references/users.md) | Before any user profile query or cohort count |
| [exploration.md](references/exploration.md) | When the user asks for insights, a "look around", or works in an unfamiliar project |
| [segmentation.md](references/segmentation.md) | When a breakdown needs derived values, a behavioral population (inline cohort), or a frequency threshold |
| [custom-property-formulas.md](references/custom-property-formulas.md) | Before you write any formula for a custom property (inline or saved) |
| [business-context.md](references/business-context.md) | When the user asks to read, write, audit, or seed business context |
| [entities.md](references/entities.md) | Before you create, update, or delete a Mixpanel entity (reports, cohorts, flags, experiments, alerts, Lexicon, and so on; for dashboards, use the `dashboard-expert` skill) |
| The `session-replay` skill | When the user asks what a specific user did on screen, or about rage clicks, dead clicks, or recordings |
| The `dashboard-expert` skill | When the user asks to build, change, or explain a dashboard |
| The `auth` skill | When `mp.Workspace()` raises `ConfigError` or `AuthenticationError`, or reports no account or no project |
| `/mixpanel-headless:setup` | When the plugin interpreter is missing, the import fails, or `mp help` does not exist |

## Output

- Lead with the answer in one or two sentences. Then show the numbers, the date range, and the filters that you used.
- State each assumption that changes the number, for example the conversion window or the counting method.
- For a chart, call `matplotlib.use("Agg")` before you import `pyplot`, and save the chart to a file. Reason: the shell has no display. Tell the user the file path.
- When the user asks to share, send, or open a result in Mixpanel, give them `link.url` from `ws.create_report_link(...)`.

## Worked example

Question: "What share of iOS users who sign up go on to purchase within a day? Send me a link to the report."

```python
import mixpanel_headless as mp
from mixpanel_headless import Filter

ws = mp.Workspace()

# 1. Ground in the schema: confirm that each step event carries "platform".
for event in ["Sign Up", "Purchase"]:
    print(event, "platform" in ws.properties(event))
print(ws.property_values("platform", event="Sign Up"))  # exact value, e.g. "iOS"

# 2. Look-ups done before this code:
#    mp help Workspace.query_funnel
#    mp help Filter.equals

# 3. Run the funnel. A one-day window matches "within a day".
result = ws.query_funnel(
    ["Sign Up", "Purchase"],
    conversion_window=1,
    conversion_window_unit="day",
    where=Filter.equals("platform", "iOS"),
    last=90,
)
print(result.df)
print(f"Overall conversion: {result.overall_conversion_rate:.1%}")

# 4. Check: compare with a wider window before you present.
wide = ws.query_funnel(
    ["Sign Up", "Purchase"],
    conversion_window=7,
    conversion_window_unit="day",
    where=Filter.equals("platform", "iOS"),
    last=90,
)
print(f"7-day window: {wide.overall_conversion_rate:.1%}")

# 5. The user asked for a link, so share the query as a report link.
link = ws.create_report_link(result, name="iOS signup to purchase, 1-day window")
print(link.url)
```

Report the one-day rate as the answer. Mention the 7-day rate as context, and give the user the link.
