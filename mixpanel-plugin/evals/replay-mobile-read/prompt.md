---
description: Read a saved mobile (screenshot) replay timeline and tap-burst table without inventing screen names or friction.
tags: [offline]
max_turns: 20
timeout_seconds: 360
allowed_tools: [Read, Glob, Grep, Skill]
---

A user of our iOS grocery app complained that checkout was frustrating. I exported their session replay with mixpanel_headless: the action timeline (`replay.summary_markdown`) is in a file named replay_timeline.md, and the `bundle.rage_taps()` output is in rage_taps.csv. Both are in the fixtures directory you can read. What did this user struggle with? Be specific about which controls, how many taps, and over what time span.
