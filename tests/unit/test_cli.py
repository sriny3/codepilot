import subprocess
import sys

from codepilot.__main__ import main


def test_no_args_prints_help_returns_zero(capsys: object) -> None:
    rc = main([])
    assert rc == 0


def test_version_flag() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "codepilot", "--version"],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0
    assert "codepilot" in res.stdout


def test_help_returns_zero() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "codepilot", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0
    assert "Multi-agent" in res.stdout


def test_doctor_with_valid_env(min_env: None) -> None:
    rc = main(["doctor"])
    assert rc == 0


def test_doctor_with_missing_env(clean_env: None) -> None:
    rc = main(["doctor"])
    assert rc == 1
