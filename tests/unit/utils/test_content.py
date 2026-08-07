"""Tests for namespaced content utilities."""

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.utils.content import get_existing_content


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
        content = RecordEnvelope.build_content(
            "write_scenario_question",
            {
                "question": "What is X?",
                "options": ["A", "B", "C", "D"],
                "answer": "A",
            },
        )

        # Step 2: validate
        content = RecordEnvelope.build_content(
            "validate_question_contract",
            {
                "violations": [],
                "pass": True,
            },
            content,
        )

        # Step 3: rewrite SKIPS — nothing added
        # Step 4: tool reads
        record = {"content": content}

        # Question accessible from generate namespace
        question = record["content"]["write_scenario_question"]["question"]
        assert question == "What is X?"

        # Validation accessible from validate namespace
        passed = record["content"]["validate_question_contract"]["pass"]
        assert passed is True

        # Rewrite namespace absent
        assert "rewrite_failed_question" not in record["content"]

        # All namespaces present
        assert list(record["content"]) == [
            "write_scenario_question",
            "validate_question_contract",
        ]

    def test_rewrite_runs_adds_namespace(self):
        content = RecordEnvelope.build_content(
            "write_scenario_question",
            {
                "question": "Bad Q?",
                "options": ["A", "B"],
                "answer": "A",
            },
        )
        content = RecordEnvelope.build_content(
            "validate_question_contract",
            {
                "violations": ["only 2 options"],
                "pass": False,
            },
            content,
        )
        content = RecordEnvelope.build_content(
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
        assert record["content"]["rewrite_failed_question"]["question"] == "Fixed Q?"

        # Original still accessible
        assert record["content"]["write_scenario_question"]["question"] == "Bad Q?"

        # All 3 namespaces present
        assert len(record["content"]) == 3


class TestVersionMergeScenario:
    """Version consumption merge — each version is a namespace."""

    def test_three_versions_accessible(self):
        content = RecordEnvelope.build_content(
            "score_quality_1", {"score": 8, "reasoning": "clear"}
        )
        content = RecordEnvelope.build_content(
            "score_quality_2", {"score": 6, "reasoning": "decent"}, content
        )
        content = RecordEnvelope.build_content(
            "score_quality_3", {"score": 9, "reasoning": "excellent"}, content
        )

        record = {"content": content}

        scores = [record["content"][f"score_quality_{i}"]["score"] for i in range(1, 4)]
        assert scores == [8, 6, 9]


class TestDiamondFanInScenario:
    """Diamond fan-in — both branches accessible on merged record."""

    def test_both_branches_accessible(self):
        content = RecordEnvelope.build_content("root", {"raw": "data"})
        content = RecordEnvelope.build_content("branch_a", {"a_result": "from A"}, content)
        content = RecordEnvelope.build_content("branch_b", {"b_result": "from B"}, content)

        record = {"content": content}

        assert record["content"]["branch_a"]["a_result"] == "from A"
        assert record["content"]["branch_b"]["b_result"] == "from B"
        assert record["content"]["root"]["raw"] == "data"
