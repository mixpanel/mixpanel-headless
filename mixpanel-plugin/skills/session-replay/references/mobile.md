# Mobile and screenshot recordings

Read this file when `replay.capture == "screenshot"`.

Contents:

- What a screenshot recording holds
- Start with rage taps
- The four timeline lines
- What a tap hit
- Screens have no names
- Rage and dead taps
- Limits

## What a screenshot recording holds

The iOS, Android, React Native, and Flutter SDKs have no DOM to record. Flutter records this way on every target: mobile, web, and desktop. Each screen goes into the stream as a screenshot image. When the SDK has wireframes turned on, each screen also goes in as a wireframe: a flat list of the screen's elements, each with a role, a text label, and a rect.

- `replay.capture` is `"screenshot"` for these recordings.
- `replay.has_wireframes` tells you if the replay has wireframe screens. The SDK can turn wireframes off. Without them, the replay still has taps, scrolls, and clicks, but no screens, and every tap target is a bare point.
- There are no URLs. `url` is `None`, `page_path()` is empty, and `where(contains_url=...)` matches nothing. Use `screen_path()` for the sequence of screens.
- The same fetch calls work. No option is necessary.

```python
replay = bundle.replays[0]
if replay.capture == "screenshot":
    print(replay.has_wireframes)   # False when the SDK sent no wireframes
    print(replay.screen_path())    # screen headings in order, for example ["Home", "Settings"]
```

## Start with rage taps

Call `bundle.rage_taps()` before you read the timeline. It counts real finger-downs from the raw events, with real timestamps. The timeline does not: when fingers overlap in a fast burst, many finger-downs become only a few `Tapped` lines. In one real recording, 20 finger-downs gave 6 `Tapped` lines.

```python
print(bundle.rage_taps())   # replay_id, t_start, t_end, target_desc, x, y, count, kind
print(bundle.screens_df)    # replay_id, t, heading, fingerprint, element_count, description

# Most-visited screens: count by fingerprint, label by heading.
visits = bundle.screens_df.groupby("fingerprint").agg(
    heading=("heading", "first"), visits=("replay_id", "size")
)
print(visits.sort_values("visits", ascending=False).head())

# Mobile taps are touch_start actions. top_clicks() counts clicks only, so rank taps yourself.
taps = bundle.actions_df.query("action == 'touch_start'")
print(taps.groupby("target_desc").size().sort_values(ascending=False).head(10))
```

## The four timeline lines

```text
1789482332: Wireframe: Home [16,38,54,27] | text [363,27,48,48] | button:View Jokes (Compose) [98,155,215,48] | …
1789482352: Tapped at (383, 51)
1789482353: Wireframe: Settings [72,38,76,27] | image [0,24,56,56] | button:Re-initialize Session Replay [16,100,379,40]
1789482354: Tapped at (182, 142)
```

**`Wireframe:` lines** (action `screen`) show one screen. Elements are separated by `|`, in the order the SDK sent them.

- A bare label is a text element: `Home`.
- `role:label` is any other role: `button:Save`, `input:Email`. Real recordings show the roles `text`, `image`, `button`, `input`, and `switch`.
- A role with no label is an unlabeled element: `text [363,27,48,48]` is often an icon or masked text.
- `[x,y,w,h]` is the rect as the SDK sent it, from the top-left corner. An element with no usable bounds has no rect.
- A label is cut at 50 characters with `…`, and a `|` inside a label becomes `/`.

The line keeps the raw SDK rect. Some Android builds send rects in physical pixels while taps use logical pixels. The analyzer then scales the rects before it matches taps to elements, and `metadata["scale"]` on the screen action is not `1.0`. In that case, do not compare a `Tapped at (x, y)` point with the rects on the `Wireframe:` line by eye. Read the tap's target instead, or read the scaled rects in `metadata["elements"]`.

**Screens are keyframes, not a continuous record.** The analyzer keeps the screen that was showing when each gesture started, and up to two screens after the gesture ended. Consecutive identical screens appear once. A replay with no gestures shows its first and last screen. So something can happen between two screens without a line of its own. Compare consecutive screens to see what a gesture did:

- a mostly new set of elements means a navigation;
- new items under an input mean a search or a suggestion list;
- one label that changes means a toggle or a counter.

**`Tapped at (x, y)`** (action `touch_start`) is a touch that moved 10 px or less before the finger lifted. **`Scrolled`** (action `scroll`) is a touch that moved farther: a swipe or a scroll, not a tap. A touch that the system cancelled gives no line. The analyzer classifies each touch when the finger lifts, so the timestamp of a `Tapped` line is the lift time.

**`Clicked at (x, y)`** (action `click`) is a mouse click in a Flutter web or desktop recording. These clicks count in `top_clicks()`, `rage_clicks()`, and `n_clicks`, the same as web clicks. Mobile taps do not count there.

**`(×N)`** collapses N consecutive identical lines. `Tapped at (257, 638) (×7)` is seven taps at one point. The line shows the first timestamp only, so it hides the time span of the burst. Take timing from `rage_taps()` or `actions_df`.

## What a tap hit

The description always shows the point, never the element. The structured action names the element. The analyzer tests each tap and click against the screen that was showing at finger-down:

1. Elements whose rect contains the point are candidates. A non-text role (a button or an input) wins over a text element, then the smallest rect wins. `metadata["attribution"]` is `"bounds"`.
2. With no containing rect, the nearest element within 8 px wins, because real taps often land just outside a button edge. `metadata["attribution"]` is `"bounds_slop"`.
3. With no element near the point, `target_desc` is the point, `"(x, y)"`, and there is no `metadata["hit"]`.

`target_desc` names the hit element: the bare label for text, `role:label` for other roles, or `role [x,y,w,h]` for an element with no label. `metadata["hit"]` holds the element's `role`, `text`, and `bounds`.

Rects overlap, so a hit is an inference, not a fact that the SDK sent. Say so when a finding depends on it. A full-width background layer (for example, the blur behind a tab bar) is never a candidate. So a tap on a translucent tab bar or toolbar can resolve to the content that scrolls below it.

## Screens have no names

The SDKs send no screen name. The heading of a screen (the `target_desc` of a `screen` action, and the `heading` column of `screens_df`) is the label of the top-most labeled text element. It is approximate:

- it can be a clock, a back-button label, or scrolled content on the title row;
- two different screens can share a heading;
- a screen with no labeled text (for example, a fully masked screen) gets `"(screen)"`.

Identify a screen by `metadata["fingerprint"]`, a short hash of the whole `Wireframe:` line. Identical screens share a fingerprint. Any change to a label or a rect gives a new fingerprint, so a scrolled list can show as several fingerprints.

Name a screen only with text that appears on it, for example "the screen headed Settings" or "the screen with the Save button". Never invent a screen name such as "Checkout screen" when no such text is on the screen, because the user will look for that name in the app.

For `find_pattern`, the default labels give screens as `screen:Home@(no-url)`, so action sequences work on mobile recordings too.

## Rage and dead taps

A burst is 3 or more finger-downs within 2 seconds of the first one and within 24 px of its point. These are the defaults. `mp help ReplayBundle.rage_taps` shows the parameters. The method counts touch starts, plus clicks in Flutter web and desktop.

Each burst is judged per interval. The intervals are the gaps between consecutive finger-downs, plus a grace window after the last one. An interval has a change when a screen in it differs from the screen shown when the interval began.

- `kind="dead"`: no interval has a change. The control did nothing.
- Not reported: every gap between finger-downs has a change. This is intentional use, for example a quantity stepper or a carousel.
- `kind="rage"`: anything else. Some taps changed nothing, for example when a navigation arrives only after the burst.

A live clock, a timer, or an animation counts as a change. So a dead control on such a screen can show as `"rage"`, or not show at all.

Report each burst with its control (`target_desc`), its tap count, and its time span (`t_start` to `t_end`, in Unix milliseconds). A tap target that is a bare point `"(x, y)"` means that no element was near. Describe the location from the screen around it, and do not name a control.

A clean, successful flow is a valid finding. When `rage_taps()` is empty and the screens show the flow completing, report that. Do not invent friction.

## Limits

- **Masked text is gone.** A masked label is not in the recording. A masked screen has only roles and rects, and its heading is `"(screen)"`.
- **Some screens are mid-animation.** An "after" screen can be a frame from the middle of a transition. Its elements can have a negative `x` or sit past the right edge.
- **Off-screen elements are ignored.** An element whose rect is fully outside the screen width gets `"offscreen": True` in `metadata["elements"]`. The heading and the tap matching ignore it.
- **Keyframes skip frames.** A change between two kept screens has no line of its own. Do not claim that the user saw nothing in between.
