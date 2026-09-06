from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from . import cli as core
from . import cli_account_binding as account_base
from . import repository_context as repoctx
from . import windows_browser_bridge as winbridge
from .chatgpt_web2api_backend import (
    BACKEND_ID,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    Web2APIError,
    chat,
    health,
    list_projects,
    normalize_endpoint,
    project_id_from_value,
    start_windows_service,
    wait_for_service,
)
from .web_review_smoke import DEFAULT_SMOKE_PROMPT


AUTH_SOURCE = "chatgpt-web2api-consent"
PROJECT_AUTH = "chatgpt-web2api-project-binding"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yes(prompt: str, *, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    value = input(prompt + suffix).strip().casefold()
    if not value:
        return default
    return value in {"y", "yes", "s", "sim"}


def _ask(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def _account_record(data: dict[str, Any], profile: str | None) -> dict[str, Any] | None:
    if not profile:
        return None
    value = data.get("accounts", {}).get(core.platform_key(), {}).get(profile)
    return value if isinstance(value, dict) else None


def _authorized(record: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(record, dict)
        and record.get("backend") == BACKEND_ID
        and record.get("source") == AUTH_SOURCE
        and record.get("endpoint")
    )


def _active_profile() -> str | None:
    _, data = core.global_config()
    value = data.get("active_profiles", {}).get(core.platform_key())
    return str(value) if value else None


def _profile_for(args: argparse.Namespace) -> str:
    explicit = getattr(args, "profile", None)
    if explicit:
        return str(explicit)
    active = _active_profile()
    if active:
        return active
    raise core.PowerPackError("No active ChatGPT reviewer profile. Run 'speckit-powerpack review auth configure'.")


def _require_account(profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, data = core.global_config()
    record = _account_record(data, profile)
    if not _authorized(record):
        raise core.PowerPackError(
            f"Reviewer profile '{profile}' is not configured for backend={BACKEND_ID}. "
            "Run 'speckit-powerpack review auth configure'."
        )
    return data, record or {}


def _verify_endpoint(endpoint: str, *, require_projects: bool = True) -> tuple[dict[str, Any], list[Any]]:
    try:
        state = health(endpoint, timeout=10)
        projects = list_projects(endpoint, timeout=30)
    except Web2APIError as exc:
        raise core.PowerPackError(str(exc)) from exc
    status = str(state.get("status") or "unknown")
    if status == "broken":
        raise core.PowerPackError(
            f"ChatGPT-Web2API is reachable at {endpoint}, but Chrome/CDP is broken. "
            "Keep its dedicated Chrome open or restart the reviewer service."
        )
    if require_projects and not projects:
        raise core.PowerPackError(
            f"ChatGPT-Web2API is reachable at {endpoint}, but returned no ChatGPT Projects. "
            "Complete login in the dedicated Chrome window, confirm the intended Plus account, and retry."
        )
    return state, projects


def _persist_account(*, profile: str, account_label: str, endpoint: str) -> list[str]:
    path, data = core.global_config()
    platform = core.platform_key()
    invalidated = account_base._invalidate_profile_bindings(data, platform, profile)
    record = {
        "source": AUTH_SOURCE,
        "backend": BACKEND_ID,
        "account_label": account_label,
        "endpoint": normalize_endpoint(endpoint),
        "model": DEFAULT_MODEL,
        "granted_at": utc_now(),
    }
    data["schema_version"] = max(6, int(data.get("schema_version", 0) or 0))
    data.setdefault("accounts", {}).setdefault(platform, {})[profile] = record
    data.setdefault("active_profiles", {})[platform] = profile
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {})[profile] = {
        "confirmed": True,
        "source": AUTH_SOURCE,
        "backend": BACKEND_ID,
        "account_label": account_label,
        "endpoint": record["endpoint"],
        "granted_at": record["granted_at"],
    }
    core.save_global(path, data)
    return invalidated


def cmd_service_start(args: argparse.Namespace) -> None:
    profile = str(args.profile or _active_profile() or "chatgpt-review")
    port = int(args.port)
    cdp_port = int(args.cdp_port)
    if winbridge.is_wsl():
        print("Starting a dedicated ChatGPT-Web2API reviewer on the Windows host...")
        print("The reviewer uses a persistent Chrome profile owned by PowerPack and runs headed by default.")
        print("No cookies/tokens are copied from Edge/Chrome personal profiles into WSL or the repository.")
        try:
            info = start_windows_service(
                profile=profile,
                port=port,
                cdp_port=cdp_port,
                install=not bool(args.no_install),
            )
            state = wait_for_service(str(info["endpoint"]), timeout=int(args.timeout))
        except Web2APIError as exc:
            raise core.PowerPackError(str(exc)) from exc
        print(f"Reviewer service started: {info['endpoint']}")
        print(f"Dedicated Chrome profile: {info['profile_dir']}")
        print(f"Logs: {info['stdout']} | {info['stderr']}")
        print(f"Health: {state.get('status')} chrome={state.get('chrome_running')} cdp={state.get('cdp_connected')}")
        print("Complete ChatGPT login in the Chrome window that opened, then run:")
        print("  speckit-powerpack review auth configure")
        return

    executable = shutil.which("chatgpt-web2api")
    if not executable and not args.no_install:
        uv = shutil.which("uv")
        if not uv:
            raise core.PowerPackError(
                "chatgpt-web2api is not installed and uv is unavailable. Install ChatGPT-Web2API, then retry."
            )
        proc = subprocess.run([uv, "tool", "install", "--force", "chatgpt-web2api"], text=True)
        if proc.returncode != 0:
            raise core.PowerPackError("Could not install chatgpt-web2api with uv.")
        executable = shutil.which("chatgpt-web2api")
    if not executable:
        raise core.PowerPackError("chatgpt-web2api executable is unavailable.")
    profile_dir = core.global_root() / "reviewers" / profile / "chrome-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    log_dir = core.global_root() / "reviewers" / profile / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "web2api.out.log").open("ab")
    stderr = (log_dir / "web2api.err.log").open("ab")
    subprocess.Popen(
        [
            executable,
            "start",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--cdp-port",
            str(cdp_port),
            "--user-data-dir",
            str(profile_dir),
        ],
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    endpoint = f"http://127.0.0.1:{port}"
    try:
        state = wait_for_service(endpoint, timeout=int(args.timeout))
    except Web2APIError as exc:
        raise core.PowerPackError(str(exc)) from exc
    print(f"Reviewer service started: {endpoint}")
    print(f"Dedicated Chrome profile: {profile_dir}")
    print(f"Health: {state.get('status')} chrome={state.get('chrome_running')} cdp={state.get('cdp_connected')}")
    print("Complete ChatGPT login in the Chrome window that opened, then run review auth configure.")


def cmd_service_status(args: argparse.Namespace) -> None:
    endpoint = normalize_endpoint(args.endpoint or DEFAULT_ENDPOINT)
    try:
        state = health(endpoint, timeout=int(args.timeout))
    except Web2APIError as exc:
        raise core.PowerPackError(str(exc)) from exc
    print(json.dumps({"endpoint": endpoint, **state}, ensure_ascii=False, indent=2))


def cmd_auth_configure(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    active = data.get("active_profiles", {}).get(platform)
    profile = _ask("Nome lógico do reviewer/account", default=str(active or "chatgpt-review"))
    if not profile:
        raise core.PowerPackError("Reviewer profile is required.")
    existing = _account_record(data, profile)
    if _authorized(existing):
        print(
            f"\nJá existe reviewer '{profile}': account={existing.get('account_label') or profile} "
            f"endpoint={existing.get('endpoint')} backend={BACKEND_ID}."
        )
        if not _yes("Deseja substituir essa autorização/binding de conta?", default=False):
            print("Autorização atual preservada.")
            return
    account_label = _ask(
        "Identificação local da conta ChatGPT",
        default=str((existing or {}).get("account_label") or profile),
    )
    endpoint = normalize_endpoint(
        _ask("Endpoint ChatGPT-Web2API", default=str((existing or {}).get("endpoint") or DEFAULT_ENDPOINT))
    )
    print(f"\nValidando reviewer service em {endpoint}...")
    try:
        state, projects = _verify_endpoint(endpoint, require_projects=True)
    except core.PowerPackError as exc:
        print("\nO PowerPack não tentará trocar backend/conta automaticamente.")
        print("Se o serviço ainda não estiver iniciado, execute explicitamente:")
        print(f"  speckit-powerpack review service start --profile {profile}")
        raise
    print(
        f"Reviewer service OK: status={state.get('status')} chrome={state.get('chrome_running')} "
        f"cdp={state.get('cdp_connected')} projects={len(projects)}"
    )
    print("Essa autorização vincula o profile lógico ao endpoint/conta já autenticada no Chrome dedicado.")
    if not _yes(f"Confirmar que {endpoint} corresponde à conta '{account_label}'?", default=False):
        raise core.PowerPackError("Conta não confirmada; nenhuma autorização foi gravada.")
    invalidated = _persist_account(profile=profile, account_label=account_label, endpoint=endpoint)
    print(f"Conta '{account_label}' autorizada como reviewer '{profile}' usando {BACKEND_ID}.")
    if invalidated:
        print("Bindings anteriores marcados como stale: " + ", ".join(sorted(set(invalidated))))


def cmd_auth_list(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    active = data.get("active_profiles", {}).get(platform)
    accounts = data.get("accounts", {}).get(platform, {})
    values = [
        (name, raw)
        for name, raw in sorted(accounts.items())
        if isinstance(raw, dict) and raw.get("backend") == BACKEND_ID
    ] if isinstance(accounts, dict) else []
    if not values:
        print(f"Nenhuma conta reviewer configurada com backend={BACKEND_ID}.")
        return
    for profile, record in values:
        marker = "*" if profile == active else " "
        print(
            f"{marker} {profile}: account={record.get('account_label') or profile} "
            f"backend={BACKEND_ID} endpoint={record.get('endpoint')}"
        )


def cmd_auth_validate(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    _, record = _require_account(profile)
    state, projects = _verify_endpoint(str(record["endpoint"]), require_projects=True)
    print(
        f"OK profile={profile} account={record.get('account_label') or profile} backend={BACKEND_ID} "
        f"endpoint={record.get('endpoint')} status={state.get('status')} projects={len(projects)}"
    )


def cmd_auth_use(args: argparse.Namespace) -> None:
    path, data = core.global_config()
    record = _account_record(data, args.profile)
    if not _authorized(record):
        raise core.PowerPackError(f"Reviewer '{args.profile}' is not authorized with backend={BACKEND_ID}.")
    data.setdefault("active_profiles", {})[core.platform_key()] = args.profile
    core.save_global(path, data)
    print(f"Reviewer ativo: '{args.profile}'.")
    print("O repositório só muda de reviewer após project use/select/add explícito.")


def cmd_auth_logout(args: argparse.Namespace) -> None:
    path, data = core.global_config()
    platform = core.platform_key()
    profile = args.profile
    invalidated = account_base._invalidate_profile_bindings(data, platform, profile)
    data.setdefault("accounts", {}).setdefault(platform, {}).pop(profile, None)
    data.setdefault("authenticated_profiles", {}).setdefault(platform, {}).pop(profile, None)
    if data.setdefault("active_profiles", {}).get(platform) == profile:
        data["active_profiles"].pop(platform, None)
    core.save_global(path, data)
    print(f"Autorização PowerPack removida para '{profile}'.")
    print("O serviço/Chrome dedicado não foi encerrado nem deslogado automaticamente.")
    if invalidated:
        print("Bindings marcados como stale: " + ", ".join(sorted(set(invalidated))))


def _project_url(project_id: str) -> str:
    return f"https://chatgpt.com/g/{project_id}/project"


def _persist_binding(
    *,
    alias: str,
    project_id: str,
    project_name: str,
    project_url: str,
    profile: str,
    project_path: Path,
) -> None:
    cfg_path, data = core.global_config()
    platform = core.platform_key()
    _, account = _require_account(profile)
    registered = data.setdefault("projects", {}).setdefault(alias, {"bindings": {}})
    registered["display_name"] = project_name
    platform_bindings = registered.setdefault("bindings", {}).setdefault(platform, {})
    if isinstance(platform_bindings, dict) and "url" in platform_bindings and "profile" in platform_bindings:
        legacy = dict(platform_bindings)
        legacy_profile = str(legacy.get("profile") or "legacy")
        registered["bindings"][platform] = {legacy_profile: legacy}
        platform_bindings = registered["bindings"][platform]
    platform_bindings[profile] = {
        "url": project_url,
        "project_id": project_id,
        "profile": profile,
        "account_label": account.get("account_label") or profile,
        "account_backend": BACKEND_ID,
        "endpoint": account.get("endpoint"),
        "authorization": PROJECT_AUTH,
    }
    data.setdefault("active_profiles", {})[platform] = profile
    core.save_global(cfg_path, data)

    review_path, review = account_base._review_config(project_path)
    web = review.setdefault("chatgpt_web", {})
    web.update(
        {
            "required": True,
            "enabled": True,
            "backend": BACKEND_ID,
            "project_alias": alias,
            "project_id": project_id,
            "project_url": project_url,
            "project_name": project_name,
            "profile": profile,
            "account_label": account.get("account_label") or profile,
            "account_backend": BACKEND_ID,
            "endpoint": account.get("endpoint"),
            "profile_scope": "platform",
            "profile_platform": platform,
            "authorization": PROJECT_AUTH,
        }
    )
    core.write_json(review_path, review, overwrite=True)
    print(
        f"Repositório vinculado ao Project '{project_name}' ({project_id}) como '{alias}' "
        f"usando reviewer '{account.get('account_label') or profile}' em {account.get('endpoint')}."
    )


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text[:60] or "chatgpt-project"


def _projects_for(profile: str):
    _, account = _require_account(profile)
    try:
        return list_projects(str(account["endpoint"]), timeout=30)
    except Web2APIError as exc:
        raise core.PowerPackError(str(exc)) from exc


def cmd_project_discover(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    projects = _projects_for(profile)
    if not projects:
        raise core.PowerPackError("No ChatGPT Projects were returned by the selected reviewer endpoint.")
    for index, item in enumerate(projects, start=1):
        print(f"{index:2}. {item.name} | {item.project_id}")


def _choose_project(projects: list[Any], index: int | None) -> Any:
    if not projects:
        raise core.PowerPackError("No ChatGPT Projects were returned by the selected reviewer endpoint.")
    if index is None:
        for number, item in enumerate(projects, start=1):
            print(f"{number:2}. {item.name} | {item.project_id}")
        value = input("Select Project number: ").strip()
        if not value.isdigit():
            raise core.PowerPackError("Project selection must be a number.")
        index = int(value)
    if index < 1 or index > len(projects):
        raise core.PowerPackError("Project selection index is out of range.")
    return projects[index - 1]


def cmd_project_select(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    item = _choose_project(_projects_for(profile), getattr(args, "index", None))
    alias = args.alias or _slug(item.name)
    _persist_binding(
        alias=alias,
        project_id=item.project_id,
        project_name=item.name,
        project_url=_project_url(item.project_id),
        profile=profile,
        project_path=Path(args.path).resolve(),
    )


def cmd_project_add(args: argparse.Namespace) -> None:
    profile = _profile_for(args)
    project_id = project_id_from_value(args.url)
    if not project_id:
        raise core.PowerPackError("Could not extract g-p-... Project id from the supplied ChatGPT Project URL.")
    projects = _projects_for(profile)
    item = next((p for p in projects if p.project_id == project_id), None)
    if item is None:
        raise core.PowerPackError(
            f"Project {project_id} is not visible through reviewer '{profile}'. "
            "Confirm the account has access, then retry."
        )
    alias = args.alias or _slug(item.name)
    _persist_binding(
        alias=alias,
        project_id=project_id,
        project_name=item.name,
        project_url=args.url.split("?", 1)[0].split("#", 1)[0].rstrip("/"),
        profile=profile,
        project_path=Path(args.path).resolve(),
    )


def cmd_project_use(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    _, data = core.global_config()
    platform = core.platform_key()
    registered = data.get("projects", {}).get(args.alias)
    if not isinstance(registered, dict):
        raise core.PowerPackError(f"Unknown project alias: {args.alias}")
    bindings = account_base._platform_bindings(registered, platform)
    requested = getattr(args, "profile", None)
    if requested:
        binding = bindings.get(requested)
        profile = requested
    elif len(bindings) == 1:
        profile, binding = next(iter(bindings.items()))
    else:
        active = _active_profile()
        profile = str(active or "")
        binding = bindings.get(profile)
    if not profile or not isinstance(binding, dict):
        raise core.PowerPackError("Project has multiple/no reviewer bindings; pass --profile explicitly.")
    _, account = _require_account(profile)
    if binding.get("authorization") != PROJECT_AUTH or binding.get("account_backend") != BACKEND_ID:
        raise core.PowerPackError("Project binding is stale/legacy; select/add it again with the Web2API reviewer.")
    _persist_binding(
        alias=args.alias,
        project_id=str(binding.get("project_id") or ""),
        project_name=str(registered.get("display_name") or args.alias),
        project_url=str(binding.get("url") or _project_url(str(binding.get("project_id") or ""))),
        profile=profile,
        project_path=project,
    )


def cmd_project_list(args: argparse.Namespace) -> None:
    _, data = core.global_config()
    platform = core.platform_key()
    for alias, project in sorted(data.get("projects", {}).items()):
        if not isinstance(project, dict):
            continue
        platforms = project.get("bindings", {})
        names = sorted(platforms) if getattr(args, "all_platforms", False) else [platform]
        for platform_name in names:
            for profile, binding in sorted(account_base._platform_bindings(project, platform_name).items()):
                if binding.get("account_backend") != BACKEND_ID:
                    continue
                print(
                    f"{alias}: name={project.get('display_name') or alias} platform={platform_name} "
                    f"profile={profile} account={binding.get('account_label')} endpoint={binding.get('endpoint')} "
                    f"project_id={binding.get('project_id')} url={binding.get('url')}"
                )


def _bound_context(project: Path) -> tuple[dict[str, Any], str, dict[str, Any]]:
    readiness = review_readiness(project, live=False)
    if not all(readiness.values()):
        print_review_setup_status(project)
        missing = ", ".join(key for key, ok in readiness.items() if not ok)
        raise core.PowerPackError(f"Web review binding is not ready: {missing}")
    _, review = account_base._review_config(project)
    web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
    profile = str(web.get("profile") or "")
    _, account = _require_account(profile)
    return web, profile, account


def _run_prompt(project: Path, prompt: str, *, timeout: int, model: str | None = None):
    web, profile, account = _bound_context(project)
    try:
        result = chat(
            str(account["endpoint"]),
            project_id=str(web["project_id"]),
            prompt=prompt,
            model=model or str(account.get("model") or DEFAULT_MODEL),
            timeout=timeout,
        )
    except Web2APIError as exc:
        raise core.PowerPackError(str(exc)) from exc
    return web, profile, account, result


def cmd_review_smoke_test(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    prompt = args.prompt or DEFAULT_SMOKE_PROMPT
    print("\nCHATGPT WEB REVIEW — FUNCTIONAL SMOKE TEST")
    web, profile, account, result = _run_prompt(project, prompt, timeout=int(args.timeout))
    words = len(result.response.split())
    arithmetic = bool(re.search(r"(^|\D)2(\D|$)|\bdois\b|\btwo\b", result.response, re.IGNORECASE))
    max_words = words <= 100
    payload = {
        "status": "ok" if arithmetic and max_words else "contract-failed",
        "backend": BACKEND_ID,
        "profile": profile,
        "account_label": account.get("account_label") or profile,
        "endpoint": account.get("endpoint"),
        "project_alias": web.get("project_alias"),
        "project_name": web.get("project_name"),
        "project_id": web.get("project_id"),
        "project_url": web.get("project_url"),
        "conversation_id": result.conversation_id,
        "model": result.model,
        "response": result.response,
        "response_words": words,
        "arithmetic_check": arithmetic,
        "max_words_check": max_words,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"  reviewer: {profile} / {account.get('account_label') or profile}")
        print(f"  endpoint: {account.get('endpoint')}")
        print(f"  Project: {web.get('project_name')} ({web.get('project_id')})")
        print("\nPrompt enviado ao Project:")
        print(prompt)
        print("\n=== RESPOSTA RECEBIDA ===")
        print(result.response)
        print("\n=== VALIDAÇÃO ===")
        print(f"{'PASS' if max_words else 'FAIL'} resposta <= 100 palavras ({words})")
        print(f"{'PASS' if arithmetic else 'FAIL'} resposta contém resultado 1 + 1 = 2")
    if not arithmetic or not max_words:
        raise core.PowerPackError("ChatGPT Project responded, but the smoke-test content contract failed.")
    print("\nSMOKE TEST PASSED: reviewer endpoint → authenticated account → bound Project → prompt → response.")


def cmd_review_run(args: argparse.Namespace) -> None:
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        prompt = args.prompt or ""
    if not prompt.strip():
        raise core.PowerPackError("Use --prompt or --prompt-file with a non-empty reviewer prompt.")
    web, profile, account, result = _run_prompt(
        Path(args.path).resolve(),
        prompt,
        timeout=int(args.timeout),
        model=args.model,
    )
    payload = {
        "status": "ok",
        "backend": BACKEND_ID,
        "profile": profile,
        "account_label": account.get("account_label") or profile,
        "endpoint": account.get("endpoint"),
        "project_alias": web.get("project_alias"),
        "project_name": web.get("project_name"),
        "project_id": web.get("project_id"),
        "project_url": web.get("project_url"),
        "conversation_id": result.conversation_id,
        "model": result.model,
        "response": result.response,
    }
    if args.output:
        Path(args.output).write_text(result.response + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(result.response)


def review_readiness(project: Path, *, live: bool = False) -> dict[str, bool]:
    try:
        _, review = account_base._review_config(project)
    except core.PowerPackError:
        review = {}
    web = review.get("chatgpt_web", {}) if isinstance(review, dict) else {}
    if not isinstance(web, dict):
        web = {}
    profile = str(web.get("profile") or "")
    alias = str(web.get("project_alias") or "")
    project_id = str(web.get("project_id") or "")
    _, data = core.global_config()
    account = _account_record(data, profile)
    account_ok = _authorized(account)
    registered = data.get("projects", {}).get(alias) if alias else None
    binding = account_base._binding_for(registered, core.platform_key(), profile) if isinstance(registered, dict) else None
    project_ok = bool(
        account_ok
        and project_id
        and isinstance(binding, dict)
        and binding.get("project_id") == project_id
        and binding.get("profile") == profile
        and binding.get("authorization") == PROJECT_AUTH
        and web.get("authorization") == PROJECT_AUTH
        and web.get("backend") == BACKEND_ID
    )
    endpoint_ok = bool(account_ok and account and account.get("endpoint"))
    result = {
        "web-review-required": bool(web.get("required") and web.get("enabled")),
        "chatgpt-web2api-configured": endpoint_ok,
        "chatgpt-account-authenticated": account_ok,
        "chatgpt-project-bound": project_ok,
    }
    if live:
        live_ok = False
        if endpoint_ok:
            try:
                state = health(str(account.get("endpoint")), timeout=10)
                live_ok = str(state.get("status") or "") not in {"broken", ""}
                if live_ok and project_ok:
                    visible = {p.project_id for p in list_projects(str(account.get("endpoint")), timeout=30)}
                    live_ok = project_id in visible
            except Web2APIError:
                live_ok = False
        result["chatgpt-reviewer-service-live"] = live_ok
    return result


def print_review_setup_status(project: Path) -> None:
    readiness = review_readiness(project)
    if all(readiness.values()):
        print("Mandatory ChatGPT Web review is configured through ChatGPT-Web2API.")
        return
    print("\nCHATGPT WEB REVIEW SETUP")
    if not readiness.get("chatgpt-account-authenticated"):
        print("1. Start one dedicated reviewer service/account:")
        print("   speckit-powerpack review service start --profile <profile>")
        print("2. Complete ChatGPT login in the dedicated Chrome and configure the reviewer:")
        print("   speckit-powerpack review auth configure")
    if not readiness.get("chatgpt-project-bound"):
        print("3. Discover/select a Project and bind it to this repository:")
        print("   speckit-powerpack review project select --profile <profile> --path .")
    print("Reviewer account/endpoint/Project binding is user-scoped and never stored as personal state in the Git worktree.")
    print("Use 'speckit-powerpack doctor --strict-review' immediately before implement-review.\n")


def cmd_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    runtime = project / ".specify" / "powerpack" / "bin" / "powerpack.py"
    specify_binary = shutil.which("specify")
    current_spec_kit = core.specify_version(specify_binary) if specify_binary else None
    integration = core.project_integration(project)
    readiness = review_readiness(project, live=bool(args.strict_review))
    hard_checks = {
        "specify": bool(specify_binary),
        "spec-kit-compatible": core.spec_kit_compatible(current_spec_kit),
        "spec-kit-project": (project / ".specify").is_dir(),
        "powerpack-runtime": runtime.is_file(),
        "capability-resolver": runtime.with_name("capabilities.py").is_file(),
        "review-protocol-validator": runtime.with_name("review_protocol.py").is_file(),
        "technical-debt-runtime": runtime.with_name("debt.py").is_file(),
        "full-cycle-runtime": runtime.with_name("full_cycle.py").is_file(),
        "selected-executor": bool(shutil.which(integration)),
    }
    print(f"Platform:    {core.platform_key()} ({core.platform_module.system()})")
    print(f"Reviewer:    {BACKEND_ID}")
    print(f"Config:      {core.global_root()}")
    print(f"Integration: {integration}")
    print(f"Spec Kit:    {current_spec_kit or 'unknown'} (requires >= {core.SPECKIT_MIN_VERSION_TEXT})")
    for key, ok in hard_checks.items():
        print(f"{'OK' if ok else 'FAIL':5} {key}")
    for key, ok in readiness.items():
        print(f"{'OK' if ok else 'SETUP':5} {key}")
    if not all(hard_checks.values()):
        raise core.PowerPackError("PowerPack installation checks failed.")
    if args.strict_review and not all(readiness.values()):
        print_review_setup_status(project)
        raise core.PowerPackError("Mandatory ChatGPT Web review is not ready.")
    if not all(readiness.values()):
        print_review_setup_status(project)
        print("Installation is healthy; ChatGPT Web review onboarding is incomplete.")
