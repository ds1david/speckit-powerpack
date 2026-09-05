# PowerPack Update and Recovery

PowerPack has two separately controlled update surfaces:

1. **installed CLI/package** — the `speckit-powerpack` executable managed by `uv`;
2. **project materialization** — PowerPack runtime, preset, extension, policies and default configs under an initialized Spec Kit repository.

The updater never authorizes destructive Git operations.

## Source identity

When installed from Git through `uv`/pip-compatible tooling, PowerPack reads PEP 610 `direct_url.json` metadata and compares the installed `commit_id` with the selected remote Git ref using `git ls-remote`.

A development install that records `requested_revision=feat/example` follows `feat/example` by default. This prevents a feature-branch installation from accidentally treating an older `main` as an update.

If the installed commit cannot be proven, normal automatic update stops with `UNKNOWN_INSTALLED_SOURCE`. A blind reinstall then requires explicit `--force`.

## Installer-triggered update

`init` and `install` consult `.specify/powerpack/update.json` when available, otherwise packaged defaults:

```json
{
  "enabled": true,
  "auto_check_on_install": true,
  "confirmation_required": true
}
```

When a newer commit is detected the installer displays installed/remote identity and asks before updating. In non-interactive automation, confirmation must be explicit with `--yes-update`.

Disable one check with:

```bash
speckit-powerpack install . --no-update-check
```

The internal restart after a successful self-update sets a one-shot skip marker so the new CLI does not recursively check/update again.

## Manual check

```bash
speckit-powerpack update . --check
```

Possible statuses include:

- `CURRENT`
- `UPDATE_AVAILABLE`
- `UNKNOWN_INSTALLED_SOURCE`
- `CHECK_FAILED`

A check never modifies the CLI or repository.

## Normal confirmed update

```bash
speckit-powerpack update .
```

or non-interactively after the operator has already approved:

```bash
speckit-powerpack update . --yes
```

Normal update:

- updates the CLI from the resolved repository/ref through `uv`;
- rematerializes PowerPack-managed assets in the current Spec Kit project;
- preserves project-customized PowerPack JSON configuration;
- preserves technical-debt backlog/history;
- preserves source/application files;
- preserves platform-scoped browser authentication and ChatGPT Project bindings.

## Forced recovery

When source comparison is unavailable or managed files are corrupted, explicit force bypasses the `CURRENT/UNKNOWN` decision:

```bash
speckit-powerpack update . --force --yes
```

This is intentionally "brute" only inside the PowerPack ownership boundary: it reinstalls the CLI and overwrites packaged/runtime/preset/extension/policy assets that PowerPack owns. It does **not** run `git reset`, rebase, force-push, delete project code, delete debt history or delete browser profiles.

If the installed CLI is healthy and only the repository materialization is broken, prefer:

```bash
speckit-powerpack update . --project-only --force --yes
```

## Resetting PowerPack configuration

Restoring mutable PowerPack project config to package defaults is stronger and separate:

```bash
speckit-powerpack update . --project-only --force --reset-config --yes
```

This may reset custom values in:

- `model-routing.json`
- `review.json`
- `technical-debt.json`
- `full-cycle.json`
- `update.json`
- `prerequisites.json`
- `quality-gates.json`

It still does not delete the configured debt backlog or global Web authentication data. Agents MUST never add `--reset-config` without an explicit user request.

## Agent command

The `powerpack-tools` extension exposes an update skill. The agent must execute the check first, explain the selected source/ref and update scope, and obtain explicit confirmation before applying a normal update. `--force` and especially `--reset-config` require an explicit user request; they are never inferred.

## Customization

Project update policy lives in:

```text
.specify/powerpack/update.json
```

Packaged default:

```text
src/speckit_powerpack/assets/config/default-update.json
```

Update source resolution/self-install logic:

```text
src/speckit_powerpack/update_manager.py
```

Installer/project materialization orchestration:

```text
src/speckit_powerpack/cli.py
```
