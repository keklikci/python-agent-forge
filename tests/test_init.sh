#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli=$root/bin/python-agent-forge
fixture=$(mktemp -d "${TMPDIR-/tmp}/python-agent-forge.XXXXXX")
trap 'rm -rf "$fixture"' EXIT HUP INT TERM
"$cli" init "$fixture/consumer" >/dev/null
"$cli" check "$fixture/consumer" | grep -F 'check: OK' >/dev/null
grep -F 'max_parallel_tasks: 4' "$fixture/consumer/.codex/orchestration.yml" >/dev/null
grep -F 'astral-sh/setup-uv@v6' "$fixture/consumer/.github/workflows/python-ci.yml" >/dev/null
grep -F '## Risks and dependencies' "$fixture/consumer/.github/pull_request_template.md" >/dev/null
if "$cli" init "$fixture/consumer" >/dev/null 2>&1; then exit 1; fi
"$cli" reset "$fixture/consumer" >/dev/null
if "$cli" check "$fixture/consumer" >/dev/null 2>&1; then exit 1; fi
"$cli" init "$fixture/consumer" >/dev/null
printf '%s\n' 'user instructions' > "$fixture/consumer/AGENTS.md"
"$cli" reset "$fixture/consumer" >/dev/null 2>"$fixture/reset.err"
test -f "$fixture/consumer/AGENTS.md"
grep -F 'AGENTS.md' "$fixture/reset.err" >/dev/null
if "$cli" init "$fixture/secret-project" >/dev/null 2>&1; then exit 1; fi
printf '%s\n' 'Init tests passed.'
