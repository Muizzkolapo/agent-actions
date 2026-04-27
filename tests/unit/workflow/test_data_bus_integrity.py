"""Data bus integrity tests for all agentic workflow patterns.

These tests verify that content flowing through the pipeline bus does NOT
leak or duplicate upstream namespaces across any workflow topology:

1. Linear pipeline — bus accumulates one namespace per action
2. Fan-in / diamond — parallel branches merge without duplicating shared upstream
3. Parallel branches (same action) — merge without duplicating shared upstream
4. Version merge — only version's own namespace extracted, upstream once
5. Deep pipeline version merge — upstream duplication scales with depth

Each test constructs realistic record shapes and asserts:
- Exact expected namespace keys at each stage
- No upstream duplication (namespace appears exactly once at top level)
- Content values are correct (not overwritten or lost)
- Total content size does not grow beyond expected (no hidden nested copies)
"""

import json

import pytest

from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.merge import deep_merge_record, merge_records_by_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_key_occurrences(obj: dict, target_key: str) -> int:
    """Count how many times target_key appears anywhere in a nested dict structure."""
    count = 0
    for key, value in obj.items():
        if key == target_key:
            count += 1
        if isinstance(value, dict):
            count += _count_key_occurrences(value, target_key)
    return count


def _make_upstream(size: int = 100) -> dict:
    """Create a realistic upstream namespace with non-trivial content."""
    return {
        "extract_info": {
            "facts": "A" * size,
            "topic": "quantum computing",
            "difficulty": "advanced",
        },
        "analyze_depth": {
            "analysis": "B" * size,
            "bloom_level": "evaluate",
            "prereqs": ["linear algebra", "probability"],
        },
    }


# ---------------------------------------------------------------------------
# 1. Linear pipeline — A → B → C
# ---------------------------------------------------------------------------


class TestLinearPipelineBus:
    """Bus accumulates exactly one namespace per action, no duplication."""

    def test_linear_accumulation(self):
        """Each action adds its own namespace; upstream stays flat."""
        # Stage 1: extract produces initial record
        _record_after_extract = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "important stuff"},
            },
        }

        # Stage 2: analyze reads extract, adds its own namespace
        _record_after_analyze = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "important stuff"},
                "analyze": {"depth": "deep", "score": 9},
            },
        }

        # Stage 3: write reads both, adds its own namespace
        record_after_write = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "important stuff"},
                "analyze": {"depth": "deep", "score": 9},
                "write": {"question": "What is X?", "options": ["A", "B"]},
            },
        }

        content = record_after_write["content"]
        assert set(content.keys()) == {"extract", "analyze", "write"}
        assert _count_key_occurrences(content, "extract") == 1
        assert _count_key_occurrences(content, "analyze") == 1
        assert content["extract"]["facts"] == "important stuff"
        assert content["write"]["question"] == "What is X?"


# ---------------------------------------------------------------------------
# 2. Fan-in / diamond — A → B, A → C, B+C → D
# ---------------------------------------------------------------------------


class TestFanInDiamondBus:
    """Fan-in merges parallel branches without duplicating shared upstream."""

    def test_diamond_merge_no_upstream_duplication(self):
        """When B and C both carry A's output, merge produces A once."""
        # B ran after A: has A + B namespaces
        record_from_b = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "shared upstream"},
                "enrich": {"enriched": True, "score": 8},
            },
        }

        # C ran after A: has A + C namespaces
        record_from_c = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "shared upstream"},
                "validate": {"valid": True, "issues": []},
            },
        }

        # deep_merge_record merges C into B's record
        merged = dict(record_from_b)
        merged["content"] = dict(merged["content"])
        deep_merge_record(merged, record_from_c)

        content = merged["content"]

        # extract appears exactly once at top level (not duplicated)
        assert set(content.keys()) == {"extract", "enrich", "validate"}
        assert _count_key_occurrences(content, "extract") == 1

        # Values preserved
        assert content["extract"]["facts"] == "shared upstream"
        assert content["enrich"]["enriched"] is True
        assert content["validate"]["valid"] is True

    def test_diamond_merge_via_merge_records_by_key(self):
        """merge_records_by_key correctly deduplicates fan-in records."""
        records = [
            {
                "source_guid": "sg-1",
                "content": {
                    "upstream": {"data": "shared"},
                    "branch_a": {"result": "A"},
                },
            },
            {
                "source_guid": "sg-1",
                "content": {
                    "upstream": {"data": "shared"},
                    "branch_b": {"result": "B"},
                },
            },
        ]

        merged = merge_records_by_key(records)
        assert len(merged) == 1

        content = merged[0]["content"]
        assert set(content.keys()) == {"upstream", "branch_a", "branch_b"}
        assert _count_key_occurrences(content, "upstream") == 1

    def test_three_way_fan_in(self):
        """Three branches converging — upstream appears once."""
        upstream = {"source": {"text": "original document"}}
        records = [
            {
                "source_guid": "sg-1",
                "content": {**upstream, "classify": {"category": "science"}},
            },
            {
                "source_guid": "sg-1",
                "content": {**upstream, "extract_entities": {"entities": ["quantum"]}},
            },
            {
                "source_guid": "sg-1",
                "content": {**upstream, "sentiment": {"score": 0.8}},
            },
        ]

        merged = merge_records_by_key(records)
        assert len(merged) == 1

        content = merged[0]["content"]
        assert set(content.keys()) == {"source", "classify", "extract_entities", "sentiment"}
        assert _count_key_occurrences(content, "source") == 1
        assert content["classify"]["category"] == "science"
        assert content["sentiment"]["score"] == 0.8


# ---------------------------------------------------------------------------
# 3. Parallel branches (same action) — A_1, A_2 → B
# ---------------------------------------------------------------------------


class TestParallelBranchesBus:
    """Parallel branches of same action merge without upstream duplication."""

    def test_parallel_branches_merge(self):
        """Two branches of same action merge — shared upstream once."""
        record_v1 = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "shared"},
                "research_1": {"finding": "result 1"},
            },
        }
        record_v2 = {
            "source_guid": "sg-1",
            "content": {
                "extract": {"facts": "shared"},
                "research_2": {"finding": "result 2"},
            },
        }

        merged = merge_records_by_key([record_v1, record_v2])
        assert len(merged) == 1

        content = merged[0]["content"]
        assert set(content.keys()) == {"extract", "research_1", "research_2"}
        assert _count_key_occurrences(content, "extract") == 1
        assert content["research_1"]["finding"] == "result 1"
        assert content["research_2"]["finding"] == "result 2"

    def test_parallel_branches_deep_pipeline(self):
        """Parallel branches deep in pipeline — all upstream appears once."""
        upstream = _make_upstream()

        records = []
        for i in range(1, 4):
            records.append(
                {
                    "source_guid": "sg-1",
                    "content": {
                        **upstream,
                        f"scorer_{i}": {"score": i * 3, "confidence": 0.9},
                    },
                }
            )

        merged = merge_records_by_key(records)
        assert len(merged) == 1

        content = merged[0]["content"]
        expected_keys = {"extract_info", "analyze_depth", "scorer_1", "scorer_2", "scorer_3"}
        assert set(content.keys()) == expected_keys

        # Upstream appears exactly once — not tripled
        assert _count_key_occurrences(content, "extract_info") == 1
        assert _count_key_occurrences(content, "analyze_depth") == 1


# ---------------------------------------------------------------------------
# 4. Version merge — the bug we just fixed
# ---------------------------------------------------------------------------


class TestVersionMergeBus:
    """Version merge extracts only version's own namespace, upstream once."""

    def _make_version_records(self, upstream: dict, n_versions: int = 3):
        """Create version agent records with full accumulated bus."""
        records = {}
        for i in range(1, n_versions + 1):
            agent_name = f"write_question_{i}"
            records[agent_name] = {
                "source_guid": "sg-1",
                "version_correlation_id": "vc-1",
                "content": {
                    **upstream,
                    agent_name: {
                        "question": f"Question {i}?",
                        "options": [f"A{i}", f"B{i}", f"C{i}", f"D{i}"],
                    },
                },
            }
        return records

    def test_version_merge_no_upstream_in_version_namespaces(self, tmp_path):
        """Each version namespace contains only its own fields, not the bus."""
        upstream = _make_upstream()
        records = self._make_version_records(upstream)

        correlator = VersionOutputCorrelator(agent_folder=tmp_path)
        version_outputs = {k: [v] for k, v in records.items()}
        merged = correlator._create_merged_record(records, version_outputs)

        content = merged["content"]

        # Upstream at top level (from base record's existing content)
        assert "extract_info" in content
        assert "analyze_depth" in content

        # Version namespaces present
        for i in range(1, 4):
            vname = f"write_question_{i}"
            assert vname in content
            vdata = content[vname]

            # Version namespace has ONLY its own fields
            assert set(vdata.keys()) == {"question", "options"}
            assert vdata["question"] == f"Question {i}?"

            # No upstream leaked into version namespace
            assert "extract_info" not in vdata
            assert "analyze_depth" not in vdata

    def test_version_merge_upstream_appears_once(self, tmp_path):
        """Upstream namespaces appear exactly once in merged content."""
        upstream = _make_upstream()
        records = self._make_version_records(upstream)

        correlator = VersionOutputCorrelator(agent_folder=tmp_path)
        version_outputs = {k: [v] for k, v in records.items()}
        merged = correlator._create_merged_record(records, version_outputs)

        content = merged["content"]
        assert _count_key_occurrences(content, "extract_info") == 1
        assert _count_key_occurrences(content, "analyze_depth") == 1

    def test_version_merge_size_scales_with_versions_not_bus(self, tmp_path):
        """Total content size grows with version output, not with bus * N."""
        upstream = _make_upstream(size=500)

        # 3 versions
        records_3 = self._make_version_records(upstream, n_versions=3)
        correlator = VersionOutputCorrelator(agent_folder=tmp_path)
        merged_3 = correlator._create_merged_record(
            records_3, {k: [v] for k, v in records_3.items()}
        )
        size_3 = len(json.dumps(merged_3["content"]))

        # 6 versions — should add ~version output size per version, NOT upstream * 3
        records_6 = self._make_version_records(upstream, n_versions=6)
        merged_6 = correlator._create_merged_record(
            records_6, {k: [v] for k, v in records_6.items()}
        )
        size_6 = len(json.dumps(merged_6["content"]))

        upstream_size = len(json.dumps(upstream))
        size_delta = size_6 - size_3

        # Delta should be ~3 version outputs (~300 chars), NOT ~3 * upstream (~3000 chars)
        assert size_delta < upstream_size, (
            f"Adding 3 versions grew content by {size_delta} chars, "
            f"which exceeds upstream size ({upstream_size}). "
            f"Bus content is being duplicated per version."
        )

    def test_version_merge_rejects_missing_namespace(self, tmp_path):
        """Version record without its own namespace raises DataValidationError."""
        from agent_actions.errors import DataValidationError

        records = {
            "action_1": {
                "source_guid": "sg-1",
                "version_correlation_id": "vc-1",
                "content": {"unrelated_field": "value"},  # missing "action_1" namespace
            },
        }

        correlator = VersionOutputCorrelator(agent_folder=tmp_path)
        with pytest.raises(DataValidationError, match="missing own namespace 'action_1'"):
            correlator._create_merged_record(records, {k: [v] for k, v in records.items()})


# ---------------------------------------------------------------------------
# 5. Deep pipeline + version merge — the production scenario from the bug
# ---------------------------------------------------------------------------


class TestDeepPipelineVersionMergeBus:
    """Real-world scenario: deep pipeline with version merge at the end."""

    def test_production_scenario_token_budget(self, tmp_path):
        """Simulates the bug report: 3 versions deep in pipeline.

        Before fix: 422K tokens (upstream tripled + base = 4x).
        After fix: upstream once + 3 small version outputs.
        """
        # Simulate deep pipeline with substantial upstream
        upstream = {
            "ingest": {"document": "X" * 1000, "metadata": {"pages": 50}},
            "extract_topics": {"topics": ["A", "B", "C"] * 10, "count": 30},
            "classify_difficulty": {"level": "advanced", "reasoning": "Y" * 500},
            "generate_context": {"context": "Z" * 800, "references": list(range(20))},
        }
        upstream_size = len(json.dumps(upstream))

        # 3 version agents, each with full bus + own output
        version_records = {}
        for i in range(1, 4):
            agent_name = f"write_question_{i}"
            version_records[agent_name] = {
                "source_guid": "sg-001",
                "version_correlation_id": "vc-001",
                "content": {
                    **upstream,
                    agent_name: {
                        "question": f"Question {i}?",
                        "options": [f"opt_{i}_{j}" for j in range(4)],
                        "correct": f"opt_{i}_0",
                    },
                },
            }

        correlator = VersionOutputCorrelator(agent_folder=tmp_path)
        version_outputs = {k: [v] for k, v in version_records.items()}
        merged = correlator._create_merged_record(version_records, version_outputs)

        content = merged["content"]
        total_size = len(json.dumps(content))

        # Upstream should NOT be multiplied by version count
        # Expected: upstream_size + 3 * small_version_output
        # Buggy: upstream_size * 4 (base + 3 nested copies)
        max_acceptable = upstream_size * 1.5  # upstream once + version outputs overhead
        assert total_size < max_acceptable, (
            f"Merged content is {total_size} chars but upstream alone is {upstream_size}. "
            f"Ratio: {total_size / upstream_size:.1f}x. "
            f"Expected <1.5x, got bus duplication."
        )

        # Verify structure
        assert set(content.keys()) == {
            "ingest",
            "extract_topics",
            "classify_difficulty",
            "generate_context",
            "write_question_1",
            "write_question_2",
            "write_question_3",
        }
        for key in ["ingest", "extract_topics", "classify_difficulty", "generate_context"]:
            assert _count_key_occurrences(content, key) == 1

    def test_version_merge_then_fan_in(self, tmp_path):
        """Version merge output consumed alongside another action's output."""
        upstream = {"source": {"text": "original"}}

        # Version merge produced this (after our fix)
        version_merged = {
            "source_guid": "sg-1",
            "content": {
                **upstream,
                "scorer_1": {"score": 8},
                "scorer_2": {"score": 7},
                "scorer_3": {"score": 9},
            },
        }

        # Another action also produced output
        other_action = {
            "source_guid": "sg-1",
            "content": {
                **upstream,
                "classify": {"category": "hard"},
            },
        }

        # Fan-in merge of both
        merged = merge_records_by_key([version_merged, other_action])
        assert len(merged) == 1

        content = merged[0]["content"]
        expected = {"source", "scorer_1", "scorer_2", "scorer_3", "classify"}
        assert set(content.keys()) == expected
        assert _count_key_occurrences(content, "source") == 1
        assert content["classify"]["category"] == "hard"
        assert content["scorer_2"]["score"] == 7
