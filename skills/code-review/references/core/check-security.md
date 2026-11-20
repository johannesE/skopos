---
name: code-review.check.security
description: Compact checklist for security review; use a sub-agent for this check.
---

# Security

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] No hardcoded secrets - API keys, passwords, tokens, credentials not in code or committed .env files
- [ ] Input validation - All external input (API responses, CSV/JSON feeds) is validated/sanitized
- [ ] SQL injection - Use parameterized queries, no string concatenation in queries
- [ ] Authentication checks - Protected flows/tasks verify credentials/block access
- [ ] Authorization checks - Service accounts and tokens are scoped to least privilege
- [ ] Sensitive data exposure - Don't log passwords, tokens, PII, or credentials
- [ ] HTTPS only - No plaintext HTTP URLs for external API calls
- [ ] Dependency security - No known vulnerable packages in uv.lock
- [ ] Secret management - Secrets come from a secret manager or the environment, not inline literals
