#!/usr/bin/env bash
# Skopos entrypoint: package -> agent review (no GitHub credentials) -> post.
#
# Runs with the working directory set to the checked-out pull request head.
#
# Required environment:
#   PR_NUMBER                  pull request to review
#   GH_TOKEN                   token for reading the PR and posting (never given to the agent)
#   SKOPOS_LLM_API_KEY         model provider API key
#   SKOPOS_ENGINE_BIN          path to the review engine binary
#
# Optional environment (defaults match action.yml):
#   SKOPOS_BOT_LOGIN               login the review posts as (thread-ownership gate)
#   SKOPOS_MODEL                   model id at the provider     (glm-5.3)
#   SKOPOS_PROVIDER_BASE_URL       OpenAI-compatible base URL   (https://ollama.com/v1)
#   SKOPOS_PROVIDER_NAME           provider display name        (Ollama Cloud)
#   SKOPOS_PROJECT_CHECKLISTS_DIR  checklist overlay dir        (.github/skopos/checklists)
#   SKOPOS_MAX_CHANGED_LINES       skip PRs larger than this    (0 = no limit)
set -euo pipefail

: "${PR_NUMBER:?PR_NUMBER must be set}"
: "${GH_TOKEN:?GH_TOKEN must be set}"
: "${SKOPOS_LLM_API_KEY:?SKOPOS_LLM_API_KEY must be set}"
: "${SKOPOS_ENGINE_BIN:?SKOPOS_ENGINE_BIN must be set}"

MODEL="${SKOPOS_MODEL:-glm-5.3}"
PROVIDER_BASE_URL="${SKOPOS_PROVIDER_BASE_URL:-https://ollama.com/v1}"
PROVIDER_NAME="${SKOPOS_PROVIDER_NAME:-Ollama Cloud}"
CHECKLISTS_DIR="${SKOPOS_PROJECT_CHECKLISTS_DIR-.github/skopos/checklists}"
MAX_CHANGED_LINES="${SKOPOS_MAX_CHANGED_LINES:-0}"
if ! [[ "$MAX_CHANGED_LINES" =~ ^[0-9]+$ ]]; then
  echo "::error title=Skopos::max_changed_lines must be a non-negative integer, got '$MAX_CHANGED_LINES'"
  exit 1
fi

ACTION_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/skopos"
RUN_ID="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
SUMMARY_FILE="${GITHUB_STEP_SUMMARY:-/dev/null}"

echo "::add-mask::$SKOPOS_LLM_API_KEY"
rm -rf "$WORK"
mkdir -p "$WORK"

summary() { printf '%s\n' "$@" >> "$SUMMARY_FILE"; }

# --- Skill: private copy plus project checklist overlay -----------------------
SKILL_DIR="$WORK/skill"
cp -R "$ACTION_PATH/skills/code-review" "$SKILL_DIR"
mkdir -p "$SKILL_DIR/references/project"
if [ -n "$CHECKLISTS_DIR" ] && [ -d "$CHECKLISTS_DIR" ]; then
  echo "Overlaying project checklists from $CHECKLISTS_DIR"
  find "$CHECKLISTS_DIR" -maxdepth 1 -type f \( -name '*.md' -o -name '*.markdown' \) \
    -exec cp {} "$SKILL_DIR/references/project/" \;
else
  echo "No project checklists at '${CHECKLISTS_DIR}' (core checks only)"
fi
export SKOPOS_SKILL_DIR="$SKILL_DIR"
export UV_CACHE_DIR="$WORK/uv-cache"

# --- Phase 0: package -----------------------------------------------------------
CONTEXT_BASE="$PROJECT_DIR/.skopos/review-context"
REVIEW_BASE="$PROJECT_DIR/.skopos/review"
REVIEW_DIR="$REVIEW_BASE/$PR_NUMBER/$RUN_ID"
mkdir -p "$CONTEXT_BASE" "$REVIEW_DIR"

echo "::group::Package pull request #$PR_NUMBER"
package_result="$(uv run --quiet --script "$SKILL_DIR/scripts/package_review_context.py" pr "$PR_NUMBER" --output-dir "$CONTEXT_BASE")"
echo "$package_result"
echo "::endgroup::"
CONTEXT_JSON="$(jq -r '.context_json' <<< "$package_result")"
MANIFEST_JSON="$(jq -r '.manifest_json' <<< "$package_result")"
CHANGED_LINES="$(jq -r '.changed_lines' <<< "$package_result")"

if [ "$MAX_CHANGED_LINES" -gt 0 ] && [ "$CHANGED_LINES" -gt "$MAX_CHANGED_LINES" ]; then
  echo "::notice title=Skopos::PR changes $CHANGED_LINES lines (limit $MAX_CHANGED_LINES); skipping review."
  summary "### Skopos review skipped" "" "The pull request changes $CHANGED_LINES lines, above the configured limit of $MAX_CHANGED_LINES."
  exit 0
fi

# Warm the executor's dependencies so the agent's offline validation is fast.
uv run --quiet --script "$SKILL_DIR/scripts/post_review_comments.py" --help > /dev/null

# --- Phase 1: agent review (isolated engine, no GitHub credentials) -------------
ENGINE_HOME="$WORK/home"
mkdir -p "$ENGINE_HOME/.config/opencode" "$ENGINE_HOME/.local/share" "$ENGINE_HOME/.cache"

# A per-run provider id: repository config cannot target (and so cannot
# redirect) a provider whose id it does not know.
PROVIDER_ID="skopos$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
REVIEW_REL="${REVIEW_DIR#"$PROJECT_DIR"/}"

# Global config. Its policies outrank anything in the reviewed repository's own
# opencode.json(c): only our provider, no plugins/MCP/skills/web access, edits only
# inside the review directory, and a short shell allowlist.
jq -n \
  --arg pid "$PROVIDER_ID" \
  --arg pname "$PROVIDER_NAME" \
  --arg url "$PROVIDER_BASE_URL" \
  --arg mid "$MODEL" \
  --arg review_abs "$REVIEW_DIR" \
  --arg review_rel "$REVIEW_REL" \
  --arg skill "$SKILL_DIR" \
  '{
    "$schema": "https://opencode.ai/config.json",
    update: "disable",
    snapshots: false,
    model: ($pid + "/" + $mid),
    providers: {
      ($pid): {
        name: $pname,
        env: ["SKOPOS_PROVIDER_API_KEY"],
        package: "@opencode/ai/providers/openai-compatible",
        settings: { baseURL: $url },
        models: { ($mid): { name: $mid } }
      }
    },
    permissions: [
      { action: "*", resource: "*", effect: "allow" },
      { action: "question", resource: "*", effect: "deny" }
    ],
    policies: [
      { action: "provider.use", resource: "*", effect: "deny" },
      { action: "provider.use", resource: $pid, effect: "allow" },
      { action: "plugin.use", resource: "*", effect: "deny" },
      { action: "mcp.use", resource: "*", effect: "deny" },
      { action: "skill.use", resource: "*", effect: "deny" },
      { action: "websearch.use", resource: "*", effect: "deny" },
      { action: "tool.use", resource: "webfetch:*", effect: "deny" },
      { action: "tool.use", resource: "websearch:*", effect: "deny" },
      { action: "tool.use", resource: "question:*", effect: "deny" },
      { action: "tool.use", resource: "edit:*", effect: "deny" },
      { action: "tool.use", resource: ("edit:" + $review_abs + "/*"), effect: "allow" },
      { action: "tool.use", resource: ("edit:" + $review_rel + "/*"), effect: "allow" },
      { action: "tool.use", resource: "external_directory:*", effect: "deny" },
      { action: "tool.use", resource: ("external_directory:" + $skill + "/*"), effect: "allow" },
      { action: "tool.use", resource: "shell:*", effect: "deny" },
      { action: "tool.use", resource: "shell:skopos-post *", effect: "allow" },
      { action: "tool.use", resource: "shell:jq *", effect: "allow" },
      { action: "tool.use", resource: "shell:git diff *", effect: "allow" },
      { action: "tool.use", resource: "shell:git show *", effect: "allow" },
      { action: "tool.use", resource: "shell:git log *", effect: "allow" },
      { action: "tool.use", resource: "shell:git grep *", effect: "allow" },
      { action: "tool.use", resource: "shell:ls *", effect: "allow" },
      { action: "tool.use", resource: "shell:mkdir *", effect: "allow" },
      { action: "tool.use", resource: "shell:grep *", effect: "allow" },
      { action: "tool.use", resource: "shell:head *", effect: "allow" },
      { action: "tool.use", resource: "shell:tail *", effect: "allow" },
      { action: "tool.use", resource: "shell:wc *", effect: "allow" }
    ]
  }' > "$ENGINE_HOME/.config/opencode/opencode.json"

PROMPT="Follow the attached Skopos code-review skill. Review GitHub pull request #${PR_NUMBER}.
The packaged review context is at ${CONTEXT_JSON} (summary attached as manifest.json); it is the source of truth.
Write the dashboard and comment markdown files into ${REVIEW_DIR} (also in \$SKOPOS_REVIEW_DIR).
Validate them offline with: skopos-post ${PR_NUMBER} ${REVIEW_DIR} --context ${CONTEXT_JSON}
Fix every skipped or invalid item and validate again until the run is clean. Do not try to post; posting happens after you finish."

AGENT_LOG="$REVIEW_DIR/agent.log"
echo "::group::Agent review (model ${MODEL} via ${PROVIDER_NAME})"
run_status=0
# env -i: the agent gets no GitHub token and none of the runner's other secrets.
env -i \
  PATH="$ACTION_PATH/bin:$PATH" \
  HOME="$ENGINE_HOME" \
  XDG_CONFIG_HOME="$ENGINE_HOME/.config" \
  XDG_DATA_HOME="$ENGINE_HOME/.local/share" \
  XDG_STATE_HOME="$ENGINE_HOME/.local/state" \
  XDG_CACHE_HOME="$ENGINE_HOME/.cache" \
  LANG="${LANG:-C.UTF-8}" \
  TERM=dumb \
  CI=true \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  SKOPOS_PROVIDER_API_KEY="$SKOPOS_LLM_API_KEY" \
  SKOPOS_SKILL_DIR="$SKILL_DIR" \
  SKOPOS_REVIEW_DIR="$REVIEW_DIR" \
  SKOPOS_REVIEW_DIR_BASE="$REVIEW_BASE" \
  SKOPOS_CONTEXT_JSON="$CONTEXT_JSON" \
  "$SKOPOS_ENGINE_BIN" run --standalone --auto --archived \
    --model "${PROVIDER_ID}/${MODEL}" \
    --file "$SKILL_DIR/SKILL.md" \
    --file "$MANIFEST_JSON" \
    "$PROMPT" 2>&1 | tee "$AGENT_LOG" || run_status=$?
echo "::endgroup::"
if [ "$run_status" -ne 0 ]; then
  echo "::error title=Skopos::Review engine exited with status $run_status"
  summary "### Skopos review failed" "" "The review engine exited with status $run_status. See the job log and the uploaded artifact."
  exit "$run_status"
fi

# --- Guard: never publish anything containing a credential -----------------------
if grep -rqF -- "$SKOPOS_LLM_API_KEY" "$REVIEW_DIR" --include='*.md' --include='*.markdown'; then
  echo "::error title=Skopos::A review file contains the LLM API key; refusing to post."
  find "$REVIEW_DIR" -maxdepth 1 -type f \( -name '*.md' -o -name '*.markdown' \) -delete
  exit 1
fi
if grep -rqF -- "$GH_TOKEN" "$REVIEW_DIR"; then
  echo "::error title=Skopos::A review file contains the GitHub token; refusing to post."
  find "$REVIEW_DIR" -maxdepth 1 -type f \( -name '*.md' -o -name '*.markdown' \) -delete
  exit 1
fi

if ! find "$REVIEW_DIR" -maxdepth 1 -type f \( -name '*.md' -o -name '*.markdown' \) | grep -q .; then
  echo "::error title=Skopos::The agent produced no review files."
  summary "### Skopos review failed" "" "The agent finished without writing any review files."
  exit 1
fi

# --- Phase 2: post against live PR state -----------------------------------------
echo "::group::Post review"
post_status=0
uv run --quiet --script "$SKILL_DIR/scripts/post_review_comments.py" "$PR_NUMBER" "$REVIEW_DIR" || post_status=$?
echo "::endgroup::"

if [ -f "$REVIEW_DIR/posting-summary.json" ]; then
  jq -r '
    "### Skopos review",
    "",
    "| Inline findings | PR comments | Updated | Replies | Resolved | Skipped | Failed |",
    "|---|---|---|---|---|---|---|",
    "| \(.inline_posted) | \(.comments_created) | \(.updated) | \(.replied) | \(.resolved) | \(.skipped) | \(.failed + .resolve_failed + .resolve_invalid) |"
  ' "$REVIEW_DIR/posting-summary.json" >> "$SUMMARY_FILE"
fi
exit "$post_status"
