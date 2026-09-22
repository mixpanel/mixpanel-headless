# rrweb test fixtures

Hand-built rrweb event streams for unit + property tests of the session-replay
feature (044). These are deliberately tiny — they exercise event-shape parsing,
not realistic recording size or complexity.

## `sample-replay-001.json`

~20 events covering a minimal login → navigate → click flow:

1. `DomContentLoaded` (type 0)
2. `Load` (type 1)
3. `Meta` (type 4) — initial URL `/login`, viewport 1280×800
4. `FullSnapshot` (type 2) — login form DOM (email/password/submit button with
   `data-testid="signin-button"`)
5. `IncrementalSnapshot` MouseMove (type 3 / source 1)
6. `IncrementalSnapshot` Input (type 3 / source 5) on email field
7. `IncrementalSnapshot` Input (type 3 / source 5) on password field
8–10. `IncrementalSnapshot` MouseInteraction (type 3 / source 2):
    MouseDown → MouseUp → Click on the Sign In button (`#13`)
11. `Meta` — navigate to `/dashboard`
12. `FullSnapshot` — dashboard with a link to user 12345's profile
13. `IncrementalSnapshot` Scroll (type 3 / source 3)
14. `IncrementalSnapshot` Click (type 3 / source 2 / type 2) on the user link
15. `Meta` — navigate to `/dashboard/users/12345/profile`
16. `FullSnapshot` — profile page with an `data-testid="edit-profile"` button
17. `IncrementalSnapshot` MouseMove
18. `IncrementalSnapshot` Click on the edit button
19. `IncrementalSnapshot` ViewportResize (type 3 / source 4) — 1280×800 → 1024×768
20. `Meta` — navigate to `/dashboard/users/12345/edit`

Total duration: 15 seconds (`timestamp` field uses unix ms starting at
`1716810000000` = 2024-05-27 13:00:00 UTC). The stream is timestamp-sorted
and contains at least one of every rrweb event family the analyzer cares
about: DOM bootstrap, navigation, mouse input, keyboard input,
viewport change.

## rrweb event-shape reference

- `type: 0` — `DomContentLoaded`
- `type: 1` — `Load`
- `type: 2` — `FullSnapshot` (carries `data.node` + `data.initialOffset`)
- `type: 3` — `IncrementalSnapshot` (carries `data.source` discriminator)
- `type: 4` — `Meta` (carries `data.href`, `data.width`, `data.height`)
- `type: 5` — `Custom`
- `type: 6` — `Plugin`

`IncrementalSnapshot.data.source` values used by this fixture:

| `source` | Family            | Extras                                    |
|----------|-------------------|-------------------------------------------|
| 1        | MouseMove         | `positions: [{x, y, id, timeOffset}]`     |
| 2        | MouseInteraction  | `type: 0=Up / 1=Down / 2=Click`, `x`, `y` |
| 3        | Scroll            | `id`, `x`, `y`                            |
| 4        | ViewportResize    | `width`, `height`                         |
| 5        | Input             | `id`, `text`, `isChecked`                 |

## Mobile and screenshot replays

These fixtures are real recordings from internal Mixpanel test apps. The
apps are SDK demo apps ("Snacks", the Session Replay demo screens, and
test fragments). They do not hold customer data.

Mobile SDKs do not record a DOM. Each screen change sends two things:

- a FullSnapshot (type 2) with one `img` element that holds a JPEG
  screenshot of the screen;
- a Custom event (type 5) with the tag `mp_wireframe`. Its payload is
  `{"viewport": [w, h], "elements": [{"role", "text", "bounds"}, ...]}`.
  `bounds` is `[x, y, width, height]`.

Touch input arrives as MouseInteraction events (type 3, source 2) with
`type` 7 (touch start), 9 (touch end), or 10 (touch cancel). A drag
arrives as a TouchMove event (type 3, source 6). The Meta events of these
recordings have no `href`.

### Scrub method

Each fixture comes from the raw replay through
`scrub_mobile_fixture.py` in this directory:

```bash
python tests/fixtures/rrweb/scrub_mobile_fixture.py RAW.json OUT.json
```

The script replaces every string that starts with `data:image/` with
`data:image/jpeg;base64,REDACTED`. It writes JSON with `indent=1` when
the file is at most 200 KB, and compact JSON when the file is larger.
The script can also trim a replay to a time window (`--start-ms`,
`--end-ms`). When it trims, it keeps the first Meta event, and the most
recent Meta, FullSnapshot, and `mp_wireframe` events before the window.
All nine fixtures below were under 200 KB after the image replacement,
so none of them is trimmed. Each fixture is the full replay.

A review of all wireframe text found no emails, no names of real
people, no tokens, and no distinct IDs. The SDK already masked the one
email field (`Receipt sent to [EMAIL]` in `rn-ios-001.json`). The only
user ID is the test ID `User: Rn-5`. The Flutter settings screen has
`Token` and `Distinct ID` labels, but their `input` elements have no
text. No wireframe text was changed.

### Upstream reference output

`upstream/mobile-expected.json` maps each fixture name to the
`markdown_summary` that the upstream analyzer (the source of our vendored
copy, after its mobile wireframe support) produces for that fixture.
Tests use it to show where our output agrees with upstream and where it
differs on purpose. The file is in a subdirectory because the golden
generator loads every `*.json` file directly in this directory as an
event stream.

Event counts below use the rrweb type codes: 2 = FullSnapshot,
3 = IncrementalSnapshot, 4 = Meta, 5 = Custom.

### `android-wireframe-001.json`

- Source: project 1055570, replay `a436a4ec-076b-4a14-851c-b6a80f7c6fdc`.
- SDK: `android-sr`. Duration: 21 s. Window: full replay.
- Meta 411×914. Wireframe viewport 411×914.
- Events: 11 (type 2: 4, type 3: 4, type 4: 1, type 5: 2).
- Cases: two screens (Home, then Settings) and two taps. The first tap,
  at (383, 51), hits an icon button with role `text` and no label
  (`[363,27,48,48]`). The second tap, at (182, 142), is 2 px below the
  "Re-initialize Session Replay" button (`[16,100,379,40]`).

### `android-wireframe-masked-001.json`

- Source: project 1055570, replay `51723b08-e878-42da-a9b3-ca49c3e10042`.
- SDK: `android-sr` (an older build). Duration: 0 s. Window: full replay.
- Meta 411×866. Wireframe viewport 1080×2400.
- Events: 3 (type 2: 1, type 4: 1, type 5: 1).
- Cases: every label is masked (`"text": null`). The bounds are in
  physical pixels, but the Meta size is in logical pixels (a scale of
  about 2.63). The replay has no touches.

### `android-snacks-001.json`

- Source: project 4003103, replay `e30f6237-e675-4283-832d-8bef10cfd398`.
- SDK: `android-sr`. Duration: 158 s. Window: full replay.
- Meta 411×914. Wireframe viewport 411×914.
- Events: 85 (type 2: 30, type 3: 32, type 4: 7, type 5: 16).
- Cases: full, unmasked labels in a cart flow. The user taps the `+`
  buttons, and the "Checkout N item(s)" button changes from 1 to 11
  items. The replay has 16 touch starts, 16 touch ends, and 16
  wireframes.

### `ios-early-touch-001.json`

- Source: project 4003103, replay `EA4E8C42-D044-4F2B-858F-32A70E8111FD`.
- SDK: `swift-sr`. Duration: 2 s. Window: full replay.
- Meta 402×874. Wireframe viewport 402×874.
- Events: 6 (type 2: 1, type 3: 3, type 4: 1, type 5: 1).
- Cases: the touch start (at y 873) comes 45 ms before the first
  wireframe. Then a touch move goes up from y 874 to y 782, and the
  system cancels the gesture (touch cancel, `type` 10). The correct
  reading is one swipe up from the bottom edge that was cancelled. One
  element has a negative x (`[-118,731,638,286]`).

### `ios-wireframe-001.json`

- Source: project 4003103, replay `6CDBD778-46BE-4C7F-964C-7E4223198532`.
- SDK: `swift-sr`. Duration: 13 s. Window: full replay.
- Meta 402×874. Wireframe viewport 402×874.
- Events: 23 (type 2: 5, type 3: 10, type 4: 2, type 5: 6).
- Cases: four touches. Two are scrolls (a touch move between start and
  end) and two are taps, at (372, 605) and (147, 815). Elements go off
  screen: the right edge of some elements reaches x = 522 on a 402-wide
  screen, and one element starts at x = -120. Each screen has about 70
  elements, most of them masked. The screen has `input` elements.

### `flutter-android-rage-001.json`

- Source: project 4003103, replay `81cf456f-3bde-4369-90c0-ba7f6db546ef`.
- SDK: `flutter-sr` on Android. Duration: 125 s. Window: full replay.
- Meta 412×915. Wireframe viewport 411×914 (a rounding difference, not
  a scale difference).
- Events: 308 (type 2: 44, type 3: 241, type 4: 1, type 5: 22).
- Cases: real rage bursts. The replay has 20 touch starts at (257, 638)
  in 1.2 s. The upstream analyzer shows them as eight
  `Tapped at (257, 638)` lines with one `Scrolled` line in the middle.
  Two later bursts have 33 touch starts at (275, 368) in 0.9 s (11
  upstream `Tapped` lines) and 39 touch starts at (244, 678) in 1.1 s
  (nine upstream `Tapped` lines). Most touch ends in the bursts have
  other coordinates than their touch starts. The replay has 111 touch
  starts, 111 touch ends, and 19 touch moves.

### `flutter-web-clicks-001.json`

- Source: project 4003103, replay `3c5cfb4b-3d77-4e1a-8c3e-8cbdf3059be0`.
- SDK: `flutter-sr` on the web. Duration: 25 s. Window: full replay.
- Meta 1200×1213. Wireframe viewport 1200×1213.
- Events: 37 (type 2: 20, type 3: 9, type 4: 1, type 5: 7).
- Cases: mouse input, not touch input. Three MouseDown, MouseUp, and
  Click sequences (`type` 1, 0, 2) on node 28, the screenshot `img`.
  All labels are masked. The Meta event has no `href`, although the
  recording comes from a browser.

### `rn-ios-001.json`

- Source: project 4003103, replay `9F276478-C1D6-4464-AE6E-C647BF724287`.
- SDK: `react-native-sr` on iOS. Duration: 35 s. Window: full replay.
- Meta 390×844. Wireframe viewport 390×844.
- Events: 54 (type 2: 12, type 3: 29, type 4: 4, type 5: 9).
- Cases: five elements with role `switch`. A frame from the middle of a
  slide transition has negative x values
  (`Mixpanel Session Replay Demo [-96,260,350,29]`). The replay has 11
  touch starts, 11 touch ends, and 7 touch moves.

### `rn-android-no-wireframe-001.json`

- Source: project 4003103, replay `553483d1-e1bb-4d21-be6f-1bc3435a77e4`.
- SDK: `react-native-sr` on Android. Duration: 29 s. Window: full replay.
- Meta 411×914. No wireframes.
- Events: 15 (type 2: 8, type 3: 6, type 4: 1).
- Cases: touches and screenshots, but the wireframe setting is off. The
  replay has three touch starts, three touch ends, and no
  `mp_wireframe` events.
