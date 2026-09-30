"""Preflight refuses a guard clause naming a field without its namespace.

Such a clause resolves against nothing: the runtime filters or skips the record with a
warning and the run exits successfully, so a workflow spelled that way discards every
record and reports success. Detection was editor-only.

The refusal is narrow on purpose. A bare name resolves through several promotions, and
refusing every un-dotted reference would reject configurations that work today — the
tests below pin each promotion that must stay silent.
"""

from agent_actions.validation.preflight.guard_validation import validate_guard_conditions


def _errors(configs: dict) -> list[str]:
    return [e for e in validate_guard_conditions(configs) if "without an action prefix" in e]


class TestItRefusesWhatProvablyResolvesNowhere:
    def test_a_bare_field_is_refused(self):
        errors = _errors(
            {
                "a1": {},
                "b": {"dependencies": ["a1"], "guard": {"clause": "n > 1"}},
            }
        )

        assert len(errors) == 1, errors
        assert "'n'" in errors[0]

    def test_the_message_names_the_spelling_that_would_resolve(self):
        """The runtime computes this suggestion too — per record, after the data is gone."""
        errors = _errors(
            {
                "a1": {},
                "b": {"dependencies": ["a1"], "guard": {"clause": "n > 1"}},
            }
        )

        assert "Did you mean 'a1.n'?" in errors[0], errors[0]

    def test_it_offers_every_upstream_when_there_are_several(self):
        errors = _errors(
            {
                "a1": {},
                "a2": {},
                "b": {"dependencies": ["a1", "a2"], "guard": {"clause": "n > 1"}},
            }
        )

        assert "'a1.n'" in errors[0] and "'a2.n'" in errors[0], errors[0]

    def test_a_bare_reference_on_the_left_of_a_comparison_is_seen(self):
        """The pre-existing check inspected only the RHS, which is why this was missed."""
        errors = _errors(
            {
                "a1": {},
                "b": {"dependencies": ["a1"], "guard": {"clause": 'n == "x"'}},
            }
        )

        assert len(errors) == 1, errors


class TestItStaysSilentWhereTheNameResolves:
    def test_a_dotted_reference_is_never_refused(self):
        assert (
            _errors({"a1": {}, "b": {"dependencies": ["a1"], "guard": {"clause": "a1.n > 1"}}})
            == []
        )

    def test_a_dependency_output_field_is_promoted(self):
        """guard_context promotes the output_field's value to the top level."""
        assert (
            _errors(
                {
                    "a1": {"output_field": "verdict"},
                    "b": {"dependencies": ["a1"], "guard": {"clause": "verdict == true"}},
                }
            )
            == []
        )

    def test_a_first_stage_action_is_left_alone(self):
        """Its content is the staging row, whose columns config cannot know."""
        assert _errors({"b": {"guard": {"clause": "priority == 1"}}}) == []

    def test_a_record_envelope_field_is_left_alone(self):
        """_prepare_eval_context keeps every record key except `content`."""
        for name in ("source_guid", "node_id", "lineage"):
            assert (
                _errors(
                    {
                        "a1": {},
                        "b": {"dependencies": ["a1"], "guard": {"clause": f"{name} IS NOT NULL"}},
                    }
                )
                == []
            ), name

    def test_a_promoted_version_key_is_left_alone(self):
        for name in ("i", "idx", "base_name", "param_name"):
            assert (
                _errors(
                    {
                        "a1": {},
                        "b": {"dependencies": ["a1"], "guard": {"clause": f"{name} == 1"}},
                    }
                )
                == []
            ), name

    def test_a_declared_version_param_is_left_alone(self):
        assert (
            _errors(
                {
                    "a1": {},
                    "b": {
                        "dependencies": ["a1"],
                        "versions": {"param": "voter_id", "range": [1, 2]},
                        "guard": {"clause": "voter_id == 1"},
                    },
                }
            )
            == []
        )

    def test_an_upstream_namespace_name_is_left_alone(self):
        """Every dependency namespace is promoted to top level, so `a1` resolves bare."""
        assert (
            _errors(
                {"a1": {}, "b": {"dependencies": ["a1"], "guard": {"clause": "a1 IS NOT NULL"}}}
            )
            == []
        )

    def test_an_unknown_upstream_makes_nothing_provable(self):
        """A dependency this config does not contain could declare any output_field."""
        assert _errors({"b": {"dependencies": ["elsewhere"], "guard": {"clause": "n > 1"}}}) == []

    def test_a_file_granularity_version_merge_upstream_spreads_flat(self):
        """Such a tool makes its fields content's own top-level keys, so any bare name
        may be one of them — and the dotted spelling is the one that fails."""
        assert (
            _errors(
                {
                    "fmerge": {
                        "kind": "tool",
                        "granularity": "file",
                        "version_consumption": {"pattern": "merge"},
                    },
                    "b": {"dependencies": ["fmerge"], "guard": {"clause": "fdecision == 1"}},
                }
            )
            == []
        )


class TestTheShippedConfigsAreAccepted:
    """The refusal must not reject a workflow that runs today."""

    @staticmethod
    def _configs_for(path):
        from ruamel.yaml import YAML

        data = YAML(typ="safe").load(path.read_text()) or {}
        defaults = data.get("defaults") or {}
        configs = {}
        for action in data.get("actions", []) or []:
            if not isinstance(action, dict) or not action.get("name"):
                continue
            config = dict(action)
            guard = config.get("guard")
            if isinstance(guard, str):
                config["guard"] = {"clause": guard}
            elif isinstance(guard, dict) and "condition" in guard:
                config["guard"] = {**guard, "clause": guard["condition"]}
            if "output_field" not in config and defaults.get("output_field"):
                config["output_field"] = defaults["output_field"]
            configs[action["name"]] = config
        return configs

    def test_no_example_workflow_is_refused(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "examples"
        files = sorted(root.glob("*/agent_workflow/*/agent_config/*.yml"))
        assert files, "no example workflows found"

        guards = 0
        offenders = []
        for path in files:
            configs = self._configs_for(path)
            guards += sum(
                1
                for c in configs.values()
                if isinstance(c.get("guard"), dict) and c["guard"].get("clause")
            )
            offenders += [f"{path.name}: {e}" for e in _errors(configs)]

        # Counted first: with the check disabled this test is green either way.
        assert guards >= 8, f"only {guards} guards seen across {len(files)} files"
        assert offenders == [], "\n".join(offenders)
