set positional-arguments

default: check

check: lint typecheck test

dev *args:
    uv run --locked p2-dice "$@"

test:
    uv run --locked pytest

lint:
    uv run --locked ruff check .
    uv run --locked ruff format --check .

typecheck:
    uv run --locked pyright

audit:
    uv audit --locked
