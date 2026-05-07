"""Reconstruct a full task timeline from logs by trace_id.

Usage:
    python -m codepilot.observability.trace_cli <trace_id> [--log-dir ./logs]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return out


def collect(log_dir: Path, trace_id: str) -> list[dict[str, Any]]:
    """Join main log + audit log entries for this trace_id, sorted by ts."""
    rows: list[dict[str, Any]] = []
    for p in log_dir.glob("*.jsonl"):
        for entry in _iter_jsonl(p):
            if entry.get("trace_id") == trace_id:
                entry["_source"] = p.name
                rows.append(entry)
    for r in rows:
        if "ts" not in r and "timestamp" in r:
            r["ts"] = r["timestamp"]
    rows.sort(key=lambda r: r.get("ts", ""))
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no events found for trace_id"
    lines = []
    for r in rows:
        ts = r.get("ts", "?")
        ev = r.get("event") or r.get("event_name") or r.get("level", "log")
        agent = r.get("agent") or r.get("actor") or "-"
        state = r.get("state") or "-"
        msg = r.get("event_message") or r.get("message") or ""
        lines.append(f"{ts}  [{state:>14}]  {agent:>14}  {ev}  {msg}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="codepilot.trace")
    p.add_argument("trace_id")
    p.add_argument("--log-dir", default="./logs")
    p.add_argument("--json", action="store_true", help="emit raw JSON array")
    args = p.parse_args(argv)

    rows = collect(Path(args.log_dir), args.trace_id)
    if args.json:
        sys.stdout.write(json.dumps(rows, indent=2, sort_keys=True))
        return 0 if rows else 1
    sys.stdout.write(render(rows) + "\n")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
