"""Output modes (SPEC §6c). Precedence: flag > workspace > global > default."""

from __future__ import annotations

from enum import StrEnum


class Mode(StrEnum):
    DEFAULT = "default"
    CONCISE = "concise"
    THOROUGH = "thorough"


def resolve_mode(
    flag: Mode | None = None,
    workspace: Mode | None = None,
    global_: Mode | None = None,
) -> Mode:
    for candidate in (flag, workspace, global_):
        if candidate is not None:
            return candidate
    return Mode.DEFAULT
