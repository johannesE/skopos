---
name: code-review.reference.negative-rules
description: High-value false-positive guardrails for pull request review.
---

# Negative Rules

Use these as hard guardrails before posting a finding.

## Convention checks

- Do not flag a pattern as "wrong" if it is used consistently across 3+ relevant sibling files.
- Treat repeated repo usage as an established convention unless it creates a correctness, security, performance, or maintainability problem with concrete evidence.
- Prefer "this differs from the local convention" only when the new code is the outlier, not when the repo convention is the pattern itself.

## Data-flow checks

- Do not suggest defensive null checks, guards, or default branches until you trace where the value comes from.
- If earlier validation, typing, or framework guarantees prove the value is present, suppress the defensive-code suggestion.
- Do not ask for impossible or redundant error handling on paths that cannot occur in the actual flow.

## Test-request checks

- Do not request tests for language, runtime, or framework behavior that is already guaranteed by the platform.
- Do not request direct tests of private/internal helpers when public tests already exercise the behavior.
- Do not ask for duplicate tests that only restate existing coverage without increasing signal.

## General skip rules

- Skip preference-only cleanups when the code is already consistent and intentional.
- Skip findings that only rephrase an existing open/resolved/waived discussion without new evidence.
- Skip findings that depend on assumptions you have not validated from the package, code path, or thread history.
