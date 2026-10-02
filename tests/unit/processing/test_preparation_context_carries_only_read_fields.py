"""`PreparationContext` carries only fields something reads.

It is an input struct with two builders, and three of its fields were assigned by both and
read by neither: `file_path`, `output_directory` and `record_index`. Nothing in the package
read them off a `PreparationContext` -- the same-named reads elsewhere are on
`ProcessingContext` and `DataPreparationContext`, different classes -- and the only reference
was a test asserting the copy itself.

A field nothing reads is not free: it has to be threaded through every builder, and the batch
builder took two parameters purely to derive and set one of them.
"""

from __future__ import annotations

import dataclasses

from agent_actions.processing.prepared_task import PreparationContext

_REMOVED = ("file_path", "output_directory", "record_index")


class TestTheDeadFieldsAreGone:
    def test_none_of_them_is_declared(self):
        declared = {f.name for f in dataclasses.fields(PreparationContext)}
        assert declared.isdisjoint(_REMOVED), sorted(declared & set(_REMOVED))

    def test_constructing_with_one_is_refused(self):
        """A silent tolerate would let a caller believe it had been carried."""
        for name in _REMOVED:
            try:
                PreparationContext(agent_config={}, agent_name="x", **{name: "v"})
            except TypeError:
                continue
            raise AssertionError(f"PreparationContext accepted a removed field: {name}")

    def test_the_fields_something_does_read_are_still_carried(self):
        """The control: removal must not have taken a live field with it."""
        declared = {f.name for f in dataclasses.fields(PreparationContext)}
        for name in (
            "agent_config",
            "agent_name",
            "current_item",
            "storage_backend",
            "tools_path",
            "is_first_stage",
            "mode",
            "source_data",
            "agent_indices",
            "dependency_configs",
            "workflow_metadata",
            "version_context",
        ):
            assert name in declared, name
