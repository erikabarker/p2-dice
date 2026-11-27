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
