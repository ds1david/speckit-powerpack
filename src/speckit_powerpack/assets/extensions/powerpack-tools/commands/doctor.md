---
description: "Diagnose a SpecKit PowerPack installation and mandatory review readiness."
---

Run:

```bash
speckit-powerpack doctor
```

Treat the CLI result as authoritative. Validate at least:

1. official Spec Kit exists and satisfies the PowerPack minimum version;
2. `.specify/powerpack/bin/*` managed runtimes exist;
3. the configured primary executor exists;
4. Playwright is installed and the current platform has a completed Chromium install receipt;
5. `.specify/powerpack/review.json` requires the Web gate;
6. the current platform/profile has an explicit `playwright-consent` grant;
7. the exact ChatGPT Project alias/URL/profile binding matches that grant;
8. legacy login/project bindings without `playwright-consent` do not count as ready;
9. no password, MFA code, raw cookie or browser authentication material is stored in version-controlled project state.

If Web authorization is missing, direct the user to the single explicit setup flow:

```bash
speckit-powerpack review authorize \
  --profile <profile> \
  --project <alias> \
  --url 'https://chatgpt.com/g/g-p-.../project' \
  --path .
```

The PowerPack Playwright profile must remain separate from the user's default Windows Edge/Chrome profile.
