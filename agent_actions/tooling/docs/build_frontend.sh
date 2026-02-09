#!/usr/bin/env bash
set -euo pipefail

# Build the Next.js frontend and copy the static export into docs_site/
# Usage: bash build_frontend.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
DOCS_SITE_DIR="$SCRIPT_DIR/docs_site"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "Error: frontend/ directory not found at $FRONTEND_DIR"
  exit 1
fi

echo "Installing dependencies..."
cd "$FRONTEND_DIR"
npm install

echo "Building static export..."
npm run build

echo "Replacing docs_site/ contents..."
# Remove old content but keep the directory
find "$DOCS_SITE_DIR" -mindepth 1 -delete 2>/dev/null || true

# Copy build output
cp -r "$FRONTEND_DIR/out/"* "$DOCS_SITE_DIR/"

echo "Done. Built frontend copied to docs_site/"
