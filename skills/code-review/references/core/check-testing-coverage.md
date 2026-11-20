---
name: code-review.check.testing-coverage
description: Compact checklist for testing coverage; use a sub-agent for this check.
---

# Testing Coverage

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] New code has tests - All new functions/components have test coverage
- [ ] Edge cases tested - Tests cover boundary conditions and error states
- [ ] Happy path tested - Normal operation is verified
- [ ] Error handling tested - Exception paths have test coverage
- [ ] Mocking appropriate - External dependencies are properly mocked
- [ ] Test isolation - Tests don't depend on each other or external state
- [ ] Async tests correct - Async operations properly awaited
- [ ] Test naming clear - Test names describe what they verify

Do not flag when:

- the requested test would only verify language/runtime/framework behavior rather than project-specific logic
- a private/internal helper is only exercised through a public wrapper and that public behavior is already covered
- the suggested test would duplicate existing coverage without adding a new failure mode or regression signal
