"""Fail if a wheel contains GFDL or CC BY-SA material (SPEC §2, §11).

Usage: python scripts/check_wheel_licences.py dist/*.whl
Exit 0 clean, 1 forbidden content found, 2 usage error.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

FORBIDDEN_PATHS = re.compile(r"(^|/)data-packs/|(^|/)(rosetta|cc-by-sa)[^/]*/", re.IGNORECASE)
FORBIDDEN_TEXT = re.compile(
    rb"GNU Free Documentation License|\bGFDL(-1\.[23])?\b|\bCC[ -]BY-SA\b"
    rb"|Creative Commons Attribution-ShareAlike",
    re.IGNORECASE,
)


def scan(wheel: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if FORBIDDEN_PATHS.search(name):
                problems.append(f"{name}: path from a share-alike data pack")
                continue
            if name.endswith(".dist-info/METADATA"):
                continue  # README text describing the policy is allowed
            if FORBIDDEN_TEXT.search(zf.read(name)):
                problems.append(f"{name}: contains GFDL / CC BY-SA licence text")
    return problems


def main(argv: list[str]) -> int:
    wheels = [Path(a) for a in argv]
    if not wheels or not all(w.suffix == ".whl" and w.is_file() for w in wheels):
        print("usage: check_wheel_licences.py WHEEL [WHEEL...]", file=sys.stderr)
        return 2
    bad = [p for w in wheels for p in scan(w)]
    for p in bad:
        print(f"FORBIDDEN {p}", file=sys.stderr)
    if bad:
        print(f"licence-pack check failed: {len(bad)} problem(s)", file=sys.stderr)
        return 1
    print(f"licence-pack check passed: {len(wheels)} wheel(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
