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

`changie batch` empties `.changes/unreleased/`, but the **Changelog Entry** CI job
fails any PR whose `.changes/unreleased/` is empty. So the release PR carries one
entry announcing itself:

```bash
cat > ".changes/unreleased/Under the Hood-$(date -u +%Y%m%d-%H%M%S).yaml" <<EOF
kind: Under the Hood
body: "Release vX.Y.Z — batch changie entries, bump version"
time: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
```

That entry is not consumed by this release, so it appears in the *next* one's notes.

Commit and open a PR:

```bash
git add pyproject.toml agent_actions/__version__.py CHANGELOG.md .changes/
git commit -m "chore: release vX.Y.Z"
git push -u origin chore/release-X.Y.Z
gh pr create --base main --title "chore: release vX.Y.Z"
```

Base the release PR on `main`, not on another branch. Squash-merging a branch
below it rewrites the base out from under it, and the release merges somewhere
that never reaches `main` — leaving a half-released `main` and a tag that would
point at the wrong version.

### 3. Tag the release

After the PR merges, confirm the version actually landed before tagging. A tag
cannot be moved once published, and PyPI will not accept a replacement:

```bash
git checkout main && git pull
git show origin/main:pyproject.toml | grep '^version'   # must read X.Y.Z

git tag vX.Y.Z
git push origin vX.Y.Z
```

The tag on its own publishes nothing. It exists so the GitHub Release in the
next step has something to point at.

### 4. Create a GitHub Release — this is what publishes

`publish.yml` triggers on `release: published`, not on the tag push, so nothing
reaches PyPI until the release exists:

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <(sed -n '/^## X.Y.Z/,/^## /p' CHANGELOG.md | sed '1d;$d')
```

Or draft it from **Releases → Draft a new release**, select the tag, and publish.

Confirm it ran:

```bash
gh run list --workflow=publish.yml --limit 1
```

### 5. The VS Code extension

The extension is versioned separately in `vscode-extension/package.json` and is
not published by any workflow. Build and upload it by hand:

```bash
cd vscode-extension
npm run package                                          # produces agent-actions-X.Y.Z.vsix
npx vsce publish --packagePath agent-actions-X.Y.Z.vsix  # needs a Marketplace PAT
```

Prefer `--packagePath` over a bare `vsce publish`: it ships the artefact you
verified rather than rebuilding on the publishing machine.

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
