#!/usr/bin/env bash
# Works out the next release from the commits since the last vX.Y.Z tag, using
# Conventional Commits:
#   type!: ...  or a "BREAKING CHANGE:" footer  -> major
#   feat: ...                                   -> minor
#   anything else                               -> patch
#
# Prints "tag=vX.Y.Z" and "major=vX" (for $GITHUB_OUTPUT), or nothing when there
# is nothing new to release. Writes release notes to $NOTES_FILE.
set -euo pipefail

notes_file="${NOTES_FILE:-release-notes.md}"
repo_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-johannesE/skopos}"

# Highest strict vX.Y.Z tag reachable from HEAD. Anything else (v1, v1.1.0-rc1,
# v1.2.3.4) is ignored, so a hand-made tag cannot break the version arithmetic.
last="$(git tag --merged HEAD --sort=-v:refname | awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && !found { print; found = 1 }')"
range="HEAD"
[ -n "$last" ] && range="$last..HEAD"

mapfile -t shas < <(git rev-list --no-merges --reverse "$range")
if [ "${#shas[@]}" -eq 0 ]; then
  echo "No new commits since ${last:-the first commit}; nothing to release." >&2
  exit 0
fi

breaking_re='^[a-zA-Z]+(\([^)]*\))?!:'
feat_re='^feat(\([^)]*\))?:'
fix_re='^(fix|perf)(\([^)]*\))?:'

bump="patch"
breaking=() features=() fixes=() other=()
for sha in "${shas[@]}"; do
  subject="$(git log -1 --format=%s "$sha")"
  body="$(git log -1 --format=%b "$sha")"
  line="- ${subject} (${sha:0:7})"
  if [[ $subject =~ $breaking_re ]] || grep -q '^BREAKING[ -]CHANGE:' <<<"$body"; then
    bump=major
    breaking+=("$line")
  elif [[ $subject =~ $feat_re ]]; then
    [ "$bump" = patch ] && bump=minor
    features+=("$line")
  elif [[ $subject =~ $fix_re ]]; then
    fixes+=("$line")
  else
    other+=("$line")
  fi
done

IFS=. read -r major minor patch <<<"${last#v}"
major="${major:-0}" minor="${minor:-0}" patch="${patch:-0}"
case "$bump" in
  major) major=$((major + 1)) minor=0 patch=0 ;;
  minor) minor=$((minor + 1)) patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac
tag="v${major}.${minor}.${patch}"

section() {
  local title="$1"
  shift
  [ "$#" -gt 0 ] || return 0
  printf '## %s\n\n' "$title"
  printf '%s\n' "$@"
  printf '\n'
}
{
  section "Breaking changes" ${breaking[@]+"${breaking[@]}"}
  section "Features" ${features[@]+"${features[@]}"}
  section "Fixes" ${fixes[@]+"${fixes[@]}"}
  section "Other changes" ${other[@]+"${other[@]}"}
  if [ -n "$last" ]; then
    printf '**Full diff:** %s/compare/%s...%s\n' "$repo_url" "$last" "$tag"
  fi
} > "$notes_file"

echo "Next release: $tag ($bump, ${#shas[@]} commits since ${last:-the first commit})" >&2
echo "tag=$tag"
echo "major=v$major"
