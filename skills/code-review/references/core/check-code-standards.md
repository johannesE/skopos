---
name: code-review.check.code-standards
description: Compact checklist for code standards and AGENTS.md compliance; use a sub-agent for this check.
---

# Code Standards (AGENTS.md Compliance)

Use a sub-agent to perform this check; keep the output compact.

Language-specific standards and examples live in:

- `AGENTS.md`

Checklist (language-agnostic):

- [ ] Linting and formatting pass for the stack
- [ ] Import patterns follow repo conventions (no inline imports and no importing an import)
- [ ] Type annotations are present where required
- [ ] Naming conventions align with the stack guide

Do not flag when:

- the code follows an established local convention used across 3+ relevant files, even if you would prefer a different style
- the import or naming pattern matches the surrounding module/package and does not violate an explicit documented standard
