# Changelog

## Unreleased

- Fall back to `github_token` with a warning when only one of `app_client_id` / `app_private_key` is set, instead of failing the run
- Simpler README and usage guide with diagrams, copy-paste prompts for coding agents, and a checklist template

## v1.0.0 — 2026-11-20

First release.

- Composite GitHub Action reviewing pull requests on every push
- Packaging of PR diff, file contents, review threads, comments, linked issue and `AGENTS.md`/`CLAUDE.md` standards
- Sandboxed review agent with no GitHub credentials, enforced by engine policies; offline validation via `skopos-post --context`
- Deterministic executor: one batched review per run, per-comment fallback, thread replies, ownership-gated resolution, dashboard upsert
- GitHub App identity (client ID + private key) with `GITHUB_TOKEN` fallback
- Project checklist overlay from `.github/skopos/checklists/`
