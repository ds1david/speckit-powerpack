# Codex-first installation and migration

This guide is for an **existing Spec Kit project** that already has generated Claude/Codex skills and wants to install SpecKit PowerPack as the managed enhancement layer while using **Codex as the primary executor**.

The operation is intentionally non-destructive to application code and SpecKit feature artifacts. PowerPack installs its preset/extension and project-local runtime, then Spec Kit rematerializes the managed command/skill views for the selected integration.

## Target workflow

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
       -> Sol/xhigh independent review
            -> findings? implement fixes -> speckit-converge -> Sol review ...
       -> mandatory ChatGPT Project Web review
            -> findings? implement fixes -> speckit-converge -> Sol review -> Web review ...
            -> both gates approve same final snapshot? COMPLETE
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

The Terra parent never starts a recursive `codex` CLI only to obtain an independent review. Review uses either a context already proven as `gpt-5.6-sol/xhigh/read-only` or exactly one in-session Sol reviewer/subagent with that contract.

## 1. Pre-install checkpoint

Run from the project root:

```bash
git status --short
git branch --show-current
git rev-parse --short HEAD
```

PowerPack does not require a clean tree merely to install, but a checkpoint makes it easy to distinguish current project customizations from generated skill changes.

## 2. Prerequisites in WSL/Linux

Verify:

```bash
python3 --version
git --version
uv --version
specify version
codex --version
```

Requirements:

- Python 3.11+;
- Git;
- `uv` for Git-based CLI installation/update and Spec Kit bootstrap;
- official Spec Kit `>=1.0.0`;
- Codex CLI authenticated in the environment where the project will be executed;
- a graphical environment capable of opening Playwright Chromium for the mandatory ChatGPT Web authorization/review gate.

Claude Code is **not required** for a Codex-first PowerPack run.

## 3. Install/update the PowerPack CLI

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@main
```

Confirm:

```bash
speckit-powerpack --version
```

## 4. Install into an existing Spec Kit project

Recommended command:

```bash
speckit-powerpack install . \
  --integration codex \
  --bootstrap-speckit
```

`--bootstrap-speckit` handles both missing and incompatible Spec Kit installations. For example, an installed `0.14.x` CLI is upgraded to the PowerPack-tested release before preset/extension installation.

The installer:

1. preserves the existing `.specify` project;
2. installs/refreshes the `powerpack-tools` Spec Kit extension;
3. removes and rematerializes the `powerpack-core` preset;
4. wraps official `speckit-implement` and `speckit-converge` rather than freezing old upstream command bodies;
5. replaces PowerPack-owned commands such as `speckit-checklist-converge`, `speckit-implement-review`, `speckit-full-cycle` and debt lifecycle skills;
6. materializes the project-local PowerPack runtime under `.specify/powerpack/`;
7. selects Codex in `.specify/powerpack/model-routing.json` when creating that config;
8. prepares Playwright Chromium for the Web review gate;
9. leaves Web authorization intentionally ungranted until the user explicitly consents.

PowerPack does **not** intentionally delete unrelated project-owned custom skills.

## 5. Authorize ChatGPT Web in an isolated PowerPack browser profile

PowerPack does **not** attach to the normal Edge/Chrome profile. The browser session is stored under a PowerPack-owned platform namespace outside the repository, for example:

```text
~/.config/speckit-powerpack/browser-profiles/linux/atsel/
```

Run one authorization command:

```bash
speckit-powerpack review authorize \
  --profile atsel \
  --project atsel \
  --url 'https://chatgpt.com/g/g-p-.../project' \
  --path .
```

The Playwright flow is deliberately explicit:

1. PowerPack opens an isolated Chromium profile;
2. the first tab explains the requested scope, profile storage path and exact ChatGPT Project URL;
3. choose **Autorizar e abrir ChatGPT**;
4. a second tab opens the selected Project;
5. sign in on `chatgpt.com` if necessary; credentials/MFA never pass through the PowerPack CLI;
6. confirm the intended Project is visible;
7. return to the consent tab and choose **Conceder acesso ao projeto**;
8. only then does PowerPack persist the platform/profile/Project grant.

Cancelling the consent screen records no authorization.

The persistent Playwright profile is separate from Windows Edge/Chrome history, cookies and localStorage. Do not point PowerPack at the Windows browser `User Data` directory.

## 6. Verify the Codex reviewer route

A Codex-first project needs an in-session Sol reviewer configuration unless the review is already executing in a proven Sol/xhigh/read-only context.

Expected effective configuration:

```toml
name = "speckit_sol_reviewer"
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"
sandbox_mode = "read-only"
```

The reviewer must be independent/read-only and must not own implementation writes.

## 7. Diagnose the installation and review readiness

Run:

```bash
speckit-powerpack doctor
```

Expected required checks include:

```text
OK   specify
OK   spec-kit-compatible
OK   spec-kit-project
OK   powerpack-runtime
OK   selected-executor
OK   web-review-required
OK   playwright-package
OK   playwright-browser
OK   chatgpt-authenticated
OK   chatgpt-project-bound
```

`chatgpt-authenticated` means the isolated profile has a user-confirmed `playwright-consent` grant. Live session validity is still re-established by the actual browser gate at review time; no password/cookie is copied into project configuration.

Inspect configuration:

```bash
cat .specify/powerpack/model-routing.json
cat .specify/powerpack/full-cycle.json
cat .specify/powerpack/prerequisites.json
cat .specify/powerpack/review.json
```

Important expected values:

```text
active_integration = codex
implement            -> gpt-5.6-terra/high
full-cycle           -> gpt-5.6-terra/high
implement-review     -> gpt-5.6-terra/high parent
converge gate        -> gpt-5.6-sol/high
independent reviewer -> gpt-5.6-sol/xhigh/read-only
chatgpt_web.required = true
chatgpt_web.enabled = true
chatgpt_web.authorization = playwright-consent
```

The full-cycle config must keep:

```json
{
  "explicit_initial_implement_required": true,
  "implement_review_owns_convergence": true
}
```

## 8. Existing PowerPack installation: switch active integration safely

If an older installation was Claude-first, inspect `.specify/powerpack/model-routing.json`. For a Codex-first project, set only:

```json
"active_integration": "codex"
```

Do not use `--reset-config` merely to switch executors; that option restores all mutable PowerPack project config to packaged defaults.

## 9. Open a new Codex session

After installing/rematerializing skills, close/reopen the Codex project session from the repository root so the agent sees the new generated skill catalog and project routing.

Recommended environment hint when executor auto-detection is ambiguous:

```bash
export SPECKIT_POWERPACK_EXECUTOR=codex
```

## 10. Smoke test before real implementation

Start with read-only/low-risk checks:

```text
$speckit-debt-list ALL
```

Inspect routing:

```bash
python .specify/powerpack/bin/powerpack.py model route --stage implement
python .specify/powerpack/bin/powerpack.py model route --stage converge
python .specify/powerpack/bin/powerpack.py model route --stage implement-review
```

Then inspect full-cycle state if relevant:

```bash
python .specify/powerpack/bin/full_cycle.py status --feature-dir <SPEC_DIR>
```

## 11. Normal Codex-first operation

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

Before `implement-review` accepts review work, PowerPack readiness must prove the mandatory Web authorization and exact Project binding. A Sol approval alone is not enough for `COMPLETE`.

If the review limit is exhausted without both gates approving the current snapshot:

```text
$speckit-implement-review extend 2
```

No silent extension is allowed.

## 12. Revoking Web access

The browser profile is PowerPack-owned and platform-scoped. To remove the stored profile:

```bash
speckit-powerpack review auth forget atsel
```

After profile removal, `doctor` must fail Web readiness until a new explicit `review authorize` grant is completed. Project source and SpecKit artifacts are unaffected.

## 13. When Claude Code becomes available again

PowerPack is executor-aware; you do not need a different SDD design. Claude can later become the primary executor again by switching the active integration and rematerializing as needed.

The semantic workflow remains identical. Only model routing changes:

- Claude: Sonnet parent, Haiku bounded worker, Opus conditional advisor, external Codex Sol/xhigh reviewer;
- Codex: Terra parent, Luna bounded worker, Sol advisor/gate/reviewer.

The mandatory isolated ChatGPT Project Web gate remains the same across executors.
