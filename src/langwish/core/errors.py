"""Typed errors and exit codes (SPEC §7: 0 ok, 2 no result, 3 data, 4 auth, 5 quota)."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    NO_RESULT = 2
    DATA = 3
    AUTH = 4
    QUOTA = 5


class LangwishError(Exception):
    """Base error. `message` is short and user-facing; `hint` says what to do next."""

    exit_code: ExitCode = ExitCode.DATA

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class NoResultError(LangwishError):
    exit_code = ExitCode.NO_RESULT


class DataError(LangwishError):
    exit_code = ExitCode.DATA


class AuthError(LangwishError):
    exit_code = ExitCode.AUTH


class QuotaError(LangwishError):
    exit_code = ExitCode.QUOTA


class NotBuiltYetError(NoResultError):
    """Raised by command stubs whose milestone has not landed."""

    def __init__(self, command: str, milestone: str) -> None:
        super().__init__(
            f"`{command}` is not built yet (milestone {milestone}).",
            hint="See docs/SPEC.md §10 for the roadmap.",
        )
