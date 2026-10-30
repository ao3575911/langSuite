# Releasing

Publishing uses PyPI trusted publishing (OIDC). No PyPI token is stored in the repo or its secrets. Only Adam tags or publishes.

## One-time setup (Adam)

1. On pypi.org, go to Account → Publishing → *Add a pending publisher*. Enter:
   - project `langsuite`
   - owner `ao3575911`
   - repository `langsuite`
   - workflow `release.yml`
   - environment `pypi`
2. On GitHub, go to Settings → Environments and create `pypi`. Adding yourself as a required reviewer is recommended, so every publish waits for your click.

## Each release

1. Make sure `version` in `pyproject.toml` and `__version__` match (for example `1.0.0`), the CHANGELOG has a section for that version, and CI on `main` is green.
2. Tag and push: `git tag -s v1.0.0 -m "langsuite 1.0.0" && git push origin v1.0.0`.
3. `release.yml` then runs. It checks the tag matches the version, runs lint, types and tests, builds, runs the licence-pack check and `twine check`, and publishes once the `pypi` environment is approved.
4. Optionally, create a GitHub release from `docs/RELEASE_NOTES_<version>.md`.
