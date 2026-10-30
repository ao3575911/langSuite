"""M6 release prep: version, release workflow shape, notes."""

import tomllib
from pathlib import Path

import yaml

from langsuite import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent() -> None:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert meta["version"] == __version__ == "1.0.1"
    assert "Changelog" in meta["urls"]
    assert f"## {__version__}" in (ROOT / "CHANGELOG.md").read_text()
    assert (ROOT / "docs" / f"RELEASE_NOTES_{__version__}.md").exists()


def test_release_workflow_is_tag_only_trusted_publishing() -> None:
    text = (ROOT / ".github/workflows/release.yml").read_text()
    wf = yaml.safe_load(text)
    on = wf[True] if True in wf else wf["on"]  # yaml 1.1 reads `on` as True
    assert set(on) == {"push"} and set(on["push"]) == {"tags"}
    assert wf["permissions"] == {"contents": "read"}
    pub = wf["jobs"]["publish"]
    assert pub["permissions"] == {"id-token": "write"}
    assert pub["environment"]["name"] == "pypi"
    assert pub["steps"][-1]["uses"].startswith("pypa/gh-action-pypi-publish@")
    assert "secrets." not in text and "password" not in text
    assert "check_wheel_licences" in text
