---
name: code-review.reference.comment-examples
description: Compact examples for review markdown files.
---

# Comment Examples

## Inline comment (single line)

````markdown
---
type: inline
file: src/orders/pricing.py
line: 88
finding_key: pricing/discount-applied-twice
rule_id: correctness.discount_double_apply
certainty: high
---
_⚠️ Potential issue_ | _Major_

**The discount is applied to a subtotal that already includes it.**

`apply_discount()` runs on `subtotal`, but `subtotal` is computed from `line_totals`, which already include the per-line discount. Orders with both discounts are under-charged.

```suggestion
    total = apply_discount(raw_subtotal, order.discount)
```
````

## Inline comment without a suggestion

````markdown
---
type: inline
file: migrations/versions/0042_add_invoice_status.py
line: 12
finding_key: migrations/missing-downgrade
rule_id: architecture.migration_reversible
certainty: high
---
_⚠️ Potential issue_ | _Major_

**The new migration has no `downgrade()` step.**

Every other migration in `migrations/versions/` is reversible, and the deploy runbook relies on `alembic downgrade -1` for rollbacks. Add a `downgrade()` that drops the `status` column.
````

## Multi-line suggestion: replace a range, not one line

On GitHub a suggestion replaces **exactly** the commented line range: `start_line` through `line`. Set both in the frontmatter and make the block body the complete new content of that range.

Original code at `src/importer/runner.py:70-72`:

```python
            for repository in self._repositories:
                save(repository, batch)
            total += len(batch)
```

````markdown
---
type: inline
file: src/importer/runner.py
start_line: 70
line: 72
finding_key: importer/count-ignores-save-result
rule_id: correctness.save_return_ignored
certainty: high
---
_💡 Suggestion_ | _Minor_

**`run()` counts rows streamed, not rows persisted.** Fold the save return value into `total` so the count and the log reflect what the repositories actually wrote.

```suggestion
            for repository in self._repositories:
                total += save(repository, batch)
```
````

Why the range matters: lines 70-72 are replaced by the two body lines. The body repeats the loop header only because the header is **inside** the replaced range.

Anti-pattern that corrupts code: commenting on the single `save(repository, batch)` line and writing a body that re-declares `for repository in self._repositories:`. GitHub replaces only that one line, so the loop nests. Never put statements in the body that live outside the replaced range.

Range rules:

- `start_line` and `line` must both be on the new side of the **same diff hunk** (added or context lines). The executor rejects anything else, because GitHub would reject the whole review.
- One range per comment. Do not put two suggestion blocks with different ranges in one comment.

## Reply that resolves a fixed finding

`discussion_id` is the id of the thread's root comment, as listed in `context.json` → `review_state.discussions[].id`.

```markdown
---
type: reply
discussion_id: "1712345678"
finding_key: pricing/discount-applied-twice
resolve_thread: true
resolution_kind: fixed_by_code
resolution_basis: total is now computed from the undiscounted subtotal
resolution_evidence: lines 84-90 compute raw_subtotal and apply the discount once
---
This looks fixed now: `apply_discount()` runs on `raw_subtotal`, so the order discount is applied exactly once.
```

Do not write a reply like "this is fixed now" or "this is no longer valid" without `resolve_thread: true` plus resolution metadata. If the finding is gone, the thread should be resolved.

## Reply that retires a duplicate thread

```markdown
---
type: reply
discussion_id: "1712349999"
finding_key: lifecycle/acknowledged-state
resolve_thread: true
resolution_kind: duplicate_of_canonical
resolution_basis: this thread duplicates the canonical lifecycle-state discussion
resolution_evidence: same finding_key and same missing ACKNOWLEDGED lifecycle state
canonical_discussion_id: "1712345678"
---
This is tracked in the canonical thread; closing this duplicate.
```

## Dashboard skeleton

```markdown
---
type: dashboard
key: review-dashboard
---
<!-- skopos:review-dashboard -->

## Skopos review

### Open actionable findings

| Severity | File | Finding | Thread |
|---|---|---|---|
| Major | `src/api/search.py` | SQL injection risk in raw query | `1712345678` |

<details>
<summary>Resolved since last run</summary>

| Finding | Resolved by | Thread |
|---|---|---|
| Missing null guard | `octocat` | `1712340000` |

</details>

<details>
<summary>Waived / by-design</summary>

| Finding | Waiver type | Reason |
|---|---|---|
| Private helper typing | `by_design` | intentionally internal and dynamic |

</details>

<details>
<summary>Duplicates suppressed</summary>

| Finding key | Canonical thread | Suppressed threads |
|---|---|---|
| `testing/missing-case/auth` | `1712341111` | `1712342222`, `1712343333` |

</details>

<details>
<summary>Files reviewed</summary>

| File | Findings | Details |
|---|---|---|
| `src/orders/pricing.py` | 2 | 1 major, 1 nitpick |

</details>
```

## Formatting rules

- Keep `Open actionable findings` expanded.
- Keep `Files reviewed` collapsed.
- Do not add a separate summary section to the dashboard.
- Use `suggestion` blocks by default; use an AI-agent prompt section only for multi-file or architectural fixes.
- A `suggestion` block replaces exactly the commented range (`start_line`..`line`, or just `line`). The body must be the complete final content of that range.
- Quote numeric ids in frontmatter (`discussion_id: "1712345678"`) so YAML keeps them as strings.
