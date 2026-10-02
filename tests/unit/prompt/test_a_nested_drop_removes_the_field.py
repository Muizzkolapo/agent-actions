"""A nested `context_scope.drop` ref must remove the field, not silently keep it.

`drop` is how an author keeps a field out of a prompt, so an inert drop sends data to the
provider that was explicitly withheld. `observe` already traverses a dotted path via
`get_nested_value`; `drop` popped by exact key, so `upstream.body.text` matched no key and
the field survived.
"""

import logging

from agent_actions.prompt.context.scope_application import apply_context_scope


def _scoped(scope: dict) -> tuple[dict, dict, dict]:
    field_context = {
        "upstream": {"body": {"text": "SECRET", "ok": "1"}, "title": "keep me"},
    }
    return apply_context_scope(field_context, scope)


class TestANestedDropRemovesTheField:
    def test_a_nested_drop_keeps_the_value_out_of_the_llm_context(self):
        _, llm_context, _ = _scoped({"observe": ["upstream.*"], "drop": ["upstream.body.text"]})

        assert "SECRET" not in str(llm_context), llm_context

    def test_a_nested_drop_leaves_its_siblings_alone(self):
        prompt_context, _, _ = _scoped({"observe": ["upstream.*"], "drop": ["upstream.body.text"]})

        assert prompt_context["upstream"]["body"] == {"ok": "1"}
        assert prompt_context["upstream"]["title"] == "keep me"

    def test_a_nested_drop_removes_an_explicitly_passed_through_field(self):
        """passthrough stores an explicit nested ref under its LITERAL dotted key.

        Traversal alone misses it -- the key is the string `body.text`, not a path. This is
        the shape that actually leaked: withheld from the prompt, still written to output.
        """
        _, _, passthrough = _scoped(
            {
                "passthrough": ["upstream.body.text", "upstream.title"],
                "drop": ["upstream.body.text"],
            }
        )

        assert "SECRET" not in str(passthrough), passthrough
        assert passthrough["upstream"] == {"title": "keep me"}

    def test_a_nested_drop_removes_it_from_a_wildcard_passthrough(self):
        """A wildcard copies the nested dict instead, so this shape needs the traversal."""
        _, _, passthrough = _scoped({"passthrough": ["upstream.*"], "drop": ["upstream.body.text"]})

        assert "SECRET" not in str(passthrough), passthrough
        assert passthrough["upstream"]["body"] == {"ok": "1"}

    def test_a_flat_drop_still_works(self):
        prompt_context, _, _ = _scoped({"observe": ["upstream.*"], "drop": ["upstream.title"]})

        assert "title" not in prompt_context["upstream"]
        assert prompt_context["upstream"]["body"]["text"] == "SECRET"

    def test_a_whole_namespace_drop_still_works(self):
        prompt_context, _, _ = _scoped({"observe": ["upstream.*"], "drop": ["upstream.*"]})

        assert prompt_context.get("upstream", {}) == {}

    def test_a_nested_drop_naming_a_path_that_does_not_exist_is_not_silent(self, caplog):
        """A drop that matched nothing is a withheld field that was not withheld."""
        with caplog.at_level(logging.WARNING):
            _scoped({"observe": ["upstream.*"], "drop": ["upstream.body.absent"]})

        assert any("upstream.body.absent" in r.getMessage() for r in caplog.records), (
            "a drop matching nothing must say so above debug"
        )

    def test_an_inner_wildcard_drop_is_not_silent(self, caplog):
        """`a.*.c` is not a path the runtime can walk; saying nothing implies it worked."""
        with caplog.at_level(logging.WARNING):
            _scoped({"observe": ["upstream.*"], "drop": ["upstream.*.text"]})

        assert any("upstream.*.text" in r.getMessage() for r in caplog.records)


class TestFileModeAgreesWithRecordMode:
    """FILE mode applies drops through its own function, which had the identical flat pop."""

    def test_a_nested_drop_is_applied_in_file_mode(self):
        from agent_actions.prompt.context.scope_application import _apply_drops_to_content

        content = {"upstream": {"body": {"text": "SECRET", "ok": "1"}}}
        _apply_drops_to_content(content, ["upstream.body.text"])

        assert content == {"upstream": {"body": {"ok": "1"}}}

    def test_a_whole_namespace_drop_still_works_in_file_mode(self):
        from agent_actions.prompt.context.scope_application import _apply_drops_to_content

        content = {"upstream": {"body": {"text": "SECRET"}}}
        _apply_drops_to_content(content, ["upstream.*"])

        assert content == {"upstream": {}}


class TestTheTraversalIsExactlyAsWideAsAsked:
    """Two wrong implementations pass everything above; these are what separate them."""

    def test_a_nested_drop_spares_the_same_key_under_another_parent(self):
        """A delete-the-leaf-anywhere implementation removes three fields, not one."""
        from agent_actions.utils.dict import pop_nested_value

        data = {"a": {"b": 1}, "z": {"b": 2}, "b": 3}
        assert pop_nested_value(data, "a.b") is True
        assert data == {"a": {}, "z": {"b": 2}, "b": 3}, data

    def test_a_path_through_a_non_dict_returns_false_instead_of_raising(self):
        """`ns.items.text` where `items` is a list, or a scalar — an editor sees both."""
        from agent_actions.utils.dict import pop_nested_value

        assert pop_nested_value({"items": ["a", "b"]}, "items.text") is False
        assert pop_nested_value({"items": "scalar"}, "items.text") is False
        assert pop_nested_value({"items": None}, "items.text") is False
        assert pop_nested_value("not a dict", "a.b") is False
        assert pop_nested_value({"a": {"b": 5}}, "a.b.c") is False
        # FOUR segments is the shape that pins the guard INSIDE the loop: with three, the
        # scalar is reached as the loop ends and the final isinstance catches it. With
        # four, `"c" not in 5` is evaluated and raises TypeError without the guard.
        assert pop_nested_value({"a": {"b": 5}}, "a.b.c.d") is False
        assert pop_nested_value({"a": {"b": ["x"]}}, "a.b.c.d") is False

    def test_a_literal_dotted_key_is_removed_before_the_path_is_tried(self):
        """The framework stores one: merge_passthrough_namespaces copies it verbatim.

        Traversing only would leave it in place — which is how the first version of this
        fix removed the nested shape and stopped removing the literal one.
        """
        from agent_actions.utils.dict import pop_nested_value

        data = {"body.text": "SECRET", "body": {"text": "other"}}
        assert pop_nested_value(data, "body.text") is True
        assert data == {"body": {"text": "other"}}, data

    def test_a_literal_dotted_key_still_drops_end_to_end(self):
        """The shape the reviewer found regressed: RECORD mode, literal key, real leak."""
        _, llm_context, _ = apply_context_scope(
            {"ns": {"body.text": "SECRET"}},
            {"observe": ["ns.*"], "drop": ["ns.body.text"]},
        )

        assert "SECRET" not in str(llm_context), llm_context

    def test_a_literal_dotted_key_still_drops_in_file_mode(self):
        from agent_actions.prompt.context.scope_application import _apply_drops_to_content

        content = {"ns": {"body.text": "SECRET"}}
        _apply_drops_to_content(content, ["ns.body.text"])

        assert content == {"ns": {}}, content


class TestASeedDropDoesNotMutateTheCaller:
    """builder.py copies before dropping; a nested ref needs a deep copy to do that."""

    def test_a_nested_seed_drop_leaves_the_caller_s_seed_intact(self):
        from agent_actions.prompt.context.builder import LLMContextBuilder

        base = {"seed": {"rubric": {"public": "ok", "private": "SECRET"}}}
        result = LLMContextBuilder._build_llm_context(
            base_context=base,
            additional_context=None,
            context_scope={"drop": ["seed.rubric.private"]},
        )

        assert "SECRET" not in str(result), result
        assert base["seed"]["rubric"] == {"public": "ok", "private": "SECRET"}, (
            "a shallow copy shares the sub-dict, so the drop edits the caller's seed"
        )
