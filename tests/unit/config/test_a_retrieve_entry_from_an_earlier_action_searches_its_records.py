"""What the load makes of `context_scope.retrieve` with `from:` an earlier action, and refuses."""

from __future__ import annotations

import pytest

from agent_actions.config.retrieve import expand_retrieves
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin_spec import checked_builtin
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

WF = "agent_config/wf.yml"
LABEL = "link: retrieve 'similar' (link__similar)"


@pytest.fixture(autouse=True)
def knowledge(monkeypatch):
    return install_fake_knowledge(monkeypatch, FakeBase("help_center"), FakeBase("both"))


def _action(name, **extra):
    return {"name": name, "intent": "x", "prompt": "p", "schema": {"x": "string"}, **extra}


def _similar(**entry):
    entry = {
        "from": "summarize",
        "text": ["summary", "keywords"],
        "query": "summarize.summary",
        **entry,
    }
    return {"similar": entry}


def _workflow(retrieve=None, *, extra=None, depends=("summarize",), defaults=None):
    scope = {"observe": ["summarize.*"], "retrieve": retrieve or _similar()}
    data = {
        "name": "wf",
        "actions": [
            _action("summarize"),
            *(extra or []),
            _action("link", dependencies=list(depends), context_scope=scope),
        ],
    }
    if defaults is not None:
        data["defaults"] = defaults
    return data


def _step(data, tmp_path):
    expanded = expand_retrieves(data, WF, tmp_path)
    return {a["name"]: a for a in expanded["actions"] if "name" in a}["link__similar"]


def _refusal(data, tmp_path):
    with pytest.raises(ConfigurationError) as caught:
        expand_retrieves(data, WF, tmp_path)
    return str(caught.value)


class TestTheStep:
    def test_the_step_searches_the_records_of_the_action_from_names(self, tmp_path):
        step = _step(_workflow(_similar(id="ticket_id", title="product")), tmp_path)

        assert step["_builtin"] == {
            "tool": "retrieve",
            "corpus": {
                "action": "summarize",
                "text": ["summary", "keywords"],
                "title": "product",
                "id": "ticket_id",
            },
            "methods": {"keyword": 1.0},
            "query": ["summarize.summary"],
            "where": {},
            "top_k": 5,
            "candidates": 20,
            "max_context_tokens": None,
            "max_per_origin": None,
            "entry": "similar",
            "action": "link",
        }
        assert checked_builtin(step["_builtin"]) == step["_builtin"]
        assert step["intent"] == "Retrieve from the records of action summarize for link"

    def test_text_may_name_one_field_and_title_and_id_are_optional(self, tmp_path):
        step = _step(_workflow(_similar(text="summary")), tmp_path)

        assert step["_builtin"]["corpus"] == {
            "action": "summarize",
            "text": ["summary"],
            "title": None,
            "id": None,
        }

    def test_the_action_from_names_is_a_dependency_of_the_step_beside_the_actions_own(
        self, tmp_path
    ):
        data = _workflow(
            _similar(query="source.text"),
            extra=[_action("classify", dependencies=["summarize"])],
            depends=("classify",),
        )

        step = _step(data, tmp_path)

        assert step["dependencies"] == ["classify", "summarize"]
        assert "summarize.*" in step["context_scope"]["observe"]

    def test_a_where_field_names_an_output_field_outside_the_text(self, tmp_path):
        step = _step(_workflow(_similar(where={"product": "billing"})), tmp_path)

        assert step["_builtin"]["where"] == {"product": {"value": "billing"}}

    def test_the_methods_of_a_search_of_records_are_keyword_all_words_phrase_and_fuzzy(
        self, tmp_path
    ):
        step = _step(_workflow(_similar(method=["keyword", "fuzzy"])), tmp_path)

        assert step["_builtin"]["methods"] == {"keyword": 1.0, "fuzzy": 1.0}

    def test_a_join_may_be_searched(self, tmp_path):
        data = _workflow(
            _similar(**{"from": "assigned"}),
            extra=[
                _action("left", dependencies=["summarize"]),
                {"join": "assigned", "of": ["left"]},
            ],
            depends=("assigned",),
        )

        assert _step(data, tmp_path)["_builtin"]["corpus"]["action"] == "assigned"


class TestTheRefusals:
    @pytest.mark.parametrize(
        ("entry", "words"),
        [
            ({"text": None}, "'text:' must name the output field of 'summarize'"),
            ({"text": []}, "'text:' must name the output field"),
            ({"text": [{"a": 1}]}, "'text:' must name the output field"),
            ({"text": ["summary", "summary"]}, "names a field twice"),
            ({"id": ["ticket_id"]}, "'id:' must name one output field"),
            ({"title": 3}, "'title:' must name one output field"),
            ({"max_per_origin": 2}, "'max_per_origin' does not apply to the records of one"),
            ({"weights": {}}, "unknown key weights"),
            ({"method": "key"}, "method 'key' on the records of an action comes in a later"),
            ({"method": "semantic"}, "no search method"),
            ({"where": {"summary": "x"}}, "no metadata field of action 'summarize' outside"),
            ({"top_k": 51}, "'top_k:' must be a whole number from 1 to 50"),
        ],
    )
    def test_the_load_refuses(self, tmp_path, entry, words):
        message = _refusal(_workflow(_similar(**entry)), tmp_path)

        assert words in message
        assert "link: retrieve 'similar' (link__similar)" in message

    def test_an_action_that_is_not_upstream_is_refused(self, tmp_path):
        data = _workflow(_similar(query="source.text"), depends=())

        assert "names an action that is not upstream of the action" in _refusal(data, tmp_path)

    def test_the_action_itself_is_refused(self, tmp_path):
        data = _workflow(_similar(**{"from": "link"}, query="source.text"))

        assert "'from: link' names an action that is not upstream" in _refusal(data, tmp_path)

    def test_a_name_that_is_both_a_base_and_an_action_is_refused(self, tmp_path):
        data = _workflow(
            _similar(**{"from": "both"}, query="source.text"),
            extra=[_action("both")],
            depends=("both",),
        )

        assert "names both a knowledge base of agent_actions.yml and an action" in _refusal(
            data, tmp_path
        )

    def test_a_file_granularity_tool_is_refused(self, tmp_path):
        tool = {"name": "files", "kind": "tool", "impl": "f", "granularity": "File"}
        data = _workflow(_similar(**{"from": "files"}), extra=[tool], depends=("files",))

        assert "'from: files' names a tool of granularity File" in _refusal(data, tmp_path)

    def test_a_tool_that_inherits_file_granularity_is_refused(self, tmp_path):
        tool = {"name": "files", "kind": "tool", "impl": "f"}
        data = _workflow(
            _similar(**{"from": "files"}),
            extra=[tool],
            depends=("files",),
            defaults={"granularity": "file"},
        )

        assert "names a tool of granularity File" in _refusal(data, tmp_path)

    def test_a_tool_that_inherits_file_granularity_from_the_project_is_refused(self, tmp_path):
        (tmp_path / "agent_actions.yml").write_text("default_agent_config:\n  granularity: file\n")
        tool = {"name": "files", "kind": "tool", "impl": "f"}
        data = _workflow(_similar(**{"from": "files"}), extra=[tool], depends=("files",))

        assert "names a tool of granularity File" in _refusal(data, tmp_path)

    def test_a_hitl_action_is_accepted(self, tmp_path):
        review = _action("review", kind="hitl")
        data = _workflow(
            _similar(**{"from": "review"}), extra=[review], depends=("summarize", "review")
        )

        expanded = expand_retrieves(data, WF, tmp_path)

        assert "link__similar" in {a.get("name") for a in expanded["actions"]}

    def test_a_version_group_is_refused(self, tmp_path):
        score = _action("score", versions={"param": "rater", "range": [1, 2]})
        data = _workflow(_similar(**{"from": "score"}), extra=[score], depends=("score",))

        message = _refusal(data, tmp_path)

        assert "'from: score' names a version group, which fans out each record" in message
        assert "Name the action that merges them" in message

    def test_a_version_of_a_group_that_fans_out_is_refused(self, tmp_path):
        score = _action("score", versions={"param": "rater", "range": [1, 2]})
        data = _workflow(_similar(**{"from": "score_1"}), extra=[score], depends=("score",))

        assert "'from: score_1' names a version of 'score'" in _refusal(data, tmp_path)

    def test_an_action_a_router_reads_is_upstream_of_its_branches(self, tmp_path):
        scope = {"observe": ["summarize.*"], "retrieve": _similar()}
        data = {
            "name": "wf",
            "actions": [
                _action("summarize"),
                {"route": "by_queue", "on": "summarize.queue", "cases": {"a": ["link"]}},
                _action("link", context_scope=scope),
            ],
        }

        expanded = expand_retrieves(data, WF, tmp_path)

        assert "link__similar" in {a.get("name") for a in expanded["actions"]}

    def test_a_router_is_refused(self, tmp_path):
        router = {"route": "by_queue", "on": "summarize.queue", "cases": {"a": ["x"]}}
        data = _workflow(_similar(**{"from": "by_queue"}), extra=[router], depends=("by_queue",))

        assert "'from: by_queue' names a router" in _refusal(data, tmp_path)

    def test_a_loop_name_is_refused(self, tmp_path):
        loop = {
            "name": "rounds",
            "kind": "tool",
            "impl": "agac.pick",
            "dependencies": ["summarize"],
            "_builtin": {"tool": "pick", "of": ["x"], "loop": {"result": "check_reply"}},
        }
        data = _workflow(_similar(**{"from": "rounds"}), extra=[loop], depends=("rounds",))

        message = _refusal(data, tmp_path)

        assert "'from: rounds' names a loop" in message
        assert "rounds_iter1__check_reply" in message

    def test_text_title_and_id_stay_refused_on_a_knowledge_base(self, tmp_path):
        data = _workflow(
            {"help": {"from": "help_center", "query": "source.text", "id": "ticket_id"}}
        )

        assert "is set on the knowledge base's source" in _refusal(data, tmp_path)
