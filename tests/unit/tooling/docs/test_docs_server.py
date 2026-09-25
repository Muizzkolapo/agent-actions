"""Tests for docs server path traversal protection, binding and concurrency."""

import socket
import threading
from contextlib import closing
from functools import partial

import pytest

from agent_actions.tooling.docs.server import DocsRequestHandler, DocsServer


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


class TestConcurrency:
    """A browser fetches catalog.json and runs.json at once, and drains a large
    response slowly. A server that handles one request at a time stalls on the
    first socket's buffer and never reaches the second."""

    @pytest.fixture()
    def running_server(self, tmp_path):
        docs_dir = tmp_path / "docs_site"
        docs_dir.mkdir()
        (docs_dir / "index.html").write_text("<html>docs</html>")
        artefact_dir = tmp_path / "artefact"
        artefact_dir.mkdir()
        # Larger than any plausible combined socket buffer, so the server blocks
        # writing it while the client is not reading.
        (artefact_dir / "catalog.json").write_bytes(b"x" * (16 * 1024 * 1024))
        (artefact_dir / "runs.json").write_text("{}")

        handler = partial(DocsRequestHandler, docs_site_dir=docs_dir, artefact_dir=artefact_dir)
        httpd = DocsServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield httpd.server_address[1]
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_a_stalled_large_response_does_not_block_the_next_request(self, running_server):
        port = running_server

        with closing(socket.create_connection(("127.0.0.1", port), timeout=10)) as slow:
            slow.sendall(b"GET /artefact/catalog.json HTTP/1.0\r\n\r\n")
            assert slow.recv(64)  # headers arrive; the body is left undrained

            with closing(socket.create_connection(("127.0.0.1", port), timeout=10)) as quick:
                quick.sendall(b"GET /artefact/runs.json HTTP/1.0\r\n\r\n")
                quick.settimeout(10)
                received = b""
                while b"\r\n\r\n" not in received:
                    chunk = quick.recv(4096)
                    if not chunk:
                        break
                    received += chunk
                assert b"200" in received.split(b"\r\n")[0]
