---
name: code-review.check.logging-observability
description: Compact checklist for logging and observability; use a sub-agent for this check.
---

# Logging and Observability

Use a sub-agent to perform this check; keep the output compact.

Language-specific examples live in:

- `AGENTS.md`

- [ ] Appropriate log levels - DEBUG, INFO, WARNING, ERROR used correctly
- [ ] Structured logging - Use extra dict for context, not string interpolation
- [ ] Sensitive data excluded - No passwords, tokens, PII in logs
- [ ] Request context - Include request_id, user_id for tracing
- [ ] Error context - Exceptions logged with relevant context
- [ ] Performance logging - Long operations have timing logs
- [ ] Audit logging - Security-relevant actions are logged
