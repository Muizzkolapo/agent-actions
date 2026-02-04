"""
Smoke tests to verify LSP server module is importable and VS Code extension uses correct path.

These tests prevent regressions like using the wrong module path in the VS Code extension.
"""

import re
from pathlib import Path


def test_lsp_server_module_importable():
    """Verify the LSP server module can be imported."""
    # This will fail if the module path is wrong or server has import errors
    from agent_actions.tooling.lsp import server  # noqa: F401

    # Verify server has the expected entry point
    assert hasattr(server, "main"), "LSP server should have a main() entry point"


def test_vscode_extension_uses_correct_lsp_module_path():
    """Verify VS Code extension references the correct LSP server module path."""
    # Find the VS Code extension source
    repo_root = Path(__file__).resolve().parents[4]
    extension_ts = repo_root / "editors" / "vscode" / "src" / "extension.ts"

    assert extension_ts.exists(), f"VS Code extension not found at {extension_ts}"

    content = extension_ts.read_text()

    # The correct module path
    correct_path = "agent_actions.tooling.lsp.server"

    # Common wrong paths that have caused issues
    wrong_paths = [
        "agent_actions.lsp.server",
        "agent_actions.lsp",
        "tooling.lsp.server",
    ]

    # Verify correct path is used
    assert correct_path in content, (
        f"VS Code extension should use '{correct_path}' for LSP server. "
        f"Check editors/vscode/src/extension.ts"
    )

    # Verify wrong paths are NOT used
    for wrong_path in wrong_paths:
        # Use regex to match the exact module path (not as substring of correct path)
        pattern = rf"['\"](-m\s+)?{re.escape(wrong_path)}['\"]"
        match = re.search(pattern, content)
        assert match is None, (
            f"VS Code extension uses incorrect LSP path '{wrong_path}'. Should be '{correct_path}'"
        )


def test_lsp_server_starts_without_error():
    """Verify LSP server can be initialized (dry run)."""
    from agent_actions.tooling.lsp.server import server

    # Server should be a pygls LanguageServer instance
    assert server is not None, "LSP server instance should exist"
    assert hasattr(server, "start_io"), "Server should have start_io method for stdio mode"
