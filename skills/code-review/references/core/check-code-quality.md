---
name: code-review.check.code-quality
description: Compact checklist for code quality review; use a sub-agent for this check.
---

# Code Quality

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] Single Responsibility - Each function/class does one thing well
- [ ] DRY (Don't Repeat Yourself) - No duplicated logic; extract shared code unless the best alternative is way less readable
- [ ] Meaningful names - Variables, functions, classes have descriptive names
- [ ] Function length - Functions are not excessively long (< 50 lines preferred)
- [ ] Cyclomatic complexity - Avoid deeply nested conditionals
- [ ] Magic numbers/strings - Use named constants instead
- [ ] Dead code - No commented-out code or unused imports unless there is a TODO with a linked JIRA ticket
- [ ] Consistent patterns - Follows existing codebase conventions

Do not flag when:

- the same pattern appears consistently across 3+ relevant sibling files and the PR follows that convention
- the suggestion is only stylistic and does not improve correctness, maintainability, or repo consistency
- a defensive-code suggestion would only guard a value that is already guaranteed by upstream validation or framework behavior
