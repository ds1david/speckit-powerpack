---
description: "Diagnose a SpecKit PowerPack installation."
---

Run the project-local PowerPack runtime and validate at least:

1. `.specify/powerpack/bin/powerpack.py` exists and is executable by Python;
2. the current feature can be resolved;
3. Claude Code and/or Codex CLI availability is reported accurately;
4. `review route` produces a non-recursive reviewer route for the active executor;
5. quality-gate discovery is either `REQUIRED`, `NOT_APPLICABLE`, or explicitly `BLOCKED_CONFIGURATION`;
6. no authentication material is stored inside version-controlled PowerPack state.
