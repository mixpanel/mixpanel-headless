---
description: The user has a mixpanel_headless release older than 0.3.0, so mp help does not exist. The reply should explain the upgrade instead of ignoring the error. The error is quoted in the prompt instead of set up with a fake mp on PATH, because a case cannot change PATH (only EVAL_* variables reach the run) and a scaffold script runs only with --scaffold, outside the sandbox.
tags: [offline]
max_turns: 20
timeout_seconds: 360
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

I tried `mp help Workspace.query_funnel` on my laptop and it printed:

```text
Usage: mp [OPTIONS] COMMAND [ARGS]...
Try 'mp --help' for help.

Error: No such command 'help'.
```

Anyway, can you write me a mixpanel_headless script that gets the Signup → Purchase funnel conversion rate for the last 30 days? Save it as funnel.py; I will run it on my laptop.
