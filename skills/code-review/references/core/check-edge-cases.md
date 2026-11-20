---
name: code-review.check.edge-cases
description: Compact checklist for edge case handling; use a sub-agent for this check.
---

# Edge Cases

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] Null/undefined handling - Proper checks before accessing properties
- [ ] Empty collections - Handle empty arrays, objects, strings
- [ ] Boundary values - Handle min/max values, zero, negative numbers
- [ ] Invalid input - Validate and handle malformed data
- [ ] Race conditions - Consider concurrent access scenarios
- [ ] Network failures - Handle timeout, connection errors
- [ ] Pagination boundaries - First page, last page, empty results
