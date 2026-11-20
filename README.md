# Skopos

*σκοπός — "watcher, lookout"*

Skopos is a GitHub Action that reviews pull requests with an LLM agent and posts
the results back to the PR:

- **3–7 inline findings** per review, submitted as one GitHub review, with ready-to-commit `suggestion` blocks
- **a dashboard comment** listing open, resolved, waived and duplicate findings, updated in place on each run
- **replies on existing threads** when there is new evidence, and **resolves its own threads** once the code is fixed

It runs on every push to a pull request and is idempotent. Findings are matched to
existing threads, so a new push replies in the existing thread instead of opening a
duplicate. Replies such as `by design` or `false positive` from the PR author or
reviewers mark a finding as waived, and it is not raised again.

It works in any repository and language. The core checks are generic: standards,
quality, edge cases, security, performance, tests, logging, architecture and docs.
Each repository can add its own checklists.

## Quick start

1. **Set the secrets once** (details in [docs/usage.md](docs/usage.md#secrets-and-identity)):

   | Name | Kind | Value |
   |---|---|---|
   | `SKOPOS_LLM_API_KEY` | secret | API key of your model provider |
   | `SKOPOS_APP_CLIENT_ID` | variable | Client ID of your Skopos GitHub App (optional, recommended) |
   | `SKOPOS_APP_PRIVATE_KEY` | secret | Private key of that App (optional, recommended) |

   Set them at organization level and share them with selected repositories, or set
   them per repository.

2. **Add the workflow.** Copy [`examples/workflows/skopos.yml`](examples/workflows/skopos.yml)
   to `.github/workflows/skopos.yml`:

   ```yaml
   name: Skopos review
   on:
     pull_request:
       types: [opened, synchronize, reopened, ready_for_review]
   concurrency:
     group: skopos-${{ github.event.pull_request.number }}
     cancel-in-progress: true
   permissions:
     contents: read
     pull-requests: write
   jobs:
     review:
       if: >-
         !github.event.pull_request.draft &&
         !contains(github.event.pull_request.labels.*.name, 'skip-skopos') &&
         github.event.pull_request.user.type != 'Bot'
       runs-on: ubuntu-latest
       timeout-minutes: 30
       continue-on-error: true
       steps:
         - uses: johannesE/skopos@v1
           with:
             llm_api_key: ${{ secrets.SKOPOS_LLM_API_KEY }}
             app_client_id: ${{ vars.SKOPOS_APP_CLIENT_ID }}
             app_private_key: ${{ secrets.SKOPOS_APP_PRIVATE_KEY }}
   ```

3. **Optional:** add project checklists under `.github/skopos/checklists/`
   ([how](docs/usage.md#project-checklists)).

Open a pull request. The review shows up a few minutes later.

## How it works

```
pull_request push
  └─ Skopos action
       1. Package   gh + git → .skopos/review-context/…/context.json
                    (diff, file contents, review threads, comments, linked issue, AGENTS.md)
       2. Review    LLM agent in a sandbox: no GitHub token, no network tools,
                    writes markdown findings, validates them offline
       3. Post      deterministic Python executor: dedupe, one review with inline
                    comments, replies, thread resolution, dashboard upsert
```

The agent never sees a GitHub credential. It runs with a minimal environment, a
short shell allowlist, edits limited to its output directory, and no plugins, MCP
servers or web access. These limits are enforced as engine policies that the
reviewed repository's own configuration cannot loosen. Posting is done afterwards
by the executor, which checks every inline comment against the diff and refuses to
post anything that contains a credential.

## Inputs

| Input | Default | Description |
|---|---|---|
| `llm_api_key` | — | Model provider API key. Empty → review skipped (e.g. fork PRs) |
| `app_client_id` / `app_private_key` | `""` | GitHub App that posts reviews; empty → `github_token` (github-actions[bot]) |
| `github_token` | `${{ github.token }}` | Fallback token |
| `model` | `glm-5.3` | Model ID at the provider |
| `provider_base_url` | `https://ollama.com/v1` | Any OpenAI-compatible endpoint |
| `provider_name` | `Ollama Cloud` | Display name (logs only) |
| `project_checklists_dir` | `.github/skopos/checklists` | Project checklist directory; `""` disables |
| `max_changed_lines` | `0` | Skip PRs that change more lines than this (`0` = no limit) |
| `engine_version` | pinned | Review engine release |
| `upload_artifacts` | `true` | Upload context, review files and agent log |
| `artifacts_retention_days` | `7` | Artifact retention |

## Repository layout

- `action.yml` — the composite action
- `scripts/run-review.sh` — entrypoint: package → sandboxed agent → post
- `scripts/install-engine.sh` — installs the pinned review engine
- `bin/skopos-post` — executor wrapper the agent uses for offline validation
- `skills/code-review/` — review skill: `SKILL.md`, core checklists, packaging and posting scripts
- `examples/workflows/skopos.yml` — consumer workflow
- `docs/usage.md` — setup, secrets, checklists, options, costs
- `tests/` — unit tests for the GitHub-specific logic

## Development

```bash
uv run --no-project --with pytest --with pyyaml python -m pytest -q tests
uvx ruff check .
uvx --from actionlint-py actionlint
```

Run the skill against a local branch without GitHub access:

```bash
uv run skills/code-review/scripts/package_review_context.py local --base-ref main
```

## Releasing

Push a semver tag (`v1.2.3`). The release workflow moves the major tag (`v1`) and
creates a GitHub release. Consumers on `@v1` pick it up automatically; pin
`@v1.2.3` or a commit SHA for full reproducibility.
