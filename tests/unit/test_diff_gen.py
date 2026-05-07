"""Diff generation and application tests."""
from pathlib import Path

import pytest

from codepilot.sandbox.diff import (
    apply_diff,
    generate_diff,
    generate_diff_from_content,
    generate_sandbox_diff,
)
from codepilot.sandbox.local import LocalSandbox


# ── generate_diff_from_content ─────────────────────────────────────────────────


class TestGenerateDiffFromContent:
    def test_identical_content_returns_empty(self) -> None:
        diff = generate_diff_from_content("hello\n", "hello\n")
        assert diff == ""

    def test_diff_has_unified_header(self) -> None:
        diff = generate_diff_from_content("a\n", "b\n", label_a="a/f", label_b="b/f")
        assert "--- a/f" in diff
        assert "+++ b/f" in diff

    def test_diff_has_hunk_header(self) -> None:
        diff = generate_diff_from_content("a\n", "b\n")
        assert "@@" in diff

    def test_added_line_marked_with_plus(self) -> None:
        diff = generate_diff_from_content("line1\n", "line1\nline2\n")
        assert "+line2" in diff

    def test_removed_line_marked_with_minus(self) -> None:
        diff = generate_diff_from_content("line1\nline2\n", "line1\n")
        assert "-line2" in diff

    def test_context_lines_shown(self) -> None:
        original = "ctx1\nctx2\nchange_me\nctx3\nctx4\n"
        modified = "ctx1\nctx2\nchanged\nctx3\nctx4\n"
        diff = generate_diff_from_content(original, modified, context_lines=2)
        assert "ctx2" in diff  # context before
        assert "ctx3" in diff  # context after

    def test_labels_appear_in_output(self) -> None:
        diff = generate_diff_from_content("x\n", "y\n", label_a="original", label_b="revised")
        assert "original" in diff
        assert "revised" in diff

    def test_empty_original_produces_pure_addition(self) -> None:
        diff = generate_diff_from_content("", "new content\n")
        assert "+new content" in diff

    def test_empty_modified_produces_pure_deletion(self) -> None:
        diff = generate_diff_from_content("old content\n", "")
        assert "-old content" in diff

    def test_multiline_change(self) -> None:
        original = "".join(f"line{i}\n" for i in range(10))
        modified = original.replace("line5\n", "replaced\n")
        diff = generate_diff_from_content(original, modified)
        assert "-line5" in diff
        assert "+replaced" in diff


# ── generate_diff (file-based) ─────────────────────────────────────────────────


class TestGenerateDiff:
    def test_identical_files_no_diff(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same\n")
        b.write_text("same\n")
        assert generate_diff(a, b) == ""

    def test_diff_matches_from_content_variant(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("alpha\n")
        b.write_text("beta\n")
        from_files = generate_diff(a, b, label_a="a/a.txt", label_b="b/b.txt")
        from_content = generate_diff_from_content(
            "alpha\n", "beta\n", label_a="a/a.txt", label_b="b/b.txt"
        )
        assert from_files == from_content

    def test_default_labels_use_filename(self, tmp_path: Path) -> None:
        a = tmp_path / "module.py"
        b = tmp_path / "module.py"
        a.write_text("old\n")
        # Use same name, different content via content variant
        diff = generate_diff(a, b)
        # Identical → empty
        assert diff == ""

    def test_nonexistent_original_treated_as_empty(self, tmp_path: Path) -> None:
        orig = tmp_path / "does_not_exist.txt"
        mod = tmp_path / "new.txt"
        mod.write_text("new file\n")
        diff = generate_diff(orig, mod)
        assert "+new file" in diff


# ── generate_sandbox_diff ──────────────────────────────────────────────────────


class TestGenerateSandboxDiff:
    @pytest.fixture()
    def source(self, tmp_path: Path) -> Path:
        root = tmp_path / "source"
        root.mkdir()
        (root / "a.py").write_text("original\n")
        (root / "b.py").write_text("unchanged\n")
        return root

    @pytest.fixture()
    def sandbox(self, tmp_path: Path, source: Path) -> LocalSandbox:
        sb = LocalSandbox(tmp_path / "sandbox")
        sb.copy_subset(source, ["a.py", "b.py"])
        return sb

    def test_modified_file_appears_in_diff(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.write_file("a.py", "modified\n")
        diff = generate_sandbox_diff(sandbox, source, ["a.py", "b.py"])
        assert "-original" in diff
        assert "+modified" in diff

    def test_unchanged_file_absent_from_diff(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.write_file("a.py", "modified\n")
        diff = generate_sandbox_diff(sandbox, source, ["a.py", "b.py"])
        # b.py unchanged — not in diff
        assert "b.py" not in diff

    def test_no_changes_returns_empty(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        diff = generate_sandbox_diff(sandbox, source, ["a.py", "b.py"])
        assert diff == ""

    def test_new_file_appears_as_addition(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.write_file("new.py", "brand new\n")
        diff = generate_sandbox_diff(sandbox, source, ["new.py"])
        assert "+brand new" in diff

    def test_diff_structure_matches_git_shape(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.write_file("a.py", "new content\n")
        diff = generate_sandbox_diff(sandbox, source, ["a.py"])
        # Must have --- / +++ headers and at least one @@ hunk
        assert "---" in diff
        assert "+++" in diff
        assert "@@" in diff


# ── apply_diff ─────────────────────────────────────────────────────────────────


class TestApplyDiff:
    def test_apply_addition(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("line1\nline2\n")
        diff = generate_diff_from_content(
            "line1\nline2\n",
            "line1\nINSERTED\nline2\n",
            label_a="a/f.txt",
            label_b="b/f.txt",
        )
        apply_diff(target, diff)
        assert target.read_text() == "line1\nINSERTED\nline2\n"

    def test_apply_deletion(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("keep\ndelete_me\nkeep2\n")
        diff = generate_diff_from_content(
            "keep\ndelete_me\nkeep2\n",
            "keep\nkeep2\n",
        )
        apply_diff(target, diff)
        assert target.read_text() == "keep\nkeep2\n"

    def test_apply_replacement(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("hello\n")
        diff = generate_diff_from_content("hello\n", "world\n")
        apply_diff(target, diff)
        assert target.read_text() == "world\n"

    def test_apply_empty_diff_is_noop(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("unchanged\n")
        apply_diff(target, "")
        assert target.read_text() == "unchanged\n"

    def test_round_trip(self, tmp_path: Path) -> None:
        original = "alpha\nbeta\ngamma\ndelta\n"
        modified = "alpha\nbeta\nGAMMA\ndelta\n"
        target = tmp_path / "f.txt"
        target.write_text(original)
        diff = generate_diff_from_content(original, modified)
        apply_diff(target, diff)
        assert target.read_text() == modified

    def test_apply_multi_hunk_diff(self, tmp_path: Path) -> None:
        lines = [f"line{i}\n" for i in range(20)]
        original = "".join(lines)
        changed = original.replace("line2\n", "CHANGED2\n").replace("line15\n", "CHANGED15\n")
        target = tmp_path / "f.txt"
        target.write_text(original)
        diff = generate_diff_from_content(original, changed)
        apply_diff(target, diff)
        assert target.read_text() == changed
