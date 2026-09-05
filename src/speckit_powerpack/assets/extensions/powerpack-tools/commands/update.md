---
description: "Check and update the installed SpecKit PowerPack and rematerialize its project-managed assets with explicit confirmation."
---

# SpecKit PowerPack Update

This command manages PowerPack updates; it must never silently self-modify the developer environment.

## Check first

Run:

```bash
speckit-powerpack update . --check
```

Show installed source/commit, configured ref and remote commit/status. If the check cannot prove the installed VCS commit, report that explicitly; do not pretend an update is available.

## Normal update

If `UPDATE_AVAILABLE`, explain that a normal update:

1. updates the `speckit-powerpack` CLI through `uv` from the resolved Git source/ref;
2. rematerializes PowerPack-managed runtime/preset/extension assets in the current repository;
3. preserves project-owned PowerPack configuration, technical-debt backlog, source code, Web authentication profiles and project bindings;
4. performs no destructive Git operation.

Ask the user for explicit confirmation. Only after confirmation run:

```bash
speckit-powerpack update . --yes
```

Never infer consent from a previous unrelated install/update operation.

## Forced recovery update

Use force only when the user explicitly requests a forced/recovery reinstall or the normal version/source comparison cannot operate and the user accepts that risk:

```bash
speckit-powerpack update . --force --yes
```

`--force` blindly reinstalls the CLI from the selected source/ref and overwrites PowerPack-managed package/runtime/preset/extension assets in the repository. It still MUST NOT reset application code, delete the debt backlog, delete Web profiles, force-push, reset/rebase Git or overwrite project configuration.

Resetting PowerPack project configuration to packaged defaults is a separate stronger recovery action and requires the user to explicitly request it:

```bash
speckit-powerpack update . --force --reset-config --yes
```

Before this command, warn that `review.json`, `model-routing.json`, `technical-debt.json`, `full-cycle.json`, `update.json`, prerequisites and quality-gate customization may be restored to defaults. Never select `--reset-config` autonomously.

## Project-only refresh

When the installed CLI is known-good but project materialization is damaged:

```bash
speckit-powerpack update . --project-only --force --yes
```

This is the preferred recovery path for corrupted/missing `.specify/powerpack/bin/*` or generated PowerPack components.

## Source/ref override

A user may explicitly choose another source/ref:

```bash
speckit-powerpack update . --check --ref <branch-or-tag>
speckit-powerpack update . --force --yes --ref <branch-or-tag>
```

Development installations made from a Git branch follow their installed `requested_revision` by default, so a feature-branch install does not accidentally downgrade to an older `main`.
