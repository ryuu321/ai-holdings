"""
ventures/shared/metrics.py — 統一メトリクスストレージ
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def save_state(state_path: Path, state: dict):
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def record_performance(state: dict, metrics: dict) -> dict:
    entry = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **metrics}
    state.setdefault("performance_history", []).append(entry)
    state["performance_history"] = state["performance_history"][-90:]
    return state


def apply_optimization(state: dict, opt_result: dict) -> dict:
    if opt_result.get("updated_params"):
        state["params"] = opt_result["updated_params"]
    state.setdefault("learnings", [])
    insight = opt_result.get("insight", "")
    action = opt_result.get("action", "")
    if insight:
        state["learnings"].append({
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "insight": insight,
            "action": action,
        })
        state["learnings"] = state["learnings"][-20:]
    state["last_optimized"] = datetime.now(timezone.utc).isoformat()
    return state
