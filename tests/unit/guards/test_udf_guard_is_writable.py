"""A `udf:` guard names a registered UDF, which is a bare function name (#1188).

`guard: "udf:..."` is documented in `agent_actions/guards/ARCHITECTURE.md`, and no
spelling of it loaded. The parser required at least one dot, so a bare name was refused
outright; a dotted name then passed the parser and became a `conditional_clause`, which
the preflight static checker reads for `action.field` references and rejected as naming a
missing action — and had it got through, `UDF_REGISTRY` is keyed on the bare lowercased
function name, so the lookup would have raised anyway.

Bare is the form every other UDF reference in the framework uses: `impl:` values are
collected verbatim and checked against that same registry. The dot was the outlier.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ValidationError
from agent_actions.guards import GuardBehavior, parse_guard_config
from agent_actions.guards.guard_parser import GuardParser, GuardType
from agent_actions.output.response.expander_action_types import process_guard_config
from agent_actions.utils.udf_management.registry import UDF_REGISTRY
from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor


class TestTheParserAcceptsTheNameTheRegistryHolds:
    def test_a_bare_function_name_parses_as_a_udf_guard(self):
        parsed = GuardParser.parse("udf:check_eligibility")

        assert parsed.type is GuardType.UDF
        assert parsed.expression == "check_eligibility"

    def test_the_registry_is_keyed_on_exactly_that_form(self):
        """The reason bare is right rather than merely allowed: a dotted name is not a
        key of the registry, so it could never have resolved."""

        def check_eligibility(data):
            return True

        from agent_actions.utils.udf_management.registry import udf_tool

        udf_tool(check_eligibility)
        try:
            assert "check_eligibility" in UDF_REGISTRY
            assert "tools.check_eligibility" not in UDF_REGISTRY
        finally:
            UDF_REGISTRY.pop("check_eligibility", None)

    def test_a_dict_guard_carrying_a_bare_udf_name_parses(self):
        config = parse_guard_config({"condition": "udf:check_eligibility", "behavior": "skip"})

        assert config.is_udf_condition()
        assert config.get_condition_expression() == "check_eligibility"

    def test_a_dotted_name_is_refused_with_the_form_to_use(self):
        """Refused rather than resolved by its last segment: two spellings answering to
        one UDF would make the module half decorative."""
        with pytest.raises(ValidationError, match="Invalid UDF expression format"):
            GuardParser.parse("udf:tools.check_eligibility")


class TestTheDangerousNameBlocklistStillApplies:
    """It matched on word boundaries already, so it never needed the dot — but dropping
    the dot requirement must not drop the blocklist with it."""

    @pytest.mark.parametrize("name", ["exec", "eval", "compile", "open"])
    def test_a_dangerous_bare_name_is_refused(self, name):
        with pytest.raises(ValidationError, match="potentially dangerous pattern"):
            GuardParser.parse(f"udf:{name}")

    def test_a_dunder_bare_name_is_refused(self):
        with pytest.raises(ValidationError, match="potentially dangerous pattern"):
            GuardParser.parse("udf:__import__")

    @pytest.mark.parametrize("name", ["eval_something", "compile_code", "open_file"])
    def test_a_legitimate_name_containing_one_is_not(self, name):
        assert GuardParser.parse(f"udf:{name}").expression == name

    @pytest.mark.parametrize("bad", ["123start", "has-dash", "has space", ""])
    def test_a_name_that_is_not_an_identifier_is_refused(self, bad):
        with pytest.raises(ValidationError):
            GuardParser.parse(f"udf:{bad}")


class TestTheStaticCheckerReadsNoActionReferenceFromIt:
    """What made the dotted form fail twice over. The expander turns a `udf:` guard into
    a `conditional_clause`, which the extractor scans for `action.field` references; a
    dot there is read as an action name, and the action does not exist."""

    def test_a_bare_udf_guard_contributes_no_requirement(self):
        agent: dict = {}
        process_guard_config(agent, {"name": "fold", "guard": "udf:check_eligibility"})
        assert agent["conditional_clause"] == "check_eligibility"

        requirements = ReferenceExtractor().extract_from_agent(agent)

        assert [r.source_agent for r in requirements if r.location == "conditional_clause"] == []

    def test_a_dotted_clause_is_what_the_checker_misread(self):
        """Pins the mechanism rather than the fix: the extractor is unchanged, and this
        is why nothing more than the parser had to move. A clause can no longer hold a
        dot, so this input is now unreachable from any config."""
        requirements = ReferenceExtractor().extract_from_agent(
            {"conditional_clause": "tools.check_eligibility"}
        )

        assert [r.source_agent for r in requirements] == ["tools"]


class TestABehaviourIsStillForcedToSkip:
    def test_a_udf_guard_cannot_be_given_filter_behaviour(self):
        """Unchanged by this, and worth holding: a UDF verdict is a skip, and the
        expander refuses `filter` outright rather than quietly downgrading it."""
        from agent_actions.errors import ConfigurationError

        agent: dict = {}
        with pytest.raises(ConfigurationError, match="cannot use 'filter' behavior"):
            process_guard_config(
                agent,
                {
                    "name": "fold",
                    "guard": {"condition": "udf:check_eligibility", "on_false": "filter"},
                },
            )

    def test_a_bare_udf_guard_defaults_to_skip(self):
        config = parse_guard_config({"condition": "udf:check_eligibility"})

        assert config.on_false is GuardBehavior.SKIP
