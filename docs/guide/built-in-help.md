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
mp.help("search cohort")           # search names, docstrings, enum members, Literal values
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
hits.hits[0].name                               # best match tier first, then category, then name

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
| `types` | `listing` | Public types grouped by kind: models, dataclasses, enums, literal aliases, other aliases, protocols and plain classes. Every row carries a one-line summary. No hints. |
| `exceptions` | `listing` | Indented tree from `MixpanelHeadlessError`. No hints. |
| `search <term>` | `SearchResult` | Case-insensitive substring match over names, docstring summaries, enum members, and Literal values. Hits sort by match tier (`name`, then `doc`, then `member`), then category, then name. |
| `help` | `function` | The function documents itself. |
| miss | raises `HelpLookupError` | One line, `No help entry for 'X'. Did you mean: a, b?`, followed by the search view for the same term. |

Resolution order for a name: exact match, then a unique case-insensitive match (`filter` → `Filter`), then a miss. An ambiguous case-insensitive match is a miss.

## Output formats

Three formats, selected with `format=` in Python or `-f/--format` in the CLI. The CLI default is `text`.

**`text`** is a compact plain-text layout: a multi-line signature block, Google docstring sections, two-column rows, `Used by Workspace (N methods):` rows, a `See also` line, and one `---` / `Tip:` / `WebFetch(url=...)` block per hint. Output contains no Rich markup, so literal tags such as `[property]` survive.

`mp help Workspace.segmentation` (the docstring text comes from the installed version):

```
Workspace.segmentation(
    event: str,
    *,
    from_date: str,
    to_date: str,
    on: str | None = None,
    unit: Literal['day', 'week', 'month'] = 'day',
    where: str | None = None
) -> SegmentationResult

Run a segmentation query against Mixpanel API.

Args:
    event: Event name to query.
    from_date: Start date (YYYY-MM-DD).
    to_date: End date (YYYY-MM-DD).
    on: Optional property to segment by.
    unit: Time unit for aggregation.
    where: Optional WHERE clause.

Returns:
    SegmentationResult with time-series data.

Raises:
    ConfigError: If API credentials not available.

Referenced types (2):
  SegmentationResult                         Result of a segmentation query.
  TimeUnit                                   Bucket size for the legacy live queries segmentation, retention, event_counts, property_counts, and frequency, and the retention_unit of Workspace.query_retention / build_retention_params.

See also (legacy live queries): activity_feed, event_counts, frequency, funnel, property_counts, query_saved_flows, query_saved_report, retention, segmentation_average, segmentation_numeric, segmentation_sum

---
Tip: For segmentation, funnels, retention (legacy live queries),
     WebFetch(url="https://mixpanel.github.io/mixpanel-headless/guide/live-analytics/index.md")
```

Signatures follow `inspect.signature`: a bare `*,` line precedes the first keyword-only parameter when no `*args` does, and a `/` line follows the last positional-only parameter. In JSON the same fact is `ParamDoc.kind`, one of `positional_only`, `positional_or_keyword`, `var_positional`, `keyword_only`, `var_keyword`. On a class entry the factory classmethods and staticmethods print under `Construction (N):`.

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

---
Tip: For MathType, Filter, GroupBy, Formula, validation rules,
     WebFetch(url="https://mixpanel.github.io/mixpanel-headless/guide/query/index.md")
```

**`markdown`** uses `#` for the entry title, `##` per section, fenced `python` blocks for signatures and examples, pipe tables where the text format has columns, and hints as links under `## Further reading`. Paste it into a notebook or a chat context as-is.

**`json`** is `json.dumps(entry.to_dict(), indent=2)`. See [JSON shape](#json-shape).

## The `--domain` filter

`Workspace` has more than 200 public methods. `mp help Workspace` groups them into 32 domains, and `--domain NAME` (CLI) or `domain=NAME` (Python) shows one group. The match is case-insensitive and accepts a unique prefix, so `--domain funnel` selects `funnel query`. An unknown domain, an ambiguous prefix (`--domain s` matches five titles), or `domain=` with a query other than `Workspace` raises `HelpDomainError` in Python and exits 3 in the CLI, which prints the message and the candidate titles on one `Domains:` line to stderr. See [Exit codes and errors](#exit-codes-and-errors).

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

Most entries end with one or more hint blocks that point at a page on this site. The `text` format prints each hint as a `WebFetch(url=...)` line so an agent can fetch the page directly; `markdown` prints them as links under `## Further reading`; `json` lists them under `hints` with `title` and `url`. Every `Workspace` domain has at least one hint rule, so every `Workspace.<method>` entry ends with a pointer. `types` and `exceptions` never carry hints. Pass `hints=False` in Python or `--no-hints` in the CLI to drop the section.

## JSON shape

`mp.reference.describe()` returns a frozen `HelpEntry` dataclass. `to_dict()` converts it recursively; every tuple becomes a list and every pair becomes a two-item list. The top-level keys, in order:

| Key | Type | Content |
| --- | --- | --- |
| `kind` | `str` | One of the result kinds from the grammar table (`HelpKind`). |
| `name` | `str` | Display name, for example `Workspace.query` or `Filter`. |
| `qualname` | `str` | Canonical help query for the entry, for example `Workspace.query` or `Filter`. Pass it back to `describe()` to get the same entry. Not an import path. |
| `summary` | `str` | First docstring line. |
| `doc` | object | `summary`, `body`, `args` (pairs), `returns`, `raises` (pairs), `example`, `notes`. |
| `signature` | object or `null` | `name`, `params`, `returns`. Each param: `name`, `annotation` (`null` when absent), `default`, `description`, `values`, `kind`. |
| `bases` | `list[str]` | Public base class names; for a constant, the one type name of its value. |
| `config` | pairs | Non-default Pydantic model config. |
| `construction` | list | Factory classmethods and staticmethods, each a member (`name`, `kind`, `summary`, `signature`, `depth`). |
| `fields` | list | Public fields (`name`, `annotation`, `default`, `required`, `constraints`, `alias`, `values`, `description`). An enum reuses this shape for its members. |
| `properties` | list | Public properties, same member shape as `construction`. |
| `methods` | list | Public methods, same member shape. |
| `values` | `list[str]` | Enum member names, Literal values, or union member names. `[]` for a constant. |
| `value` | `str` or `null` | The `repr` of a constant's value (an enum member such as `FeatureFlagStatus.ENABLED` is a constant). `null` for every other kind. |
| `groups` | list | `title` plus `items` (members). `Workspace` domains, listings, module sections, and exception subclass trees. `[]` for a method. |
| `referenced_types` | pairs | `(type_name, summary)` for a callable. |
| `used_by` | list | `Workspace` methods that accept this type (`method`, `params`). |
| `domain` | `str` or `null` | Registry domain title of a `Workspace` method, for example `legacy live queries`. `null` for every other kind. |
| `see_also` | `list[str]` | Sibling method names from the same domain. |
| `hints` | list | Hosted-docs pointers (`title`, `url`). |

A member (`construction`, `properties`, `methods`, and every `groups[].items[]` row) carries `name`, `kind`, `summary`, `signature`, and `depth`. Names never carry indentation; in the `exceptions` listing and in an `<Exception>` entry, `depth` is the nesting level of the subclass tree (`MixpanelHeadlessError` is depth `0` in the listing; a direct subclass is depth `0` in a single exception's `Subclasses` group). Which fields each kind fills is listed in the `HelpEntry` docstring; `mp help HelpEntry` prints it.

A `search` query returns a `SearchResult` with `term`, `hits` (each: `category`, `name`, `summary`, `matched_on` ∈ `name` / `doc` / `member`), and `suggestions`.

The result types are root exports, so the help system documents itself: `mp.HelpEntry`, `mp.SearchResult`, `mp.SearchHit`, `mp.ParamDoc`, `mp.SignatureDoc`, `mp.FieldDoc`, `mp.MemberDoc`, `mp.Group`, `mp.DocSections`, `mp.UsageDoc`, and `mp.Hint`. Three kind literals describe the surface: `ExportKind` (the ten kinds an export can have: `module`, `exception`, `enum`, `model`, `dataclass`, `class`, `literal`, `alias`, `function`, `constant`), `MemberKind` (`ExportKind` plus `method` and `property`; the type of `SearchHit.category` and `MemberDoc.kind`), and `HelpKind` (`MemberKind` plus `overview`, `listing`, `parameter`; the type of `HelpEntry.kind`).

## Tips for agents

- Use `-f json --jq EXPR` to extract one fact instead of a page of text: `mp help Workspace.query -f json --jq '.signature.params[].name'`, `mp help FilterOperator -f json --jq '.values'`. `--jq` requires `-f json`; without it the command exits 3.
- Use `mp help search TERM` before you guess a name. The hit list covers exports, `Workspace` members, `accounts` / `session` / `targets` members, enum member values, and Literal values.
- Follow the hint at the bottom of an entry. Every hint URL ends in `index.md` and is safe to `WebFetch`. The site also publishes <a href="https://mixpanel.github.io/mixpanel-headless/llms.txt">`llms.txt`</a> (index) and <a href="https://mixpanel.github.io/mixpanel-headless/llms-full.txt">`llms-full.txt`</a> (everything in one file).
- In a sandbox where `mp` is not on `PATH`, `python3 -m mixpanel_headless help ...` accepts the same arguments.
- `mp help` ignores `-a / -p / -w / -t`. No account, project, or workspace is needed or consulted.

## Exit codes and errors

CLI exit codes (this table is the reference; the CLI page and the changelog summarize it):

| Code | When | Stream |
| --- | --- | --- |
| `0` | Entry found; search with one or more hits. | stdout |
| `2` | An option value the parser rejects, for example `-f table`. Click prints the usage error. | stderr |
| `3` | `--jq` without `-f json`; bare `search` with no term (`Error: search needs a term. Usage: mp help search <term>`); a `--domain` that is unknown or ambiguous, or given with anything other than the `Workspace` query — the overview, another name, or `search` (`HelpDomainError`: `Error: <message>` plus one `Domains: ...` line when titles apply). Nothing on stdout. | stderr |
| `4` | Describe miss, also when `--domain` was passed; search with zero hits. The miss line and search view (or the JSON error object, filtered by `--jq` when given) print first. | stdout |

A miss prints one line, `No help entry for 'Cohor'. Did you mean: Cohort, Workspace.cohorts, CohortInfo, SavedCohort, CohortMetric?`, then the search view for the same term. Under `-f json` the miss is an object with `error`, `query`, `suggestions`, and `hits`.

In Python, `describe()` raises `HelpLookupError` on a miss and `HelpDomainError` (a `HelpLookupError` subclass) when `domain=` is rejected. `help()` catches a plain miss and prints the same line and search view; it re-raises `HelpDomainError`. `search()` raises `HelpLookupError` for an empty term. Both exceptions carry structured recovery data, and `details` (so `to_dict()`) includes `hits` as dicts:

```python
import mixpanel_headless as mp
from mixpanel_headless import reference as ref

try:
    entry = ref.describe("Cohor")
except mp.HelpLookupError as exc:
    print(exc.query)         # Cohor
    print(exc.suggestions)   # ('Cohort', 'Workspace.cohorts', 'CohortInfo', 'SavedCohort', 'CohortMetric')
    for hit in exc.hits:     # SearchHit records for the same term
        print(hit.category, hit.name)
    exc.details["hits"][0]   # {'category': 'class', 'name': 'RetentionCohortData', ...}

try:
    ref.describe("Workspace", domain="s")
except mp.HelpDomainError as exc:
    print(exc.reason)        # ambiguous  (one of: unknown, ambiguous, not_workspace)
    print(exc.domain)        # s
    print(exc.domains)       # ('session and switching', 'streaming', 'schema registry', 'schema enforcement', 'session replay')
```

`HelpLookupError` subclasses `MixpanelHeadlessError` directly, not `APIError`, because the lookup never touches the network. `HelpDomainError` has the error code `HELP_BAD_DOMAIN`; its `query` is the help query (`Workspace`), never the domain.

## Next Steps

- [API Reference: Built-in help](../api/help.md) — `mixpanel_headless.reference` module docs
- [Exceptions](../api/exceptions.md#help-lookup-exceptions) — `HelpLookupError` and `HelpDomainError`
- [CLI Commands](../cli/commands.md#built-in-help) — `mp help` options
