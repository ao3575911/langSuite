"""Deferred module imports so `langsuite --help` does not pay for numpy, urllib or telegram."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class _LazyModule(ModuleType):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__dict__["_lazy_mod"] = None

    def _load(self) -> ModuleType:
        mod: ModuleType | None = self.__dict__["_lazy_mod"]
        if mod is None:
            mod = importlib.import_module(self.__name__)
            self.__dict__["_lazy_mod"] = mod
        return mod

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._load(), attr)


def lazy(name: str) -> Any:
    """Return a stand-in for module `name` that imports it on first attribute access."""
    return _LazyModule(name)
