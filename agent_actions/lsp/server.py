"""Backward-compatible entrypoint shim for the LSP server."""

from agent_actions.tooling.lsp.server import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
