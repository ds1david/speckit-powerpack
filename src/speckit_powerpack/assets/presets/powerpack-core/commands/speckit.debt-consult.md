---
description: "Inspect one governed technical-debt item, provenance, relationships, evidence and readiness."
---

# SpecKit Technical Debt — Consult

Resolve the exact debt ID from the configured backlog. Fail explicitly when the ID does not exist; never substitute a similar item.

Read PowerPack debt policy plus all configured project policy paths.

Show ID/owner/title or type, original description, origin/provenance, impact/priority, status/readiness, original resolution criteria, deferral rationale, probable future SPEC/capability, dependencies/blockers, lifecycle history and available implementation/test/documentation evidence.

When asked for related items, use objective relationships only: explicit dependency, same proposed SPEC/capability, same origin or clearly shared technical capability. Separate recorded fact from grouping recommendation.

A reference to a PR/commit/test does not by itself prove resolution. This command is read-only.
