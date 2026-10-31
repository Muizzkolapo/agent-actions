"""`--rerun` takes the name a versioned action is written under in the config.

`vote_direct` runs as `vote_direct_1` and `vote_direct_2`. The user writes `vote_direct`, so
`--rerun vote_direct` answers both versions again, with everything reading them.
"""

import re

from tests.integration.test_a_config_edit_keeps_the_answers import (
    ITEMS,
    WORKFLOW,
    _agac,
    _ran,
    completed,  # noqa: F401 — fixture
    project,  # noqa: F401 — fixture
)


def _rerun_line(result):
    found = re.findall(r"--rerun: (.*?) answer every record again", result.printed)
    assert len(found) == 1, result.printed
    return sorted(found[0].split(", "))


def test_rerun_of_a_versioned_actions_base_name_answers_every_version_again(completed):  # noqa: F811
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "vote_direct")

    assert result.returncode == 0, result.printed
    assert _rerun_line(result) == [
        "after_recap",
        "merge_direct",
        "recap",
        "vote_direct_1",
        "vote_direct_2",
    ]
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}


def test_rerun_of_one_version_leaves_the_other_version_complete(completed):  # noqa: F811
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "vote_direct_1")

    assert result.returncode == 0, result.printed
    assert "vote_direct_2" not in _rerun_line(result)
    assert "vote_direct_1" in _rerun_line(result)
