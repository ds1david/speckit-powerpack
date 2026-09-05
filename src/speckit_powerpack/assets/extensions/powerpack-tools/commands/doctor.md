---
description: "Diagnose the project-local SpecKit PowerPack installation."
---

# PowerPack Doctor

Verify, without modifying application code:

1. `.specify/powerpack/bin/powerpack.py` exists.
2. `.specify/powerpack/model-routing.json` is valid JSON.
3. `.specify/powerpack/prerequisites.json` is valid JSON.
4. `.specify/powerpack/quality-gates.json` is valid JSON.
5. The current feature can be resolved by the official Spec Kit prerequisite script or by `--feature-dir`.
6. Report the active Spec Kit integration when discoverable.
7. Do not expose browser cookies, tokens, passwords, or profile contents.

Return a compact PASS/FAIL table and remediation for every failed check.
