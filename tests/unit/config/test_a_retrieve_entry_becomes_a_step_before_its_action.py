"""What the load makes of `context_scope.retrieve` on an action, and what it refuses."""

from __future__ import annotations

import copy

import pytest

from agent_actions.config.retrieve import expand_retrieves, finish_retrieve_routes
from agent_actions.config.routes import expand_routes
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin_spec import checked_builtin
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

WF = "agent_config/wf.yml"


@pytest.fixture(autouse=True)
def knowledge(monkeypatch):
    return install_fake_knowledge(
        monkeypatch,
        FakeBase("help_center", index=["keyword", "fuzzy"], metadata_fields={"product"}),
        FakeBase("faq", index=["keyword"], has_key=True),
    )


def _action(name, **extra):
    return {"name": name, "intent": "x", "prompt": "p", "schema": {"x": "string"}, **extra}


def _retrieve(**entry):
    return {"help": {"from": "help_center", "query": "source.text", **entry}}


def _workflow(retrieve=None, *, reply=None, actions=None):
    scope = {"observe": ["source.*"], "retrieve": retrieve or _retrieve()}
    return {
        "name": "wf",
        "actions": [
            _action("classify"),
            _action(
                "write_reply", dependencies=["classify"], context_scope=scope, **(reply or {})
            ),
            *(actions or []),
        ],
    }


def _by_name(data):
    return {a["name"]: a for a in data["actions"]}


def _expanded(data, tmp_path):
    return _by_name(expand_retrieves(data, WF, tmp_path))


def _refusal(data, tmp_path):
    with pytest.raises(ConfigurationError) as caught:
        expand_retrieves(data, WF, tmp_path)
    return str(caught.value)


class TestTheStep:
    def test_each_entry_becomes_a_built_in_retrieve_step_named_after_its_action(self, tmp_path):
        data = expand_retrieves(_workflow(), WF, tmp_path)

        assert [a["name"] for a in data["actions"]] == [
            "classify",
            "write_reply__help",
            "write_reply",
        ]
        step = _by_name(data)["write_reply__help"]
        assert step["kind"] == "tool"
        assert step["impl"] == "agac.retrieve"
        assert step["_builtin"] == {
            "tool": "retrieve",
            "base": "help_center",
            "methods": {"keyword": 1.0},
            "query": ["source.text"],
            "where": {},
            "top_k": 5,
            "candidates": 20,
            "max_context_tokens": None,
            "max_per_origin": None,
            "entry": "help",
            "action": "write_reply",
        }
        assert checked_builtin(step["_builtin"]) == step["_builtin"]

    def test_the_action_depends_on_the_step_and_observes_all_of_it(self, tmp_path):
        reply = _expanded(_workflow(), tmp_path)["write_reply"]

        assert reply["dependencies"] == ["classify", "write_reply__help"]
        assert reply["context_scope"] == {"observe": ["source.*", "write_reply__help.*"]}

    def test_the_step_depends_on_what_its_query_and_where_read_and_observes_it(self, tmp_path):
        data = _workflow(
            _retrieve(
                query=["source.subject", "classify.keywords"],
                where={"product": "classify.product"},
            )
        )
        step = _expanded(data, tmp_path)["write_reply__help"]

        assert step["dependencies"] == ["classify"]
        assert step["context_scope"] == {
            "observe": ["source.subject", "classify.keywords", "classify.product"]
        }
        assert step["_builtin"]["where"] == {"product": "classify.product"}

    def test_a_step_that_reads_only_source_takes_all_of_its_actions_dependencies(self, tmp_path):
        assert _expanded(_workflow(), tmp_path)["write_reply__help"]["dependencies"] == [
            "classify"
        ]

    def test_the_step_takes_its_actions_dependencies_and_then_what_its_refs_read(self, tmp_path):
        data = _workflow(_retrieve(query=["source.text", "first.keywords"]))
        data["actions"][1]["dependencies"] = ["classify", "second"]
        data["actions"][1:1] = [_action("first"), _action("second", dependencies=["first"])]

        step = _expanded(data, tmp_path)["write_reply__help"]

        assert step["dependencies"] == ["classify", "second", "first"]

    def test_the_step_observes_each_dependency_its_refs_do_not_read_whole(self, tmp_path):
        step = _expanded(_workflow(), tmp_path)["write_reply__help"]

        assert step["context_scope"] == {"observe": ["source.text", "classify.*"]}

    def test_the_step_of_a_version_merge_takes_its_version_consumption(self, tmp_path):
        merge = {"source": "classify", "pattern": "merge"}
        step = _expanded(_workflow(reply={"version_consumption": merge}), tmp_path)[
            "write_reply__help"
        ]

        assert step["version_consumption"] == merge

    def test_a_later_action_in_a_route_branch_has_its_step_after_the_earlier_one(self, tmp_path):
        later = _action(
            "follow_up",
            dependencies=["write_reply"],
            context_scope={"observe": ["write_reply.*"], "retrieve": _retrieve()},
        )
        data = _workflow(actions=[later])
        data["actions"][1]["context_scope"].pop("retrieve")
        data["actions"].insert(
            1,
            {
                "route": "router",
                True: "classify.kind",
                "cases": {"a": ["write_reply"]},
                "default": "filter",
            },
        )
        data = expand_routes(expand_retrieves(data, WF, tmp_path), WF)
        finish_retrieve_routes(data)
        actions = _by_name(data)

        step = actions["follow_up__help"]
        assert step["dependencies"] == ["write_reply"]
        assert "guard" not in step
        assert actions["write_reply"]["guard"]["condition"] == 'router.case == "a"'

    def test_the_step_has_the_fixed_output_schema(self, tmp_path):
        schema = _expanded(_workflow(), tmp_path)["write_reply__help"]["schema"]

        assert [f["id"] for f in schema["fields"]] == ["matches", "count", "query", "index"]
        assert all(f["required"] for f in schema["fields"])
        item = schema["fields"][0]["items"]
        assert list(item["properties"]) == [
            "id",
            "rank",
            "score",
            "text",
            "title",
            "origin",
            "hash",
            "metadata",
        ]

    @pytest.mark.parametrize(
        ("method", "methods"),
        [
            ("fuzzy", {"fuzzy": 1.0}),
            (["keyword", "fuzzy"], {"keyword": 1.0, "fuzzy": 1.0}),
            ({"keyword": 0.7, "fuzzy": 0.3}, {"keyword": 0.7, "fuzzy": 0.3}),
        ],
    )
    def test_a_method_is_one_name_a_list_of_equal_weights_or_a_map_of_weights(
        self, tmp_path, method, methods
    ):
        step = _expanded(_workflow(_retrieve(method=method)), tmp_path)["write_reply__help"]

        assert step["_builtin"]["methods"] == methods

    def test_a_where_value_is_a_constant_unless_it_reads_source_or_an_upstream_action(
        self, tmp_path
    ):
        data = _workflow(_retrieve(where={"product": "billing.plan"}))
        assert _expanded(data, tmp_path)["write_reply__help"]["_builtin"]["where"] == {
            "product": {"value": "billing.plan"}
        }
        data = _workflow(_retrieve(where={"product": {"value": "source.x"}}))
        assert _expanded(data, tmp_path)["write_reply__help"]["_builtin"]["where"] == {
            "product": {"value": "source.x"}
        }

    def test_candidates_default_to_four_times_top_k_and_at_least_twenty(self, tmp_path):
        step = _expanded(_workflow(_retrieve(top_k=10)), tmp_path)["write_reply__help"]

        assert step["_builtin"]["candidates"] == 40

    def test_a_workflow_without_retrieve_is_left_as_it_is(self, tmp_path):
        data = {"name": "wf", "actions": [_action("a")]}

        assert expand_retrieves(copy.deepcopy(data), WF, tmp_path) == data

    def test_a_workflow_without_retrieve_never_reads_the_knowledge_config(
        self, tmp_path, monkeypatch
    ):
        import sys

        monkeypatch.delitem(sys.modules, "agent_actions.knowledge.api", raising=False)

        expand_retrieves({"name": "wf", "actions": [_action("a")]}, WF, tmp_path)

        assert "agent_actions.knowledge.api" not in sys.modules


class TestTheAlias:
    def test_retrieve_entry_in_the_action_scope_names_the_step(self, tmp_path):
        data = _workflow()
        data["actions"][1]["context_scope"]["passthrough"] = ["retrieve.help.count"]

        reply = _expanded(data, tmp_path)["write_reply"]

        assert reply["context_scope"]["passthrough"] == ["write_reply__help.count"]

    def test_retrieve_entry_in_the_guard_names_the_step(self, tmp_path):
        guard = {"condition": 'retrieve.help.count > 0 AND source.x != "retrieve.help"'}
        reply = _expanded(_workflow(reply={"guard": guard}), tmp_path)["write_reply"]

        assert reply["guard"]["condition"] == (
            'write_reply__help.count > 0 AND source.x != "retrieve.help"'
        )

    def test_an_alias_of_no_entry_is_refused_by_name(self, tmp_path):
        guard = {"condition": "retrieve.other.count > 0"}

        message = _refusal(_workflow(reply={"guard": guard}), tmp_path)

        assert "retrieve.other" in message
        assert "entries: help" in message

    def test_an_alias_on_an_action_with_no_entry_is_refused(self, tmp_path):
        data = {
            "name": "wf",
            "actions": [_action("a", context_scope={"observe": ["retrieve.help.matches"]})],
        }

        assert "retrieve.help" in _refusal(data, tmp_path)


class TestTheGuard:
    def test_the_step_takes_a_guard_that_reads_none_of_the_actions_entries(self, tmp_path):
        guard = {"condition": 'classify.kind == "question"', "on_false": "filter"}
        actions = _expanded(_workflow(reply={"guard": guard}), tmp_path)

        step = actions["write_reply__help"]
        assert step["guard"] == guard
        assert step["dependencies"] == ["classify"]
        assert "classify.kind" in step["context_scope"]["observe"]
        assert actions["write_reply"]["guard"] == guard

    def test_the_step_runs_for_every_record_when_the_guard_reads_its_own_entry(self, tmp_path):
        guard = {"condition": "retrieve.help.count > 0", "on_false": "filter"}
        actions = _expanded(_workflow(reply={"guard": guard}), tmp_path)

        assert "guard" not in actions["write_reply__help"]
        assert actions["write_reply"]["guard"]["condition"] == "write_reply__help.count > 0"

    def test_a_udf_guard_is_left_to_the_action(self, tmp_path):
        guard = {"condition": "udf:check"}

        assert (
            "guard"
            not in _expanded(_workflow(reply={"guard": guard}), tmp_path)["write_reply__help"]
        )

    def test_the_step_takes_the_route_entry_status_of_its_action(self, tmp_path):
        data = _workflow()
        data["actions"].insert(
            1,
            {
                "route": "router",
                True: "classify.kind",
                "cases": {"a": ["write_reply"]},
                "default": "filter",
            },
        )
        data["actions"][2]["dependencies"] = []
        data = expand_routes(expand_retrieves(data, WF, tmp_path), WF)
        finish_retrieve_routes(data)
        actions = _by_name(data)

        step = actions["write_reply__help"]
        assert step["guard"] == actions["write_reply"]["guard"]
        assert step["guard"]["condition"] == 'router.case == "a"'
        assert step["_sends_elsewhere"] is True
        assert step["dependencies"] == ["router"]
        assert "router.case" in step["context_scope"]["observe"]


class TestTheRefusals:
    @pytest.mark.parametrize(
        ("entry", "words"),
        [
            ({"from": "help_centre"}, "Did you mean 'help_center'"),
            ({"method": "fuzzy", "from": "faq"}, "does not build"),
            ({"method": ["key", "keyword"], "from": "faq"}, "cannot be combined"),
            ({"method": "key"}, "to set 'id:'"),
            ({"method": "semantic"}, "no search method"),
            ({"method": {"keyword": 0}}, "weight above 0"),
            ({"where": {"team": "source.team"}}, "no metadata field"),
            ({"query": "later.text"}, "'later' is no action of the workflow upstream"),
            ({"query": "write_reply.text"}, "upstream of the action"),
            ({"where": {"product": "after.kind"}}, "upstream of the action"),
            ({"top_k": 0}, "'top_k:' must be a whole number from 1 to 50"),
            ({"top_k": 51}, "'top_k:' must be a whole number from 1 to 50"),
            ({"candidates": 2}, "'candidates:'"),
            ({"max_context_tokens": 0}, "'max_context_tokens:'"),
            ({"weights": {}}, "unknown key weights"),
            ({"text": ["body"]}, "set on the knowledge base's source"),
            ({"from": "classify"}, "retrieval from an action comes in a later version"),
            ({"query": []}, "'query:' must be a field reference"),
        ],
    )
    def test_the_load_refuses(self, tmp_path, entry, words):
        data = _workflow(_retrieve(**entry), actions=[_action("after")])

        message = _refusal(data, tmp_path)

        assert words in message
        assert "write_reply: retrieve 'help' (write_reply__help)" in message

    def test_an_entry_name_read_as_a_version_is_refused(self, tmp_path):
        data = _workflow({"help_2": {"from": "help_center", "query": "source.text"}})

        assert "reads as a version" in _refusal(data, tmp_path)

    def test_a_step_name_that_clashes_with_an_action_is_refused(self, tmp_path):
        data = _workflow(actions=[_action("write_reply__help")])

        assert "already an action" in _refusal(data, tmp_path)

    def test_an_action_named_retrieve_is_refused(self, tmp_path):
        data = {"name": "wf", "actions": [_action("retrieve")]}

        assert "'retrieve' cannot name an action" in _refusal(data, tmp_path)

    def test_retrieve_under_the_workflow_defaults_is_refused(self, tmp_path):
        data = _workflow()
        data["defaults"] = {"context_scope": {"retrieve": _retrieve()}}

        assert "under 'defaults:'" in _refusal(data, tmp_path)

    def test_retrieve_under_default_agent_config_is_refused(self, tmp_path):
        (tmp_path / "agent_actions.yml").write_text(
            "default_agent_config:\n  context_scope:\n    retrieve: {}\n"
        )

        assert "'default_agent_config:'" in _refusal(_workflow(), tmp_path)

    def test_a_retrieve_directive_the_load_did_not_expand_is_refused_by_the_normalizer(self):
        from agent_actions.input.context.normalizer import normalize_context_scope

        with pytest.raises(ConfigurationError, match="not under 'defaults:'"):
            normalize_context_scope({"retrieve": _retrieve()}, {})


class TestTheSpec:
    def _step(self, tmp_path):
        data = _workflow(_retrieve(query="classify.keywords"))
        return _expanded(data, tmp_path)["write_reply__help"]

    def test_the_step_validates_as_an_action(self, tmp_path):
        from agent_actions.config.schema import ActionConfig

        ActionConfig.model_validate(self._step(tmp_path))

    def test_a_step_that_does_not_depend_on_what_its_query_reads_is_refused(self, tmp_path):
        from pydantic import ValidationError

        from agent_actions.config.schema import ActionConfig

        step = {**self._step(tmp_path), "dependencies": []}

        with pytest.raises(ValidationError, match="retrieves with classify"):
            ActionConfig.model_validate(step)

    @pytest.mark.parametrize(
        "change", [{"top_k": 51}, {"query": []}, {"extra": 1}, {"methods": {}}]
    )
    def test_a_spec_the_step_cannot_run_is_refused(self, tmp_path, change):
        spec = {**self._step(tmp_path)["_builtin"], **change}

        with pytest.raises(ValueError):
            checked_builtin(spec)


def test_an_included_action_with_an_as_name_gets_a_step_under_its_final_name(tmp_path):
    from tests.unit.config.test_a_workflow_includes_a_branch_file import (
        B1,
        B2,
        A,
        C,
        _pair,
        _render,
    )

    b1 = copy.deepcopy(B1)
    b1["context_scope"]["retrieve"] = {"help": {"from": "help_center", "query": "a.text"}}
    c = {**copy.deepcopy(C), "dependencies": ["one__b2"]}
    c["context_scope"] = {"observe": ["one__b2.text"]}
    include = {"include": "pair", "as": "one", "inputs": {"a": "a"}}

    actions = _by_name(_render(tmp_path, [A, include, c], {"pair": _pair([b1, B2])}))

    assert actions["one__b1__help"]["_builtin"]["action"] == "one__b1"
    assert actions["one__b1__help"]["dependencies"] == ["a"]
    assert "one__b1__help" in actions["one__b1"]["dependencies"]
