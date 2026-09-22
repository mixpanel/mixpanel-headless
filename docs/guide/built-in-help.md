# Built-in Help

Look up any part of the public API from Python or from the `mp` CLI — signatures, fields, allowed values, exception trees, and pointers to the hosted docs — without a network call and without credentials.

!!! tip "Offline by design"
    `mp.help()`, `mp.reference.describe()`, `mp.reference.search()`, and `mp help` introspect the installed package only. They make no HTTP request, read no config file, and never construct a `Workspace`. They work before `mp login` and inside a sandbox with no `MP_*` variables.

## Quick start

From Python:

```python
import mixpanel_headless as mp

mp.help()                          # overview: version, entry points, domains, grammar
mp.help("Workspace.query")         # signature, docstring, referenced types, see also, hint
mp.help("Filter")                  # construction, fields, properties, methods, used by
mp.help("MathType")                # allowed values, description, used by
mp.help("search cohort")           # search names, docstrings, enum members
mp.help(mp.Filter)                 # object form — same entry as the string form
```

From the CLI:

```bash
mp help                                   # overview
mp help Workspace                         # methods grouped by domain
mp help Workspace --domain "funnel query" # one domain only
mp help Workspace.query
mp help Filter -f json --jq '.construction[].name'
mp help MathType -f markdown
mp help search cohort
mp help exceptions --no-hints
python3 -m mixpanel_headless help Workspace.query   # when `mp` is not on PATH
```

Query tokens are split on whitespace, so `mp help search cohort` and `mp help "search cohort"` are the same query.

## Python surface

`mp.help()` prints and returns `None`, like the builtin. Structured access lives in `mixpanel_headless.reference`:

```python
import mixpanel_headless as mp
from mixpanel_headless import reference as ref

mp.help("Workspace", domain="funnel query")
mp.help("Workspace.query.events")               # one parameter
mp.help("Filter", format="json")                # machine-readable
mp.help("Workspace.query", format="markdown", hints=False)

entry = ref.describe("Workspace.query_funnel")  # HelpEntry
entry.kind                                      # "method"
entry.signature.params[0].name                  # "steps"
entry.to_dict()                                 # JSON-ready dict

hits = ref.search("retention")                  # SearchResult
hits.hits[0].name                               # sorted by category, then name

ref.render(entry, "markdown")                   # str
ref.clear_cache()                               # drop the per-process inventory cache
```

Signatures:

```python
def help(
    query: str | object | None = None,
    *,
    format: HelpFormat = "text",          # Literal["text", "markdown", "json"]
    file: TextIO | None = None,           # default sys.stdout
    hints: bool = True,
    domain: str | None = None,            # only with "Workspace"
) -> None: ...

def describe(query: str | object, *, hints: bool = True, domain: str | None = None) -> HelpEntry: ...
def search(term: str, *, limit: int | None = None) -> SearchResult: ...
def render(entry: HelpEntry | SearchResult, format: HelpFormat = "text") -> str: ...
def clear_cache() -> None: ...
```

Object queries are accepted. `mp.help(mp.Filter)`, `mp.help(ws.query)`, `mp.help(ws)`, `mp.help(mp.accounts)`, and `mp.help(mp)` resolve to the same entries as their string forms. A bound method resolves to `Workspace.<name>`. An object from outside the package raises `HelpLookupError`.

!!! warning "`help` shadows the Python builtin"
    `from mixpanel_headless import help` replaces the interactive `help()` builtin in that namespace. Import the package with an alias instead: `import mixpanel_headless as mp`, then call `mp.help(...)`. The REPL builtin and `python -m pydoc` are not affected.

## Query grammar

| Query | Result kind | What you get |
| --- | --- | --- |
| `None` or `""` | `overview` | Version, import line, five entry points, domain table with counts, grammar summary, `llms.txt` hint. |
| `Workspace` | `listing` | Methods grouped by domain; properties first. `domain=` / `--domain` filters to one group (case-insensitive; a unique prefix is accepted). |
| `Workspace.<method>` | `method` | Signature with one parameter per line, docstring sections, referenced types, see also (same domain), hint. |
| `Workspace.<property>` | `property` | Return annotation and docstring. |
| `Workspace.<method>.<param>` | `parameter` | Annotation, default, allowed values, and the description from the `Args:` section. |
| `<Model>` (Pydantic) | `model` | Bases, non-default config, construction, fields with constraints and JSON aliases, properties, methods, used by, hint. |
| `<Dataclass>` | `dataclass` | Same as `model`, with dataclass default and factory rules. |
| `<Enum>` | `enum` | Member table with values, docstring, used by. |
| `<LiteralAlias>` | `literal` | Allowed values, one-line description, used by with parameter names. |
| `<UnionAlias>` / `Account` | `alias` | Expanded members, each with its first doc line. |
| `<Exception>` | `exception` | Bases, docstring, subclass tree, and the `Workspace` methods whose `Raises:` section names it. |
| `<Class>.<member>` | `method` / `property` | Any public class, not only `Workspace`. |
| `<function>` | `function` | `login_unified`, `validate_bookmark`, the replay label helpers. |
| `accounts` / `session` / `targets` | `module` | `__all__` members with first doc lines and compact signatures. |
| `<constant>` | `constant` | Value and type. |
| `types` | `listing` | Public types grouped by kind: models, dataclasses, enums, literal aliases, other aliases, plain classes. No hints. |
| `exceptions` | `listing` | Indented tree from `MixpanelHeadlessError`. No hints. |
| `search <term>` | `search` | Case-insensitive substring match over names, docstring summaries, and enum members. |
| `help` | `function` | The function documents itself. |
| miss | raises `HelpLookupError` | "Did you mean?" suggestions plus the top search hits. |

Resolution order for a name: exact match, then a unique case-insensitive match (`filter` → `Filter`), then a miss. An ambiguous case-insensitive match is a miss.

## Output formats

Three formats, selected with `format=` in Python or `-f/--format` in the CLI. The CLI default is `text`.

**`text`** is a compact plain-text layout: a multi-line signature block, Google docstring sections, two-column rows, `Used by Workspace (N methods):` rows, a `See also` line, and one `---` / `Tip:` / `WebFetch(url=...)` block per hint. Output contains no Rich markup, so literal tags such as `[property]` survive.

An illustrative `mp help Workspace.create_dashboard` (the exact docstring text comes from the installed version):

```
Workspace.create_dashboard(
    params: CreateDashboardParams
) -> Dashboard

Create a new dashboard.

Args:
    params: Dashboard creation parameters.
...

Referenced types (2):
  CreateDashboardParams                      Parameters for creating a new dashboard.
  Dashboard                                  A Mixpanel dashboard as returned by the App API.

See also (dashboards): add_report_to_dashboard, bulk_delete_dashboards, delete_dashboard, ...

---
Tip: For dashboards, reports, and cohorts (entity management),
     WebFetch(url="https://mixpanel.github.io/mixpanel-headless/guide/entity-management/index.md")
```

An illustrative `mp help MathType`:

```
MathType = Literal[22 values]
  total | unique | dau | wau | mau | average | median | min | max | p25 | p75 | p90
  | p99 | percentile | histogram | cumulative_unique | sessions | unique_values
  | most_frequent | first_value | multi_attribution | numeric_summary

Aggregation for a plain-string event in Workspace.query / build_params and for Metric.math.

Used by Workspace (2 methods):
  build_params(math)
  query(math)
```

**`markdown`** uses `#` for the entry title, `##` per section, fenced `python` blocks for signatures and examples, pipe tables where the text format has columns, and hints as links under `## Further reading`. Paste it into a notebook or a chat context as-is.

**`json`** is `json.dumps(entry.to_dict(), indent=2)`. See [JSON shape](#json-shape).

## The `--domain` filter

`Workspace` has more than 200 public methods. `mp help Workspace` groups them into 32 domains, and `--domain NAME` (CLI) or `domain=NAME` (Python) shows one group. The match is case-insensitive and accepts a unique prefix, so `--domain funnel` selects `funnel query`. An unknown domain exits 3 in the CLI and raises `HelpLookupError` in Python. `domain=` with a query other than `Workspace` also raises `HelpLookupError`.

The 32 domain titles, in display order:

| | | | |
| --- | --- | --- | --- |
| `session and switching` | `discovery` | `lexicon schemas` | `streaming` |
| `legacy live queries` | `insights query` | `funnel query` | `retention query` |
| `flow query` | `user query` | `report links` | `dashboards` |
| `reports` | `cohorts` | `feature flags` | `experiments` |
| `annotations` | `webhooks` | `alerts` | `lexicon governance` |
| `drop filters` | `custom properties` | `custom events` | `lookup tables` |
| `tracking and history` | `schema registry` | `schema enforcement` | `data audit` |
| `volume anomalies` | `deletion requests` | `business context` | `session replay` |

The same registry drives the `See also (<domain>):` line on every `Workspace.<method>` entry: siblings are the other methods of the same domain.

## Hints

Most entries end with one or more hint blocks that point at a page on this site. The `text` format prints each hint as a `WebFetch(url=...)` line so an agent can fetch the page directly; `markdown` prints them as links under `## Further reading`; `json` lists them under `hints` with `title` and `url`. `types` and `exceptions` never carry hints. Pass `hints=False` in Python or `--no-hints` in the CLI to drop the section.

## JSON shape

`mp.reference.describe()` returns a frozen `HelpEntry` dataclass. `to_dict()` converts it recursively; every tuple becomes a list and every pair becomes a two-item list. The top-level keys, in order:

| Key | Type | Content |
| --- | --- | --- |
| `kind` | `str` | One of the result kinds from the grammar table. |
| `name` | `str` | Display name, for example `Workspace.query` or `Filter`. |
| `qualname` | `str` | Fully qualified import path. |
| `summary` | `str` | First docstring line. |
| `doc` | object | `summary`, `body`, `args` (pairs), `returns`, `raises` (pairs), `example`, `notes`. |
| `signature` | object or `null` | `name`, `params` (each: `name`, `annotation`, `default`, `description`, `values`), `returns`. |
| `bases` | `list[str]` | Public base class names. |
| `config` | pairs | Non-default Pydantic model config. |
| `construction` | list | Factory classmethods (`name`, `kind`, `summary`, `signature`). |
| `fields` | list | Public fields (`name`, `annotation`, `default`, `required`, `constraints`, `alias`, `values`, `description`). |
| `properties` | list | Public properties, same member shape as `construction`. |
| `methods` | list | Public methods, same member shape. |
| `values` | `list[str]` | Enum member names or literal values. |
| `groups` | list | `title` plus `items` (members) — `Workspace` domains, listings, module sections. |
| `referenced_types` | pairs | `(type_name, summary)` for a callable. |
| `used_by` | list | `Workspace` methods that accept this type (`method`, `params`). |
| `see_also` | `list[str]` | Sibling method names from the same domain. |
| `hints` | list | Hosted-docs pointers (`title`, `url`). |

A `search` query returns a `SearchResult` with `term`, `hits` (each: `category`, `name`, `summary`, `matched_on` ∈ `name` / `doc` / `member`), and `suggestions`.

## Tips for agents

- Use `-f json --jq EXPR` to extract one fact instead of a page of text: `mp help Workspace.query -f json --jq '.signature.params[].name'`, `mp help FilterOperator -f json --jq '.values'`. `--jq` requires `-f json`; without it the command exits 3.
- Use `mp help search TERM` before you guess a name. The hit list covers exports, `Workspace` members, and enum member values.
- Follow the hint at the bottom of an entry. Every hint URL ends in `index.md` and is safe to `WebFetch`. The site also publishes <a href="https://mixpanel.github.io/mixpanel-headless/llms.txt">`llms.txt`</a> (index) and <a href="https://mixpanel.github.io/mixpanel-headless/llms-full.txt">`llms-full.txt`</a> (everything in one file).
- In a sandbox where `mp` is not on `PATH`, `python3 -m mixpanel_headless help ...` accepts the same arguments.
- `mp help` ignores `-a / -p / -w / -t`. No account, project, or workspace is needed or consulted.

## Exit codes and errors

CLI exit codes:

| Code | Meaning |
| --- | --- |
| `0` | The query resolved. |
| `4` | Miss. Suggestions and the first search hits print to stdout. |
| `3` | `--jq` without `-f json`, or an unknown `--domain`. |

In Python, `describe()` raises `HelpLookupError` on a miss. `help()` catches it and prints the suggestions instead. `search()` raises it for an empty term. The exception carries the structured recovery data:

```python
import mixpanel_headless as mp
from mixpanel_headless import reference as ref

try:
    entry = ref.describe("Filtr")
except mp.HelpLookupError as exc:
    print(exc.query)         # "Filtr"
    print(exc.suggestions)   # close names, most similar first
    for hit in exc.hits:     # SearchHit records for the same term
        print(hit.category, hit.name)
```

`HelpLookupError` subclasses `MixpanelHeadlessError` directly, not `APIError`, because the lookup never touches the network.

## Next Steps

- [API Reference: Built-in help](../api/help.md) — `mixpanel_headless.reference` module docs
- [Exceptions](../api/exceptions.md#help-lookup-exceptions) — `HelpLookupError`
- [CLI Commands](../cli/commands.md#built-in-help) — `mp help` options
