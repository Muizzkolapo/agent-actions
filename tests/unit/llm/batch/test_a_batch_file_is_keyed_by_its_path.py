"""Every key a batch keeps for an input file is the file's path under the input root.

Keyed by its basename, a file in a subdirectory shares its registry entry, context map,
recorded inputs and recovery state with every other file of that name, and its output
with a top-level one. A top-level file's key is its name.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    batch_output_name,
)
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager

KEYS = {
    "context map": (BatchContextManager._metadata_key, "batch_context"),
    "recorded inputs": (BatchContextManager._inputs_key, "batch_inputs"),
    "recovery state": (RecoveryStateManager._metadata_key, "recovery_state"),
}
EACH_KEY = pytest.mark.parametrize("key", KEYS.values(), ids=KEYS.keys())


@pytest.mark.parametrize(
    ("name", "stored"),
    [
        ("page.json", "page.json"),
        ("page.csv", "page.json"),
        ("sub/page.csv", "sub/page.json"),
        ("sub/page.json", "sub/page.json"),
        ("a/b/c.tar.gz", "a/b/c.tar.json"),
        ("noext", "noext.json"),
        (".hidden", ".hidden.json"),
    ],
)
def test_a_batch_output_is_stored_under_its_input_path_as_json(name, stored):
    assert batch_output_name(name) == stored


@EACH_KEY
@pytest.mark.parametrize(
    "name",
    [
        pytest.param("page.json", id="top-level-json"),
        pytest.param("page.csv", id="top-level-csv"),
        pytest.param("noext", id="top-level-noext"),
        pytest.param("sub/page.json", id="subdirectory-kept"),
        # The store refuses only a `..` that is a whole part; online writes these files.
        pytest.param("v1..2/page.json", id="dots-inside-directory-name"),
        pytest.param("notes..v2.json", id="dots-inside-file-name"),
    ],
)
def test_a_file_is_keyed_by_its_path_under_the_input_root(key, name):
    build, prefix = key
    assert build("act", name) == f"{prefix}:act:{name}"


@EACH_KEY
@pytest.mark.parametrize("name", ["../x.json", "a/../b.json", "/abs/x.json"])
def test_a_name_that_leaves_the_input_root_is_refused(key, name):
    build, _prefix = key
    with pytest.raises(ValueError):
        build("act", name)
