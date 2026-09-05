---
description: "Official Spec Kit command enhanced by SpecKit PowerPack."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage plan
```

Apply the route only when the active integration supports safe model switching/delegation.

{CORE_TEMPLATE}

## PowerPack completion receipt

After successful completion:

```bash
python .specify/powerpack/bin/powerpack.py state mark plan --status COMPLETED
```
