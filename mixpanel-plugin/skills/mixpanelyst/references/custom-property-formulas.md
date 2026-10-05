# Custom property formulas: the expression language and its regex quirks

This file covers the formula language for custom properties (`InlineCustomProperty` at query time, `CreateCustomPropertyParams` when you save one), the Mixpanel-specific regex rules, and a worked cleanup example.

**Contents**

- [Variables and binding](#variables-and-binding)
- [Functions](#functions)
- [Regex quirks](#regex-quirks)
- [Worked example: clean campaign names](#worked-example-clean-campaign-names)
- [Try inline, then save](#try-inline-then-save)

Look up the types with `mp help InlineCustomProperty`, `mp help PropertyInput`, `mp help CreateCustomPropertyParams`, and `mp help ComposedPropertyValue`.

## Variables and binding

A formula is a SQL-like expression. Variables (`A`, `B`, `_A`, and so on) map to properties: through `inputs` for an `InlineCustomProperty`, and through `composed_properties` for a saved custom property.

`LET(name, expression, body)` defines an intermediate result:

```text
LET(raw, A, REGEX_REPLACE(raw, "pattern", "replacement"))
LET(x, A * B, IFS(x < 50, "low", x < 200, "mid", TRUE, "high"))
```

## Functions

| Group | Functions |
| --- | --- |
| Conditionals | `IF(cond, then, else)`, `IFS(cond1, val1, cond2, val2, ..., TRUE, default)` |
| Strings | `UPPER(s)`, `LOWER(s)`, `LEN(s)`, `LEFT(s, n)`, `RIGHT(s, n)`, `MID(s, start, count)`, `SPLIT(s, delim, n)`, `HAS_PREFIX(s, p)`, `HAS_SUFFIX(s, p)`, `PARSE_URL(s, "domain")` |
| Regex (PCRE2) | `REGEX_MATCH(haystack, pattern)` returns true or false. `REGEX_EXTRACT(haystack, pattern, capture_group)` returns the match or the capture group. `REGEX_REPLACE(haystack, pattern, replacement)` replaces all matches. |
| Types | `STRING(x)`, `NUMBER(x)`, `BOOLEAN(x)`, `DEFINED(x)` |
| Math | `+`, `-`, `*`, `/`, `%`, `MIN(a, b)`, `MAX(a, b)`, `FLOOR(n)`, `CEIL(n)`, `ROUND(n)` |
| Dates | `DATEDIF(start, end, unit)` with units `D`, `M`, `Y`, `MD`, `YM`, `YD`. `TODAY()` is the current date. |
| Lists | `SUM(list)`, `ANY(x, list, expr)`, `ALL(x, list, expr)`, `FILTER(x, list, expr)`, `MAP(x, list, expr)` |
| Comparison | `==`, `!=`, `<`, `>`, `<=`, `>=`, and `IN` for list membership. String comparison is case-insensitive. |
| Logic | `AND`, `OR`, `NOT(x)` |
| Constants | `TRUE`, `FALSE`, `UNDEFINED` |

This language is Mixpanel's, and the library does not document it. Treat this table as the reference.

## Regex quirks

These rules are specific to Mixpanel. Each one causes a silent wrong result or a rejected formula if you forget it.

- **Matching is case-insensitive by default.** Put `(?-i)` at the start of a pattern for case-sensitive matching.
- **Backreferences work.** In a `REGEX_REPLACE` replacement, `$1`, `$2` refer to capture groups and `$0` to the whole match.
- **`{n,m}` quantifiers conflict with the formula syntax.** The parser reads curly braces as formula constructs. Repeat the character class instead: `[0-9][0-9][0-9][0-9]`, not `[0-9]{4}`.
- **`\d` and `\w` do not work.** Use `[0-9]` and `[A-Za-z0-9_]`.
- **Escape backslashes with care.** The string passes through Python, then JSON, then the regex engine. A literal `\` can need `\\\\` in Python source, depending on how you build the formula. A raw string (`r"..."`) removes one layer.

Split CamelCase words by inserting a space at each lowercase-to-uppercase boundary. The `(?-i)` is necessary, because without it `[a-z]` also matches capitals:

```text
REGEX_REPLACE(text, "(?-i)([a-z])([A-Z])", "$1 $2")
ChickenSundaysApril -> Chicken Sundays April
```

## Worked example: clean campaign names

Campaign names from Braze look like `20250412_TARGETED_Chicken_Sundays_Push_v2`. Remove one structural layer per step:

```text
LET(s1, REGEX_REPLACE(A, "^[0-9][0-9][0-9][0-9][0-9]*_", ""),
LET(s2, REGEX_REPLACE(s1, "^(NW|TARGETED|REGIONAL|NTL)_", ""),
LET(s3, REGEX_REPLACE(s2, "_(Push|Email|NotificationCenter|ModalInAppMessage)_.*$", ""),
LET(s4, REGEX_REPLACE(s3, "_", " "),
  REGEX_REPLACE(s4, " +", " ")
))))
```

1. `s1` removes the leading date code (four or more digits and an underscore).
2. `s2` removes the targeting prefix.
3. `s3` removes the channel suffix and everything after it.
4. `s4` turns underscores into spaces, and the last step collapses repeated spaces.

## Try inline, then save

Try the formula at query time first. An `InlineCustomProperty` changes nothing in the project:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
clean_name = mp.InlineCustomProperty(
    formula='LET(raw, A, REGEX_REPLACE(REGEX_REPLACE(raw, "^[0-9]+_", ""), "_", " "))',
    inputs={"A": mp.PropertyInput("campaign_name", type="string")},
    property_type="string",
)
result = ws.query("Campaign Open", group_by=mp.GroupBy(property=clean_name),
                  last=30, mode="total")
print(result.df.head(20))
```

When the output is clean, save it so that other reports can use it. `ws.validate_custom_property(params)` checks a definition without creating it. Saving writes to the project, so confirm with the user first:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
params = mp.CreateCustomPropertyParams(
    name="Clean Campaign Name",
    resource_type="events",
    display_formula='LET(raw, A, REGEX_REPLACE(REGEX_REPLACE(raw, "^[0-9]+_", ""), "_", " "))',
    composed_properties={
        "A": mp.ComposedPropertyValue(
            resource_type="event", type="string", value="campaign_name",
            label="Campaign Name", property_default_type="string",
        )
    },
)
print(ws.validate_custom_property(params))
prop = ws.create_custom_property(params)
ref = mp.CustomPropertyRef(prop.custom_property_id)
result = ws.query("Campaign Open", group_by=mp.GroupBy(property=ref),
                  last=30, mode="total")
```

The two resource type fields use different words: `CreateCustomPropertyParams.resource_type` is `"events"` (plural), and `ComposedPropertyValue.resource_type` is `"event"` (singular), as in the example.
