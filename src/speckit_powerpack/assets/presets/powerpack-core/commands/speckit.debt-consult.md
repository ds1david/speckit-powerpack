---
description: "Inspect one governed technical-debt item, provenance, relationships, evidence and readiness."
---

# SpecKit Technical Debt — Consult

Read `.specify/powerpack/technical-debt-policy.md`, `.specify/powerpack/technical-debt.json`, the configured backlog and every project policy in `project_policy_paths`.

Resolve the exact debt ID. Fail explicitly when the ID does not exist; never substitute a similar item.

Show ID/owner/title or type, original description, origin/provenance, impact/priority, status/readiness, original resolution criteria, deferral rationale, probable future SPEC/capability, dependencies/blockers, lifecycle history and available implementation/test/documentation evidence.

Also report a policy verdict. If the item would violate the current PowerPack floor if created today—for example because it is a blocker, active convergence gap or unresolved implementation-review finding—show `GOVERNANCE_CONFLICT` without silently rewriting history.

When asked for related items, use objective relationships only: explicit dependency, same proposed SPEC/capability, same origin or clearly shared technical capability. Separate recorded fact from grouping recommendation.

A reference to a PR/commit/test does not by itself prove resolution. This command is read-only.
