"""LocalSandbox — ephemeral working directory for agent execution.

All file and command operations are confined to a single root directory.
Paths escaping the root raise SandboxEscapeError; blocked shell commands
raise PermissionError before execution begins.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from codepilot.observability import get_logger
from codepilot.observability.events import Event
from codepilot.observability.redaction import redact_cmd

if TYPE_CHECKING:
    from codepilot.guardrails.shell import ShellGuard
    from codepilot.observability.audit import AuditLog

_log = get_logger("sandbox")


# ── Exceptions ─────────────────────────────────────────────────────────────────


class SandboxEscapeError(PermissionError):
    """Raised when a path resolves to a location outside the sandbox root."""

    def __init__(self, path: Path, root: Path) -> None:
        super().__init__(f"path {str(path)!r} escapes sandbox root {str(root)!r}")
        self.path = path
        self.root = root


class ExecuteTimeout(TimeoutError):
    """Raised when a sandbox command exceeds its wall-clock timeout."""

    def __init__(self, cmd: str, timeout: float) -> None:
        super().__init__(f"command timed out after {timeout}s: {cmd!r}")
        self.cmd = cmd
        self.timeout = timeout


# ── Result ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecuteResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int

    @property
    def success(self) -> bool:
        return self.exit_code == 0


# ── Sandbox ────────────────────────────────────────────────────────────────────


class LocalSandbox:
    """All operations confined to `root`.

    - `copy_subset` stages specific source files.
    - `execute` runs shell commands with timeout + guardrail pre-check.
    - `read_file` / `write_file` are path-safe I/O helpers.
    - `list_files` enumerates sandbox contents.
    """

    def __init__(
        self,
        root: Path,
        *,
        shell_guard: "ShellGuard | None" = None,
        audit: "AuditLog | None" = None,
        agent: str = "sandbox",
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._shell_guard = shell_guard
        self._audit = audit
        self._agent = agent

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        return self._root

    # ── Path safety ───────────────────────────────────────────────────────────

    def _safe_path(self, path: str | Path) -> Path:
        """Resolve `path` within the sandbox; raise SandboxEscapeError if outside.

        Accepts both relative paths (joined with root) and absolute paths
        (must already be inside root). Symlinks are resolved, so a symlink
        pointing outside the sandbox is also caught.
        """
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self._root / p).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise SandboxEscapeError(resolved, self._root) from None
        return resolved

    # ── File staging ──────────────────────────────────────────────────────────

    def copy_subset(
        self,
        source_root: Path,
        files: Sequence[str | Path],
    ) -> None:
        """Copy specific files from `source_root` into the sandbox, preserving structure.

        Files listed in `files` are relative to `source_root`. Missing source
        files are skipped silently (the caller controls what exists).
        """
        source_root = source_root.resolve()
        copied = 0
        for rel in files:
            src = source_root / rel
            if not src.exists():
                continue
            dst = self._safe_path(rel)
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            copied += 1
        _log.debug("sandbox.copy_subset", copied=copied, root=str(self._root))

    # ── Command execution ─────────────────────────────────────────────────────

    def execute(
        self,
        cmd: str,
        *,
        timeout: float = 30.0,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecuteResult:
        """Run `cmd` in a subprocess confined to the sandbox.

        Pre-checks:
        - Shell guardrail: BLOCK → PermissionError; HITL → PermissionError with
          instructions to call the HITL gate before execute().
        - `cwd` must be within sandbox root (path-safe check).

        Emits `sandbox.execute` structlog event with redacted command.
        """
        from codepilot.guardrails.base import Decision
        from codepilot.guardrails.shell import ShellGuard as _DefaultGuard

        guard = self._shell_guard if self._shell_guard is not None else _DefaultGuard()
        guard_result = guard.validate(cmd)

        if guard_result.decision is Decision.BLOCK:
            _log.error(
                "sandbox.blocked",
                rule=guard_result.rule,
                reason=guard_result.reason,
                cmd=cmd[:80],
                agent=self._agent,
            )
            if self._audit is not None:
                self._audit.write(
                    Event.GUARDRAIL_BLOCK,
                    {
                        "rule": guard_result.rule,
                        "operation": redact_cmd(cmd),
                        "agent": self._agent,
                    },
                    actor=self._agent,
                )
            raise PermissionError(
                f"command blocked by guardrail {guard_result.rule!r}: {guard_result.reason}"
            )

        if guard_result.decision is Decision.HITL:
            raise PermissionError(
                f"command requires HITL approval (rule {guard_result.rule!r}: "
                f"{guard_result.reason}). Obtain approval before calling execute()."
            )

        cwd_path = self._safe_path(cwd) if cwd is not None else self._root

        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd_path),
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise ExecuteTimeout(cmd, timeout) from None

        duration_ms = int((time.monotonic() - started) * 1000)

        _log.info(
            Event.SANDBOX_EXECUTE,
            cmd_redacted=redact_cmd(cmd),
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            stdout_len=len(proc.stdout),
            stderr_len=len(proc.stderr),
            agent=self._agent,
        )

        return ExecuteResult(
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
        )

    # ── File I/O ──────────────────────────────────────────────────────────────

    def read_file(self, relative: str | Path) -> str:
        """Read a text file from within the sandbox."""
        return self._safe_path(relative).read_text(encoding="utf-8")

    def write_file(self, relative: str | Path, content: str) -> None:
        """Write a text file within the sandbox, creating intermediate dirs."""
        path = self._safe_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_file(self, relative: str | Path) -> None:
        """Remove a file from the sandbox (no-op if absent)."""
        self._safe_path(relative).unlink(missing_ok=True)

    def exists(self, relative: str | Path) -> bool:
        """Return True if `relative` exists within the sandbox."""
        try:
            return self._safe_path(relative).exists()
        except SandboxEscapeError:
            return False

    def list_files(self, pattern: str = "**/*") -> list[Path]:
        """Return paths of all files matching `pattern`, relative to sandbox root."""
        return sorted(
            p.relative_to(self._root)
            for p in self._root.glob(pattern)
            if p.is_file()
        )
