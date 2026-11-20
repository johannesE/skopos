---
name: code-review.check.documentation-quality
description: Verify AGENTS.md and agent-guidance docs are consistent, accurate, and clear; use a sub-agent for this check.
---

# Documentation Quality (AGENTS.md and Agent Guidance)

Use a sub-agent to perform this check; keep the output compact.

Run this check when the PR adds or modifies any `AGENTS.md`, `CLAUDE.md`, `docs/coding-guidelines.md`, or similar agent-guidance documentation.

## Checklist

### Consistency and coherence

- [ ] Internal consistency — No contradictions within the same file (e.g. one section says "use upsert", another says "use append" for the same scenario)
- [ ] Cross-file consistency — Root `AGENTS.md` doesn't conflict with component/base/test `AGENTS.md` files; if a component file overrides or specializes a root rule, it says so explicitly
- [ ] Convention alignment — Documented conventions match what the codebase actually does; if the docs say "repositories use `upsert_by_key`", existing repositories should follow that pattern (spot-check 2-3 sibling files)
- [ ] Terminology consistency — The same concept uses the same term throughout (e.g. don't call it "row model" in one place and "data model" in another)

### Accuracy of references

- [ ] File paths exist — Every referenced path (e.g. `services/billing/AGENTS.md`, `docs/coding-guidelines.md`) resolves to a real file
- [ ] Commands are current — `just` recipes, CLI commands, and script paths mentioned in the docs still exist and work (check against `justfile`, `pyproject.toml`, actual scripts on disk)
- [ ] Section references valid — If the doc says "see §2.3.1" or "see Table Schemas section", that section exists with that name or number
- [ ] Tool/dependency names correct — Mentioned tools, frameworks and libraries match what is actually declared in the dependency manifests (`package.json`, `pyproject.toml`, `go.mod`, `pom.xml`, lockfiles)

### Freshness

- [ ] No stale references — No mentions of removed features, deleted files, deprecated patterns, or old tooling that no longer applies
- [ ] No orphaned guidance — No instructions for code paths or components that have been removed or renamed
- [ ] Examples compile mentally — Code examples use current APIs, correct imports, and valid syntax for the project's Python version

### Clarity

- [ ] Unambiguous instructions — Directions have one reasonable interpretation; no "maybe do X or Y" without saying when to pick which
- [ ] No confusing phrasing — Sentences that a reader would have to read twice to understand are rewritten
- [ ] Actionable for agents — Instructions describe things an agent can actually do (concrete steps, file operations, commands), not human-only process notes

### Structure

- [ ] No unintended duplication — The same guidance isn't copy-pasted across multiple files unless each copy adds context specific to its location
- [ ] Correct placement — Information lives in the right file (component-specific detail in the component `AGENTS.md`, not in root; cross-cutting rules in root, not buried in a component)

## Do not flag when

- a component `AGENTS.md` intentionally restates a root rule with added component-specific context or examples
- a doc references a file by a stable, well-known path even if the path uses a different separator or casing convention
- the doc intentionally describes a planned/migration state and labels it as such (e.g. "planned but not yet implemented")
- a command uses a placeholder argument (e.g. `<pr_number>`) that is clearly a template, not a literal
