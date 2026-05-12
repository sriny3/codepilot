import argparse
import os
import re
import sys
from typing import Any


_STATE_ORDER = ["TRIAGED", "EXPLORING", "IMPLEMENTING", "TESTING", "PR_OPENED", "DONE"]

_TOOL_STATE: dict[str, str] = {
    "classify_issue": "TRIAGED",
    "query_lessons": "TRIAGED",
    "build_repo_map": "EXPLORING",
    "retrieve_relevant_files": "EXPLORING",
    "load_cached_repo_map": "EXPLORING",
    "cache_repo_map": "EXPLORING",
    "run_tests": "TESTING",
    "parse_test_output": "TESTING",
    "create_branch": "PR_OPENED",
    "commit_files": "PR_OPENED",
    "open_pr": "PR_OPENED",
    "add_lesson": "DONE",
}

_SUBAGENT_STATE: dict[str, str] = {
    "repo_explorer": "EXPLORING",
    "coder": "IMPLEMENTING",
    "test_agent": "TESTING",
    "pr_agent": "PR_OPENED",
}


def _advance(current: str, candidate: str) -> str:
    try:
        if _STATE_ORDER.index(candidate) > _STATE_ORDER.index(current):
            return candidate
    except ValueError:
        pass
    return current


def _infer_state(messages: list[Any]) -> tuple[str, str, list[str]]:
    """Return (state, skill, todos) from LangGraph message list."""
    state, skill, todos = "TRIAGED", "", []
    for msg in messages:
        tool_name = getattr(msg, "name", None)
        if tool_name:
            state = _advance(state, _TOOL_STATE.get(tool_name, state))
            if tool_name == "classify_issue":
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    skill = content.strip()
            if tool_name == "write_todos":
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    # DeepAgents returns Python repr: [{'content': 'text', ...}, ...]
                    extracted = re.findall(r"['\"]content['\"]\s*:\s*['\"]([^'\"]+)['\"]", content)
                    if extracted:
                        todos = extracted
                    else:
                        # Fallback: newline-separated plain text
                        todos = [t.lstrip("- ").strip() for t in content.splitlines() if t.strip()]
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            state = _advance(state, _TOOL_STATE.get(name, state))
            if name == "task":
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                # DeepAgents uses 'subagent_type' as the key for the agent name
                sub = (args.get("subagent_type") or args.get("agent_name")
                       or args.get("name", ""))
                state = _advance(state, _SUBAGENT_STATE.get(sub, state))
    return state, skill, todos


def _summarize_call(name: str, args: dict) -> str:
    if name == "task":
        sub = args.get("subagent_type") or args.get("agent_name") or args.get("name", "?")
        return f"task → {sub}"
    if name == "write_todos":
        todos = args.get("todos", [])
        n = len(todos) if isinstance(todos, list) else "?"
        done = sum(1 for t in (todos if isinstance(todos, list) else [])
                   if isinstance(t, dict) and t.get("status") == "completed")
        return f"write_todos({done}/{n} done)"
    if name == "get_issue":
        return f"get_issue(#{args.get('issue_number', '?')})"
    if name in ("read_file", "ls", "edit_file"):
        path = args.get("file_path") or args.get("path", "")
        return f"{name}({path})" if path else name
    if name in ("load_cached_repo_map", "build_repo_map", "cache_repo_map"):
        root = args.get("root_path") or args.get("repo_root", ".")
        return f"{name}(root={root!r})"
    if name == "retrieve_relevant_files":
        root = args.get("repo_root") or args.get("root_path", ".")
        return f"retrieve_relevant_files(root={root!r})"
    if name == "classify_issue":
        title = str(args.get("title", ""))[:40]
        return f"classify_issue({title!r})"
    if name in ("query_lessons", "add_lesson"):
        val = str(args.get("task_description") or args.get("lesson", ""))[:40]
        return f"{name}({val!r})"
    if name in ("create_branch", "commit_files", "open_pr", "list_open_issues"):
        return name
    if args:
        k, v = next(iter(args.items()))
        return f"{name}({str(v)[:40]!r})"
    return name


def _summarize_result(name: str, content: str) -> str:
    if not content.strip():
        return "(empty)"
    if content.lstrip().startswith("{") and '"error"' in content:
        try:
            import json as _json
            err = str(_json.loads(content).get("error", ""))
            for line in err.splitlines():
                line = line.strip()
                if line and not line.startswith("1 validation"):
                    return f"error: {line[:100]}"
            return f"error: {err.splitlines()[-1][:100]}" if err else "error (unknown)"
        except Exception:
            pass
    if name == "write_todos":
        n = content.count("'content'") + content.count('"content"')
        return f"{n} todos saved"
    if name in ("load_cached_repo_map", "build_repo_map"):
        lines = [l for l in content.splitlines() if l.strip()]
        first = lines[0][:60] if lines else ""
        return f"{first} … ({len(lines)} entries)"
    if name == "retrieve_relevant_files":
        lines = [l for l in content.strip().splitlines() if l.strip()]
        return f"{len(lines)} relevant files"
    if name == "task":
        clean = content.replace("\n", " ").strip()
        idx = clean.find(". ")
        return clean[:idx + 1] if 0 < idx < 120 else clean[:120]
    if name == "classify_issue":
        return content.strip()[:60]
    return content.replace("\n", " ")[:100]


def _msg_log_line(msg: Any) -> str | None:
    """Return a human-readable log line for one LangGraph message, or None to skip."""
    tool_name = getattr(msg, "name", None)
    tool_calls = getattr(msg, "tool_calls", None) or []
    content = getattr(msg, "content", "")

    if tool_calls:
        parts = [_summarize_call(
            tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
            tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
        ) for tc in tool_calls]
        return f"[→] {' | '.join(parts)}"

    if tool_name and isinstance(content, str):
        return f"[{tool_name}] {_summarize_result(tool_name, content)}"

    if isinstance(content, str) and content.strip() and not tool_calls:
        snippet = content[:80].replace("\n", " ")
        return f"[Orchestrator] {snippet}"

    return None


def _msg_raw_line(msg: Any) -> str | None:
    """Full verbose log line for file output (no truncation)."""
    tool_name = getattr(msg, "name", None)
    tool_calls = getattr(msg, "tool_calls", None) or []
    content = getattr(msg, "content", "")

    if tool_calls:
        parts = []
        for tc in tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            parts.append(f"{name}({arg_str})")
        return f"[Orchestrator] → {' | '.join(parts)}"

    if tool_name and isinstance(content, str):
        return f"[{tool_name}] {content}"

    if isinstance(content, str) and content.strip() and not tool_calls:
        return f"[Orchestrator] {content}"

    return None


from codepilot import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codepilot",
        description="Multi-agent autonomous coding platform.",
    )
    parser.add_argument("--version", action="version", version=f"codepilot {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start the orchestrator + TUI.")
    sub.add_parser("doctor", help="Validate environment and dependencies.")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "doctor":
        from codepilot.config.settings import Settings

        try:
            s = Settings()  # type: ignore[call-arg]
        except Exception as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 1
        dump = s.model_dump()
        for k in ("github_token", "github_app_private_key", "openai_api_key",
                  "anthropic_api_key", "qdrant_api_key", "langsmith_api_key"):
            if dump.get(k) is not None:
                dump[k] = "***SET***"
        for k, v in dump.items():
            print(f"{k}={v}")
        return 0

    if args.command == "run":
        import asyncio
        import threading

        from codepilot.config.settings import get_settings
        from codepilot.observability import bind_task, bind_span, configure_langsmith, configure_logging, get_logger

        try:
            cfg = get_settings()
        except Exception as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 1

        configure_logging(level=cfg.log_level, log_dir=cfg.log_dir, log_format=cfg.log_format, tui_mode=True)

        # Export secrets to os.environ so deepagents/LangChain can find them.
        if cfg.anthropic_api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", cfg.anthropic_api_key.get_secret_value())
        if cfg.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", cfg.openai_api_key.get_secret_value())
        if cfg.groq_api_key:
            os.environ.setdefault("GROQ_API_KEY", cfg.groq_api_key.get_secret_value())
        if cfg.github_token:
            os.environ.setdefault("GITHUB_TOKEN", cfg.github_token.get_secret_value())
        # GitHubAPIWrapper validator always requires GITHUB_APP_ID even when using token auth
        os.environ.setdefault("GITHUB_APP_ID", cfg.github_app_id)
        if not cfg.github_token and cfg.github_app_private_key:
            os.environ.setdefault("GITHUB_APP_PRIVATE_KEY", cfg.github_app_private_key.get_secret_value())
        if cfg.langsmith_api_key:
            os.environ.setdefault("LANGCHAIN_API_KEY", cfg.langsmith_api_key.get_secret_value())
            os.environ.setdefault("LANGSMITH_API_KEY", cfg.langsmith_api_key.get_secret_value())
            os.environ.setdefault("LANGCHAIN_PROJECT", cfg.langsmith_project)

        if cfg.langsmith_api_key:
            configure_langsmith(
                cfg.langsmith_api_key.get_secret_value(),
                project=cfg.langsmith_project,
            )

        from codepilot.orchestrator.factory import PipelineConfig
        from codepilot.orchestrator.deep_agent import build_orchestrator
        from codepilot.tui.app import CodePilotApp
        from codepilot.tui.hitl import HITLCoordinator

        pipeline_cfg = PipelineConfig.from_settings(cfg)
        app = CodePilotApp(max_log_lines=cfg.tui_max_log_lines, log_dir=cfg.log_dir)
        hitl = HITLCoordinator(app)
        app._hitl = hitl

        orchestrator = build_orchestrator(pipeline_cfg)

        # Build IssuePoller if a token is available for PyGithub.
        poller = None
        if cfg.github_token:
            try:
                from codepilot.github_io.client import build_default_client
                from codepilot.github_io.poller import IssuePoller

                gh_client = build_default_client(
                    cfg.github_token.get_secret_value(),
                    cfg.repo_full_name,
                )
                poller = IssuePoller(gh_client)
            except Exception as exc:
                print(f"github client error (polling disabled): {exc}", file=sys.stderr)

        stop_bg = asyncio.Event()
        app_ready = threading.Event()
        app._on_ready = app_ready.set  # type: ignore[attr-defined]

        async def _run_orchestrator(issue_id: int, title: str, body: str) -> None:
            from pathlib import Path as _Path
            from codepilot.github_io.workspace import cleanup as _ws_cleanup
            from codepilot.github_io.workspace import clone_or_pull as _clone

            app.post_upsert_issue(issue_id, title, "TRIAGED")
            app.post_update_active_task(issue_id, title, "TRIAGED", "", 0, [])
            app.post_append_log(f"[Orchestrator] Picked up #{issue_id}: {title!r}")

            _log = get_logger("orchestrator")
            workspace: "_Path | None" = None
            with bind_task(issue_id, repo=cfg.repo_full_name):
                with bind_span("orchestrator.run"):
                    _log.info("orchestrator.start", issue_id=issue_id, title=title)
                    try:
                        if cfg.github_token:
                            base_dir = _Path(".codepilot") / "workspace"
                            workspace = await asyncio.to_thread(
                                _clone,
                                cfg.repo_full_name,
                                cfg.github_token.get_secret_value(),
                                base_dir,
                            )
                            _log.info("workspace.cloned", path=str(workspace))
                            app.post_append_log(f"[Workspace] Cloned {cfg.repo_full_name} → {workspace}")
                        else:
                            raise RuntimeError("GITHUB_TOKEN not set — cannot clone target repo")

                        # Use a relative path with forward slashes so LLM doesn't
                        # prepend "/" to Windows absolute paths like "C:\..." → "/C:/..."
                        workspace_str = str(workspace).replace("\\", "/")
                        task_content = (
                            f"Process GitHub issue #{issue_id}: {title}\n"
                            f"{body}\n"
                            f"Workspace: {workspace_str}"
                        )

                        import time as _time
                        from collections import deque as _deque
                        config = {"configurable": {"thread_id": str(issue_id)}}
                        retry = 0
                        last_state = "TRIAGED"
                        prev_msg_count = 0
                        # (subagent_name, dispatch_monotonic) — FIFO matches dispatch to result order
                        _pending_tasks: "_deque[tuple[str, float]]" = _deque()
                        _heartbeat: "list[threading.Timer]" = []  # mutable container for nonlocal-safe cancel

                        def _cancel_heartbeat() -> None:
                            if _heartbeat:
                                _heartbeat[0].cancel()
                                _heartbeat.clear()

                        def _schedule_heartbeat(sub_name: str, t0: float, interval: float = 10.0) -> None:
                            def _tick() -> None:
                                elapsed = _time.monotonic() - t0
                                msg = f"[{sub_name}] working… ({elapsed:.0f}s)"
                                app.post_append_log(msg)
                                app.post_heartbeat(msg)
                                _schedule_heartbeat(sub_name, t0, interval)
                            _cancel_heartbeat()
                            timer = threading.Timer(interval, _tick)
                            timer.daemon = True
                            timer.start()
                            _heartbeat.append(timer)

                        def _process_event(event: object) -> bool:
                            """Process one stream event. Returns True if an interrupt was hit."""
                            nonlocal prev_msg_count, retry, last_state
                            if not isinstance(event, dict):
                                return False
                            interrupts = event.get("__interrupt__")
                            if interrupts:
                                _cancel_heartbeat()
                                intr = interrupts[0] if isinstance(interrupts, list) else interrupts
                                op = str(intr.get("value", intr) if isinstance(intr, dict) else intr)
                                _log.info("hitl.interrupt", operation=op)
                                app.post_append_log(f"[HITL] Approval required: {op}")
                                approved = hitl.request_approval(op, intr if isinstance(intr, dict) else {"value": op})
                                if not approved:
                                    _log.info("hitl.rejected", operation=op)
                                    raise RuntimeError(f"HITL rejected: {op}")
                                _log.info("hitl.approved", operation=op)
                                app.post_append_log(f"[HITL] Approved: {op}")
                                return True
                            messages = event.get("messages", [])
                            for msg in messages[prev_msg_count:]:
                                for tc in getattr(msg, "tool_calls", None) or []:
                                    tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                                    if tc_name == "task":
                                        tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                                        sub = tc_args.get("subagent_type") or tc_args.get("agent_name") or tc_args.get("name", "?")
                                        t0 = _time.monotonic()
                                        _pending_tasks.append((sub, t0))
                                        _schedule_heartbeat(sub, t0)
                                tool_name = getattr(msg, "name", None)
                                if tool_name == "task":
                                    _cancel_heartbeat()
                                    sub_name, t0 = _pending_tasks.popleft() if _pending_tasks else ("subagent", _time.monotonic())
                                    elapsed = _time.monotonic() - t0
                                    summary = _summarize_result("task", getattr(msg, "content", ""))
                                    _log.info("subagent.done", subagent=sub_name, elapsed_s=round(elapsed, 1))
                                    app.post_heartbeat("")
                                    app.post_append_log(
                                        f"[{sub_name}] done ({elapsed:.0f}s) — {summary}",
                                        raw=_msg_raw_line(msg),
                                    )
                                else:
                                    line = _msg_log_line(msg)
                                    if line:
                                        app.post_append_log(line, raw=_msg_raw_line(msg))
                            prev_msg_count = len(messages)
                            state, skill, todos = _infer_state(messages)
                            if state == "TESTING" and last_state == "TESTING":
                                retry += 1
                            if state != last_state:
                                _log.info("state.transition", from_state=last_state, to_state=state)
                                last_state = state
                                app.post_upsert_issue(issue_id, title, state)
                                app.post_update_active_task(issue_id, title, state, skill, retry, todos)
                            return False

                        try:
                            stream_input: object = {"messages": [{"role": "user", "content": task_content}]}
                            while True:
                                interrupted = False
                                for event in orchestrator.stream(stream_input, config, stream_mode="values"):
                                    if _process_event(event):
                                        interrupted = True
                                        break
                                if not interrupted:
                                    break
                                # Resume graph after HITL approval (None = resume from checkpoint)
                                stream_input = None
                        except Exception as exc:
                            _cancel_heartbeat()
                            _log.error("orchestrator.error", error=str(exc))
                            app.post_upsert_issue(issue_id, title, "FAILED")
                            app.post_update_active_task(issue_id, title, "FAILED", "", retry, [])
                            app.post_append_log(f"[Orchestrator] ERROR #{issue_id}: {exc}")
                    except Exception as exc:
                        _log.error("orchestrator.error", error=str(exc))
                        app.post_upsert_issue(issue_id, title, "FAILED")
                        app.post_update_active_task(issue_id, title, "FAILED", "", retry, [])
                        app.post_append_log(f"[Orchestrator] ERROR #{issue_id}: {exc}")
                    finally:
                        if workspace is not None:
                            await asyncio.to_thread(_ws_cleanup, workspace)
                            _log.info("workspace.cleaned", path=str(workspace))
                            app.post_append_log(f"[Workspace] Cleaned up {workspace}")

        async def _pipeline_loop() -> None:
            app_ready.wait()
            # Drain manual tasks submitted via [i]
            async def _drain_manual() -> None:
                manual_id = 0
                while True:
                    try:
                        task_text = app._task_queue.get_nowait()
                        manual_id -= 1
                        await _run_orchestrator(manual_id, task_text, "")
                    except Exception:
                        break

            if poller is None:
                app.post_append_log("[Orchestrator] GitHub polling disabled — set GITHUB_TOKEN to enable. Use [i] for manual tasks.")
                while not stop_bg.is_set():
                    await _drain_manual()
                    await asyncio.sleep(1)
                return
            interval = cfg.poll_interval_min * 60.0
            async for issue in poller.stream(interval_sec=interval, stop=stop_bg):
                await _drain_manual()
                await _run_orchestrator(issue.number, issue.title, issue.body or "")

        def _bg_thread() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_pipeline_loop())
            except RuntimeError as exc:
                # Expected on quit mid-task: thread pool / app already shut down.
                if "not running" not in str(exc) and "cannot schedule" not in str(exc):
                    raise
            except Exception:
                pass
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()

        bg = threading.Thread(target=_bg_thread, daemon=True, name="codepilot-pipeline")
        bg.start()

        app.run()
        stop_bg.set()
        return 0

    print(f"command '{args.command}' not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
