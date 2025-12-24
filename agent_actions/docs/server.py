"""
Documentation HTTP server.

Serves static files from the docs_site package directory and data files
from the user's project artefact directory without modifying the package.
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
from typing import Optional
import urllib.parse


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
        """
        # Decode URL and remove query string
        path = urllib.parse.unquote(path)
        path = path.split('?')[0].split('#')[0]
        path = path.lstrip('/')

        # Route artefact requests to user's directory
        if path.startswith('artefact/') or path == 'artefact':
            relative = path[len('artefact'):].lstrip('/')
            if relative:
                return str(self.artefact_dir / relative)
            return str(self.artefact_dir)

        # Route everything else to docs_site
        if path:
            return str(self.docs_site_dir / path)
        return str(self.docs_site_dir)

    def log_message(self, format, *args):
        """Suppress default logging for cleaner output."""
        pass


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
    docs_site_dir = Path(__file__).parent / 'docs_site'

    if not docs_site_dir.exists():
        print("Error: docs_site directory not found!")
        print(f"   Expected at: {docs_site_dir}")
        return False

    # Find artefact directory (in user's project)
    if artefact_path:
        artefact_dir = Path(artefact_path)
        if not artefact_dir.is_absolute():
            artefact_dir = (Path.cwd() / artefact_dir).resolve()
        else:
            artefact_dir = artefact_dir.resolve()
    else:
        artefact_dir = Path.cwd() / 'artefact'

    if not artefact_dir.exists():
        print("Error: artefact/ directory not found!")
        print("   Run 'agac docs generate' first.\n")
        return False

    # Check for required data files
    catalog_path = artefact_dir / 'catalog.json'
    runs_path = artefact_dir / 'runs.json'

    if not catalog_path.exists() or not runs_path.exists():
        print("Error: Data files not found in artefact/")
        print("   Run 'agac docs generate' first.\n")
        return False

    # Create handler class with bound directories
    handler = partial(
        DocsRequestHandler,
        docs_site_dir=docs_site_dir,
        artefact_dir=artefact_dir
    )

    print(f"\nServing docs at http://localhost:{port}")
    print("Press Ctrl+C to exit\n")

    try:
        with HTTPServer(('', port), handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")

    return True
