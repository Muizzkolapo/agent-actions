"""The static analyzer reports each finding once, and nothing a valid workflow does wrong (1536).

Pre-flight's warnings now print without an error, so a warning that repeats another or is
wrong for a valid workflow reaches every run.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _schema(*fields):
    return {"type": "object", "properties": {f: {"type": "string"} for f in fields}}


def _analyze(*actions):
    return WorkflowStaticAnalyzer({"actions": list(actions)}).analyze()


class TestABadObserveEntryIsReportedOnce:
    def test_a_misspelt_field(self):
        result = _analyze(
            {"name": "produce", "prompt": "p", "schema": _schema("severity")},
            {
                "name": "consumer",
                "prompt": "c",
                "dependencies": ["produce"],
                "context_scope": {"observe": ["produce.severty"]},
            },
        )

        refs = [e for e in result.errors if e.location.raw_reference == "produce.severty"]
        assert len(refs) == 1, [e.message for e in refs]
        assert "not found in action 'produce'" in refs[0].message

    def test_an_action_that_does_not_exist(self):
        result = _analyze(
            {"name": "produce", "prompt": "p", "schema": _schema("severity")},
            {
                "name": "consumer",
                "prompt": "c",
                "dependencies": ["produce"],
                "context_scope": {"passthrough": ["prodce.severity"]},
            },
        )

        refs = [e for e in result.errors if e.location.raw_reference == "prodce.severity"]
        assert len(refs) == 1, [e.message for e in refs]
        assert "Did you mean 'produce'?" in (refs[0].hint or "")

    def test_a_field_only_forwarded_names_where_it_is_stored(self):
        result = _analyze(
            {
                "name": "produce",
                "prompt": "p",
                "schema": _schema("severity"),
                "context_scope": {"observe": ["source.page_content"]},
            },
            {
                "name": "consumer",
                "prompt": "c",
                "dependencies": ["produce"],
                "context_scope": {"observe": ["produce.page_content"]},
            },
        )

        refs = [e for e in result.errors if e.location.raw_reference == "produce.page_content"]
        assert len(refs) == 1, [e.message for e in refs]
        assert "Did you mean 'source.page_content'?" in (refs[0].hint or ""), refs[0].hint

    def test_a_schema_that_does_not_load_is_still_an_error_for_an_observe(self):
        result = _analyze(
            {"name": "extractor", "schema_name": "nonexistent_schema"},
            {
                "name": "processor",
                "dependencies": ["extractor"],
                "context_scope": {"observe": ["extractor.some_field"]},
            },
        )

        refs = [e for e in result.errors if e.location.raw_reference == "extractor.some_field"]
        assert len(refs) == 1, [e.message for e in result.errors]
        assert "nonexistent_schema" in refs[0].message
        assert not [
            w for w in result.warnings if w.location.raw_reference == "extractor.some_field"
        ]

    def test_a_schemaless_upstream_is_warned_about_once(self):
        result = _analyze(
            {"name": "produce", "prompt": "p"},
            {
                "name": "consumer",
                "prompt": "c",
                "dependencies": ["produce"],
                "context_scope": {"observe": ["produce.anything"]},
            },
        )

        refs = [w for w in result.warnings if w.location.raw_reference == "produce.anything"]
        assert len(refs) == 1, [w.message for w in refs]


class TestAnOutputFieldIsAKnownField:
    """A plain-text action stores its answer under `output_field` and nothing else."""

    @staticmethod
    def _workflow(reads: str):
        return _analyze(
            {
                "name": "classify",
                "prompt": "p",
                "json_mode": False,
                "output_field": "issue_type",
                "context_scope": {"observe": ["source.title"]},
            },
            {
                "name": "route",
                "prompt": f"Route {{{{ {reads} }}}}",
                "dependencies": ["classify"],
                "schema": _schema("team"),
                "context_scope": {"observe": [reads]},
                "guard": {"clause": f"{reads} != 'x'", "behavior": "filter"},
            },
        )

    def test_reading_it_is_not_warned_about(self):
        result = self._workflow("classify.issue_type")

        assert [w.message for w in result.warnings if "classify" in w.message] == []
        assert result.errors == []

    def test_reading_another_field_is_still_warned_about(self):
        result = self._workflow("classify.other")

        assert [w for w in result.warnings if "has no schema" in w.message]


class TestASchemaLoadedByNameIsReadForItsTypes:
    """A schema file loaded by name reaches the analyzer as `{name, fields: [...]}`."""

    def test_the_field_types_are_read(self):
        schema_file = {
            "name": "produce_out",
            "fields": [{"id": "score", "type": "integer"}, {"id": "tag", "type": "string"}],
        }

        types = WorkflowStaticAnalyzer._extract_field_types_from_schema(schema_file)

        assert types == {"score": "integer", "tag": "string"}


class TestAnAncestorReadIsNoImplicitDependency:
    def test_a_drop_of_an_ancestor_reached_through_dependencies(self):
        """The record carries every action upstream of it; adding one would change the DAG."""
        result = _analyze(
            {"name": "split", "prompt": "s", "schema": _schema("clause")},
            {
                "name": "analyze",
                "prompt": "a",
                "dependencies": ["split"],
                "schema": _schema("risk"),
                "context_scope": {"observe": ["split.clause"]},
            },
            {
                "name": "summarize",
                "prompt": "z",
                "dependencies": ["analyze"],
                "schema": _schema("summary"),
                "context_scope": {"observe": ["analyze.*"], "drop": ["split.clause"]},
            },
        )

        assert [w.message for w in result.warnings if "Implicit dependency" in w.message] == []
