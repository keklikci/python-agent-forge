#!/bin/sh
set -eu

usage() {
    printf '%s\n' \
        'Usage: scripts/caf-worktree.sh create <task-id> [base-branch]' \
        '       scripts/caf-worktree.sh list' \
        '       scripts/caf-worktree.sh remove <task-id>'
}

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
worktree_root=${CAF_WORKTREE_ROOT-"$repo_root/../.paf-worktrees"}
prefix=${CAF_BRANCH_PREFIX-codex/}
slugify() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9._-' '-'; }

[ "$#" -ge 1 ] || { usage >&2; exit 2; }
case "$1" in
    create)
        [ "$#" -ge 2 ] && [ "$#" -le 3 ] || { usage >&2; exit 2; }
        task_slug=$(slugify "$2")
        base_branch=${3-main}
        worktree="$worktree_root/$task_slug"
        mkdir -p "$worktree_root"
        [ ! -e "$worktree" ] || { printf 'worktree already exists: %s\n' "$worktree" >&2; exit 1; }
        git -C "$repo_root" worktree add -b "${prefix}${task_slug}" "$worktree" "$base_branch"
        ;;
    list) git -C "$repo_root" worktree list ;;
    remove)
        [ "$#" -eq 2 ] || { usage >&2; exit 2; }
        git -C "$repo_root" worktree remove "$worktree_root/$(slugify "$2")"
        ;;
    *) usage >&2; exit 2 ;;
esac
