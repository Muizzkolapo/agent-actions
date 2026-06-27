"""The LSP must advertise non-empty ``trigger_characters`` on both
``completionProvider`` and ``signatureHelpProvider``.

pygls discards the return value of any user-supplied ``initialize``
handler and rebuilds capabilities from ``fm.feature_options`` (see
``pygls/protocol/language_server.py::lsp_initialize`` and
``pygls/capabilities.py::ServerCapabilitiesBuilder``). Asserting on
``fm.feature_options`` is therefore equivalent to asserting on the wire
payload.
"""

from __future__ import annotations

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.server import server


def _options_for(method: str):
    return server.protocol.fm.feature_options.get(method)


def test_completion_provider_advertises_trigger_characters() -> None:
    opts = _options_for(lsp.TEXT_DOCUMENT_COMPLETION)
    assert opts is not None, (
        "No options registered for textDocument/completion — pygls will "
        "build InitializeResult with default empty trigger_characters."
    )
    assert isinstance(opts, lsp.CompletionOptions)
    assert opts.trigger_characters, (
        "completionProvider.trigger_characters is empty; IDE auto-trigger "
        "will never fire on member access."
    )
    assert "." in opts.trigger_characters
    # Preserve the wider set the manual InitializeResult was advertising.
    for ch in ("$", ":", "-"):
        assert ch in opts.trigger_characters, (
            f"completion trigger char {ch!r} dropped from advertised set."
        )


def test_signature_help_provider_advertises_trigger_characters() -> None:
    opts = _options_for(lsp.TEXT_DOCUMENT_SIGNATURE_HELP)
    assert opts is not None, (
        "No options registered for textDocument/signatureHelp — pygls will "
        "build InitializeResult with default empty trigger_characters."
    )
    assert isinstance(opts, lsp.SignatureHelpOptions)
    assert opts.trigger_characters, (
        "signatureHelpProvider.trigger_characters is empty; signature help "
        "will never pop up automatically."
    )
    assert ":" in opts.trigger_characters
