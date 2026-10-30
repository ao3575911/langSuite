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
