---
description: "Resolve technical debt only with objective evidence against its original resolution criteria."
---

# SpecKit Technical Debt — Close

Closing debt is an evidence gate. `RESOLVED` is allowed only when the original resolution criteria are demonstrated.

For each ID:

1. confirm exact identity, owner and unresolved state;
2. recover the original resolution criteria and refuse inference when they are too vague;
3. validate implementation/documentation/test evidence;
4. verify a linked SPEC actually covers the intended debt without assuming a checkbox is proof;
5. treat PR/commit/branch references as provenance, not correctness evidence;
6. when executable validation is required, run the PowerPack capability-selected gate through `.specify/powerpack/bin/capabilities.py`, never a hard-coded language/framework command;
7. confirm no relevant residual remains against the original criterion.

If evidence is insufficient, a required gate failed, residual work remains or ownership conflicts, return `NOT_CLOSABLE` and do not write.

On success, update only the debt item lifecycle/history: mark `RESOLVED`, record date, relevant SPEC/PR/commit provenance and concise validated evidence. Never delete the item or its history.
