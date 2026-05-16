#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# release.sh — Publish VS Code extension + Python package
#
# Usage:
#   ./scripts/release.sh              # reads versions from source files
#   ./scripts/release.sh --dry-run    # show what would happen, don't publish
#
# Prerequisites:
#   - On main branch, up to date with origin
#   - Versions already bumped in package.json, pyproject.toml, __version__.py
#   - VSIX already built (vscode-extension/agent-actions-*.vsix)
#   - vsce logged in (npx @vscode/vsce login runagac)
#   - gh CLI authenticated
# ──────────────────────────────────────────────────────────────────────────────

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Read versions from source files ──────────────────────────────────────────

PYTHON_VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")

MODULE_VERSION=$(python3 -c "
import re
with open('agent_actions/__version__.py') as f:
    print(re.search(r'__version__ = \"(.+)\"', f.read()).group(1))
")

EXT_VERSION=$(node -p "require('./vscode-extension/package.json').version")

VSIX="vscode-extension/agent-actions-${EXT_VERSION}.vsix"

# ── Preflight checks ────────────────────────────────────────────────────────

echo "=== Release Preflight ==="
echo "  Python version (pyproject.toml):   $PYTHON_VERSION"
echo "  Python version (__version__.py):   $MODULE_VERSION"
echo "  Extension version (package.json):  $EXT_VERSION"
echo "  VSIX artifact:                     $VSIX"
echo ""

ERRORS=0

if [[ "$PYTHON_VERSION" != "$MODULE_VERSION" ]]; then
    echo "ERROR: pyproject.toml ($PYTHON_VERSION) != __version__.py ($MODULE_VERSION)"
    ERRORS=$((ERRORS + 1))
fi

if [[ ! -f "$VSIX" ]]; then
    echo "ERROR: VSIX not found at $VSIX"
    echo "  Run: cd vscode-extension && npx @vscode/vsce package"
    ERRORS=$((ERRORS + 1))
fi

BRANCH=$(git branch --show-current)
if [[ "$BRANCH" != "main" ]]; then
    echo "ERROR: Not on main branch (on: $BRANCH)"
    ERRORS=$((ERRORS + 1))
fi

if ! git diff --quiet HEAD; then
    echo "ERROR: Uncommitted changes present"
    ERRORS=$((ERRORS + 1))
fi

if [[ $ERRORS -gt 0 ]]; then
    echo ""
    echo "Fix $ERRORS error(s) above before releasing."
    exit 1
fi

echo "All checks passed."
echo ""

# ── Step 1: Publish VS Code Extension ───────────────────────────────────────

echo "=== Step 1/3: Publish VS Code Extension v${EXT_VERSION} ==="

if $DRY_RUN; then
    echo "  [dry-run] Would run: cd vscode-extension && npx @vscode/vsce publish"
else
    (cd vscode-extension && npx @vscode/vsce publish)
    echo "  Extension v${EXT_VERSION} published to Marketplace."
fi

echo ""

# ── Step 2: Tag Python release ──────────────────────────────────────────────

TAG="v${PYTHON_VERSION}"

echo "=== Step 2/3: Create git tag ${TAG} ==="

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "  Tag $TAG already exists — skipping."
else
    if $DRY_RUN; then
        echo "  [dry-run] Would run: git tag $TAG && git push origin $TAG"
    else
        git tag "$TAG"
        git push origin "$TAG"
        echo "  Tag $TAG pushed."
    fi
fi

echo ""

# ── Step 3: Create GitHub Release (triggers PyPI publish) ───────────────────

echo "=== Step 3/3: Create GitHub Release ${TAG} ==="

if $DRY_RUN; then
    echo "  [dry-run] Would run: gh release create $TAG --generate-notes"
else
    gh release create "$TAG" \
        --title "v${PYTHON_VERSION}" \
        --generate-notes
    echo "  GitHub Release created — PyPI publish workflow triggered."
fi

echo ""
echo "=== Release Complete ==="
echo "  Extension: https://marketplace.visualstudio.com/items?itemName=runagac.agent-actions"
echo "  PyPI:      https://pypi.org/project/agent-actions/${PYTHON_VERSION}/"
echo "  GitHub:    https://github.com/Muizzkolapo/agent-actions/releases/tag/${TAG}"
