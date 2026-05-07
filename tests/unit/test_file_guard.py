import pytest

from codepilot.guardrails.base import Decision
from codepilot.guardrails.files import FileGuard, FileRule

_GUARD = FileGuard()

# ── Paths that must be blocked ─────────────────────────────────────────────────

_BLOCKED: list[tuple[str, str]] = [
    # .env variants
    ("dotenv_bare",        ".env"),
    ("dotenv_config",      "config.env"),
    ("dotenv_local",       ".env.local"),
    ("dotenv_production",  ".env.production"),
    ("dotenv_staging",     ".env.staging"),
    # TLS / PKI
    ("pem_bare",           "server.pem"),
    ("pem_nested",         "certs/server.pem"),
    ("key_bare",           "private.key"),
    ("key_nested",         "keys/server.key"),
    ("pfx_cert",           "cert.pfx"),
    ("p12_cert",           "identity.p12"),
    # Secrets
    ("secret_bare",        "api.secret"),
    ("secret_nested",      "config/token.secret"),
    ("credentials_bare",   "credentials"),
    ("credentials_json",   "credentials.json"),
    ("credentials_aws",    "aws_credentials.txt"),
    ("credentials_nested", "~/.aws/credentials"),
    # SSH keys
    ("id_rsa",             "id_rsa"),
    ("id_rsa_nested",      "~/.ssh/id_rsa"),
    ("id_ed25519",         "id_ed25519"),
    ("id_ed25519_nested",  "~/.ssh/id_ed25519"),
    ("id_dsa",             "id_dsa"),
    ("id_ecdsa",           "id_ecdsa"),
    # Credential stores
    ("netrc",              ".netrc"),
    ("netrc_home",         "/home/user/.netrc"),
    # Git config with auth
    ("git_config",         ".git/config"),
]

# ── Paths that must be allowed ─────────────────────────────────────────────────

_ALLOWED: list[tuple[str, str]] = [
    ("src_py",            "src/main.py"),
    ("test_py",           "tests/test_app.py"),
    ("requirements",      "requirements.txt"),
    ("readme",            "README.md"),
    ("pyproject",         "pyproject.toml"),
    ("env_txt",           "env.txt"),            # NOT a .env file
    ("config_py",         "src/config.py"),
    ("dockerfile",        "Dockerfile"),
    ("json_data",         "data/output.json"),
    ("yaml_config",       "config/settings.yaml"),
    ("lock_file",         "requirements.lock"),
    ("setup_py",          "setup.py"),
    ("git_log",           ".git/COMMIT_EDITMSG"),  # not config
]


@pytest.mark.parametrize("name,path", _BLOCKED)
def test_blocked_paths(name: str, path: str) -> None:
    result = _GUARD.validate_path(path)
    assert result.decision == Decision.BLOCK, (
        f"{name!r}: {path!r} should be BLOCK, got {result}"
    )


@pytest.mark.parametrize("name,path", _ALLOWED)
def test_allowed_paths(name: str, path: str) -> None:
    result = _GUARD.validate_path(path)
    assert result.decision == Decision.ALLOW, (
        f"{name!r}: {path!r} should be ALLOW, got {result}"
    )


class TestGlobEdgeCases:
    """Verify fnmatch semantics for tricky patterns."""

    def test_dotenv_star_matches_dotenv_bare(self) -> None:
        # *.env matches .env because * can match empty string
        assert _GUARD.validate_path(".env").is_blocked

    def test_dotenv_star_matches_nested_dotenv(self) -> None:
        # fnmatch * matches path separators
        assert _GUARD.validate_path("subdir/.env").is_blocked

    def test_dotenv_local_pattern_matches_env_local(self) -> None:
        assert _GUARD.validate_path(".env.local").is_blocked

    def test_dotenv_local_pattern_does_not_match_dotenv_alone(self) -> None:
        # .env does NOT match .env.* (no trailing dot + ext)
        # but *.env rule catches it — overall still blocked
        assert _GUARD.validate_path(".env").is_blocked

    def test_env_txt_is_not_blocked(self) -> None:
        # env.txt does not end with .env and doesn't start with .env.
        assert _GUARD.validate_path("env.txt").is_allowed

    def test_environment_py_is_not_blocked(self) -> None:
        assert _GUARD.validate_path("environment.py").is_allowed

    def test_pem_matches_nested_path(self) -> None:
        assert _GUARD.validate_path("certs/ca/root.pem").is_blocked

    def test_credentials_substring_match(self) -> None:
        # *credentials* catches strings containing "credentials"
        assert _GUARD.validate_path("my_credentials_backup.json").is_blocked

    def test_git_config_matched_by_full_path(self) -> None:
        assert _GUARD.validate_path(".git/config").is_blocked

    def test_git_commit_editmsg_allowed(self) -> None:
        # .git/COMMIT_EDITMSG does not match .git/config
        assert _GUARD.validate_path(".git/COMMIT_EDITMSG").is_allowed


class TestFromSkill:
    def test_skill_file_rules_added(self) -> None:
        from codepilot.skills.registry import SkillsRegistry

        skill = SkillsRegistry().load("bug_fix")
        guard = FileGuard.from_skill(skill)
        # bug_fix forbids .env files via FILE kind
        assert guard.validate_path(".env").is_blocked

    def test_custom_skill_adds_extra_rule(self) -> None:
        from codepilot.skills.base import (
            ForbiddenAction,
            ForbiddenKind,
            Skill,
            TaskType,
            WorkflowStep,
        )

        skill = Skill(
            name="custom",
            description="d",
            task_types=(TaskType.BUG_FIX,),
            instructions="i",
            workflow_steps=(WorkflowStep(id="a", title="A", instructions="i"),),
            forbidden_actions=(
                ForbiddenAction(
                    kind=ForbiddenKind.FILE,
                    pattern="*.terraform",
                    reason="infra files",
                ),
            ),
        )
        guard = FileGuard.from_skill(skill)
        assert guard.validate_path("main.terraform").is_blocked
        assert guard.validate_path("main.py").is_allowed


class TestExtraRules:
    def test_extra_rule_appended_after_builtins(self) -> None:
        extra = [FileRule("block_md", "*.md", Decision.BLOCK, "test")]
        guard = FileGuard(extra_rules=extra)
        assert guard.validate_path("README.md").is_blocked
        # Built-in still works
        assert guard.validate_path(".env").is_blocked

    def test_rule_reason_returned(self) -> None:
        result = _GUARD.validate_path(".env")
        assert result.reason != ""
        assert result.rule != ""
