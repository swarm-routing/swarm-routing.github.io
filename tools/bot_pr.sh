#!/usr/bin/env bash
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
#
# Open or update one bot PR from the working tree's change to <paths> (#120).
#
#   tools/bot_pr.sh <branch> <title> <body-file> <path>...
#
# When <paths> are unchanged it prints so and exits 0. Otherwise it commits
# them on <branch> (made from HEAD, force-pushed: a bot/ branch belongs to the
# bot), opens a PR to main or leaves the open one (the push updated it),
# enables auto-merge (the merge queue squashes after the required checks), and
# returns the checkout to where it was. Needs GH_TOKEN (the bot's token, so the
# PR's checks run), GITHUB_REPOSITORY, and git's user.name/email set.
set -euo pipefail

[ $# -ge 4 ] || { echo "usage: $0 <branch> <title> <body-file> <path>..." >&2; exit 2; }
branch=$1 title=$2 body=$3
shift 3
case "$branch" in bot/*) ;; *) echo "bot_pr.sh: $branch is not a bot/ branch" >&2; exit 2 ;; esac

if git diff --quiet -- "$@" && [ -z "$(git ls-files --others --exclude-standard -- "$@")" ]; then
  echo "bot_pr.sh: $* unchanged; no PR"
  exit 0
fi
: "${GH_TOKEN:?bot_pr.sh: GH_TOKEN is empty (no bot token); the change is not pushed}"

start=$(git rev-parse HEAD)
git switch -q -C "$branch"
git add -- "$@"
{ printf '%s\n\n' "$title"; cat "$body"; } | git commit -q -F -
remote=${BOT_PR_REMOTE:-"https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"}  # BOT_PR_REMOTE: a test's local remote
git push -q --force "$remote" "HEAD:refs/heads/$branch"
pr=$(gh pr list --repo "$GITHUB_REPOSITORY" --head "$branch" --state open --json number --jq '.[0].number // empty')
if [ -z "$pr" ]; then
  url=$(gh pr create --repo "$GITHUB_REPOSITORY" --base main --head "$branch" --title "$title" --body-file "$body")
  pr=${url##*/}
  echo "bot_pr.sh: opened #$pr"
else
  gh pr edit "$pr" --repo "$GITHUB_REPOSITORY" --title "$title" --body-file "$body" >/dev/null
  echo "bot_pr.sh: updated #$pr"
fi
gh pr merge "$pr" --repo "$GITHUB_REPOSITORY" --auto --squash || echo "::warning::bot_pr.sh: auto-merge not enabled on #$pr"
git switch -q --detach "$start"
