# p2-dice

The project researches read-only DiCE diagnostics for Volvo P2 on macOS. Use
Python 3.13 and the locked uv project environment. The CLI lives in
`src/p2_dice/`, and the test suite lives in `tests/`.

- Run `uv sync --locked`, then `just check` before handing off changes.
- Run `just audit` to check the locked dependencies for reported vulnerabilities.
- Keep default tests and CI hardware-free. Use synthetic identifiers and mock the
  USB boundary.
- Treat USB descriptors as capability evidence. Keep firmware or vehicle behavior
  unverified until a separately authorized observation establishes it.
- Keep personal and vehicle identifiers, raw captures, credentials, proprietary
  software and firmware out of Git. Use reproducible synthetic fixtures in tests.
- Use a named working branch and open a PR for review when publication is authorized.

## Owner-run agent teams

For Erika's coordinated development sessions, use the authorized local checkout of
https://github.com/erikabarker/agent-playbooks at
`caa38d724477933e8f11692cd62fbfe6e56f0dd0`. Read its README, shared core protocol,
hierarchical swarm protocol and the selected task playbook. Record the loaded
revision and actual delegation receipts in the private session handoff. Keep each
editing agent on a separate branch/worktree and retain independent verification.
The private playbook library is optional for other contributors; the commands and
project rules above remain the public development contract. Never copy private
playbooks, vehicle records or captures into this repository.
