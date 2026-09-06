# ChatGPT Web Review — functional smoke test

This procedure validates the smallest complete PowerPack Web-review path:

```text
reviewer account
  -> selected desktop browser
  -> explicit Playwright/CDP attach
  -> repository-bound ChatGPT Project
  -> real prompt
  -> assistant response captured back in the CLI
```

The smoke command never accepts a reviewer profile or Project override. It must use the binding already persisted for the repository in `.specify/powerpack/review.json`.

## 1. Install this development branch

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@feat/interactive-windows-browser-auth

speckit-powerpack install . --integration codex --bootstrap-speckit
```

## 2. Configure one reviewer account interactively

```bash
speckit-powerpack review auth configure
```

The PowerPack detects the runtime/browser host (for example WSL -> Windows or native Linux desktop), lists compatible browsers, and asks which browser/account identity will perform Web review.

There is no silent fallback. Choosing another browser is an explicit reviewer-identity change.

For Chrome/Edge existing-context automation, enable remote debugging when instructed and keep that exact browser/profile open.

Validate the account:

```bash
speckit-powerpack review auth list
speckit-powerpack review auth validate
```

## 3. Bind this repository to a Project

Discover Projects visible to the selected account:

```bash
speckit-powerpack review project discover
```

Then select and persist one:

```bash
speckit-powerpack review project select --alias atsel --path .
```

Alternatively, bind a known Project URL or accept a shared/invite link with the existing project commands.

Inspect the persisted repository binding:

```bash
jq '.chatgpt_web' .specify/powerpack/review.json
```

The important fields are the reviewer `profile`, `account_label`, `automation_browser_id`, `project_alias`, `project_url`, and `authorization`.

## 4. Strict readiness gate

```bash
speckit-powerpack doctor --strict-review
```

This must pass before the smoke execution.

## 5. Execute the real bound-Project smoke test

```bash
speckit-powerpack review smoke-test --path .
```

The built-in prompt is exactly:

```text
me diga qual é o nome do projeto e sua principal missão, produza uma resposta simplificada de no máximo 100 palavras. e me responda quanto é 1 +1
```

The command:

1. reads the repository binding;
2. resolves the authorized reviewer account and browser;
3. attaches Playwright to that same existing browser context;
4. opens the exact persisted Project URL and rejects a navigation mismatch;
5. verifies that the ChatGPT composer is available;
6. submits the prompt;
7. waits for a new assistant message to stabilize;
8. captures the response back into the terminal;
9. verifies the answer contains the arithmetic result `2` and stays within 100 words.

Expected terminal shape:

```text
CHATGPT WEB REVIEW — FUNCTIONAL SMOKE TEST
  reviewer profile: ds1david-edge
  reviewer account: ds1david-plus
  browser: Microsoft Edge
  project alias: atsel
  project URL: https://chatgpt.com/.../project

=== RESPOSTA RECEBIDA ===
<real ChatGPT Project response>

=== VALIDAÇÃO ===
PASS Project URL vinculada foi aberta: ...
PASS resposta <= 100 palavras (...)
PASS resposta contém resultado 1 + 1 = 2

SMOKE TEST PASSED: reviewer account -> browser -> bound Project -> prompt -> response.
```

For machine-readable evidence:

```bash
speckit-powerpack review smoke-test --path . --json
```

## Failure policy

The functional test is fail-closed. It does not automatically change reviewer, browser, backend, account, or Project. If the configured browser cannot be attached, the ChatGPT session is no longer authenticated, the Project URL does not open exactly, the composer cannot be found, or the response cannot be captured, the command exits with an error and the persisted binding remains unchanged.
