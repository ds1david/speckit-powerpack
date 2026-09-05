---
description: "List governed technical debt with stable filters and readiness/status visibility."
---

# SpecKit Technical Debt — List

Read `.specify/powerpack/technical-debt-policy.md`, `.specify/powerpack/technical-debt.json` and project policy references first so owner/priority semantics are interpreted correctly. This command is read-only.

Use the deterministic ledger runtime for the canonical inventory:

```bash
python .specify/powerpack/bin/debt.py list
```

Optional filters:

```bash
python .specify/powerpack/bin/debt.py list \
  --status OPEN \
  --readiness READY \
  --priority P2 \
  --owner "<owner>"
```

Present a compact table with ID, owner, priority, status, readiness, title and blockers/dependencies when present. Keep `status` and `readiness` distinct: an OPEN item may still be BLOCKED or NEEDS_REFINEMENT.

When several items form one coherent capability, recommend grouping them into a future SPEC rather than creating one SPEC per item. Do not mutate lifecycle while listing.

If project policy or provenance reveals a P0/BLOCKER, active convergence gap or unresolved review finding in the backlog, flag it as a governance inconsistency; do not silently normalize it as legitimate debt.
