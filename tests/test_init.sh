#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli=$root/bin/python-agent-forge
fixture=$(mktemp -d "${TMPDIR-/tmp}/python-agent-forge.XXXXXX")
trap 'rm -rf "$fixture"' EXIT HUP INT TERM
"$cli" init "$fixture/consumer" >/dev/null
"$cli" check "$fixture/consumer" | grep -F 'check: OK' >/dev/null
grep -F 'max_parallel_tasks: 4' "$fixture/consumer/.codex/orchestration.yml" >/dev/null
printf '%s\n' 'Init tests passed.'
