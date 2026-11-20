---
name: code-review.check.performance
description: Compact checklist for performance review; use a sub-agent for this check.
---

# Performance

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] N+1 queries - Avoid querying in loops; batch API/DB calls and load related data up front
- [ ] Memoization - Expensive computations are cached/memoized where appropriate
- [ ] Dependency weight - No unnecessary large dependencies added to uv.lock
- [ ] Lazy imports - Heavy modules imported lazily where startup or flow overhead matters
- [ ] Algorithmic complexity - No O(n^2) or worse when O(n) is possible
- [ ] Memory - Large datasets are streamed or chunked (polars lazy, Arrow batches) instead of loaded whole
- [ ] Resource cleanup - Connections, sessions, file handles, and catalogs are released/closed
