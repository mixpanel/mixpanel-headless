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
