"""A planted GFDL file in the wheel must fail the licence-pack check (SPEC §10 M0)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check_wheel_licences.py"


def _build(src: Path, out: Path) -> Path:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(src)],
        check=True,
        capture_output=True,
    )
    return next(out.glob("*.whl"))


def _copy(tmp: Path) -> Path:
    dst = tmp / "repo"
    shutil.copytree(
        ROOT,
        dst,
        ignore=shutil.ignore_patterns(".git", ".venv", "dist", "__pycache__", ".*_cache"),
    )
    return dst


def _check(wheel: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CHECK), str(wheel)], capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv needed to build wheels")
def test_clean_wheel_passes(tmp_path: Path) -> None:
    res = _check(_build(_copy(tmp_path), tmp_path / "dist"))
    assert res.returncode == 0, res.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv needed to build wheels")
def test_planted_gfdl_fails(tmp_path: Path) -> None:
    repo = _copy(tmp_path)
    (repo / "src" / "langwish" / "planted.txt").write_text(
        "Permission is granted to copy under the GNU Free Documentation License 1.2\n"
    )
    res = _check(_build(repo, tmp_path / "dist"))
    assert res.returncode == 1
    assert "planted.txt" in res.stderr


def test_usage_error() -> None:
    assert _check(Path("nope.whl")).returncode == 2
