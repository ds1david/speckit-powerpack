---
description: "Official Spec Kit converge wrapped with PowerPack state."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage converge
```

{CORE_TEMPLATE}

## Completion

Only when the official convergence command reports no remaining implementation gaps for the current SPEC, record:

```bash
python .specify/powerpack/bin/powerpack.py state mark converge --status CONVERGED
```
