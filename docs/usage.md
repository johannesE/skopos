# Usage guide

Setting Skopos up for a repository or an organization. The [README](../README.md)
covers what Skopos is and how it works.

## Quick start: one-prompt adoption

A coding agent can do the setup for you. Paste this prompt into it while it is
working in the repository you want reviewed, and fill in the bracketed part. It
adds the workflow, writes repository-specific checklists, and opens a pull request.

Prerequisite: the secrets below already exist for this repository.

```text
Add the Skopos pull request review (GitHub Action johannesE/skopos) to this
repository on a new branch, then open a pull request.

Background: Skopos reviews every push to a pull request and posts inline
findings plus a dashboard comment. The review logic ships with the action;
this repository only adds a workflow file and optional project checklists.

1. Read AGENTS.md / CLAUDE.md and README.md to understand the stack,
   architecture, conventions and testing patterns. Ask me before assuming
   anything important.

2. Create .github/workflows/skopos.yml with exactly the content of
   https://github.com/johannesE/skopos/blob/v1/examples/workflows/skopos.yml
   Do not commit any secrets; SKOPOS_LLM_API_KEY, SKOPOS_APP_CLIENT_ID and
   SKOPOS_APP_PRIVATE_KEY are already configured.

3. Create review checklists under .github/skopos/checklists/. Every markdown
   file there runs. Use check-<topic>.md names and pick topics that matter
   here, focusing on: <your focus, e.g. "API contract stability, query
   performance, test coverage for repositories">.
   Each file has: YAML frontmatter (name, description); "When to run" naming
   the files/changes that trigger it; "Checklist" with one concrete rule per
   item, pointing to where the rule is documented (an AGENTS.md section)
   instead of restating it; "Severity guidance" (Critical/Major/Minor);
   "Do not flag when" for accepted conventions. Keep each to 8-12 items.

4. Add .skopos/ to .gitignore.

5. Create a branch, commit, push, and open a pull request.

Ask if you are unsure which checks matter most or what could cause noisy findings.
```

## Secrets and identity

Skopos needs a model API key, plus a GitHub identity to post with.

| Name | Kind | Required | Content |
|---|---|---|---|
| `SKOPOS_LLM_API_KEY` | Actions **secret** | yes | API key of your OpenAI-compatible model provider |
| `SKOPOS_APP_CLIENT_ID` | Actions **variable** | recommended | Client ID of the Skopos GitHub App (not secret) |
| `SKOPOS_APP_PRIVATE_KEY` | Actions **secret** | recommended | Private key (`.pem` content) of that App |

### Why a GitHub App

Without an App, Skopos posts with the workflow's built-in `GITHUB_TOKEN` as
`github-actions[bot]`. That works, but every bot shares that name, and review
threads opened by other workflows look the same. A dedicated App gives you:

- a clear reviewer identity (`skopos-yourorg[bot]`), which is also the identity
  Skopos uses to decide which threads it may resolve
- a token minted per run that expires after an hour, scoped to the current
  repository, with only the permissions listed below
- one private key to rotate instead of long-lived personal access tokens

### Create the GitHub App (once)

1. Open **Settings → Developer settings → GitHub Apps → New GitHub App**. Use your
   organization's settings if the repositories belong to an organization; a
   private App can only be installed on the account that owns it.
2. Name it, e.g. `skopos-<org>`. Homepage URL: any URL, e.g. your org page.
3. **Webhook:** uncheck *Active*. Skopos never receives events.
4. **Repository permissions:**
   - Contents: **Read-only**
   - Issues: **Read-only** (to read linked issues)
   - Pull requests: **Read and write**
   - Metadata: Read-only (mandatory, preselected)
5. **Where can this App be installed:** *Only on this account*.
6. Create it, then copy the **Client ID** from the App page, and generate a
   **private key** (a `.pem` file downloads).
7. **Install App** → choose all repositories or the ones you want reviewed.

### Store the values

Organization-wide, shared with selected repositories (recommended for orgs):

```bash
gh secret set SKOPOS_LLM_API_KEY --org <org> --visibility selected --repos repo-a,repo-b
gh variable set SKOPOS_APP_CLIENT_ID --org <org> --visibility selected --repos repo-a,repo-b --body "Iv23li..."
gh secret set SKOPOS_APP_PRIVATE_KEY --org <org> --visibility selected --repos repo-a,repo-b < skopos.private-key.pem
```

Use `--visibility all` to share with every repository, or `private` for all
private repositories. To add a repository later, run the same commands with the
full `--repos` list, or use the org settings UI (Secrets and variables → Actions).

Repositories on a personal account have no account-wide secrets; set them per
repository:

```bash
for repo in johannesE/repo-a johannesE/repo-b; do
  gh secret set SKOPOS_LLM_API_KEY --repo "$repo"
  gh variable set SKOPOS_APP_CLIENT_ID --repo "$repo" --body "Iv23li..."
  gh secret set SKOPOS_APP_PRIVATE_KEY --repo "$repo" < skopos.private-key.pem
done
```

`gh secret set` without `--body` prompts for the value, so the key never ends up
in your shell history.

Delete the downloaded `.pem` file after storing it.

### How the secrets are handled at runtime

- Secrets only reach the steps that need them, via `env`. They are never
  interpolated into scripts.
- The App token is minted with only `contents: read`, `issues: read` and
  `pull-requests: write`, for the current repository.
- The review agent runs in a cleared environment. It gets the model key but no
  GitHub token and none of the runner's other variables. Its engine config lives
  in a temporary home directory, not in the repository.
- Engine policies hard-deny network tools, web fetch, plugins, MCP servers, edits
  outside the review output directory, and any shell command not on a short
  read-only allowlist. These policies outrank any `opencode.json` the reviewed
  repository contains.
- Before posting, the entrypoint refuses to publish any review file that
  contains the model key or the GitHub token.
- Pull requests from **forks** receive no secrets on `pull_request` events, so
  the review is skipped with a notice. Skopos never uses `pull_request_target`.
- Dependabot PRs get Dependabot secrets, not Actions secrets. The example
  workflow skips bot-authored PRs anyway.

## Model provider

Any OpenAI-compatible chat completions endpoint works. The default is Ollama Cloud
(`https://ollama.com/v1`, model `glm-5.3`):

1. Create an account at [ollama.com](https://ollama.com) and pick a plan.
2. Settings → Keys → **Add API Key**.
3. Store it as `SKOPOS_LLM_API_KEY`.

Other providers:

```yaml
- uses: johannesE/skopos@v1
  with:
    llm_api_key: ${{ secrets.SKOPOS_LLM_API_KEY }}
    model: <model-id>
    provider_base_url: https://api.openai.com/v1
    provider_name: OpenAI
```

Self-hosted (e.g. Ollama or vLLM on your network) works too if the runner can
reach it: `provider_base_url: http://llm.internal:11434/v1`.

## Project checklists

Skopos ships generic **core checks**. Repositories add **project checks**: every
markdown file in

```
.github/skopos/checklists/
```

runs **in addition to** the core checks. Core checks are never replaced. A missing
directory means core checks only. Use the `project_checklists_dir` input to move it,
or set it to `""` to disable.

Each checklist decides when it applies through its `When to run` section; a
checklist without one runs on every PR. Common names:

| File | Typical `When to run` |
|---|---|
| `check-project-conventions.md` | every PR — your stack-specific focus |
| `check-documentation-drift.md` | every PR (self-suppress for docs/test/CI-only PRs) |
| `check-api-regressions.md` | public API surface changes |
| `check-testing.md` | test files added or modified |
| `check-performance.md` | database/query changes |
| `check-architecture.md` | new files |

Example (`check-api-regressions.md` for a REST service):

```markdown
---
name: code-review.check.api-regressions
description: Detect breaking REST API contract changes in the /api/v1 surface.
---

# API Regressions

## When to run

Run when the PR changes files under `src/**/controllers/`, `src/**/dto/`,
`openapi.yaml`, or error-to-status mappings.

## Checklist

- [ ] Removed or renamed endpoints — a deleted/renamed route or HTTP-method change
  breaks clients; needs a deprecation period or a new `/api/v2` path (`AGENTS.md` API)
- [ ] Request parameter changes — renaming parameters or making an optional one
  required without a default is breaking
- [ ] Response field removal/renames — need a deprecation path; additive fields are fine
- [ ] Status code stability — changing which error maps to which status is client-visible
- [ ] CHANGELOG entry — user-visible API changes add an entry to `CHANGELOG.md`

## Severity guidance

| Finding | Default severity |
|---|---|
| Breaking change without versioning or deprecation path | **Critical** |
| Status code / error contract change without changelog | **Major** |
| Missing CHANGELOG entry | **Minor** |

## Do not flag when

- the change is purely additive (new optional parameter, new field, new endpoint)
- the endpoint is already marked deprecated and the PR documents the removal timeline
- the change touches only internal code with no API surface
```

Tips:

- **Anchor rules in `AGENTS.md` / `CLAUDE.md`.** The packaging step embeds those
  files (root plus the nearest one for each changed file), so rules that cite them
  are checked against the real text.
- **Write "Do not flag when" sections.** They suppress false positives better than
  anything else.
- **Include severity guidance**, so triage matches your expectations: Critical/Major
  post inline, Nitpicks stay on the dashboard.
- **Keep checklists compact.** Focused lists beat exhaustive ones.

## Rolling out to many repositories

- **Organization workflow template:** put `examples/workflows/skopos.yml` into your
  organization's `.github` repository as `workflow-templates/skopos.yml`, plus a
  `workflow-templates/skopos.properties.json`:

  ```json
  { "name": "Skopos review", "description": "AI pull request review", "iconName": "octicon eye" }
  ```

  Every repository can then add it from **Actions → New workflow**.
- **Script it:** create a branch with the workflow file in each repository using `gh`.

## Reading the result

- The **dashboard comment** shows open findings expanded, with resolved, waived and
  duplicate findings collapsed. It is edited in place on every run.
- **Inline findings** arrive as one review. Critical and Major findings are always
  posted inline, Minor ones when actionable, and Nitpicks only on the dashboard.
- Pushing a fix makes Skopos reply in the thread and resolve it, but only threads
  it opened itself. Threads humans open stay under human control.
- Reply `by design`, `intentional`, `false positive` or `already addressed` to
  waive a finding for good. `thanks`, `ok` and emoji are not waivers.
- To opt a single PR out, add the `skip-skopos` label.
- Every run uploads `context.json`, the generated review files, the posting logs
  and the agent log as a workflow artifact. These help when tuning a checklist.

## Costs

Each review is one agent session over the packaged PR, so cost scales with PR size
and with your provider's prices. Check your provider's usage dashboard after the
first few reviews. Because Skopos runs on every push, consider:

- `max_changed_lines` to skip very large PRs
- `cancel-in-progress` (already in the example workflow) so rapid pushes only pay for the last one
- the `skip-skopos` label for PRs that do not need a review

The only other cost is Actions minutes for the job.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Notice "No LLM API key available" | Fork PR, or the secret is not shared with this repository |
| `Resource not accessible by integration` | App not installed on the repo, or missing Pull requests write permission; without an App, the workflow lacks `pull-requests: write` |
| Findings skipped as `inline_line_not_in_diff` | The model anchored a finding outside the diff. The agent is told to move such findings to the dashboard; `posting-skipped.jsonl` in the artifact lists what was dropped |
| Duplicate dashboards | Two runs posted in parallel; keep the `concurrency` block from the example |
| Review engine exited with an error | See the `agent.log` in the artifact; usually a wrong model ID or base URL |
