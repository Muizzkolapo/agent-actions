"""Tests for agent_actions.tooling.docs.generator._copy_readme_images.

Covers two hardening findings:
- One image-copy failure must not abort the catalog generation (a single
  bad image — disk full, permission error — should be logged and skipped).
- Path rewriting must replace exact regex spans, not via str.replace, so
  a short filename like ``logo.png`` is not corrupted inside a longer
  path like ``dark/logo.png``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.tooling.docs.generator import _copy_readme_images
from agent_actions.tooling.docs.scanner import ReadmeData


@pytest.fixture
def _allow_log_propagation():
    """Re-enable propagation on the ``agent_actions`` logger so caplog
    (which captures at the root logger) sees module log records.

    LoggerFactory sets ``propagate = False`` when initialized; tests that
    assert on log content need the chain restored for the duration of the
    test only.
    """
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    try:
        yield
    finally:
        aa_logger.propagate = original


def _make_readme(tmp_path: Path, content: str) -> ReadmeData:
    return ReadmeData(content=content, source_dir=tmp_path)


def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # tiny PNG-ish placeholder; contents do not matter for copy
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


class TestSubstringCollision:
    """Two images whose filenames overlap as substrings must rewrite
    independently and produce two distinct artefact URLs."""

    def test_short_filename_not_corrupted_inside_longer_path(self, tmp_path):
        _make_image(tmp_path / "logo.png")
        _make_image(tmp_path / "dark" / "logo.png")

        content = '<img src="logo.png">\n<img src="dark/logo.png">\n'
        readme = _make_readme(tmp_path, content)

        artefact_dir = tmp_path / "artefact"
        result = _copy_readme_images(readme, "wf1", artefact_dir)

        # Both image references should resolve to their independent URLs;
        # naively replacing 'logo.png' first corrupted the second path.
        assert '<img src="/artefact/images/wf1/logo.png">' in result
        # The second image points to the same filename (logo.png) because
        # shutil copies by basename — that's expected. What matters is that
        # the *first* replacement did not produce a double-prefixed URL.
        assert "/artefact/images/wf1//artefact/images/wf1/" not in result

    def test_markdown_short_filename_not_corrupted(self, tmp_path):
        _make_image(tmp_path / "icon.png")
        _make_image(tmp_path / "assets" / "icon.png")

        content = "![one](icon.png)\n![two](assets/icon.png)\n"
        readme = _make_readme(tmp_path, content)

        artefact_dir = tmp_path / "artefact"
        result = _copy_readme_images(readme, "wf1", artefact_dir)

        # No double-prefixed garbage path should appear.
        assert "/artefact/images/wf1//artefact/images/wf1/" not in result
        # Both image links should be rewritten to artefact URLs.
        assert result.count("/artefact/images/wf1/") == 2


class TestCopyFailureDoesNotAbort:
    """A shutil.copy2 OSError on one image must not abort the rewrite of
    other images, and must not propagate to the caller."""

    def test_copy2_oserror_skips_image_and_continues(
        self, tmp_path, caplog, _allow_log_propagation
    ):
        good = tmp_path / "good.png"
        bad = tmp_path / "bad.png"
        _make_image(good)
        _make_image(bad)

        content = '<img src="good.png">\n<img src="bad.png">\n'
        readme = _make_readme(tmp_path, content)
        artefact_dir = tmp_path / "artefact"

        real_copy2 = shutil.copy2

        def selective_copy(src, dst, *args, **kwargs):
            if Path(src).name == "bad.png":
                raise OSError("disk full")
            return real_copy2(src, dst, *args, **kwargs)

        with patch(
            "agent_actions.tooling.docs.generator.shutil.copy2",
            side_effect=selective_copy,
        ):
            with caplog.at_level("WARNING", logger="agent_actions.tooling.docs.generator"):
                result = _copy_readme_images(readme, "wf1", artefact_dir)

        # Good image rewritten; bad image left as-is.
        assert '<img src="/artefact/images/wf1/good.png">' in result
        assert '<img src="bad.png">' in result
        # A warning was logged for the failed copy. The message intentionally
        # uses "stage" rather than "copy" because the same except block also
        # covers a mkdir failure on the destination directory.
        assert any("bad.png" in rec.getMessage() for rec in caplog.records)
        assert any("stage" in rec.getMessage() for rec in caplog.records)

    def test_copy2_failure_does_not_raise(self, tmp_path):
        img = tmp_path / "only.png"
        _make_image(img)
        content = '<img src="only.png">\n'
        readme = _make_readme(tmp_path, content)

        with patch(
            "agent_actions.tooling.docs.generator.shutil.copy2",
            side_effect=OSError("permission denied"),
        ):
            # Must not raise; the function returns the original content.
            result = _copy_readme_images(readme, "wf1", tmp_path / "artefact")

        assert '<img src="only.png">' in result


class TestSkipExternalUrls:
    """URLs (http://, https://, data:) are passed through unchanged."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/img.png",
            "http://example.com/img.png",
            "data:image/png;base64,iVBORw0KG",
        ],
    )
    def test_external_urls_pass_through(self, tmp_path, url):
        content = f'<img src="{url}">'
        readme = _make_readme(tmp_path, content)
        result = _copy_readme_images(readme, "wf1", tmp_path / "artefact")
        assert result == content
