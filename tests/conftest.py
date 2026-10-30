"""Shared test fixtures."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode
from textual._doc import take_svg_screenshot

_TERMINAL_ID = re.compile(r"terminal-\d+")
_FAILURES = Path("snapshot_failures")


class StableSVGExtension(SingleFileSnapshotExtension):
    """One plain SVG file per snapshot."""

    file_extension = "svg"
    _write_mode = WriteMode.TEXT


def stable_svg(svg: str) -> str:
    """Drop Rich's per-process style hash so identical renders compare equal."""
    return _TERMINAL_ID.sub("terminal", svg)


@pytest.fixture
def snap_compare(snapshot: Any, request: pytest.FixtureRequest) -> Callable[..., bool]:
    """Like pytest-textual-snapshot's fixture, but stable across processes."""
    snap = snapshot.use_extension(StableSVGExtension)

    def compare(app: Any, **kwargs: Any) -> bool:
        actual = stable_svg(take_svg_screenshot(app=app, **kwargs))
        ok = bool(snap == actual)
        if not ok:
            _FAILURES.mkdir(exist_ok=True)
            name = re.sub(r"[^\w.-]+", "_", request.node.name)
            (_FAILURES / f"{name}.svg").write_text(actual, encoding="utf-8")
        return ok

    return compare


@pytest.fixture(autouse=True)
def _colour_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshots are rendered in full colour whatever the developer's terminal says."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TEXTUAL_COLOR_SYSTEM", raising=False)


FIXTURES = Path(__file__).parent / "fixtures" / "kb"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets an empty LANGSUITE_HOME so a developer's real base never leaks in."""
    home = tmp_path / "home"
    monkeypatch.setenv("LANGSUITE_HOME", str(home))
    # No Docker unless a test asks for it (tests/test_verify.py `docker` marker), so
    # renders do not depend on whether the machine has Docker.
    monkeypatch.setenv("LANGSUITE_DOCKER", "langsuite-no-docker-in-tests")
    monkeypatch.delenv("LANGSUITE_PACKS", raising=False)
    monkeypatch.delenv("LANGSUITE_TELEGRAM_TOKEN", raising=False)
    return home


@pytest.fixture(scope="session")
def built_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from langsuite.ingest.build import build

    home = tmp_path_factory.mktemp("kb")
    build(home=home, from_dir=FIXTURES)
    return home


@pytest.fixture
def kb_home(built_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private copy of the fixture base, so workspace writes never leak between tests."""
    import shutil

    home = tmp_path / "kbhome"
    shutil.copytree(built_home, home)
    monkeypatch.setenv("LANGSUITE_HOME", str(home))
    monkeypatch.delenv("LANGSUITE_WORKSPACE", raising=False)
    return home
