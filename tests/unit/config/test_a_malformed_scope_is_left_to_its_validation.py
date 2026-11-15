"""A context_scope the include checks cannot read is refused as it is without an include."""

from __future__ import annotations

import pytest

from tests.unit.cli.conftest import isolated_user_tools  # noqa: F401
from tests.unit.cli.test_inspect_shows_where_an_included_action_comes_from import (
    _run,
    _without_origin,
)
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    B1,
    B2,
    INCLUDE,
    WF,
    A,
    Z,
    _refusal,
    _with,
)
from tests.unit.config.test_an_include_overrides_removes_and_sets_defaults import (
    B3,
    _include,
    _loaded,
)
from tests.unit.config.test_an_inherited_read_is_checked_at_the_branch_boundary import (  # noqa: F401
    _pair,
    cli_project,
)

BAD_DIRECTIVE = {"context_scope": {"observ": ["z.text"]}}
LIST_SEED = {"context_scope": {"seed": ["z.text"]}}


def _same_refusal(cli_project, monkeypatch, included, inline, branches=None, **defaults):  # noqa: F811
    code, with_include, _ = _run(
        cli_project(included, branches, folder="included", **defaults), monkeypatch, "-a", "wf"
    )
    inline_code, without, _ = _run(
        cli_project(inline, folder="inline", **defaults), monkeypatch, "-a", "wf"
    )
    assert code != 0 and inline_code != 0
    assert _without_origin(with_include) == without
    return without


class TestAnInheritedScope:
    @pytest.mark.parametrize(
        "level, scope, problem",
        [
            ("workflow_defaults", BAD_DIRECTIVE, "context_scope.observ is not a valid directive."),
            ("project_defaults", BAD_DIRECTIVE, "context_scope.observ is not a valid directive."),
            ("workflow_defaults", LIST_SEED, "  Location: context_scope.seed"),
        ],
        ids=["workflow-directive", "project-directive", "workflow-seed-list"],
    )
    def test_gets_the_refusal_it_gets_without_an_include(
        self,
        cli_project,  # noqa: F811
        monkeypatch,
        level,
        scope,
        problem,
    ):
        lines = _same_refusal(
            cli_project, monkeypatch, [A, Z, INCLUDE], [A, Z, B1, B2], **{level: scope}
        )

        assert any(problem in line for line in lines), lines
        assert not any("Declare it under 'inputs:'" in line for line in lines)

    @pytest.mark.parametrize(
        "include, inline",
        [
            (INCLUDE, [B1, B2]),
            (_include(defaults={"context_scope": {"observe": ["a.text"]}}), [B1, B2]),
            (
                _include(remove=["b2"], defaults={"context_scope": {"observe": ["a.text"]}}),
                [B1],
            ),
        ],
        ids=["plain", "include-scope", "include-scope-and-removal"],
    )
    def test_a_project_scope_that_is_not_a_mapping_reaches_the_same_later_error(
        self, tmp_path, include, inline
    ):
        bad = {"context_scope": "bad"}
        caught = []
        for folder, actions in (("included", [A, Z, include]), ("inline", [A, Z, *inline])):
            with pytest.raises(Exception) as error:
                _loaded(tmp_path / folder, actions, project_defaults=bad)
            caught.append((type(error.value), str(error.value)))

        assert caught[0] == caught[1]
        assert caught[0] == (TypeError, "'str' object is not a mapping")


class TestAMalformedWorkflowBesideARemoval:
    def test_gets_the_validation_refusal_and_not_the_removal_refusal(
        self,
        cli_project,  # noqa: F811
        monkeypatch,
    ):
        lines = _same_refusal(
            cli_project,
            monkeypatch,
            [A, _include(remove=["b1"])],
            [A, B2],
            workflow_defaults={"record_limit": 0},
        )

        assert any("record_limit" in line for line in lines), lines
        assert not any("remove names" in line for line in lines)


class TestAnOwnScope:
    def test_a_misspelt_directive_in_a_branch_action(self, cli_project, monkeypatch):  # noqa: F811
        misspelt = _with(B2, context_scope={"observe": ["b1.text"], "observ": ["z.text"]})

        lines = _same_refusal(
            cli_project,
            monkeypatch,
            [A, Z, INCLUDE],
            [A, Z, B1, misspelt],
            {"pair": _pair([B1, misspelt])},
        )

        assert any("context_scope.observ is not a valid directive." in line for line in lines)


class TestTheRemovalRefusalForAnInheritedReader:
    REROUTED = {"b2": {"dependencies": ["a"], "context_scope": {"observe": ["a.text"]}}}
    VIA_INCLUDE = "(from 'context_scope' under 'defaults:' of include 'pair')"

    def test_every_reader_inherits_the_read(self, tmp_path):
        after_b2 = _with(B3, dependencies=["b2"], context_scope={"observe": ["b2.text"]})
        include = _include(
            remove=["b1"],
            override=self.REROUTED,
            defaults={"context_scope": {"drop": ["b1.text"]}},
        )

        message = _refusal(
            tmp_path, [A, include], {"pair": _pair([B1, B2, after_b2], outputs=["b3"])}
        )

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            f"'b2' {self.VIA_INCLUDE}, 'b3' {self.VIA_INCLUDE} still read it. "
            "Remove the readers too, override them so that they do not read it, or remove the read "
            "from the defaults named above. In an override, null takes away an inherited directive, "
            "and a list is added to it."
        )

    def test_one_reader_inherits_the_read_and_one_has_its_own(self, tmp_path):
        include = _include(
            remove=["b1"],
            override=self.REROUTED,
            defaults={"context_scope": {"drop": ["b1.text"]}},
        )

        message = _refusal(tmp_path, [A, include], {"pair": _pair([B1, B2, B3], outputs=["b3"])})

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            f"'b2' {self.VIA_INCLUDE}, 'b3' still read it. "
            "Remove the readers too, override them so that they do not read it, or remove the read "
            "from the defaults named above. In an override, null takes away an inherited directive, "
            "and a list is added to it."
        )

    def test_a_reader_with_its_own_read_keeps_the_plain_advice(self, tmp_path):
        message = _refusal(tmp_path, [A, _include(remove=["b1"])])

        assert message == (
            f"Include 'pair' in {WF}: remove names 'b1' of branch 'pair' (branches/pair.yml), but "
            "'b2' still reads it. Remove the readers too, or override them so that they do not "
            "read it."
        )


def test_project_defaults_the_load_refuses_leave_the_include_unchecked(tmp_path):
    bad = {"expect": {"max_iterations": 99}}
    reads_z = _with(B2, dependencies=["b1", "z"], context_scope={"observe": ["z.text"]})
    caught = []
    for folder, actions, branches in (
        ("included", [A, Z, INCLUDE], {"pair": _pair([B1, reads_z])}),
        ("inline", [A, Z, B1, reads_z], None),
    ):
        with pytest.raises(Exception) as error:
            _loaded(tmp_path / folder, actions, branches, project_defaults=bad)
        caught.append((type(error.value).__name__, str(error.value)))

    assert caught[0] == caught[1]
    assert caught[0][1].startswith("default_agent_config.expect: ")
