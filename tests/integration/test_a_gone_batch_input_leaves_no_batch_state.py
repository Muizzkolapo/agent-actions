"""A batch action whose input file is gone forgets that file's batch state with its rows.

The walk deletes the file it stored for an input that is gone. Its context map, the inputs
it recorded and its registry entry go too; the other file's stay.
"""

import json

from agent_actions.cli.exit_codes import EXIT_SUCCESS
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from tests.integration.test_retry_selection_under_batch import (
    ACTION,
    WORKFLOW,
    _backend,
    _cycle,
    _project,
)

PAGES = "pages.json"
OTHER = "other.json"


def _staging(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"


def _batch_state(root):
    """{file: the batch keys it holds} and the files the registry names."""
    backend = _backend(root)
    try:
        keys = [
            key
            for prefix in (f"batch_context:{ACTION}:", f"batch_inputs:{ACTION}:")
            for key in backend.list_metadata_prefix(prefix)
        ]
        held = {
            name: sorted(key for key in keys if key.split(":", 2)[2].startswith(name))
            for name in (PAGES, OTHER)
        }
        return held, sorted(BatchRegistryManager(backend, ACTION).get_all_jobs())
    finally:
        backend.close()


def test_a_gone_input_leaves_no_batch_state_and_the_other_file_keeps_its_own(tmp_path):
    root = _project(tmp_path)
    for name, prefix in ((PAGES, "p"), (OTHER, "o")):
        _staging(root).joinpath(name).write_text(
            json.dumps([{"page_id": f"{prefix}{i}", "page_content": f"{name} {i}"} for i in (0, 1)])
        )
    _cycle(root, "run", "-a", WORKFLOW, "--fresh", ends_with=EXIT_SUCCESS)
    held, registry = _batch_state(root)
    assert held[PAGES] and held[OTHER], held
    assert registry == [OTHER, PAGES]
    kept = held[PAGES]

    _staging(root).joinpath(OTHER).unlink()
    transcript = _cycle(root, "run", "-a", WORKFLOW, ends_with=EXIT_SUCCESS)

    assert f"'{ACTION}' has no input for {OTHER} any more" in " ".join(" ".join(transcript).split())
    held, registry = _batch_state(root)
    assert held == {PAGES: kept, OTHER: []}
    assert registry == [PAGES]
