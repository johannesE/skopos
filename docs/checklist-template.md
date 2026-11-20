---
name: code-review.check.<topic>
description: <One sentence: what this checklist catches.>
---

# <Topic>

## When to run

<Which changed files or kinds of change trigger this checklist, e.g. "When the PR
changes files under `src/api/`". Leave this section out to run on every PR.>

## Checklist

- [ ] <One concrete, checkable rule> (<where it is documented, e.g. `AGENTS.md` Testing>)
- [ ] <Another rule>
- [ ] <8-12 items in total>

## Severity guidance

| Finding | Severity |
|---|---|
| <Something that breaks users or data> | Critical |
| <Something that will cause bugs or outages> | Major |
| <Something worth fixing but not urgent> | Minor |

## Do not flag when

- <An accepted convention that looks like a problem but is not>
- <A case where the rule does not apply>
