---
description: "Official Spec Kit analyze enhanced by PowerPack prerequisite enforcement."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage analyze
python .specify/powerpack/bin/powerpack.py prereq check --step analyze
```

If the prerequisite check fails, STOP and execute the returned `next_action`.

{CORE_TEMPLATE}

## PowerPack completion receipt

After successful completion:

```bash
python .specify/powerpack/bin/powerpack.py state mark analyze --status COMPLETED
```
