#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cli=$root/bin/python-agent-forge
"$cli" help | grep -F 'python-agent-forge init <target-directory>' >/dev/null
"$cli" help | grep -F 'inspect' >/dev/null
"$cli" help | grep -F 'adopt' >/dev/null
if "$cli" unknown >/dev/null 2>&1; then exit 1; fi
printf '%s\n' 'CLI tests passed.'
