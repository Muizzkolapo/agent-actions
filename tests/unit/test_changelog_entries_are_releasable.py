"""Every unreleased changelog entry must survive the release that reads it.

Nothing else looks at `.changes/`. CI checks only that a `.yaml` file exists in
`unreleased/` (`.github/workflows/ci.yml`), ruff and mypy do not read YAML, and no other
test opens the directory. So a malformed entry passes every gate and surfaces at
`changie batch` during a release -- by which time the PR that introduced it merged long
ago, and whoever is cutting the release has to work out which entry is broken and what it
was meant to say. That has now happened twice: an entry whose quoted scalar never closed,
and one missing `time:`, which `changie batch` reads.

The checks mirror what a release consumes: the file parses as a mapping, `kind` is one of
the labels `.changie.yaml` declares, and `body` and `time` are present and non-empty.
`_problems` is the single implementation -- the real entries and the negative controls
below both go through it, so a check that stops working stops working for both.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNRELEASED = _REPO_ROOT / ".changes" / "unreleased"
_CHANGIE_CONFIG = _REPO_ROOT / ".changie.yaml"


def _declared_kinds() -> set[str]:
    config = yaml.safe_load(_CHANGIE_CONFIG.read_text(encoding="utf-8"))
    return {kind["label"] for kind in config["kinds"]}


def _entry_paths() -> list[Path]:
    return sorted(_UNRELEASED.glob("*.yaml"))


def _problems(raw: str, kinds: set[str]) -> list[str]:
    """Every reason a release would reject this entry, or an empty list."""
    try:
        entry = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [f"does not parse as YAML: {exc.__class__.__name__}"]

    if not isinstance(entry, dict):
        return [f"is not a mapping, but {type(entry).__name__}"]

    found = []
    kind = entry.get("kind")
    if kind not in kinds:
        found.append(f"kind {kind!r} is not one of the labels .changie.yaml declares")
    body = entry.get("body")
    if not isinstance(body, str) or not body.strip():
        found.append("body is missing or empty")
    if not entry.get("time"):
        found.append("time is missing or empty, and changie batch reads it")
    return found


class TestTheGateIsLookingAtSomething:
    """Without these, a moved directory makes every test below vanish and pass silently."""

    def test_the_changie_config_declares_kinds(self):
        kinds = _declared_kinds()
        assert kinds, f"{_CHANGIE_CONFIG} declares no kinds"

    def test_the_unreleased_directory_holds_entries(self):
        assert _UNRELEASED.is_dir(), f"{_UNRELEASED} is not a directory"
        assert _entry_paths(), f"{_UNRELEASED} holds no .yaml entries -- nothing was checked"


@pytest.mark.parametrize("path", _entry_paths(), ids=lambda p: p.name)
def test_an_unreleased_entry_would_survive_the_release(path: Path):
    found = _problems(path.read_text(encoding="utf-8"), _declared_kinds())
    assert found == [], f"{path.name}: " + "; ".join(found)


class TestTheChecksCanActuallyFail:
    """Negative controls. Each feeds `_problems` the defect it exists to catch."""

    KINDS = {"Bug Fix", "Under the Hood"}

    def test_an_unclosed_quoted_scalar_is_reported(self):
        raw = 'kind: Bug Fix\nbody: "never closed\ntime: 2026-01-01T00:00:00Z\n'
        assert any("does not parse as YAML" in p for p in _problems(raw, self.KINDS))

    def test_a_missing_time_is_reported(self):
        raw = "kind: Bug Fix\nbody: a real body\n"
        assert any("time is missing" in p for p in _problems(raw, self.KINDS))

    def test_an_undeclared_kind_is_reported(self):
        raw = "kind: Documentation\nbody: a real body\ntime: 2026-01-01T00:00:00Z\n"
        assert any("is not one of the labels" in p for p in _problems(raw, self.KINDS))

    def test_an_empty_body_is_reported(self):
        raw = "kind: Bug Fix\nbody: '   '\ntime: 2026-01-01T00:00:00Z\n"
        assert any("body is missing or empty" in p for p in _problems(raw, self.KINDS))

    def test_a_bare_scalar_file_is_reported(self):
        assert any("is not a mapping" in p for p in _problems("just a string\n", self.KINDS))

    def test_a_well_formed_entry_reports_nothing(self):
        raw = "kind: Bug Fix\nbody: a real body\ntime: 2026-01-01T00:00:00Z\n"
        assert _problems(raw, self.KINDS) == []
