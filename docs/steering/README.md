
# Steering Docs

One per phase. Each captures: goal, deliverables, exit criteria, **per-file description (what each source/test file does)**, FAQ (why-this-step), decisions log, risks.

## Required sections per doc

1. Header (status, owner, depends-on, unblocks)
2. Goal (one paragraph)
3. Deliverables table (artifact / path / purpose)
4. Exit criteria (checklist)
5. **Files** — `### Source` and `### Tests` subsections, one entry per file describing what it exports, key functions, how it interacts with siblings
6. Architecture / flow diagram if non-trivial
7. FAQ — every non-obvious choice gets a Q
8. Decisions log (table: # / decision / alternatives / rationale)
9. Risks / things to revisit

| Phase | Doc |
|---|---|
| 0 — Scaffold | [phase_00_scaffold.md](phase_00_scaffold.md) |
| 0.5 — Logging & Tracing | [phase_05_logging.md](phase_05_logging.md) |
| 1 — GitHub I/O | [phase_01_github_io.md](phase_01_github_io.md) |
| 2 — Memory | [phase_02_memory.md](phase_02_memory.md) |
| 3 — Skills | [phase_03_skills.md](phase_03_skills.md) |
| 4 — Guardrails | [phase_04_guardrails.md](phase_04_guardrails.md) |
| 5 — Sandbox | [phase_05_sandbox.md](phase_05_sandbox.md) |
| 6 — Repo Explorer | [phase_06_repo_explorer.md](phase_06_repo_explorer.md) |
| 7 — Coder | [phase_07_coder.md](phase_07_coder.md) |
| 8 — Test Agent | [phase_08_test_agent.md](phase_08_test_agent.md) |
| 9 — PR Agent | [phase_09_pr_agent.md](phase_09_pr_agent.md) |
| 10 — Orchestrator | [phase_10_orchestrator.md](phase_10_orchestrator.md) |
| 11 — TUI | [phase_11_tui.md](phase_11_tui.md) |
| 12 — E2E | [phase_12_e2e.md](phase_12_e2e.md) |
| 13 — Hardening | [phase_13_hardening.md](phase_13_hardening.md) |

Each doc must answer at minimum: **why this step now?**, **what changes after?**, **what could break?**
