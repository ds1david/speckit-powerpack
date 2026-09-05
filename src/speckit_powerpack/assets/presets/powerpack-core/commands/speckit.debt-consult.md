---
description: "Inspect one governed technical-debt item, provenance, relationships, evidence and readiness."
---

# SpecKit Technical Debt — Consult

Read `.specify/powerpack/technical-debt-policy.md`, `.specify/powerpack/technical-debt.json` and project policies. Then resolve the exact item through:

```bash
python .specify/powerpack/bin/debt.py consult <TD-ID>
```

Fail explicitly when the ID does not exist; never substitute a similar item.

Show ID/owner/title, original description, origin/provenance, impact/priority, status/readiness, resolution criteria, deferral rationale, future SPEC/capability, dependencies/blockers and evidence. Read lifecycle history from the backlog section when needed; do not rewrite it.

Also report a policy verdict. If the historical item would violate today's PowerPack floor—for example it is effectively a blocker, active convergence gap or unresolved implementation-review finding—show `GOVERNANCE_CONFLICT` without deleting or silently rewriting history.

When asked for related items, use objective relationships: explicit dependency, same proposed capability/SPEC, same origin or clearly shared technical capability. Separate recorded fact from grouping recommendation.

A PR, commit SHA or agent assertion is provenance, not sufficient resolution evidence by itself. This command is read-only.
