#!/bin/sh
set -eu

uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest
