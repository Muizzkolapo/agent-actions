"""
Documentation HTTP server.

Serves static files from the docs_site package directory and data files
from the user's project artefact directory without modifying the package.
"""

import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
from typing import Optional
import urllib.parse

import click

logger = logging.getLogger(__name__)


class DocsRequestHandler(SimpleHTTPRequestHandler):
    """
    HTTP handler that serves from two directories:
    - Static site files from docs_site/ (in package)
    - Data files from artefact/ (in user's project)
    """

    def __init__(self, *args, docs_site_dir: Path, artefact_dir: Path, **kwargs):
        self.docs_site_dir = docs_site_dir
        self.artefact_dir = artefact_dir
        # Must set directory before calling super().__init__
        super().__init__(*args, directory=str(docs_site_dir), **kwargs)

    def translate_path(self, path: str) -> str:
        """
        Map URL path to filesystem path.

        - /artefact/* -> user's artefact directory
        - /* -> docs_site directory (static files)

        All resolved paths are validated to stay within their respective
        root directory to prevent path-traversal attacks.
        """
        # Decode URL and remove query string
        path = urllib.parse.unquote(path)
        path = path.split("?")[0].split("#")[0]
        path = path.lstrip("/")

        # Route artefact requests to user's directory
        if path.startswith("artefact/") or path == "artefact":
            relative = path[len("artefact") :].lstrip("/")
            root = self.artefact_dir
            if relative:
                target = (root / relative).resolve()
            else:
                return str(root)
            return self._guard_path(target, root)

        # Route everything else to docs_site
        root = self.docs_site_dir
        if path:
            target = (root / path).resolve()
            return self._guard_path(target, root)
        return str(root)

    @staticmethod
    def _guard_path(target: Path, root: Path) -> str:
        """Return *target* as a string if it is inside *root*, else empty string (→ 404)."""
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return ""
        return str(target)

    def log_message(self, format, *args):
        """Suppress default logging for cleaner output."""
        # Override to suppress logs - intentionally ignore all arguments


def serve_docs(port: int = 8000, artefact_path: Optional[str] = None) -> bool:
    """
    Start HTTP server to serve documentation.

    Args:
        port: Port number to serve on
        artefact_path: Path to artefact directory (defaults to ./artefact)

    Returns:
        True if started successfully
    """
    # Find docs_site directory (in package)
    docs_site_dir = Path(__file__).parent / "docs_site"

    if not docs_site_dir.exists():
        logger.error("docs_site directory not found at %s", docs_site_dir)
        click.echo(f"Error: docs_site directory not found!\n   Expected at: {docs_site_dir}")
        return False

    # Find artefact directory (in user's project)
    if artefact_path:
        artefact_dir = Path(artefact_path)
        if not artefact_dir.is_absolute():
            artefact_dir = (Path.cwd() / artefact_dir).resolve()
        else:
            artefact_dir = artefact_dir.resolve()
    else:
        artefact_dir = Path.cwd() / "artefact"

    if not artefact_dir.exists():
        logger.error("artefact directory not found at %s", artefact_dir)
        click.echo("Error: artefact/ directory not found!\n   Run 'agac docs generate' first.\n")
        return False

    # Check for required data files
    catalog_path = artefact_dir / "catalog.json"
    runs_path = artefact_dir / "runs.json"

    if not catalog_path.exists() or not runs_path.exists():
        logger.error("Data files not found in %s", artefact_dir)
        click.echo("Error: Data files not found in artefact/\n   Run 'agac docs generate' first.\n")
        return False

    # Create handler class with bound directories
    handler = partial(DocsRequestHandler, docs_site_dir=docs_site_dir, artefact_dir=artefact_dir)

    logger.info("Serving docs at http://127.0.0.1:%d", port)
    click.echo(f"\nServing docs at http://127.0.0.1:{port}")
    click.echo("Press Ctrl+C to exit\n")

    try:
        with HTTPServer(("127.0.0.1", port), handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nShutting down server...")

    return True
