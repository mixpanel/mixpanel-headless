# Built-in Help

`mixpanel_headless.help()` prints reference text for any public name. `mixpanel_headless.reference` returns the same information as structured, frozen dataclasses. Both work offline: no network call, no config file, no `Workspace`. See the [Built-in Help guide](../guide/built-in-help.md) for the query grammar, the three output formats, the JSON shape, the exit codes, and the `mp help` CLI command.

```python
import mixpanel_headless as mp
from mixpanel_headless import reference as ref

mp.help("Workspace.query")                       # prints text, returns None
entry = ref.describe("Workspace.query_funnel")   # HelpEntry
hits = ref.search("retention")                   # SearchResult
print(ref.render(entry, "markdown"))
```

!!! warning "Import with an alias"
    `from mixpanel_headless import help` shadows the Python builtin in that namespace. Prefer `import mixpanel_headless as mp` and `mp.help(...)`.

## `mixpanel_headless.reference`

::: mixpanel_headless.reference
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Result types

`describe()` returns a `HelpEntry`; `search()` returns a `SearchResult`. Every result type is a frozen `slots=True` dataclass with a recursive `to_dict()`, and every one is a root export, so `mp.HelpEntry`, `mp.ParamDoc`, and the rest work as type hints and as help queries (`mp help HelpEntry`).

| Type | Role |
|------|------|
| `HelpEntry` | One resolved query. Its docstring lists which fields each `kind` fills; `domain` holds the registry domain title of a `Workspace` method and `value` the `repr` of a constant. |
| `DocSections` | Parsed Google-style docstring: `summary`, `body`, `args`, `returns`, `raises`, `example`, `notes`. |
| `SignatureDoc` / `ParamDoc` | Callable signature. `ParamDoc.kind` is one of `positional_only`, `positional_or_keyword`, `var_positional`, `keyword_only`, `var_keyword`; `annotation` is `None` when the source has none. |
| `FieldDoc` | One model or dataclass field (also reused for enum members). |
| `MemberDoc` | One row of a class section or group; `depth` is the nesting level in an exception subclass tree. |
| `Group` | A titled list of `MemberDoc` rows (a `Workspace` domain, a `types` kind, a module's members). |
| `UsageDoc` | One `Workspace` method that accepts or raises the described type. |
| `Hint` | One hosted-documentation pointer (`title`, `url`). |
| `SearchResult` / `SearchHit` | Search output; `SearchHit.category` is a `MemberKind` and `matched_on` is `name`, `doc`, or `member`. |

Three `Literal` kind families describe the surface. `ExportKind` names what an export can be (`module`, `exception`, `enum`, `model`, `dataclass`, `class`, `literal`, `alias`, `function`, `constant`). `MemberKind` adds `method` and `property`. `HelpKind` adds `overview`, `listing`, and `parameter` and is the type of `HelpEntry.kind`.

::: mixpanel_headless.HelpEntry
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.DocSections
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.SignatureDoc
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ParamDoc
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.FieldDoc
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.MemberDoc
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.Group
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.UsageDoc
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.Hint
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.SearchResult
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.SearchHit
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Errors

`describe()` raises `HelpLookupError` on a miss and `HelpDomainError` (a `HelpLookupError` subclass) when `domain=` names no registered domain, matches several titles, or is given with a query other than `Workspace`. `search()` raises `HelpLookupError` for an empty term. `help()` catches a plain miss and prints the suggestions and the first search hits; it re-raises `HelpDomainError`. Both exceptions are listed with the rest of the hierarchy under [Exceptions](exceptions.md#help-lookup-exceptions).

### `HelpLookupError`

Carries `query`, `suggestions`, and `hits`; `details` (and so `to_dict()`) includes the hits as dicts. The CLI prints the miss on stdout and exits 4.

::: mixpanel_headless.HelpLookupError
    options:
      show_root_heading: true
      show_root_toc_entry: true

### `HelpDomainError`

Carries `query` (the help query, never the domain), `domain`, `domains` (the titles to offer), and `reason` (`unknown`, `ambiguous`, or `not_workspace`; the `HelpDomainReason` literal). Error code `HELP_BAD_DOMAIN`. The CLI prints the message and one `Domains:` line on stderr and exits 3.

::: mixpanel_headless.HelpDomainError
    options:
      show_root_heading: true
      show_root_toc_entry: true
