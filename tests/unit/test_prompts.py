import pytest

from codepilot.github_io.prompts import (
    OP_CREATE_BRANCH,
    OP_OPEN_PR_BASE,
    DefaultBranchSelector,
    FixedSelector,
    InteractiveSelector,
    resolve_base,
)


class TestFixedSelector:
    def test_returns_configured(self) -> None:
        s = FixedSelector("develop")
        assert s.select(operation=OP_CREATE_BRANCH,
                        candidates=["main", "develop"], default="main") == "develop"

    def test_unknown_branch_raises(self) -> None:
        s = FixedSelector("missing")
        with pytest.raises(ValueError, match="not in repo branches"):
            s.select(operation=OP_CREATE_BRANCH,
                     candidates=["main", "develop"], default="main")

    def test_empty_candidates_skips_validation(self) -> None:
        # When repo branch listing is unavailable, fall back to trusting the caller.
        s = FixedSelector("custom")
        assert s.select(operation=OP_CREATE_BRANCH,
                        candidates=[], default=None) == "custom"


class TestDefaultBranchSelector:
    def test_returns_default(self) -> None:
        s = DefaultBranchSelector()
        assert s.select(operation=OP_CREATE_BRANCH,
                        candidates=["main"], default="main") == "main"

    def test_no_default_raises(self) -> None:
        s = DefaultBranchSelector()
        with pytest.raises(ValueError, match="no default branch"):
            s.select(operation=OP_CREATE_BRANCH, candidates=["main"], default=None)


class _FakeIO:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.writes: list[str] = []

    def read(self, prompt: str) -> str:
        self.writes.append(f"PROMPT:{prompt}")
        return self.inputs.pop(0)

    def write(self, s: str) -> None:
        self.writes.append(s)


class TestInteractiveSelector:
    def test_default_on_empty_input(self) -> None:
        io = _FakeIO([""])
        s = InteractiveSelector(reader=io.read, writer=io.write)
        chosen = s.select(operation=OP_CREATE_BRANCH,
                          candidates=["main", "develop"], default="main")
        assert chosen == "main"

    def test_numeric_choice(self) -> None:
        io = _FakeIO(["2"])
        s = InteractiveSelector(reader=io.read, writer=io.write)
        chosen = s.select(operation=OP_OPEN_PR_BASE,
                          candidates=["main", "develop", "release"], default="main")
        assert chosen == "develop"

    def test_branch_name_choice(self) -> None:
        io = _FakeIO(["release"])
        s = InteractiveSelector(reader=io.read, writer=io.write)
        chosen = s.select(operation=OP_OPEN_PR_BASE,
                          candidates=["main", "release"], default="main")
        assert chosen == "release"

    def test_re_prompts_on_invalid_then_valid(self) -> None:
        io = _FakeIO(["xyz", "9", "1"])
        s = InteractiveSelector(reader=io.read, writer=io.write)
        chosen = s.select(operation=OP_CREATE_BRANCH,
                          candidates=["main", "develop"], default="main")
        assert chosen == "main"
        assert any("unknown branch" in w for w in io.writes)
        assert any("out of range" in w for w in io.writes)

    def test_prompt_label_differs_per_operation(self) -> None:
        io_a = _FakeIO([""])
        InteractiveSelector(reader=io_a.read, writer=io_a.write).select(
            operation=OP_CREATE_BRANCH, candidates=["main"], default="main",
        )
        io_b = _FakeIO([""])
        InteractiveSelector(reader=io_b.read, writer=io_b.write).select(
            operation=OP_OPEN_PR_BASE, candidates=["main"], default="main",
        )
        assert any("BASE" in w for w in io_a.writes)
        assert any("TARGET" in w for w in io_b.writes)

    def test_no_candidates_raises(self) -> None:
        io = _FakeIO([])
        s = InteractiveSelector(reader=io.read, writer=io.write)
        with pytest.raises(ValueError, match="no candidate"):
            s.select(operation=OP_CREATE_BRANCH, candidates=[], default=None)


class TestResolveBase:
    def test_logs_decision(self) -> None:
        s = FixedSelector("develop")
        chosen = resolve_base(
            s, operation=OP_CREATE_BRANCH,
            candidates=["main", "develop"], default="main",
        )
        assert chosen == "develop"

    def test_selector_returning_unknown_raises(self) -> None:
        class Liar:
            def select(self, **kw):  # type: ignore[no-untyped-def]
                return "ghost"

        with pytest.raises(ValueError, match="not among candidates"):
            resolve_base(
                Liar(), operation=OP_OPEN_PR_BASE,
                candidates=["main", "develop"], default="main",
            )
