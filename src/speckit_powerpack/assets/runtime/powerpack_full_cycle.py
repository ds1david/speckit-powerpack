#!/usr/bin/env python3
"""Resumable same-SPEC full-cycle state machine for SpecKit PowerPack."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

PHASE_ORDER = [
    "clarify", "plan", "checklist", "checklist_converge", "tasks",
    "analyze", "implement", "converge", "implement_review",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".specify" / "powerpack").is_dir():
            return candidate
    raise SystemExit("BLOCKED: .specify/powerpack not found")


def resolve_feature(root: Path, raw: str | None) -> Path:
    if raw:
        path = Path(raw)
        path = path if path.is_absolute() else root / path
        if not path.is_dir():
            raise SystemExit(f"BLOCKED: feature directory not found: {path}")
        return path.resolve()
    feature_json = root / ".specify" / "feature.json"
    if feature_json.is_file():
        try:
            value = json.loads(feature_json.read_text(encoding="utf-8")).get("feature_directory")
        except json.JSONDecodeError:
            value = None
        if value:
            return resolve_feature(root, str(value))
    raise SystemExit("BLOCKED: could not resolve feature; pass --feature-dir")


def feature_id(root: Path, feature: Path) -> str:
    try:
        return feature.relative_to(root).as_posix()
    except ValueError:
        return feature.name


def state_path(root: Path, feature: Path) -> Path:
    key = feature_id(root, feature).replace("/", "__").replace("\\", "__")
    return root / ".specify" / "powerpack" / "runtime" / "full-cycle" / f"{key}.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"BLOCKED_CONFIGURATION: cannot read {path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"BLOCKED_CONFIGURATION: {path} must contain an object")
    return data


def config(root: Path) -> dict[str, Any]:
    return read_json(root / ".specify" / "powerpack" / "full-cycle.json")


def enabled_phases(cfg: dict[str, Any]) -> list[str]:
    values = cfg.get("phases", {}) if isinstance(cfg.get("phases"), dict) else {}
    return [phase for phase in PHASE_ORDER if values.get(phase, True) is not False]


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state(root: Path, feature: Path) -> dict[str, Any]:
    path = state_path(root, feature)
    if not path.exists():
        raise SystemExit("BLOCKED: no active full-cycle run; start one first")
    return read_json(path)


def next_phase(phases: list[str], current: str) -> str:
    try:
        index = phases.index(current)
    except ValueError:
        raise SystemExit(f"BLOCKED_CONFIGURATION: phase {current} is not enabled")
    return phases[index + 1] if index + 1 < len(phases) else "DONE"


def persist_and_print(root: Path, feature: Path, state: dict[str, Any], code: int = 0) -> int:
    write_state(state_path(root, feature), state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return code


def cmd_start(args: argparse.Namespace) -> int:
    root = find_root(); feature = resolve_feature(root, args.feature_dir); cfg = config(root)
    behavior = cfg.get("behavior", {}) if isinstance(cfg.get("behavior"), dict) else {}
    invariant_ok = (
        behavior.get("same_spec_only") is True
        and behavior.get("stop_on_blocked") is True
        and behavior.get("allow_debt_escape_hatch") is False
    )
    if not invariant_ok:
        print(json.dumps({"status": "BLOCKED_CONFIGURATION", "reason": "non-weakenable-full-cycle-invariant-changed"}))
        return 8
    path = state_path(root, feature)
    if path.exists() and not args.restart:
        print(json.dumps({"status": "ALREADY_STARTED", "state": read_json(path)}, ensure_ascii=False, indent=2))
        return 0
    phases = enabled_phases(cfg)
    if not phases:
        print(json.dumps({"status": "BLOCKED_CONFIGURATION", "reason": "no-enabled-phases"}))
        return 8
    limits = cfg.get("limits", {}) if isinstance(cfg.get("limits"), dict) else {}
    state = {
        "schema_version": 1,
        "status": "RUNNING",
        "feature": feature_id(root, feature),
        "mode": args.mode or str(cfg.get("mode") or "interactive"),
        "enabled_phases": phases,
        "current_phase": phases[0],
        "return_after_implement": None,
        "convergence_round": 0,
        "review_round": 0,
        "max_convergence_rounds": int(limits.get("max_convergence_rounds", 5)),
        "max_review_rounds": int(limits.get("max_review_rounds", 5)),
        "history": [],
        "started_at": now(),
    }
    return persist_and_print(root, feature, state)


def cmd_status(args: argparse.Namespace) -> int:
    root = find_root(); feature = resolve_feature(root, args.feature_dir)
    print(json.dumps(load_state(root, feature), ensure_ascii=False, indent=2))
    return 0


def block(state: dict[str, Any], reason: str) -> None:
    state["status"] = "BLOCKED"
    state["blocked_reason"] = reason


def cmd_advance(args: argparse.Namespace) -> int:
    root = find_root(); feature = resolve_feature(root, args.feature_dir); state = load_state(root, feature)
    if state.get("status") != "RUNNING":
        print(json.dumps({"status": "BLOCKED", "reason": "cycle-not-running", "actual": state.get("status")}))
        return 9
    current = str(state.get("current_phase"))
    if args.phase != current:
        print(json.dumps({"status": "BLOCKED", "reason": "phase-mismatch", "expected": current, "actual": args.phase}))
        return 9
    outcome = args.outcome
    state.setdefault("history", []).append({"phase": current, "outcome": outcome, "evidence": args.evidence, "at": now()})
    if outcome == "blocked":
        block(state, args.evidence or "phase reported blocked")
        return persist_and_print(root, feature, state, 10)

    phases = list(state.get("enabled_phases") or [])
    if current == "checklist" and outcome == "skipped":
        candidate = next_phase(phases, current)
        if candidate == "checklist_converge":
            state["history"].append({
                "phase": "checklist_converge", "outcome": "skipped",
                "evidence": "checklist not applicable; predecessor intentionally absent", "at": now(),
            })
            state["current_phase"] = next_phase(phases, "checklist_converge")
        else:
            state["current_phase"] = candidate
    elif current == "converge":
        state["convergence_round"] = int(state.get("convergence_round", 0)) + 1
        if state["convergence_round"] > int(state.get("max_convergence_rounds", 5)):
            block(state, "max-convergence-rounds-exceeded")
            return persist_and_print(root, feature, state, 11)
        if outcome == "needs-implementation":
            state["return_after_implement"] = "converge"
            state["current_phase"] = "implement"
        elif outcome in {"converged", "completed"}:
            state["current_phase"] = next_phase(phases, current)
        else:
            print(json.dumps({"status": "BLOCKED", "reason": "invalid-converge-outcome", "outcome": outcome}))
            return 9
    elif current == "implement_review":
        state["review_round"] = int(state.get("review_round", 0)) + 1
        if state["review_round"] > int(state.get("max_review_rounds", 5)):
            block(state, "max-review-rounds-exceeded")
            return persist_and_print(root, feature, state, 12)
        if outcome == "findings":
            state["return_after_implement"] = "implement_review"
            state["current_phase"] = "implement"
        elif outcome in {"approved", "completed"}:
            state["current_phase"] = "DONE"
            state["status"] = "DONE"
        else:
            print(json.dumps({"status": "BLOCKED", "reason": "invalid-review-outcome", "outcome": outcome}))
            return 9
    elif current == "implement" and state.get("return_after_implement"):
        if outcome != "completed":
            print(json.dumps({"status": "BLOCKED", "reason": "implement-must-complete-before-return", "outcome": outcome}))
            return 9
        state["current_phase"] = str(state.get("return_after_implement"))
        state["return_after_implement"] = None
    else:
        if outcome not in {"completed", "skipped"}:
            print(json.dumps({"status": "BLOCKED", "reason": "invalid-phase-outcome", "phase": current, "outcome": outcome}))
            return 9
        state["current_phase"] = next_phase(phases, current)
        if state["current_phase"] == "DONE":
            state["status"] = "DONE"
    return persist_and_print(root, feature, state)


def cmd_resume(args: argparse.Namespace) -> int:
    root = find_root(); feature = resolve_feature(root, args.feature_dir); state = load_state(root, feature)
    if state.get("status") == "BLOCKED" and args.unblock:
        state["status"] = "RUNNING"
        state.pop("blocked_reason", None)
        write_state(state_path(root, feature), state)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_abort(args: argparse.Namespace) -> int:
    root = find_root(); feature = resolve_feature(root, args.feature_dir); path = state_path(root, feature)
    existed = path.exists()
    if existed:
        path.unlink()
    print(json.dumps({"status": "ABORTED", "state_removed": existed, "spec_artifacts_preserved": True, "review_findings_preserved": True}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="powerpack-full-cycle")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start"); p.add_argument("--feature-dir"); p.add_argument("--mode", choices=["interactive", "auto"]); p.add_argument("--restart", action="store_true"); p.set_defaults(func=cmd_start)
    p = sub.add_parser("status"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_status)
    p = sub.add_parser("advance"); p.add_argument("--feature-dir"); p.add_argument("--phase", required=True, choices=PHASE_ORDER); p.add_argument("--outcome", required=True, choices=["completed", "skipped", "blocked", "needs-implementation", "converged", "findings", "approved"]); p.add_argument("--evidence"); p.set_defaults(func=cmd_advance)
    p = sub.add_parser("resume"); p.add_argument("--feature-dir"); p.add_argument("--unblock", action="store_true"); p.set_defaults(func=cmd_resume)
    p = sub.add_parser("abort"); p.add_argument("--feature-dir"); p.set_defaults(func=cmd_abort)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
