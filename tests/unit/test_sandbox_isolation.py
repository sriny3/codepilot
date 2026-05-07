"""Path-containment tests: every operation that escapes the sandbox root must raise."""
import sys
from pathlib import Path

import pytest

from codepilot.sandbox.local import LocalSandbox, SandboxEscapeError


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    root = tmp_path / "sandbox"
    root.mkdir()
    return LocalSandbox(root)


# ── read_file / write_file ─────────────────────────────────────────────────────


class TestWriteContainment:
    def test_write_within_sandbox_succeeds(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("hello.txt", "world")
        assert (sandbox.root / "hello.txt").read_text() == "world"

    def test_write_nested_within_sandbox_succeeds(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("sub/dir/file.txt", "content")
        assert (sandbox.root / "sub" / "dir" / "file.txt").exists()

    def test_write_path_traversal_raises(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(SandboxEscapeError):
            sandbox.write_file("../../etc/passwd", "evil")

    def test_write_multiple_traversal_raises(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(SandboxEscapeError):
            sandbox.write_file("../../../tmp/evil.txt", "evil")


class TestReadContainment:
    def test_read_within_sandbox_succeeds(self, sandbox: LocalSandbox) -> None:
        (sandbox.root / "data.txt").write_text("hello")
        assert sandbox.read_file("data.txt") == "hello"

    def test_read_path_traversal_raises(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(SandboxEscapeError):
            sandbox.read_file("../../etc/hosts")

    def test_read_parent_dir_traversal_raises(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(SandboxEscapeError):
            sandbox.read_file("../sibling_file.txt")


class TestAbsolutePathContainment:
    def test_absolute_path_within_sandbox_accepted(self, sandbox: LocalSandbox) -> None:
        target = sandbox.root / "abs_file.txt"
        sandbox.write_file(target, "abs content")
        assert target.read_text() == "abs content"

    def test_absolute_path_outside_sandbox_raises(self, sandbox: LocalSandbox, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("outside")
        with pytest.raises(SandboxEscapeError):
            sandbox.read_file(outside)

    def test_absolute_path_parent_raises(self, sandbox: LocalSandbox) -> None:
        parent = sandbox.root.parent
        with pytest.raises(SandboxEscapeError):
            sandbox.read_file(parent / "file.txt")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation requires elevated privileges on Windows")
class TestSymlinkContainment:
    def test_symlink_pointing_outside_raises(self, sandbox: LocalSandbox, tmp_path: Path) -> None:
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = sandbox.root / "evil_link.txt"
        link.symlink_to(outside)
        with pytest.raises(SandboxEscapeError):
            sandbox.read_file("evil_link.txt")

    def test_symlink_within_sandbox_allowed(self, sandbox: LocalSandbox) -> None:
        target = sandbox.root / "real.txt"
        target.write_text("real content")
        link = sandbox.root / "link.txt"
        link.symlink_to(target)
        assert sandbox.read_file("link.txt") == "real content"


class TestDeleteContainment:
    def test_delete_within_sandbox_succeeds(self, sandbox: LocalSandbox) -> None:
        (sandbox.root / "del.txt").write_text("bye")
        sandbox.delete_file("del.txt")
        assert not (sandbox.root / "del.txt").exists()

    def test_delete_path_traversal_raises(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(SandboxEscapeError):
            sandbox.delete_file("../../important")


class TestExistsContainment:
    def test_exists_within_sandbox(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("x.txt", "x")
        assert sandbox.exists("x.txt") is True
        assert sandbox.exists("missing.txt") is False

    def test_exists_escape_returns_false(self, sandbox: LocalSandbox) -> None:
        # exists() swallows SandboxEscapeError and returns False
        assert sandbox.exists("../../etc/passwd") is False


class TestSandboxEscapeError:
    def test_attributes_populated(self, sandbox: LocalSandbox) -> None:
        try:
            sandbox.read_file("../../secret")
        except SandboxEscapeError as exc:
            assert exc.root == sandbox.root
            assert isinstance(exc.path, Path)
        else:
            pytest.fail("SandboxEscapeError not raised")

    def test_is_permission_error_subclass(self) -> None:
        exc = SandboxEscapeError(Path("/outside"), Path("/sandbox"))
        assert isinstance(exc, PermissionError)
