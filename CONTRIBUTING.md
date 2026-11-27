# Contributing

Use Python 3.13, uv and just. Run these checks from a fresh checkout.

```sh
uv sync --locked
just check
just audit
```

To enable local hooks, run `uv run --locked pre-commit install`. Run them without
installing a hook with `uv run --locked pre-commit run --all-files`.

Tests use synthetic fixtures and run without a DiCE adapter or vehicle. For a
hardware report, include the macOS version and chip, the project commit, the
command, its exit status and the interface and endpoint values you observed.
State whether macOS or a virtual machine owned the adapter and whether it had
power. If reporting a firmware version or a vehicle result, identify the tool
and operation that returned that value.

Keep credentials, vehicle identifiers, device serial numbers, raw captures,
proprietary software and firmware out of issues, pull requests and commits.
