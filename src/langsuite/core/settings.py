"""Global preferences (`<home>/settings.json`): output mode, gamification (SPEC §6c, M5g, M5h)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langsuite.core.paths import data_home

DEFAULTS: dict[str, Any] = {"mode": None, "gamification": True}


def settings_path(home: Path | None = None) -> Path:
    return (home or data_home()) / "settings.json"


def load(home: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(settings_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def save(changes: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    data = {**load(home), **changes}
    path = settings_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data
