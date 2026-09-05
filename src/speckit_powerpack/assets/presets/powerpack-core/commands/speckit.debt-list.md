---
description: "List and prioritize governed technical debt without modifying the backlog."
---

# SpecKit Technical Debt — List

Read `.specify/powerpack/technical-debt-policy.md`, `.specify/powerpack/technical-debt.json`, the configured backlog, and every project policy in `project_policy_paths`. This command is read-only.

Support filters for owner, status, priority, readiness, resolved items and free-text capability/group. Defaults show unresolved items.

For every item show at least: ID, owner, priority, status, short description, visible dependencies/blockers, probable future SPEC/capability and readiness (`READY`, `BLOCKED`, `NEEDS_REFINEMENT`, `RESOLVED`) with a short reason.

When several items describe one coherent capability, show a recommended group. Do not recommend one SPEC per item by default.

Never reclassify or edit an item while listing. If a P0/BLOCKER-like entry exists in the backlog, flag it as a governance inconsistency because blockers belong to the delivery flow that discovered them. Likewise flag any item whose provenance shows it is still an active convergence gap or unresolved implementation-review finding.
