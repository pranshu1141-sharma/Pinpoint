#!/usr/bin/env bash
# Compress the branch list: every branch already merged into main is kept as an
# `archive/<branch>` tag at its exact tip, then the branch itself is deleted.
# Nothing is lost - `git checkout archive/<branch>` restores any old experiment,
# and `git push origin archive/<branch>:refs/heads/<branch>` brings a branch back.
#
#   scripts/compress-branches.sh            # dry run: show what would happen
#   scripts/compress-branches.sh --apply    # tag, push tags, delete branches
#
# Branches with unmerged commits (open PRs) are never touched.
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
REMOTE=origin
BASE=main
KEEP_RE='^(main|claude/.*)$'   # never archive these

git fetch "$REMOTE" --prune --tags --quiet
merged=()
for ref in $(git for-each-ref --format='%(refname:strip=3)' "refs/remotes/$REMOTE"); do
  [[ "$ref" == HEAD || "$ref" =~ $KEEP_RE ]] && continue
  if git merge-base --is-ancestor "$REMOTE/$ref" "$REMOTE/$BASE"; then
    merged+=("$ref")
  else
    echo "keep    $ref  ($(git rev-list --count "$REMOTE/$BASE..$REMOTE/$ref") unmerged commits)"
  fi
done

for b in "${merged[@]}"; do
  echo "archive $b -> archive/$b @ $(git rev-parse --short "$REMOTE/$b")"
done
(( APPLY )) || { echo; echo "dry run - re-run with --apply to tag and delete ${#merged[@]} branches"; exit 0; }

for b in "${merged[@]}"; do
  git tag -f "archive/$b" "$REMOTE/$b" >/dev/null
done
git push "$REMOTE" $(printf 'refs/tags/archive/%s ' "${merged[@]}")
# Delete only after every tag is safely on the remote.
git push "$REMOTE" --delete "${merged[@]}"
echo "done: ${#merged[@]} branches archived as tags"
