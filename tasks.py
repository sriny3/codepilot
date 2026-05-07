"""Cross-platform task runner. Use when `make` is unavailable (Windows default).

Usage:
    python tasks.py <task>
"""
from __future__ import annotations

import subprocess
import sys

TASKS = {
    "install":     [sys.executable, "-m", "pip", "install", "-e", "."],
    "install-dev": [sys.executable, "-m", "pip", "install", "-e", ".[dev]"],
    "test":        [sys.executable, "-m", "pytest"],
    "test-unit":   [sys.executable, "-m", "pytest", "tests/unit"],
    "test-cov":    [sys.executable, "-m", "pytest", "--cov=codepilot",
                    "--cov-report=term-missing", "--cov-fail-under=85"],
    "lint":        [sys.executable, "-m", "ruff", "check", "codepilot", "tests"],
    "format":      [sys.executable, "-m", "ruff", "format", "codepilot", "tests"],
    "type":        [sys.executable, "-m", "mypy", "codepilot"],
    "run":         [sys.executable, "-m", "codepilot", "run"],
    "doctor":      [sys.executable, "-m", "codepilot", "doctor"],
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print("tasks: " + ", ".join(TASKS))
        return 1
    return subprocess.call(TASKS[sys.argv[1]])


if __name__ == "__main__":
    raise SystemExit(main())
