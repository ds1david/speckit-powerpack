---
description: "Official Spec Kit command enhanced by SpecKit PowerPack."
---

## PowerPack preflight

Run:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage specify
```

Treat the returned semantic profile as routing policy. Apply the configured concrete model only when the active integration can do so safely; otherwise continue with the current model.

{CORE_TEMPLATE}

## PowerPack completion receipt

Only after the official command above has completed successfully and its expected artifacts are present, run:

```bash
python .specify/powerpack/bin/powerpack.py state mark specify --status COMPLETED
```

Do not write a successful receipt when the official command is blocked or failed.
