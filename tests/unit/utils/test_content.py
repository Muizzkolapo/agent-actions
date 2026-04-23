"""Tests for namespaced content utilities."""

from agent_actions.utils.content import (
    get_all_namespaces,
    get_existing_content,
    has_namespace,
    read_namespace,
    wrap_content,
)


class TestWrapContent:
    def test_first_action_creates_namespace(self):
        result = wrap_content("extract", {"text": "hello"})
        assert result == {"extract": {"text": "hello"}}

    def test_second_action_preserves_first(self):
        existing = {"extract": {"text": "hello"}}
        result = wrap_content("summarize", {"summary": "hi"}, existing)
        assert result == {
            "extract": {"text": "hello"},
            "summarize": {"summary": "hi"},
        }

    def test_three_actions_accumulate(self):
        c = wrap_content("a", {"x": 1})
        c = wrap_content("b", {"y": 2}, c)
        c = wrap_content("c", {"z": 3}, c)
        assert c == {"a": {"x": 1}, "b": {"y": 2}, "c": {"z": 3}}

    def test_does_not_mutate_existing(self):
        existing = {"extract": {"text": "hello"}}
        original_copy = dict(existing)
        wrap_content("summarize", {"summary": "hi"}, existing)
        assert existing == original_copy

    def test_none_existing_treated_as_empty(self):
        result = wrap_content("extract", {"text": "hello"}, None)
        assert result == {"extract": {"text": "hello"}}

    def test_same_action_name_overwrites(self):
        existing = {"extract": {"text": "v1"}}
        result = wrap_content("extract", {"text": "v2"}, existing)
        assert result["extract"]["text"] == "v2"


class TestReadNamespace:
    def test_read_field(self):
        record = {"content": {"extract": {"text": "hello", "url": "http://..."}}}
        assert read_namespace(record, "extract", "text") == "hello"

    def test_read_entire_namespace(self):
        record = {"content": {"extract": {"text": "hello"}}}
        assert read_namespace(record, "extract") == {"text": "hello"}

    def test_missing_namespace_returns_default(self):
        record = {"content": {"extract": {"text": "hello"}}}
        assert read_namespace(record, "summarize", "summary") is None
        assert read_namespace(record, "summarize", "summary", "fallback") == "fallback"

    def test_missing_field_returns_default(self):
        record = {"content": {"extract": {"text": "hello"}}}
        assert read_namespace(record, "extract", "missing") is None

    def test_empty_content(self):
        record = {"content": {}}
        assert read_namespace(record, "extract", "text") is None

    def test_no_content_key(self):
        record = {"source_guid": "abc"}
        assert read_namespace(record, "extract", "text") is None


class TestHasNamespace:
    def test_present(self):
        record = {"content": {"extract": {"text": "hello"}}}
        assert has_namespace(record, "extract") is True

    def test_absent(self):
        record = {"content": {"extract": {"text": "hello"}}}
        assert has_namespace(record, "summarize") is False

    def test_empty_content(self):
        record = {"content": {}}
        assert has_namespace(record, "extract") is False


class TestGetAllNamespaces:
    def test_multiple(self):
        record = {"content": {"a": {}, "b": {}, "c": {}}}
        assert get_all_namespaces(record) == ["a", "b", "c"]

    def test_empty(self):
        record = {"content": {}}
        assert get_all_namespaces(record) == []


class TestGetExistingContent:
    def test_returns_content(self):
        record = {"content": {"a": {"x": 1}}}
        assert get_existing_content(record) == {"a": {"x": 1}}

    def test_no_content_returns_empty(self):
        record = {"source_guid": "abc"}
        assert get_existing_content(record) == {}


class TestGuardSkipScenario:
    """The exact production scenario: generate → validate → rewrite(skip) → tool."""

    def test_skip_preserves_all_namespaces(self):
        # Step 1: generate
        content = wrap_content(
            "write_scenario_question",
            {
                "question": "What is X?",
                "options": ["A", "B", "C", "D"],
                "answer": "A",
            },
        )

        # Step 2: validate
        content = wrap_content(
            "validate_question_contract",
            {
                "violations": [],
                "pass": True,
            },
            content,
        )

        # Step 3: rewrite SKIPS — nothing added
        # (this is just: don't call wrap_content)

        # Step 4: tool reads
        record = {"content": content}

        # Question accessible from generate namespace
        question = read_namespace(record, "write_scenario_question", "question")
        assert question == "What is X?"

        # Validation accessible from validate namespace
        passed = read_namespace(record, "validate_question_contract", "pass")
        assert passed is True

        # Rewrite namespace absent
        assert has_namespace(record, "rewrite_failed_question") is False

        # All namespaces present
        assert get_all_namespaces(record) == [
            "write_scenario_question",
            "validate_question_contract",
        ]

    def test_rewrite_runs_adds_namespace(self):
        content = wrap_content(
            "write_scenario_question",
            {
                "question": "Bad Q?",
                "options": ["A", "B"],
                "answer": "A",
            },
        )
        content = wrap_content(
            "validate_question_contract",
            {
                "violations": ["only 2 options"],
                "pass": False,
            },
            content,
        )
        content = wrap_content(
            "rewrite_failed_question",
            {
                "question": "Fixed Q?",
                "options": ["A", "B", "C", "D"],
                "answer": "A",
            },
            content,
        )

        record = {"content": content}

        # Rewrite namespace has corrected question
        assert read_namespace(record, "rewrite_failed_question", "question") == "Fixed Q?"

        # Original still accessible
        assert read_namespace(record, "write_scenario_question", "question") == "Bad Q?"

        # All 3 namespaces present
        assert len(get_all_namespaces(record)) == 3


class TestVersionMergeScenario:
    """Version consumption merge — each version is a namespace."""

    def test_three_versions_accessible(self):
        content = wrap_content("score_quality_1", {"score": 8, "reasoning": "clear"})
        content = wrap_content("score_quality_2", {"score": 6, "reasoning": "decent"}, content)
        content = wrap_content("score_quality_3", {"score": 9, "reasoning": "excellent"}, content)

        record = {"content": content}

        scores = [read_namespace(record, f"score_quality_{i}", "score") for i in range(1, 4)]
        assert scores == [8, 6, 9]


class TestDiamondFanInScenario:
    """Diamond fan-in — both branches accessible on merged record."""

    def test_both_branches_accessible(self):
        content = wrap_content("root", {"raw": "data"})
        content = wrap_content("branch_a", {"a_result": "from A"}, content)
        content = wrap_content("branch_b", {"b_result": "from B"}, content)

        record = {"content": content}

        assert read_namespace(record, "branch_a", "a_result") == "from A"
        assert read_namespace(record, "branch_b", "b_result") == "from B"
        assert read_namespace(record, "root", "raw") == "data"
