# Codex-first installation and migration

This guide is for an **existing Spec Kit project** that already has generated Claude/Codex skills and wants to install SpecKit PowerPack as the managed enhancement layer while using **Codex as the primary executor**.

The operation is intentionally non-destructive to application code and SpecKit feature artifacts. PowerPack installs its preset/extension and project-local runtime, then Spec Kit rematerializes the managed command/skill views for the selected integration.

## Target workflow

The PowerPack happy path is:

```text
speckit-specify
  -> speckit-clarify
  -> speckit-plan
  -> speckit-checklist
  -> speckit-checklist-converge
  -> speckit-tasks
  -> speckit-analyze
  -> speckit-implement
  -> speckit-implement-review
       -> speckit-converge
            -> tasks appended? speckit-implement -> speckit-converge ...
       -> independent review
            -> findings? implement fixes -> speckit-converge -> review ...
            -> approved? COMPLETE
            -> budget exhausted? BLOCKED_BUDGET -> explicit extend
```

The first `speckit-implement` is mandatory and explicit. `speckit-implement-review` cannot manufacture or skip that predecessor.

## Codex model roles

When installed with `--integration codex`, `.specify/powerpack/model-routing.json` uses these defaults:

| Role | Model | Effort | Authority |
|---|---|---:|---|
| Parent/orchestrator/implementation | `gpt-5.6-terra` | high | writes, phase ownership, user interaction |
| Bounded mechanical worker | `gpt-5.6-luna` | medium | narrow scans, inventories and evidence collection |
| Semantic gate/advisor | `gpt-5.6-sol` | high | read-only semantic analysis/escalation |
| Independent deep reviewer | `gpt-5.6-sol` | xhigh | read-only review |

The Terra parent never starts a recursive `codex` CLI only to obtain an independent review. Review uses either:

1. the current context when it is already provably `gpt-5.6-sol/xhigh/read-only`; or
2. exactly one **in-session Sol reviewer/subagent** configured as `gpt-5.6-sol/xhigh/read-only`.

If neither route can be proven, implementation review returns `BLOCKED` instead of silently reviewing with Terra/Luna or a weaker effort.

## 1. Pre-install checkpoint

Run from the project root:

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
```

PowerPack does not require a clean tree merely to install, but an intentional checkpoint makes it easy to distinguish your current project customizations from generated skill changes.

If you want a Git checkpoint, commit the project state using your normal workflow before installation. Do not use destructive reset/rebase just for PowerPack installation.

## 2. Prerequisites in WSL/Linux

Verify:

```bash
python3 --version
git --version
uv --version
specify --version
codex --version
```

Requirements:

- Python 3.11+;
- Git;
- `uv` for Git-based CLI installation/update and Spec Kit bootstrap;
- official `specify` CLI, unless `--bootstrap-speckit` is used;
- Codex CLI authenticated in the environment where the project will be executed.

Claude Code is **not required** for a Codex-first PowerPack run.

## 3. Install/update the PowerPack CLI

Install current `main`:

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@main
```

Confirm:

```bash
speckit-powerpack --version
```

## 4. Install into an existing Spec Kit project

From the existing project root:

```bash
speckit-powerpack install . --integration codex
```

If `specify` is not installed yet:

```bash
speckit-powerpack install . \
  --integration codex \
  --bootstrap-speckit
```

The installer:

1. preserves the existing `.specify` project;
2. installs/refreshes the `powerpack-tools` Spec Kit extension;
3. removes and rematerializes the `powerpack-core` preset;
4. wraps official `speckit-implement` and `speckit-converge` rather than freezing old upstream command bodies;
5. replaces the PowerPack-owned commands such as `speckit-checklist-converge`, `speckit-implement-review`, `speckit-full-cycle` and debt lifecycle skills;
6. materializes the project-local PowerPack runtime under `.specify/powerpack/`;
7. selects Codex in a newly created `.specify/powerpack/model-routing.json`.

PowerPack does **not** intentionally delete unrelated project-owned custom skills.

## 5. Existing PowerPack installation: verify active integration

If the project already had PowerPack installed previously with Claude as the active integration, inspect:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('.specify/powerpack/model-routing.json')
print(json.dumps(json.loads(p.read_text()), indent=2))
PY
```

The expected value for a Codex-first project is:

```json
"active_integration": "codex"
```

A first installation with `--integration codex` creates it correctly. When migrating an older customized PowerPack config, preserve project overrides and explicitly set only `active_integration` to `codex` if necessary rather than deleting the entire file.

Safe edit:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('.specify/powerpack/model-routing.json')
data = json.loads(p.read_text())
data['active_integration'] = 'codex'
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
PY
```

Do not use `--reset-config` merely to switch executors; that option intentionally restores all mutable PowerPack project config to packaged defaults.

## 6. Verify the Codex reviewer route

A Codex-first project needs an in-session Sol reviewer configuration unless the review is already executing in a proven Sol/xhigh/read-only context.

For projects that use Codex custom agents, the expected effective configuration is equivalent to:

```toml
name = "speckit_sol_reviewer"
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"
sandbox_mode = "read-only"
```

The reviewer must be independent/read-only and must not own implementation writes.

If your project already contains `.codex/agents/speckit-sol-reviewer.toml`, keep the project-specific reviewer instructions as long as the effective model/effort/sandbox contract above remains intact.

## 7. Diagnose the installation

Run:

```bash
speckit-powerpack doctor
```

Then inspect the installed configuration:

```bash
cat .specify/powerpack/model-routing.json
cat .specify/powerpack/full-cycle.json
cat .specify/powerpack/prerequisites.json
```

Important expected values:

```text
active_integration = codex
implement            -> gpt-5.6-terra/high
full-cycle           -> gpt-5.6-terra/high
implement-review     -> gpt-5.6-terra/high parent
converge gate        -> gpt-5.6-sol/high
independent reviewer -> gpt-5.6-sol/xhigh/read-only
```

The full-cycle config must keep:

```json
{
  "explicit_initial_implement_required": true,
  "implement_review_owns_convergence": true
}
```

## 8. Open a new Codex session

After installing/rematerializing skills, close/reopen the Codex project session from the repository root so the agent sees the new generated skill catalog and project routing.

Do not start the parent session with a CLI model override that contradicts the project routing when you want Terra to remain the parent.

Recommended environment hint when executor auto-detection is ambiguous:

```bash
export SPECKIT_POWERPACK_EXECUTOR=codex
```

## 9. Smoke test before real implementation

Start with read-only/low-risk checks:

```text
$speckit-debt-list ALL
```

or inspect routing through the runtime:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage implement
python .specify/powerpack/bin/powerpack.py model route --stage converge
python .specify/powerpack/bin/powerpack.py model route --stage implement-review
```

Then verify the full-cycle state machine on the intended SPEC without skipping phases:

```bash
python .specify/powerpack/bin/full_cycle.py status --feature-dir <SPEC_DIR>
```

If no run exists yet, that status is expected to say the cycle has not started.

## 10. Normal Codex-first operation

Manual happy path:

```text
$speckit-specify ...
$speckit-clarify
$speckit-plan
$speckit-checklist
$speckit-checklist-converge
$speckit-tasks
$speckit-analyze
$speckit-implement
$speckit-implement-review <spec-id>
```

For an existing already-specified SPEC, `speckit-full-cycle` starts from the configured post-specification phases and enforces their order.

If `implement-review` reaches its review limit without approval, it must not silently buy more rounds. Use the suggested explicit extension, normally:

```text
$speckit-implement-review extend 2
```

## 11. When Claude Code becomes available again

PowerPack is executor-aware; you do not need a different SDD design. Claude can later become the primary executor again by switching the active integration and rematerializing as needed.

The semantic workflow remains identical. Only model routing changes:

- Claude: Sonnet parent, Haiku bounded worker, Opus conditional advisor, external Codex Sol/xhigh reviewer;
- Codex: Terra parent, Luna bounded worker, Sol advisor/gate/reviewer.

Never keep two contradictory “authoritative” model-routing configurations active for the same execution. Choose one primary integration per project/runtime session.

## Optional ChatGPT Project Web gate

The Web second gate remains optional. A Codex-only review can converge without it when `chatgpt_web.enabled=false`.

If enabled later, configure the platform-scoped browser profile/project binding separately. WSL uses the Linux profile namespace; do not reuse a Windows browser profile directory directly from WSL.
