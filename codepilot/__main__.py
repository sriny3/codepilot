import argparse
import sys

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
        for k in ("github_token", "openai_api_key", "anthropic_api_key",
                  "qdrant_api_key", "langsmith_api_key"):
            if dump.get(k) is not None:
                dump[k] = "***SET***"
        for k, v in dump.items():
            print(f"{k}={v}")
        return 0

    if args.command == "run":
        from codepilot.config.settings import get_settings
        from codepilot.observability import configure_langsmith, configure_logging

        try:
            cfg = get_settings()
        except Exception as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 1

        configure_logging(level=cfg.log_level, log_dir=cfg.log_dir, fmt=cfg.log_format)

        if cfg.langsmith_api_key:
            configure_langsmith(
                cfg.langsmith_api_key.get_secret_value(),
                project=cfg.langsmith_project,
            )

        from codepilot.tui.app import CodePilotApp

        CodePilotApp().run()
        return 0

    print(f"command '{args.command}' not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
