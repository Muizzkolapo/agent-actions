"""
Documentation HTTP server.
"""
import sys
import os
import subprocess
import shutil
from pathlib import Path


def serve_docs(port: int = 8000) -> bool:
    """
    Start HTTP server to serve documentation.

    Args:
        port: Port number to serve on

    Returns:
        True if started successfully
    """
    # Find docs_site directory (in docs package)
    docs_site_dir = Path(__file__).parent / 'docs_site'

    if not docs_site_dir.exists():
        print("❌ Error: docs_site directory not found!")
        print(f"   Expected at: {docs_site_dir}")
        return False

    # Check if artefact/ exists in current working directory
    artefact_dir = Path.cwd() / 'artefact'
    if not artefact_dir.exists():
        print("❌ Error: artefact/ directory not found!")
        print("   Run 'agac docs generate' first.\n")
        return False

    # Check if data files exist
    catalog_path = artefact_dir / 'catalog.json'
    runs_path = artefact_dir / 'runs.json'

    if not catalog_path.exists() or not runs_path.exists():
        print("❌ Error: Data files not found in artefact/")
        print("   Run 'agac docs generate' first.\n")
        return False

    # Create symlink or copy artefact/ into docs_site/ so the web server can access it
    docs_artefact_link = docs_site_dir / 'artefact'

    # Remove existing symlink/directory if it exists
    if docs_artefact_link.exists() or docs_artefact_link.is_symlink():
        if docs_artefact_link.is_symlink():
            docs_artefact_link.unlink()
        elif docs_artefact_link.is_dir():
            shutil.rmtree(docs_artefact_link)

    # Try to create symlink (works on Unix/Mac), fall back to copy on Windows
    try:
        os.symlink(artefact_dir, docs_artefact_link)
    except (OSError, NotImplementedError):
        # Windows or permission issue - copy instead
        shutil.copytree(artefact_dir, docs_artefact_link)

    print(f"\nServing docs at http://localhost:{port}")
    print("Press Ctrl+C to exit\n")

    try:
        # Start HTTP server from docs_site directory
        subprocess.run([
            sys.executable, '-m', 'http.server',
            str(port),
            '--directory', str(docs_site_dir)
        ])
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        # Clean up the symlink/copy when server stops
        if docs_artefact_link.exists() or docs_artefact_link.is_symlink():
            if docs_artefact_link.is_symlink():
                docs_artefact_link.unlink()
            elif docs_artefact_link.is_dir():
                shutil.rmtree(docs_artefact_link)

    return True
