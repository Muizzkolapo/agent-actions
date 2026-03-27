"""Tests for ``agac init --example`` functionality (GitHub-fetch approach)."""

import io
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

import click
import pytest

from agent_actions.cli.init import (
    _fetch_example,
    _list_remote_examples,
    _print_available_examples,
)

# ---------------------------------------------------------------------------
# Helpers — build a fake GitHub tarball in memory
# ---------------------------------------------------------------------------


def _make_tarball(examples: dict[str, dict[str, str]]) -> bytes:
    """Build a gzipped tarball mimicking GitHub's ``/tarball/`` response.

    *examples* maps ``example_name`` → ``{relative_path: file_content}``.
    The tarball root is ``Owner-repo-abc1234/``.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        root = "Owner-repo-abc1234"
        for example_name, files in examples.items():
            for rel_path, content in files.items():
                full = f"{root}/examples/{example_name}/{rel_path}"
                data = content.encode()
                info = tarfile.TarInfo(name=full)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_FAKE_EXAMPLES = {
    "contract_reviewer": {
        "agent_actions.yml": "name: contract_reviewer\n",
        "README.md": "# Contract Reviewer\nA sample example.\n",
        "tools/__init__.py": "",
    },
    "book_catalog": {
        "agent_actions.yml": "name: book_catalog\n",
        "README.md": "# Book Catalog\nAnother example.\n",
    },
}

_FAKE_TARBALL = _make_tarball(_FAKE_EXAMPLES)

_FAKE_CONTENTS_API = json.dumps(
    [
        {"name": "contract_reviewer", "type": "dir"},
        {"name": "book_catalog", "type": "dir"},
        {"name": "README.md", "type": "file"},  # should be ignored
    ]
).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dest(tmp_path: Path) -> Path:
    return tmp_path / "my_project"


def _mock_github_request(url: str) -> bytes:
    """Route fake responses based on URL pattern."""
    if "/contents/examples" in url:
        return _FAKE_CONTENTS_API
    if "/tarball/" in url:
        return _FAKE_TARBALL
    if "README.md" in url:
        name = url.split("/examples/")[1].split("/")[0]
        readme = _FAKE_EXAMPLES.get(name, {}).get("README.md", "")
        return readme.encode()
    raise ValueError(f"Unmocked URL: {url}")


# ---------------------------------------------------------------------------
# _list_remote_examples
# ---------------------------------------------------------------------------


class TestListRemoteExamples:
    def test_returns_sorted_names(self) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            examples = _list_remote_examples()
        names = [e["name"] for e in examples]
        assert names == ["book_catalog", "contract_reviewer"]

    def test_includes_description(self) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            examples = _list_remote_examples()
        by_name = {e["name"]: e for e in examples}
        assert by_name["contract_reviewer"]["description"] == "Contract Reviewer"

    def test_network_error_raises(self) -> None:
        with patch(
            "agent_actions.cli.init._github_request",
            side_effect=click.ClickException("no internet"),
        ):
            with pytest.raises(click.ClickException, match="no internet"):
                _list_remote_examples()


# ---------------------------------------------------------------------------
# _print_available_examples
# ---------------------------------------------------------------------------


class TestPrintAvailableExamples:
    def test_prints_example_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            _print_available_examples()
        out = capsys.readouterr().out
        assert "contract_reviewer" in out
        assert "book_catalog" in out

    def test_prints_error_on_network_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "agent_actions.cli.init._github_request",
            side_effect=click.ClickException("offline"),
        ):
            _print_available_examples()
        assert "Could not fetch examples" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _fetch_example — happy path
# ---------------------------------------------------------------------------


class TestFetchExampleHappyPath:
    def test_extracts_files(self, dest: Path) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            _fetch_example("contract_reviewer", dest)
        assert dest.is_dir()
        assert (dest / "agent_actions.yml").exists()
        assert (dest / "README.md").exists()

    def test_preserves_subdirectories(self, dest: Path) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            _fetch_example("contract_reviewer", dest)
        assert (dest / "tools" / "__init__.py").exists()

    def test_force_overwrites(self, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / "old_file.txt").write_text("old")
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            _fetch_example("contract_reviewer", dest, force=True)
        assert not (dest / "old_file.txt").exists()
        assert (dest / "agent_actions.yml").exists()


# ---------------------------------------------------------------------------
# _fetch_example — error paths
# ---------------------------------------------------------------------------


class TestFetchExampleErrors:
    def test_unknown_example(self, dest: Path) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            with pytest.raises(click.BadParameter, match="Unknown example 'nonexistent'"):
                _fetch_example("nonexistent", dest)

    def test_unknown_example_lists_available(self, dest: Path) -> None:
        with patch("agent_actions.cli.init._github_request", side_effect=_mock_github_request):
            with pytest.raises(click.BadParameter, match="contract_reviewer"):
                _fetch_example("nonexistent", dest)

    def test_dest_exists_without_force(self, dest: Path) -> None:
        dest.mkdir(parents=True)
        with pytest.raises(click.ClickException, match="already exists"):
            _fetch_example("contract_reviewer", dest)

    def test_network_error(self, dest: Path) -> None:
        with patch(
            "agent_actions.cli.init._github_request",
            side_effect=click.ClickException("timeout"),
        ):
            with pytest.raises(click.ClickException, match="timeout"):
                _fetch_example("contract_reviewer", dest)


# ---------------------------------------------------------------------------
# Mutual exclusivity: --example vs --template
# ---------------------------------------------------------------------------


class TestMutualExclusivity:
    def test_example_and_template_raises(self) -> None:
        from click.testing import CliRunner

        from agent_actions.cli.init import init

        runner = CliRunner()
        result = runner.invoke(init, ["my_proj", "--example", "contract_reviewer", "-t", "full"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()
