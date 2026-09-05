# PowerPack Process Architecture

This is the canonical map from PowerPack process nodes to their implementation, installed project artifact, durable/ephemeral state and supported customization surface.

The reusable design rule is:

```text
project intent / stricter policy
        ↓
PowerPack workflow contract
        ↓
capability / state / evidence runtime
        ↓
Spec Kit primitive / Sol reviewer / mandatory Web gate
        ↓
auditable result
```

OS, language, framework, IDE and build-tool differences are resolved behind capabilities/configuration rather than embedded as workflow branches.

# 1. Package → project → machine layers

```mermaid
flowchart LR
    subgraph PKG[Installable speckit-powerpack package]
        PRESET[powerpack-core preset]
        EXT[powerpack-tools extension]
        CFG[default config assets]
        RT[Python runtime assets]
        POL[policies / review protocols]
        CLI[CLI + update_manager.py]
        ONB[review_onboarding.py]
    end

    subgraph PROJECT[Initialized Spec Kit project]
        CMD[materialized commands/skills]
        PCFG[.specify/powerpack/*.json]
        BIN[.specify/powerpack/bin/*.py]
        SPEC[specs/... + tasks.md]
        PSTATE[durable same-SPEC receipts]
        RSTATE[gitignored resumable state]
    end

    subgraph MACHINE[Machine/platform-local state]
        GCFG[PowerPack config.json]
        BREC[browser-install/platform.json]
        AUTH[browser-profiles/platform/profile]
        TOOL[uv-managed CLI]
    end

    PRESET --> CMD
    EXT --> CMD
    CFG --> PCFG
    RT --> BIN
    POL --> PCFG
    CLI --> TOOL
    ONB --> BREC
    ONB --> AUTH
    CMD --> SPEC
    BIN --> PSTATE
    BIN --> RSTATE
    GCFG --> AUTH
```

Generated `.claude/skills/*` and `.agents/skills/*` files are materialized views, not the durable customization source.

# 2. End-to-end feature process

```mermaid
flowchart TD
    U[User / agent request] --> ONE[Resolve/create exactly one SPEC]
    ONE --> C[clarify]
    C --> P[plan]
    P --> CK{Checklist applicable?}
    CK -->|yes| K[checklist]
    K --> KC[checklist-converge]
    CK -->|no| SKIP[skip checklist + checklist-converge]
    KC --> T[tasks]
    SKIP --> T
    T --> A[analyze]
    A -->|owner problem| RET[RETURN to owner stage]
    RET --> A
    A -->|clean| I[explicit implement]

    I --> IB[powerpack implement begin]
    IB --> CORE[official Spec Kit implement]
    CORE --> IE[powerpack implement end]
    IE --> RECEIPT[same-SPEC implement receipt]
    RECEIPT --> IR[implement-review]

    IR --> READY{doctor / Web consent ready?}
    READY -->|no| BC[BLOCKED_CONFIGURATION]
    READY -->|yes| V[converge]
    V -->|tasks appended| IC[corrective implement]
    IC --> V
    V -->|clean| SOL[Sol/xhigh full-snapshot review]
    SOL -->|findings| L[Persist every finding in tasks.md]
    L --> IF[Terra/implementer fixes]
    IF --> V
    SOL -->|approved| WEB[mandatory ChatGPT Project Web review]
    WEB -->|findings| L
    WEB -->|approved same snapshot| DONE[COMPLETE]
```

There is no top-level `converge` between the initial `implement` and `implement-review`. Convergence is owned by the integrated review stage.

# 3. Top-level full-cycle state machine

```mermaid
stateDiagram-v2
    [*] --> Clarify
    Clarify --> Plan
    Plan --> Checklist
    Checklist --> ChecklistConverge: applicable
    Checklist --> Tasks: not applicable
    ChecklistConverge --> Tasks
    Tasks --> Analyze
    Analyze --> Implement
    Implement --> ImplementReview
    ImplementReview --> Done: convergence + quality + Sol + Web approved
    Clarify --> Blocked: blocker
    Plan --> Blocked: blocker
    Analyze --> Blocked: blocker
    ImplementReview --> Blocked: configuration / decision / budget
```

The full-cycle runtime controls only top-level phase order. Corrective implementation/convergence and both review gates remain inside `implement_review`.

Non-weakenable configuration:

```json
{
  "same_spec_only": true,
  "stop_on_blocked": true,
  "allow_debt_escape_hatch": false,
  "explicit_initial_implement_required": true,
  "implement_review_owns_convergence": true
}
```

# 4. Implementation and quality gate

```mermaid
flowchart TD
    B[Implement begin] --> S1[Snapshot tracked + untracked content hashes]
    S1 --> SI[Official implementation]
    SI --> S2[Snapshot after]
    S2 --> D[Files attributable to this run]
    D --> DOC{Documentation-only?}
    DOC -->|yes| NA[NOT_APPLICABLE build gate]
    DOC -->|no| CAP[capabilities.py discovery]
    CAP -->|one reproducible strategy| RUN[Execute strategy]
    CAP -->|unknown / ambiguous / missing executable| BLOCK[BLOCKED_CONFIGURATION]
```

Project-specific closure checks belong in project policy/gates. PowerPack supplies the generic capability contract, not framework-specific assumptions.

# 5. Deep implementation review

```mermaid
sequenceDiagram
    participant I as Terra/implementer
    participant P as PowerPack state runtime
    participant S as Sol/xhigh reviewer
    participant V as review_protocol.py
    participant T as same-SPEC tasks.md
    participant W as ChatGPT Project Web

    I->>P: verify explicit implement predecessor + readiness
    P-->>I: same-SPEC receipt + authorized Project/profile
    I->>I: converge until clean
    I->>S: immutable current snapshot
    S-->>I: schema 2.0 evidence JSON
    I->>V: validate
    alt Sol findings
        I->>T: persist REV-* findings
        I->>I: implement + re-converge + quality gate
        I->>S: fresh full-snapshot review
    else Sol approved
        I->>W: exact same snapshot + same evidence protocol
        W-->>I: schema 2.0 evidence JSON
        I->>V: validate
        alt Web findings
            I->>T: persist findings
            I->>I: implement + re-converge + quality gate
            I->>S: fresh Sol review before Web repeats
        else Web approved
            I-->>I: COMPLETE only when both approvals match final snapshot
        end
    end
```

A previous approval becomes stale after any implementation change. No review finding may be converted to technical debt merely to force completion.

# 6. Isolated Playwright Web identity and consent

```mermaid
flowchart TD
    INSTALL[PowerPack install] --> PWP[Playwright package]
    PWP --> CH[playwright install chromium]
    CH --> REC[browser-install/platform receipt]
    AUTHZ[review authorize] --> CONSENT[PowerPack consent tab]
    CONSENT -->|cancel| NONE[No grant recorded]
    CONSENT -->|authorize| PROJ[Open exact ChatGPT Project]
    PROJ --> LOGIN[User authenticates on chatgpt.com]
    LOGIN --> GRANT[User returns and grants Project access]
    GRANT --> PROFILE[Persistent isolated PowerPack profile]
    GRANT --> BIND[platform/profile/Project playwright-consent binding]
    BIND --> DOC[doctor READY]
```

Machine-local layout:

```text
<global PowerPack config>/
├── config.json
├── browser-install/<platform>.json
└── browser-profiles/
    ├── windows/<profile>/
    ├── linux/<profile>/
    └── macos/<profile>/
```

The persistent Playwright context deliberately does **not** reuse the default Edge/Chrome profile. WSL uses the Linux namespace even when Windows browsers are already authenticated.

Canonical authorization command:

```bash
speckit-powerpack review authorize \
  --profile <profile> \
  --project <alias> \
  --url 'https://chatgpt.com/g/g-p-.../project' \
  --path .
```

`doctor` requires a matching `playwright-consent` grant. Legacy login/bind state without that grant does not satisfy readiness.

# 7. Technical-debt governance

```mermaid
flowchart TD
    C[Potential deferred work] --> FLOOR[PowerPack debt safety floor + project policy]
    FLOOR --> SEM{Current obligation/review/convergence/blocker?}
    SEM -->|yes| ND[NOT_DEBT]
    SEM -->|legitimately deferrable| OPEN[OPEN + stable ID]
    OPEN --> READY{Readiness READY?}
    READY -->|yes| PROG[IN_PROGRESS]
    READY -->|no| HOLD[OPEN / blocked refinement]
    PROG --> PROOF{Original resolution criteria proven?}
    PROOF -->|no| PROG
    PROOF -->|yes| RES[RESOLVED + evidence/history]
```

# 8. Install, update and forced recovery

Installation and update are scoped to PowerPack-managed assets. `--bootstrap-speckit` installs or upgrades an incompatible Spec Kit to the tested version before preset/extension materialization. Project configuration is preserved unless an explicitly confirmed reset is requested.

```mermaid
flowchart TD
    START[init/install/update] --> VER{Spec Kit compatible?}
    VER -->|no + bootstrap| SK[install tested Spec Kit]
    VER -->|no without bootstrap| STOP[BLOCKED]
    VER -->|yes| MAT[materialize PowerPack]
    SK --> MAT
    MAT --> BROWSER[prepare isolated Chromium]
    BROWSER --> CONSENT[explicit review authorize still required]
```

Forced updater recovery never authorizes Git reset/rebase/force-push, deletion of project source/debt history, or deletion of PowerPack browser profiles.

# 9. Session-limit resume

Usage/session/rate limits are checkpointed separately from code/test failures. Checkpoints contain safe resumable execution context, never passwords, cookies, MFA codes or raw browser authentication material.

# 10. Change decision guide

```mermaid
flowchart TD
    N[Need new behavior] --> U{Reusable across unrelated projects?}
    U -->|no| LOCAL[Project-local skill / policy / closure gate]
    U -->|yes| K{Behavior type}
    K -->|workflow ordering/state| WF[PowerPack command + state runtime]
    K -->|config/default| CFG[PowerPack config asset]
    K -->|OS/language/framework/build support| CAP[Capability strategy]
    K -->|review methodology/evidence| REV[Review protocol/validator]
    K -->|browser consent/session isolation| WEB[CLI + review_onboarding.py]
    K -->|debt lifecycle/storage| DEBT[Debt policy/runtime]
    K -->|installation/update/recovery| UPDATE[CLI/update_manager]
```

Examples that stay project-local: trading-specific invariants, Oracle APEX metadata rules, a specific backend-to-frontend traceability implementation.

Examples that belong in PowerPack: same-SPEC receipts, generic convergence/review lifecycle, evidence contracts, capability resolution, technical-debt governance mechanics, top-level orchestration, isolated Playwright consent/profile handling and safe updater/recovery behavior.

See also [`CUSTOMIZATION.md`](CUSTOMIZATION.md), [`IMPLEMENT_REVIEW.md`](IMPLEMENT_REVIEW.md), [`FULL_CYCLE.md`](FULL_CYCLE.md), [`TECHNICAL_DEBT.md`](TECHNICAL_DEBT.md), [`UPDATES.md`](UPDATES.md) and [`PORTABILITY.md`](PORTABILITY.md).
