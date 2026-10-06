---
applyTo: ".github/workflows/**"
---
# GitHub Actions

- Pin every action by full commit SHA, with the version in a comment.
- Give each job the least permissions it needs.
- A workflow that spends an API key runs only when a person with write
  access adds a label. It does not use the `pull_request_target` trigger.
- `copilot-setup-steps.yml` prepares the environment for Copilot code
  review and the Copilot cloud agent. Its job must be named
  `copilot-setup-steps`. Copilot honors only `steps`, `permissions`,
  `runs-on`, `services`, `snapshot`, and `timeout-minutes` (maximum 59).
