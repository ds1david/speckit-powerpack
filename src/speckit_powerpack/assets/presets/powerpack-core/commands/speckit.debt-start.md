---
description: "Start controlled work on technical debt after a strict readiness gate."
---

# SpecKit Technical Debt — Start

Read the PowerPack debt floor, `.specify/powerpack/technical-debt.json`, the target item and all project policy references.

This command selects existing debt for work. It does not automatically create a SPEC and does not create one SPEC per debt item.

## Readiness gate

Before writing:

1. exact ID exists and is `OPEN`;
2. readiness is `READY`;
3. item still satisfies the effective debt policy floor;
4. owner, impact, deferral rationale and objective resolution criteria remain meaningful;
5. dependencies/blockers are understood;
6. if several items will be worked together, they form one coherent implementation capability;
7. a supplied SPEC does not silently broaden unrelated scope.

If material information is missing return `NEEDS_REFINEMENT`/`BLOCKED` without mutation.

## Start

For each approved item invoke:

```bash
python .specify/powerpack/bin/debt.py start <TD-ID> \
  --spec <optional-spec> \
  --branch <optional-branch> \
  --evidence "<start provenance>"
```

The runtime mechanically requires `OPEN + READY`, changes only lifecycle/status fields, preserves the original debt description/provenance and appends an `IN_PROGRESS` lifecycle event.

Do not move entries into `specs/`, delete history, reuse IDs or edit application code as a side effect.

Return started IDs, effective policy, work references and the original resolution criteria that `speckit-debt-close` must later prove.
