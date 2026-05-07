import pytest

from codepilot.guardrails.hitl import (
    AutoApproveGate,
    AutoRejectGate,
    DEFAULT_CONDITIONS,
    LargeCommit,
    MaxRetriesReached,
    NeedsApproval,
    PrToProtectedBranch,
    RaisingHitlGate,
    RemotePush,
    check_hitl_conditions,
)


# ── check_hitl_conditions ──────────────────────────────────────────────────────


class TestPrToProtectedBranch:
    @pytest.mark.parametrize("branch", ["main", "master", "release", "develop"])
    def test_protected_branches_trigger(self, branch: str) -> None:
        cond = check_hitl_conditions(
            operation="open_pr",
            context={"base_branch": branch},
            conditions=(PrToProtectedBranch(),),
        )
        assert cond is not None
        assert cond.name == "pr_to_protected_branch"

    @pytest.mark.parametrize("branch", ["feature/login", "fix/bug-42", "chore/update-deps"])
    def test_non_protected_branches_do_not_trigger(self, branch: str) -> None:
        cond = check_hitl_conditions(
            operation="open_pr",
            context={"base_branch": branch},
            conditions=(PrToProtectedBranch(),),
        )
        assert cond is None

    def test_wrong_operation_does_not_trigger(self) -> None:
        cond = check_hitl_conditions(
            operation="create_commit",
            context={"base_branch": "main"},
            conditions=(PrToProtectedBranch(),),
        )
        assert cond is None

    def test_custom_protected_set(self) -> None:
        cond = check_hitl_conditions(
            operation="open_pr",
            context={"base_branch": "production"},
            conditions=(PrToProtectedBranch(protected=frozenset({"production"})),),
        )
        assert cond is not None

    def test_missing_base_branch_does_not_trigger(self) -> None:
        cond = check_hitl_conditions(
            operation="open_pr",
            context={},
            conditions=(PrToProtectedBranch(),),
        )
        assert cond is None


class TestLargeCommit:
    @pytest.mark.parametrize("files_changed", [6, 7, 10, 100])
    def test_above_threshold_triggers(self, files_changed: int) -> None:
        cond = check_hitl_conditions(
            operation="create_commit",
            context={"files_changed": files_changed},
            conditions=(LargeCommit(threshold=5),),
        )
        assert cond is not None
        assert cond.name == "large_commit"

    @pytest.mark.parametrize("files_changed", [0, 1, 4, 5])
    def test_at_or_below_threshold_does_not_trigger(self, files_changed: int) -> None:
        cond = check_hitl_conditions(
            operation="create_commit",
            context={"files_changed": files_changed},
            conditions=(LargeCommit(threshold=5),),
        )
        assert cond is None

    def test_commit_operation_alias(self) -> None:
        cond = check_hitl_conditions(
            operation="commit",
            context={"files_changed": 6},
            conditions=(LargeCommit(threshold=5),),
        )
        assert cond is not None

    def test_wrong_operation_does_not_trigger(self) -> None:
        cond = check_hitl_conditions(
            operation="open_pr",
            context={"files_changed": 100},
            conditions=(LargeCommit(threshold=5),),
        )
        assert cond is None


class TestRemotePush:
    @pytest.mark.parametrize("operation", ["git_push", "push"])
    def test_push_operations_trigger(self, operation: str) -> None:
        cond = check_hitl_conditions(
            operation=operation,
            context={},
            conditions=(RemotePush(),),
        )
        assert cond is not None
        assert cond.name == "remote_push"

    @pytest.mark.parametrize("operation", ["create_commit", "open_pr", "read_file", "edit"])
    def test_non_push_operations_do_not_trigger(self, operation: str) -> None:
        cond = check_hitl_conditions(
            operation=operation,
            context={},
            conditions=(RemotePush(),),
        )
        assert cond is None


class TestMaxRetriesReached:
    @pytest.mark.parametrize("retry_count", [2, 3, 10])
    def test_at_or_above_max_triggers(self, retry_count: int) -> None:
        cond = check_hitl_conditions(
            operation="anything",
            context={"retry_count": retry_count},
            conditions=(MaxRetriesReached(max_retries=2),),
        )
        assert cond is not None
        assert cond.name == "max_retries_reached"

    @pytest.mark.parametrize("retry_count", [0, 1])
    def test_below_max_does_not_trigger(self, retry_count: int) -> None:
        cond = check_hitl_conditions(
            operation="anything",
            context={"retry_count": retry_count},
            conditions=(MaxRetriesReached(max_retries=2),),
        )
        assert cond is None

    def test_missing_retry_count_does_not_trigger(self) -> None:
        cond = check_hitl_conditions(
            operation="anything",
            context={},
            conditions=(MaxRetriesReached(max_retries=2),),
        )
        assert cond is None


class TestCheckHitlConditionsComposite:
    def test_first_matching_condition_returned(self) -> None:
        # PR to main AND large commit — first condition in tuple wins
        cond = check_hitl_conditions(
            operation="open_pr",
            context={"base_branch": "main", "files_changed": 10},
        )
        assert cond is not None
        assert cond.name == "pr_to_protected_branch"

    def test_no_condition_fires_returns_none(self) -> None:
        cond = check_hitl_conditions(
            operation="read_file",
            context={"files_changed": 1, "retry_count": 0},
        )
        assert cond is None

    def test_default_conditions_cover_all_four_scenarios(self) -> None:
        names = {c.name for c in DEFAULT_CONDITIONS}
        assert "pr_to_protected_branch" in names
        assert "large_commit" in names
        assert "remote_push" in names
        assert "max_retries_reached" in names

    def test_empty_conditions_always_returns_none(self) -> None:
        cond = check_hitl_conditions(
            operation="git_push",
            context={"base_branch": "main", "retry_count": 5},
            conditions=(),
        )
        assert cond is None


# ── Gate implementations ───────────────────────────────────────────────────────


class TestAutoApproveGate:
    async def test_always_returns_true(self) -> None:
        gate = AutoApproveGate()
        approved = await gate.request_approval(operation="git_push", context={})
        assert approved is True

    async def test_multiple_calls_always_approve(self) -> None:
        gate = AutoApproveGate()
        for op in ["git_push", "open_pr", "deploy"]:
            assert await gate.request_approval(operation=op, context={}) is True

    def test_needs_approval_uses_conditions(self) -> None:
        gate = AutoApproveGate()
        cond = gate.needs_approval(
            operation="open_pr", context={"base_branch": "main"}
        )
        assert cond is not None

    def test_needs_approval_no_match_returns_none(self) -> None:
        gate = AutoApproveGate()
        cond = gate.needs_approval(operation="read_file", context={})
        assert cond is None


class TestAutoRejectGate:
    async def test_always_returns_false(self) -> None:
        gate = AutoRejectGate()
        approved = await gate.request_approval(operation="git_push", context={})
        assert approved is False

    async def test_multiple_calls_always_reject(self) -> None:
        gate = AutoRejectGate()
        for op in ["git_push", "open_pr", "deploy"]:
            assert await gate.request_approval(operation=op, context={}) is False


class TestRaisingHitlGate:
    async def test_raises_needs_approval(self) -> None:
        gate = RaisingHitlGate()
        with pytest.raises(NeedsApproval) as exc_info:
            await gate.request_approval(operation="deploy", context={"env": "prod"})
        assert exc_info.value.operation == "deploy"
        assert exc_info.value.context == {"env": "prod"}

    async def test_exception_message_contains_operation(self) -> None:
        gate = RaisingHitlGate()
        with pytest.raises(NeedsApproval) as exc_info:
            await gate.request_approval(operation="wipe_db", context={})
        assert "wipe_db" in str(exc_info.value)

    def test_needs_approval_method_present(self) -> None:
        gate = RaisingHitlGate()
        cond = gate.needs_approval(operation="git_push", context={})
        assert cond is not None  # git_push triggers RemotePush


class TestNeedsApprovalException:
    def test_has_operation_attribute(self) -> None:
        exc = NeedsApproval("deploy", {"env": "prod"})
        assert exc.operation == "deploy"

    def test_has_context_attribute(self) -> None:
        exc = NeedsApproval("deploy", {"env": "prod"})
        assert exc.context == {"env": "prod"}

    def test_is_exception_subclass(self) -> None:
        exc = NeedsApproval("x", {})
        assert isinstance(exc, Exception)
