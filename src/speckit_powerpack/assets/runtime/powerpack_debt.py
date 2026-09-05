#!/usr/bin/env python3
"""Project-local governed technical-debt ledger for SpecKit PowerPack."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

ITEM_RE = re.compile(r"^### (?P<id>[A-Za-z][A-Za-z0-9_-]*-\d+) — (?P<title>.+)$")
FIELD_RE = re.compile(r"^- \*\*(?P<name>[^*]+):\*\*\s*(?P<value>.*)$")


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify" / "powerpack").is_dir():
            return candidate
    raise SystemExit("BLOCKED: .specify/powerpack not found")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"BLOCKED_CONFIGURATION: cannot read {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"BLOCKED_CONFIGURATION: {path} must contain an object")
    return data


def config(root: Path) -> dict[str, Any]:
    return read_json(root / ".specify" / "powerpack" / "technical-debt.json")


def resolve_path(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def storage(root: Path, cfg: dict[str, Any]) -> tuple[Path, Path]:
    if cfg.get("storage_format", "markdown-v1") != "markdown-v1":
        raise SystemExit("BLOCKED_CONFIGURATION: runtime currently requires storage_format=markdown-v1 or a project adapter")
    backlog = resolve_path(root, str(cfg.get("backlog_path") or "docs/technical-debt.md"))
    template = resolve_path(root, str(cfg.get("template_path") or ".specify/powerpack/technical-debt-template.md"))
    return backlog, template


def ensure_backlog(root: Path, cfg: dict[str, Any]) -> Path:
    backlog, template = storage(root, cfg)
    if backlog.exists():
        return backlog
    if not template.is_file():
        raise SystemExit(f"BLOCKED_CONFIGURATION: technical debt template not found: {template}")
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return backlog


def visible_markdown_lines(text: str) -> list[str]:
    """Mask HTML comments while preserving one output entry per input line.

    The canonical backlog template intentionally contains a commented example
    with a `### TD-001` heading. Treating comments as ledger content would make
    that example a real item and incorrectly allocate the first debt as TD-002.
    Keeping line count stable also preserves mutation indices for real items.
    """
    result: list[str] = []
    in_comment = False
    for original in text.splitlines():
        line = original
        visible = ""
        while line:
            if in_comment:
                marker = line.find("-->")
                if marker < 0:
                    line = ""
                    break
                line = line[marker + 3:]
                in_comment = False
                continue
            marker = line.find("<!--")
            if marker < 0:
                visible += line
                line = ""
                break
            visible += line[:marker]
            line = line[marker + 4:]
            in_comment = True
        result.append(visible)
    return result


def parse_items(text: str) -> list[dict[str, Any]]:
    raw_lines = text.splitlines()
    visible_lines = visible_markdown_lines(text)
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(visible_lines):
        match = ITEM_RE.match(line)
        if match:
            starts.append((index, match))
    items: list[dict[str, Any]] = []
    for pos, (start, match) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(raw_lines)
        fields: dict[str, str] = {}
        for line in visible_lines[start + 1:end]:
            field = FIELD_RE.match(line)
            if field:
                fields[field.group("name").strip().lower()] = field.group("value").strip()
        items.append({
            "id": match.group("id"),
            "title": match.group("title").strip(),
            "fields": fields,
            "start": start,
            "end": end,
        })
    return items


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def next_id(prefix: str, items: list[dict[str, Any]]) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    numbers = []
    for item in items:
        match = pattern.match(str(item["id"]))
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}-{(max(numbers) + 1 if numbers else 1):03d}"


def item_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "title": item["title"], **item["fields"]}


def find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for item in items:
        if str(item["id"]).casefold() == item_id.casefold():
            return item
    raise SystemExit(f"NOT_FOUND: technical debt item {item_id}")


def rewrite_field(lines: list[str], item: dict[str, Any], label: str, value: str) -> None:
    prefix = f"- **{label}:**"
    for index in range(item["start"] + 1, item["end"]):
        if lines[index].startswith(prefix):
            lines[index] = f"{prefix} {value}"
            return
    insert_at = item["start"] + 1
    lines.insert(insert_at, f"{prefix} {value}")


def append_lifecycle(lines: list[str], item_id: str, entry: str) -> None:
    text = "\n".join(lines)
    items = parse_items(text)
    item = find_item(items, item_id)
    lifecycle = None
    for index in range(item["start"] + 1, item["end"]):
        if lines[index].strip() == "#### Lifecycle":
            lifecycle = index
            break
    if lifecycle is None:
        lines[item["end"]:item["end"]] = ["", "#### Lifecycle", "", f"- {entry}"]
        return
    insert_at = item["end"]
    while insert_at > lifecycle and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"- {entry}")


def cmd_create(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = config(root)
    policy = cfg.get("creation_policy", {}) if isinstance(cfg.get("creation_policy"), dict) else {}
    priority = args.priority.upper()
    if priority in {"P0", "BLOCKER"} or (policy.get("forbid_blockers") and args.blocker):
        print(json.dumps({"status": "NOT_DEBT", "reason": "blocker-must-remain-in-current-delivery-flow"}))
        return 4
    if args.active_obligation:
        print(json.dumps({"status": "NOT_DEBT", "reason": "active-spec-or-gate-obligation"}))
        return 4
    if args.origin_kind == "review" and policy.get("forbid_active_review_findings", True):
        print(json.dumps({"status": "NOT_DEBT", "reason": "review-findings-cannot-be-deferred"}))
        return 4
    if args.origin_kind == "converge" and policy.get("forbid_active_convergence_gaps", True):
        print(json.dumps({"status": "NOT_DEBT", "reason": "convergence-gaps-cannot-be-deferred"}))
        return 4
    priorities = {str(value).upper() for value in cfg.get("priorities", ["P1", "P2", "P3"])}
    if priority not in priorities:
        print(json.dumps({"status": "BLOCKED_CONFIGURATION", "reason": "priority-not-allowed", "priority": priority, "allowed": sorted(priorities)}))
        return 5

    backlog = ensure_backlog(root, cfg)
    text = backlog.read_text(encoding="utf-8")
    items = parse_items(text)
    duplicate = next((item for item in items if normalize(item["title"]) == normalize(args.title)), None)
    if duplicate is not None:
        print(json.dumps({"status": "DUPLICATE", "existing": item_payload(duplicate)}, ensure_ascii=False))
        return 3

    prefix = str(cfg.get("id_prefix") or "TD")
    item_id = next_id(prefix, items)
    today = date.today().isoformat()
    dependencies = args.dependencies or "none"
    future = args.future_spec or "unknown"
    evidence = args.evidence or "not provided"
    block = f"""
### {item_id} — {args.title.strip()}

- **Owner:** {args.owner.strip()}
- **Priority:** {priority}
- **Status:** OPEN
- **Readiness:** {args.readiness}
- **Origin:** {args.origin.strip()}
- **Description:** {args.description.strip()}
- **Impact:** {args.impact.strip()}
- **Resolution criteria:** {args.resolution_criteria.strip()}
- **Deferral rationale:** {args.deferral_rationale.strip()}
- **Dependencies / blockers:** {dependencies.strip()}
- **Probable future SPEC / capability:** {future.strip()}
- **Evidence:** {evidence.strip()}

#### Lifecycle

- {today} — CREATED — origin={args.origin_kind}; {evidence.strip()}
"""
    with backlog.open("a", encoding="utf-8") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(block)
    print(json.dumps({"status": "CREATED", "id": item_id, "backlog": str(backlog.relative_to(root))}, ensure_ascii=False))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = config(root)
    backlog, _ = storage(root, cfg)
    if not backlog.exists():
        print(json.dumps({"status": "EMPTY", "items": []}))
        return 0
    items = [item_payload(item) for item in parse_items(backlog.read_text(encoding="utf-8"))]
    filters = {"status": args.status, "readiness": args.readiness, "priority": args.priority, "owner": args.owner}
    for key, value in filters.items():
        if value:
            items = [item for item in items if normalize(str(item.get(key, ""))) == normalize(value)]
    print(json.dumps({"status": "OK", "count": len(items), "items": items}, ensure_ascii=False, indent=2))
    return 0


def cmd_consult(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = config(root)
    backlog, _ = storage(root, cfg)
    if not backlog.exists():
        raise SystemExit("NOT_FOUND: technical debt backlog does not exist")
    item = find_item(parse_items(backlog.read_text(encoding="utf-8")), args.id)
    print(json.dumps({"status": "OK", "item": item_payload(item)}, ensure_ascii=False, indent=2))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = config(root)
    backlog, _ = storage(root, cfg)
    text = backlog.read_text(encoding="utf-8")
    items = parse_items(text)
    item = find_item(items, args.id)
    fields = item["fields"]
    if fields.get("status", "").upper() != "OPEN":
        print(json.dumps({"status": "BLOCKED", "reason": "item-not-open", "actual": fields.get("status")}))
        return 6
    if fields.get("readiness", "").upper() != "READY":
        print(json.dumps({"status": "BLOCKED", "reason": "item-not-ready", "actual": fields.get("readiness")}))
        return 6
    lines = text.splitlines()
    rewrite_field(lines, item, "Status", "IN_PROGRESS")
    provenance = args.spec or args.branch or "work-started"
    append_lifecycle(lines, args.id, f"{date.today().isoformat()} — IN_PROGRESS — {provenance}; {args.evidence or 'no additional evidence'}")
    backlog.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "IN_PROGRESS", "id": args.id, "provenance": provenance}))
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = config(root)
    backlog, _ = storage(root, cfg)
    text = backlog.read_text(encoding="utf-8")
    items = parse_items(text)
    item = find_item(items, args.id)
    if item["fields"].get("status", "").upper() == "RESOLVED":
        print(json.dumps({"status": "NOOP", "id": args.id, "reason": "already-resolved"}))
        return 0
    if not args.criteria_satisfied:
        print(json.dumps({"status": "BLOCKED", "reason": "resolution-criteria-not-proven"}))
        return 7
    if not args.evidence.strip():
        print(json.dumps({"status": "BLOCKED", "reason": "objective-evidence-required"}))
        return 7
    lines = text.splitlines()
    rewrite_field(lines, item, "Status", "RESOLVED")
    reparsed = find_item(parse_items("\n".join(lines)), args.id)
    rewrite_field(lines, reparsed, "Readiness", "RESOLVED")
    gate = f"; gate={args.gate_status}" if args.gate_status else ""
    append_lifecycle(lines, args.id, f"{date.today().isoformat()} — RESOLVED — {args.evidence.strip()}{gate}")
    backlog.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "RESOLVED", "id": args.id, "evidence": args.evidence, "gate_status": args.gate_status}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerpack-debt")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--title", required=True); p.add_argument("--owner", required=True)
    p.add_argument("--description", required=True); p.add_argument("--origin", required=True)
    p.add_argument("--origin-kind", choices=["manual", "spec", "review", "converge", "incident", "audit"], required=True)
    p.add_argument("--impact", required=True); p.add_argument("--priority", required=True)
    p.add_argument("--resolution-criteria", required=True); p.add_argument("--deferral-rationale", required=True)
    p.add_argument("--readiness", choices=["READY", "BLOCKED", "NEEDS_REFINEMENT"], default="READY")
    p.add_argument("--dependencies"); p.add_argument("--future-spec"); p.add_argument("--evidence")
    p.add_argument("--active-obligation", action="store_true"); p.add_argument("--blocker", action="store_true")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list")
    p.add_argument("--status"); p.add_argument("--readiness"); p.add_argument("--priority"); p.add_argument("--owner")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("consult"); p.add_argument("id"); p.set_defaults(func=cmd_consult)
    p = sub.add_parser("start"); p.add_argument("id"); p.add_argument("--spec"); p.add_argument("--branch"); p.add_argument("--evidence"); p.set_defaults(func=cmd_start)
    p = sub.add_parser("close"); p.add_argument("id"); p.add_argument("--criteria-satisfied", action="store_true"); p.add_argument("--evidence", required=True); p.add_argument("--gate-status"); p.set_defaults(func=cmd_close)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
