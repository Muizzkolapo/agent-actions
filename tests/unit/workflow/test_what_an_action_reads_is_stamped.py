"""What an action reads — its context_scope and dependencies — is stamped beside config_hash (1332).

Each has a digest of its own, so an edit names which part changed. Every stamp writer records
each digest, so one a stamp lacks reads as an edit of that part.
"""

from agent_actions.workflow.executor import (
    CONFIG_EDIT,
    MODEL_EDIT,
    _compute_action_config_hash,
    _compute_context_scope_hash,
    _compute_dependencies_hash,
    _compute_generation_hash,
    _compute_udf_source_hash,
    _edits_since,
    config_in_force,
    edits_since_its_work_began,
)

CONFIG = {
    "prompt": "p",
    "schema": "s",
    "model_name": "m",
    "model_vendor": "v",
    "dependencies": ["a", "b"],
    "context_scope": {"observe": ["a.x", "b.*"], "drop": ["a.y"]},
}


def _stamp(config):
    return config_in_force(config)


def _with_scope(**scope):
    return {**CONFIG, "context_scope": scope}


class TestTheConfigDigest:
    def test_config_hash_ignores_what_the_action_reads(self):
        assert _compute_action_config_hash(CONFIG) == _compute_action_config_hash(
            {"prompt": "p", "schema": "s"}
        )


class TestTheContextScopeDigest:
    def test_each_directive_counts(self):
        base = _compute_context_scope_hash(CONFIG)
        for scope in (
            {"observe": ["a.x", "b.*", "a.z"], "drop": ["a.y"]},
            {"observe": ["a.x", "b.*"]},
            {"observe": ["a.x", "b.*"], "drop": ["a.y"], "passthrough": ["a.z"]},
            {"observe": ["a.x", "b.*"], "drop": ["a.y"], "seed": {"ref": "$file:r.json"}},
        ):
            assert _compute_context_scope_hash(_with_scope(**scope)) != base, scope

    def test_order_and_repeats_within_a_list_do_not(self):
        reordered = _with_scope(drop=["a.y"], observe=["b.*", "a.x", "b.*"])
        assert _compute_context_scope_hash(reordered) == _compute_context_scope_hash(CONFIG)

    def test_an_empty_observe_is_not_an_absent_one(self):
        """`observe: []` gates the action to the framework's namespaces; absent, it is not."""
        assert _compute_context_scope_hash(_with_scope(observe=[])) != _compute_context_scope_hash(
            {**CONFIG, "context_scope": None}
        )


class TestTheDependenciesDigest:
    def test_an_added_or_removed_dependency_counts(self):
        base = _compute_dependencies_hash(CONFIG)
        assert _compute_dependencies_hash({**CONFIG, "dependencies": ["a"]}) != base
        assert _compute_dependencies_hash({**CONFIG, "dependencies": ["a", "b", "c"]}) != base

    def test_a_single_name_reads_as_a_list_of_one(self):
        assert _compute_dependencies_hash({"dependencies": "a"}) == _compute_dependencies_hash(
            {"dependencies": ["a"]}
        )


class TestEditsSince:
    def test_nothing_edited(self):
        assert _edits_since(_stamp(CONFIG), CONFIG) == []

    def test_each_edit_is_named(self):
        edited = {
            **CONFIG,
            "prompt": "q",
            "model_name": "n",
            "dependencies": ["a"],
            "context_scope": {"observe": ["a.x"]},
        }
        assert _edits_since(_stamp(CONFIG), edited) == [
            MODEL_EDIT,
            CONFIG_EDIT,
            "context scope",
            "dependencies",
        ]

    def test_a_stamp_without_a_part_names_that_part_as_edited(self):
        stamp = _stamp(CONFIG)
        del stamp["context_scope_hash"], stamp["model_vendor"]

        assert _edits_since(stamp, CONFIG) == [MODEL_EDIT, "context scope"]

    def test_a_model_recorded_as_none_and_now_set_is_an_edit(self):
        stamp = {**_stamp(CONFIG), "model_name": None}

        assert _edits_since(stamp, CONFIG) == [MODEL_EDIT]

    def test_an_action_stopped_partway_reads_a_scope_edit(self):
        details = {"answered_under": _stamp(CONFIG)}
        edited = _with_scope(observe=["a.x"])

        assert edits_since_its_work_began(details, edited) == ["context scope"]
        assert edits_since_its_work_began(details, CONFIG) == []
        assert edits_since_its_work_began({}, edited) is None


class TestTheGenerationDigest:
    """Generation settings are stamped beside config_hash (1601)."""

    def test_each_setting_a_client_sends_counts(self):
        from agent_actions.llm.providers.generation_params import GENERATION_PARAMS

        base = _compute_generation_hash(CONFIG)
        for key in GENERATION_PARAMS:
            assert _compute_generation_hash({**CONFIG, key: 1}) != base, key

    def test_an_unset_setting_is_no_setting(self):
        assert _compute_generation_hash({**CONFIG, "temperature": None}) == (
            _compute_generation_hash(CONFIG)
        )

    def test_a_non_llm_action_sends_none(self):
        for kind in ("tool", "hitl"):
            assert _compute_generation_hash({**CONFIG, "kind": kind, "temperature": 1}) == ""
        assert _compute_generation_hash({**CONFIG, "kind": "llm"}) == (
            _compute_generation_hash(CONFIG)
        )

    def test_an_edit_is_named(self):
        edited = {**CONFIG, "max_tokens": 50}

        assert _edits_since(_stamp(CONFIG), edited) == ["generation settings"]


class TestTheUdfSourceDigest:
    """The files a tool and a UDF guard were loaded from are stamped (1600)."""

    @staticmethod
    def _registered(monkeypatch, **digests):
        from agent_actions.workflow import executor

        monkeypatch.setattr(
            executor,
            "UDF_REGISTRY",
            {name: {"source_digest": digest} for name, digest in digests.items()},
        )

    def test_a_tool_and_its_guard_each_count(self, monkeypatch):
        tool = {
            "kind": "tool",
            "model_vendor": "tool",
            "model_name": "Tag",
            "conditional_clause": "gate",
        }
        self._registered(monkeypatch, tag="t1", gate="g1")
        base = _compute_udf_source_hash(tool)
        self._registered(monkeypatch, tag="t2", gate="g1")
        assert _compute_udf_source_hash(tool) != base
        self._registered(monkeypatch, tag="t1", gate="g2")
        assert _compute_udf_source_hash(tool) != base

    def test_an_llm_action_without_a_udf_guard_has_none(self, monkeypatch):
        self._registered(monkeypatch, gpt="x")
        assert _compute_udf_source_hash({"model_vendor": "openai", "model_name": "gpt"}) == ""

    def test_a_udf_not_loaded_is_not_compared(self, monkeypatch):
        self._registered(monkeypatch)
        tool = {"kind": "tool", "model_vendor": "tool", "model_name": "tag"}
        assert _compute_udf_source_hash(tool) is None
        assert _edits_since({**config_in_force(tool), "udf_source_hash": "old"}, tool) == []

    def test_an_edit_is_named(self, monkeypatch):
        tool = {"kind": "tool", "model_vendor": "tool", "model_name": "tag"}
        self._registered(monkeypatch, tag="t1")
        stamp = config_in_force(tool)
        self._registered(monkeypatch, tag="t2")

        assert _edits_since(stamp, tool) == ["tool/guard code"]


def test_a_udf_registers_with_the_digest_of_its_file(tmp_path):
    from agent_actions.utils.udf_management.registry import _source_digest

    source = tmp_path / "tool.py"
    source.write_text("a")
    first = _source_digest(str(source))
    source.write_text("b")

    assert first is not None and _source_digest(str(source)) != first
    assert _source_digest(str(tmp_path / "missing.py")) is None
