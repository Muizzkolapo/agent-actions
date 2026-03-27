"""Tests for docs server path traversal protection and localhost binding."""

import pytest

from agent_actions.tooling.docs.server import DocsRequestHandler


@pytest.fixture()
def handler(tmp_path):
    """Create a DocsRequestHandler with isolated temp directories."""
    docs_dir = tmp_path / "docs_site"
    docs_dir.mkdir()
    (docs_dir / "index.html").write_text("<html>docs</html>")

    artefact_dir = tmp_path / "artefact"
    artefact_dir.mkdir()
    (artefact_dir / "catalog.json").write_text("{}")

    # DocsRequestHandler requires a request/server context.
    # We test translate_path directly, bypassing HTTP wiring.
    class FakeHandler(DocsRequestHandler):
        def __init__(self, docs_site_dir, artefact_dir):
            # Skip super().__init__ which needs a real socket
            self.docs_site_dir = docs_site_dir
            self.artefact_dir = artefact_dir

    return FakeHandler(docs_dir, artefact_dir)


class TestPathTraversal:
    def test_normal_docs_path(self, handler):
        result = handler.translate_path("/index.html")
        assert result.endswith("index.html")
        assert "docs_site" in result

    def test_normal_artefact_path(self, handler):
        result = handler.translate_path("/artefact/catalog.json")
        assert result.endswith("catalog.json")
        assert "artefact" in result

    def test_artefact_root(self, handler):
        result = handler.translate_path("/artefact")
        assert result.endswith("artefact")

    def test_docs_root(self, handler):
        result = handler.translate_path("/")
        assert result.endswith("docs_site")

    def test_traversal_via_dotdot_blocked(self, handler):
        """../../etc/passwd should resolve outside root → empty string (404)."""
        result = handler.translate_path("/../../etc/passwd")
        assert result == ""

    def test_traversal_via_artefact_dotdot_blocked(self, handler):
        result = handler.translate_path("/artefact/../../etc/passwd")
        assert result == ""

    def test_url_encoded_traversal_blocked(self, handler):
        """URL-decoded ../ segments should still be caught."""
        result = handler.translate_path("/%2e%2e/%2e%2e/etc/passwd")
        assert result == ""

    def test_artefact_url_encoded_traversal_blocked(self, handler):
        result = handler.translate_path("/artefact/%2e%2e/%2e%2e/etc/passwd")
        assert result == ""


class TestLocalhostBinding:
    def test_serve_docs_binds_to_localhost(self):
        """Verify HTTPServer is called with 127.0.0.1, not empty string."""
        import inspect

        from agent_actions.tooling.docs import server as srv_mod

        source = inspect.getsource(srv_mod.serve_docs)
        assert '"127.0.0.1"' in source or "'127.0.0.1'" in source
