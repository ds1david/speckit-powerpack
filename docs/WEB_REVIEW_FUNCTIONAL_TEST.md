# ChatGPT Web Review — functional smoke test

This procedure validates the smallest complete PowerPack Web-review path:

```text
reviewer account
  -> selected desktop browser
  -> explicit Playwright/CDP attach
  -> user-scoped repository binding
  -> ChatGPT Project
  -> real prompt
  -> assistant response captured back in the CLI
```

The smoke command never accepts a reviewer profile or Project override. It must use the binding already selected for the current Git repository.

Repository/account/Project bindings are **not stored in the worktree**. They live under:

```text
~/.config/speckit-powerpack/repositories/<repo-id>/review.json
```

The repository id is derived from the normalized Git remote (`origin` first). This is provider-agnostic and supports GitHub, GitLab, Bitbucket, Azure DevOps and self-hosted Git. A repository without remotes receives a local path-scoped identity.

Transient browser files are excluded locally through `.git/info/exclude`; the PowerPack does not modify the root `.gitignore` for per-user state.

## 1. Install this development branch

```bash
uv tool install --force \
  git+https://github.com/ds1david/speckit-powerpack.git@feat/interactive-windows-browser-auth

speckit-powerpack install . --integration codex --bootstrap-speckit
```

If an earlier PowerPack build wrote reviewer/account/Project values into `.specify/powerpack/review.json`, the new CLI migrates those values to user scope and sanitizes the versionable file automatically.

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

Inspect the effective persisted binding without knowing the storage path:

```bash
speckit-powerpack review binding show --path .
```

For machine-readable output:

```bash
speckit-powerpack review binding show --path . --json
```

To print the actual user-scoped file path:

```bash
speckit-powerpack review binding path --path .
```

The important values are repository `provider/canonical`, reviewer `profile`, `account_label`, browser identity, `project_alias`, `project_url`, and `authorization`.

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

1. resolves the current repository from its normalized Git identity;
2. loads the user-scoped binding outside the worktree;
3. resolves the authorized reviewer account and browser;
4. attaches Playwright to that same existing browser context;
5. opens the exact persisted Project URL and rejects a navigation mismatch;
6. verifies that the ChatGPT composer is available;
7. submits the prompt;
8. waits for a new assistant message to stabilize;
9. captures the response back into the terminal;
10. verifies the answer contains the arithmetic result `2` and stays within 100 words.

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

The functional test is fail-closed. It does not automatically change reviewer, browser, backend, account, or Project. If the configured browser cannot be attached, the ChatGPT session is no longer authenticated, the Project URL does not open exactly, the composer cannot be found, or the response cannot be captured, the command exits with an error and the persisted user-scoped binding remains unchanged.
