"""Every unreleased changelog entry must survive the release that reads it.

Nothing else looks at `.changes/`: CI checks only that a `.yaml` file exists in
`unreleased/`, ruff and mypy do not read YAML, and no other test opens the directory. So a
malformed entry surfaces at `changie batch`, with the PR that introduced it long merged.

`_problems` reports two separate things, and says which is which: shapes `changie batch`
genuinely rejects (exit 1), and two repo conventions it tolerates -- a non-empty `body`, and
a `time` field, which `changie new` always writes and all entries in the tree carry.
"""

from __future__ import annotations

from datetime import date, datetime
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
    except (yaml.YAMLError, ValueError) as exc:
        # ValueError, not YAMLError, is what PyYAML raises for a plain timestamp
        # scalar changie rejects (`06:70:00` -> "minute must be in 0..59").
        return [f"does not parse as YAML: {exc.__class__.__name__}: {exc}"]

    if not isinstance(entry, dict):
        return [f"is not a mapping, but {type(entry).__name__}"]

    found = []
    kind = entry.get("kind")
    if kind not in kinds:
        found.append(f"kind {kind!r} is not one of the labels .changie.yaml declares")
    body = entry.get("body")
    if not isinstance(body, str) or not body.strip():
        found.append("body is missing or empty (changie renders it, but no entry should)")
    found.extend(_time_problems(entry.get("time")))
    return found


def _time_problems(value: object) -> list[str]:
    """changie parses `time` as a timestamp and exits 1 when it cannot.

    Presence is not enough. PyYAML's timestamp resolver fires only on a *plain* scalar, so
    a quoted `'2026-04-21T06:70:00Z'` stays a `str` and reaches here unvalidated -- the exact
    shape changie rejects with "minute out of range".
    """
    if value is None:
        # changie accepts an entry with no `time`. Convention, not a release-breaker.
        return ["time is absent; changie new always writes one"]
    if isinstance(value, (datetime, date)):
        return []
    if not isinstance(value, str) or not value.strip():
        return ["time is empty, which changie rejects"]
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return [f"time {value!r} is not a timestamp changie can parse"]
    return []


class TestTheGateIsLookingAtSomething:
    """Without these, a moved directory makes every test below vanish and pass silently."""

    def test_the_changie_config_declares_kinds(self):
        kinds = _declared_kinds()
        assert kinds, f"{_CHANGIE_CONFIG} declares no kinds"
        # Non-empty is not enough: an over-broad reader would pass every entry.
        assert "Bug Fix" in kinds, sorted(kinds)

    def test_the_unreleased_directory_holds_entries(self):
        """Empty is a failure, not a pass: the test below is parametrized over this glob,
        so an empty list would make every case vanish and the suite go green having read
        nothing. `changie batch` empties the directory, so a local batch trips this."""
        assert _UNRELEASED.is_dir(), f"{_UNRELEASED} is not a directory"
        assert _entry_paths(), f"{_UNRELEASED} holds no .yaml entries -- nothing was checked"


@pytest.mark.parametrize("path", _entry_paths(), ids=lambda p: p.name)
def test_an_unreleased_entry_would_survive_the_release(path: Path):
    found = _problems(path.read_text(encoding="utf-8"), _declared_kinds())
    assert found == [], f"{path.name}: " + "; ".join(found)


class TestTheChecksCanActuallyFail:
    """Negative controls. Each feeds `_problems` the defect it exists to catch."""

    KINDS = {"Bug Fix", "Under the Hood"}

    def test_a_plain_timestamp_changie_rejects_is_reported(self):
        """`changie batch` exits 1 on this. PyYAML raises a bare ValueError, not a
        YAMLError, so a narrower except lets it through."""
        raw = "kind: Bug Fix\nbody: a real body\ntime: 2026-04-21T06:70:00Z\n"
        found = _problems(raw, self.KINDS)
        assert any("does not parse as YAML" in p for p in found), found
        assert any("minute" in p for p in found), found

    def test_a_quoted_timestamp_changie_rejects_is_reported(self):
        """The same bad value in quotes. PyYAML's resolver fires only on a plain
        scalar, so this stays a `str` and a presence check passes it straight through
        -- while changie still exits 1."""
        raw = "kind: Bug Fix\nbody: a real body\ntime: '2026-04-21T06:70:00Z'\n"
        found = _problems(raw, self.KINDS)
        assert any("not a timestamp changie can parse" in p for p in found), found

    @pytest.mark.parametrize(
        ("raw", "problem"),
        [
            (
                'kind: Bug Fix\nbody: "never closed\ntime: 2026-01-01T00:00:00Z\n',
                "does not parse as YAML",
            ),
            ("kind: Bug Fix\nbody: a real body\ntime: TBD\n", "not a timestamp"),
            # changie accepts an absent time; the check is repo convention, and says so.
            ("kind: Bug Fix\nbody: a real body\n", "time is absent"),
            (
                "kind: Documentation\nbody: a real body\ntime: 2026-01-01T00:00:00Z\n",
                "is not one of the labels",
            ),
            (
                "kind: Bug Fix\nbody: '   '\ntime: 2026-01-01T00:00:00Z\n",
                "body is missing or empty",
            ),
            ("just a string\n", "is not a mapping"),
        ],
        ids=[
            "unclosed-quote",
            "time-not-a-date",
            "absent-time-convention",
            "undeclared-kind",
            "empty-body",
            "bare-scalar",
        ],
    )
    def test_a_defective_entry_is_reported(self, raw, problem):
        found = _problems(raw, self.KINDS)
        assert any(problem in p for p in found), found

    @pytest.mark.parametrize(
        "raw",
        [
            # changie accepts a date-only time, so this check must not over-reject.
            "kind: Bug Fix\nbody: a real body\ntime: 2026-01-01\n",
            "kind: Bug Fix\nbody: a real body\ntime: 2026-01-01T00:00:00Z\n",
        ],
        ids=["date-only-time", "well-formed"],
    )
    def test_an_acceptable_entry_reports_nothing(self, raw):
        assert _problems(raw, self.KINDS) == []
