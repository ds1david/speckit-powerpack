# ChatGPT Web Review — functional smoke test

This procedure validates the smallest complete PowerPack Web-review path:

```text
reviewer account
  -> dedicated ChatGPT-Web2API service
  -> dedicated persistent Chrome profile
  -> user-scoped repository binding
  -> ChatGPT Project id
  -> real prompt
  -> assistant response captured back in the CLI
```

The smoke command never accepts a reviewer profile or Project override. It must use the binding already selected for the current Git repository.

Repository/account/Project bindings are **not stored in the worktree**. They live under the PowerPack user configuration root. Repository identity is derived from the normalized Git remote (`origin` first), so GitHub, GitLab, Bitbucket, Azure DevOps and self-hosted Git are supported without provider-specific state.

## 1. Install/refresh PowerPack

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@feat/interactive-windows-browser-auth

speckit-powerpack install . --integration codex --bootstrap-speckit
```

## 2. Start one dedicated reviewer service

For the first account:

```bash
speckit-powerpack review service start \
  --profile ds1david \
  --port 8080 \
  --cdp-port 9222
```

Under WSL the PowerPack starts ChatGPT-Web2API on Windows, because the reviewer Chrome and its loopback CDP/API should live on the same host. The command installs `chatgpt-web2api` for the selected Windows Python when needed and creates a dedicated persistent Chrome profile under the Windows user profile.

Complete ChatGPT/Google/SSO/MFA login in the Chrome window opened by the service. The browser is headed by default and may remain minimized during reviews.

For another Plus account, use another logical profile and different ports, for example:

```bash
speckit-powerpack review service start \
  --profile webflow \
  --port 8081 \
  --cdp-port 9223
```

No service/account switch happens automatically.

## 3. Authorize the reviewer identity

```bash
speckit-powerpack review auth configure
```

Enter the logical profile/account label and its endpoint, for example `http://127.0.0.1:8080`. PowerPack verifies the live service and requires the authenticated account to expose ChatGPT Projects before persisting authorization.

Validate:

```bash
speckit-powerpack review auth list
speckit-powerpack review auth validate
```

## 4. Bind this repository to a Project

Discover Projects visible to the selected reviewer endpoint:

```bash
speckit-powerpack review project discover --profile ds1david
```

Select one:

```bash
speckit-powerpack review project select \
  --profile ds1david \
  --alias atsel \
  --path .
```

Or verify a known URL:

```bash
speckit-powerpack review project add \
  'https://chatgpt.com/g/g-p-...-project-name/project' \
  --profile ds1david \
  --alias atsel \
  --path .
```

`project add` extracts the `g-p-...` id and verifies it against `/v1/projects` from that exact reviewer endpoint before persisting the binding.

Inspect the effective user-scoped mapping:

```bash
speckit-powerpack review binding show --path .
speckit-powerpack review binding show --path . --json
```

The important values are repository identity, reviewer `profile`, `account_label`, `backend=chatgpt-web2api`, `endpoint`, `project_alias`, `project_id`, `project_url`, and `authorization`.

## 5. Strict readiness gate

```bash
speckit-powerpack doctor --strict-review
```

The strict gate performs a live service check and verifies that the bound Project id is still visible to that reviewer account.

## 6. Execute the real bound-Project smoke test

```bash
speckit-powerpack review smoke-test --path .
```

The built-in prompt is exactly:

```text
me diga qual é o nome do projeto e sua principal missão, produza uma resposta simplificada de no máximo 100 palavras. e me responda quanto é 1 +1
```

The command resolves the user-scoped reviewer endpoint and Project id, submits a non-streaming `/v1/chat/completions` request with `project_id`, captures the assistant response, verifies `1 + 1 = 2`, and enforces the 100-word limit.

Expected shape:

```text
CHATGPT WEB REVIEW — FUNCTIONAL SMOKE TEST
  reviewer: ds1david / ds1david-plus
  endpoint: http://127.0.0.1:8080
  Project: autonomous-trading-strategy-evolution-lab (g-p-...)

=== RESPOSTA RECEBIDA ===
<real ChatGPT Project response>

=== VALIDAÇÃO ===
PASS resposta <= 100 palavras (...)
PASS resposta contém resultado 1 + 1 = 2

SMOKE TEST PASSED: reviewer endpoint -> authenticated account -> bound Project -> prompt -> response.
```

For machine-readable evidence:

```bash
speckit-powerpack review smoke-test --path . --json
```

## 7. Generic Web-review call used by implement-review

The same backend can execute an arbitrary review prompt against the bound Project:

```bash
speckit-powerpack review run \
  --path . \
  --prompt-file /tmp/web-review-prompt.txt \
  --output /tmp/web-review.json
```

The `speckit-implement-review` skill uses this command after the independent Sol gate is clean, then validates the returned schema `2.0` review with the PowerPack review-protocol validator.

## Failure policy

The functional test is fail-closed. It does not automatically change reviewer, endpoint, account, Project or backend. If the dedicated service is unavailable, Chrome/CDP is broken, authentication is stale, the Project is no longer visible, or the completion request fails, the command exits with an error and the user-scoped binding remains unchanged.
