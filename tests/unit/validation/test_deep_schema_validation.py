"""Deep schema checks: per-element items, additionalProperties, bounds, enum."""

from agent_actions.validation.schema_output_validator import validate_output_against_schema


class TestArrayFieldItemsRequiredPerElement:
    """items.required is enforced per element, not against the union of keys."""

    def _schema(self):
        return {
            "name": "review_findings",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "severity": {"type": "string"},
                        },
                        "required": ["summary", "severity"],
                    },
                }
            },
            "required": ["findings"],
        }

    def test_one_incomplete_element_among_complete_ones_is_non_compliant(self):
        output = {
            "findings": [
                {"summary": "first", "severity": "low"},
                {"summary": "second"},
                {"summary": "third", "severity": "high"},
            ]
        }
        report = validate_output_against_schema(output, self._schema(), "review_action")
        assert not report.is_compliant
        assert any(
            "'findings' element 1" in e and "'severity' is a required property" in e
            for e in report.validation_errors
        )

    def test_complete_elements_produce_no_element_errors(self):
        output = {
            "findings": [
                {"summary": "first", "severity": "low"},
                {"summary": "second"},
            ]
        }
        report = validate_output_against_schema(output, self._schema(), "review_action")
        assert not any("element 0" in e for e in report.validation_errors)
        assert any("element 1" in e for e in report.validation_errors)


class TestArrayFieldItemsAdditionalProperties:
    """items.additionalProperties: false rejects extra keys inside elements."""

    def test_extra_key_in_element_is_non_compliant(self):
        schema = {
            "name": "qa_pairs",
            "properties": {
                "pairs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"question": {"type": "string"}},
                        "required": ["question"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["pairs"],
        }
        output = {
            "pairs": [
                {"question": "fine"},
                {"question": "fine", "rogue": "nope"},
            ]
        }
        report = validate_output_against_schema(output, schema, "qa_action")
        assert not report.is_compliant
        assert any(
            "'pairs' element 1" in e and "rogue" in e and "Additional properties" in e
            for e in report.validation_errors
        )
        assert not any("element 0" in e for e in report.validation_errors)


class TestTopLevelAdditionalProperties:
    """Top-level additionalProperties: false applies without strict_mode."""

    def test_extra_top_level_field_is_non_compliant_in_non_strict_mode(self):
        schema = {
            "name": "strict_top",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        output = {"answer": "yes", "surprise": "extra"}
        report = validate_output_against_schema(output, schema, "strict_action", strict_mode=False)
        assert not report.is_compliant
        assert any(
            "additionalProperties" in e and "surprise" in e for e in report.validation_errors
        )

    def test_no_extra_fields_stays_compliant(self):
        schema = {
            "name": "strict_top",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        report = validate_output_against_schema({"answer": "yes"}, schema, "strict_action")
        assert report.is_compliant
        assert report.validation_errors == []


class TestNumericBounds:
    """minimum/maximum on a field are enforced."""

    def _schema(self):
        return {
            "name": "scored",
            "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 10}},
            "required": ["score"],
        }

    def test_above_maximum_is_non_compliant(self):
        report = validate_output_against_schema({"score": 15}, self._schema(), "score_action")
        assert not report.is_compliant
        assert any(
            "'score'" in e and "greater than the maximum of 10" in e
            for e in report.validation_errors
        )

    def test_below_minimum_is_non_compliant(self):
        report = validate_output_against_schema({"score": -3}, self._schema(), "score_action")
        assert not report.is_compliant
        assert any(
            "'score'" in e and "less than the minimum of 0" in e for e in report.validation_errors
        )

    def test_in_range_is_compliant(self):
        report = validate_output_against_schema({"score": 7}, self._schema(), "score_action")
        assert report.is_compliant
        assert report.validation_errors == []

    def test_bounds_on_fields_format_field(self):
        schema = {
            "name": "scored",
            "fields": [{"id": "score", "type": "integer", "minimum": 0, "maximum": 10}],
        }
        report = validate_output_against_schema({"score": 15}, schema, "score_action")
        assert not report.is_compliant
        assert any(
            "'score'" in e and "greater than the maximum of 10" in e
            for e in report.validation_errors
        )


class TestEnum:
    """enum membership is enforced."""

    def test_value_outside_enum_is_non_compliant(self):
        schema = {
            "name": "status_schema",
            "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
            "required": ["status"],
        }
        report = validate_output_against_schema({"status": "pending"}, schema, "status_action")
        assert not report.is_compliant
        assert any("'status'" in e and "is not one of" in e for e in report.validation_errors)

    def test_enum_on_fields_format_field(self):
        schema = {
            "name": "status_schema",
            "fields": [{"id": "status", "type": "string", "enum": ["open", "closed"]}],
        }
        report = validate_output_against_schema({"status": "pending"}, schema, "status_action")
        assert not report.is_compliant
        assert any("'status'" in e and "is not one of" in e for e in report.validation_errors)

    def test_enum_member_is_compliant(self):
        schema = {
            "name": "status_schema",
            "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
            "required": ["status"],
        }
        report = validate_output_against_schema({"status": "open"}, schema, "status_action")
        assert report.is_compliant
        assert report.validation_errors == []


class TestAllValidNoRegression:
    """Fully valid outputs against a constrained schema stay compliant."""

    def test_deep_schema_all_valid(self):
        schema = {
            "name": "everything",
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": 10},
                "status": {"type": "string", "enum": ["open", "closed"]},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}},
                        "required": ["label"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["score", "status", "entries"],
        }
        output = {
            "score": 5,
            "status": "open",
            "entries": [{"label": "a"}, {"label": "b"}],
        }
        report = validate_output_against_schema(output, schema, "everything_action")
        assert report.is_compliant
        assert report.validation_errors == []

    def test_none_value_skips_constraint_checks(self):
        schema = {
            "name": "status_schema",
            "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
        }
        report = validate_output_against_schema({"status": None}, schema, "status_action")
        assert report.is_compliant


class TestFieldsFormatItemsSubSchema:
    """fields-format array field with an items sub-schema is validated per element."""

    def _schema(self):
        return {
            "name": "canonicalize_qa",
            "fields": [
                {
                    "id": "canonical_questions",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"question_text": {"type": "string"}},
                        "required": ["question_text"],
                        "additionalProperties": True,
                    },
                }
            ],
        }

    def test_element_missing_items_required_is_non_compliant(self):
        output = {
            "canonical_questions": [
                {"question_text": "What is X?"},
                {"source": "no question here"},
            ]
        }
        report = validate_output_against_schema(output, self._schema(), "canonicalize_qa")
        assert not report.is_compliant
        assert any(
            "'canonical_questions' element 1" in e and "'question_text' is a required property" in e
            for e in report.validation_errors
        )

    def test_all_elements_valid_is_compliant(self):
        output = {
            "canonical_questions": [
                {"question_text": "What is X?", "source": "doc1"},
                {"question_text": "What is Y?"},
            ]
        }
        report = validate_output_against_schema(output, self._schema(), "canonicalize_qa")
        assert report.is_compliant
        assert report.validation_errors == []

    def test_non_object_element_is_non_compliant(self):
        output = {"canonical_questions": [{"question_text": "ok"}, "just a string"]}
        report = validate_output_against_schema(output, self._schema(), "canonicalize_qa")
        assert not report.is_compliant
        assert any(
            "'canonical_questions' element 1" in e and "is not of type 'object'" in e
            for e in report.validation_errors
        )


class TestTopLevelArraySchemaPerElement:
    """Top-level array schema validates each element instead of the key union."""

    def test_one_incomplete_element_is_non_compliant(self):
        schema = {
            "name": "item_list",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title", "body"],
            },
        }
        output = [
            {"title": "t1", "body": "b1"},
            {"title": "t2"},
        ]
        report = validate_output_against_schema(output, schema, "list_action")
        assert not report.is_compliant
        assert any(
            "Element 1" in e and "'body' is a required property" in e
            for e in report.validation_errors
        )
        assert not any("Element 0" in e for e in report.validation_errors)
