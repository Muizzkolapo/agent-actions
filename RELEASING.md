# Releasing agent-actions

## Prerequisites

- Write access to the `Muizzkolapo/agent-actions` repository
- PyPI trusted publishing configured (OIDC) — see note below

## Steps

### 1. Prepare the release

```bash
# Ensure main is up to date
git checkout main && git pull

# Confirm tests pass
pytest
ruff check .
ruff format --check .
```

### 2. Bump the version

Use `changie batch` to batch unreleased changelog entries and bump the version automatically:

```bash
task changelog:batch -- X.Y.Z
task changelog:merge
```

This updates the version in both `pyproject.toml` and `agent_actions/__version__.py` (configured via `.changie.yaml` replacements), and merges entries into `CHANGELOG.md`.

Commit and push:

```bash
git add pyproject.toml agent_actions/__version__.py CHANGELOG.md .changes/
git commit -m "chore: release vX.Y.Z"
git push origin main
```

### 3. Tag the release

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a `v*` tag triggers the `publish.yml` workflow, which builds and publishes to PyPI via OIDC trusted publishing.

### 4. Create a GitHub Release

Go to **Releases → Draft a new release**, select the tag, and publish. Add a summary of changes.

---

## PyPI Trusted Publishing

The `publish.yml` workflow uses OIDC — no API tokens needed. Before the first release, ensure the trusted publisher entry exists in the PyPI project settings:

- **Publisher:** GitHub Actions
- **Owner:** `Muizzkolapo`
- **Repository:** `agent-actions`
- **Workflow:** `publish.yml`
- **Environment:** (leave blank or match the workflow environment name)

If this is not configured before the first publish run, it will silently fail.

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- `MAJOR` — breaking changes to the YAML schema or public API
- `MINOR` — new features, backwards compatible
- `PATCH` — bug fixes, docs, internal changes
