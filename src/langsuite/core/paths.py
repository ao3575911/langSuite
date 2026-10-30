"""Where langsuite keeps its data (SPEC §5). `LANGSUITE_HOME` overrides the platform default."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def data_home() -> Path:
    override = os.environ.get("LANGSUITE_HOME")
    if override:
        return Path(override).expanduser()
    return Path(platformdirs.user_data_dir("langsuite", appauthor=False))


def base_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "base"


def cache_dir(home: Path | None = None) -> Path:
    return (home or data_home()) / "cache"
