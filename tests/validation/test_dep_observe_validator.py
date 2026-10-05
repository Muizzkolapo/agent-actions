"""Unit tests for the dependency/observe preflight checker."""

from agent_actions.validation.dep_observe_validator import (
    find_missing_observe_deps,
    find_reads_not_upstream,
)


def test_dep_without_observe_is_flagged():
    actions = {
        "consumer": {
            "dependencies": ["ground", "author"],
            "context_scope": {"observe": ["author.stem"]},
        }
    }
    findings = find_missing_observe_deps(actions)
    assert any("consumer" in f and "'ground'" in f for f in findings)
    assert all("'author'" not in f for f in findings)


def test_all_deps_observed_passes():
    actions = {
        "consumer": {
            "dependencies": ["author"],
            "context_scope": {"observe": ["author.stem"]},
        }
    }
    assert find_missing_observe_deps(actions) == []


def test_wildcard_observe_satisfies_dep():
    actions = {
        "consumer": {
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.*"]},
        }
    }
    assert find_missing_observe_deps(actions) == []


def test_passthrough_also_satisfies_dep():
    actions = {
        "consumer": {
            "dependencies": ["ground"],
            "context_scope": {"passthrough": ["ground.x"]},
        }
    }
    assert find_missing_observe_deps(actions) == []


def test_nested_field_path_satisfies_dep():
    actions = {
        "consumer": {
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.a.b"]},
        }
    }
    assert find_missing_observe_deps(actions) == []


def test_deps_but_no_context_scope_is_flagged():
    actions = {"consumer": {"dependencies": ["ground"]}}
    assert any("consumer" in f for f in find_missing_observe_deps(actions))


def test_deps_but_empty_context_scope_is_flagged():
    actions = {"consumer": {"dependencies": ["ground"], "context_scope": {}}}
    assert any("consumer" in f for f in find_missing_observe_deps(actions))


def test_no_deps_is_fine():
    assert find_missing_observe_deps({"a": {"context_scope": {"observe": []}}}) == []


def test_malformed_ref_does_not_satisfy_dep():
    # A dotless ref is skipped by the runtime's reference parser, so the
    # dependency is unreferenced at execution time — preflight must agree.
    actions = {
        "consumer": {
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground"]},
        }
    }
    findings = find_missing_observe_deps(actions)
    assert any("'ground'" in f and "not referenced" in f for f in findings)


def test_substring_dep_name_not_falsely_satisfied():
    actions = {
        "consumer": {
            "dependencies": ["author"],
            "context_scope": {"observe": ["coauthor.stem"]},
        }
    }
    findings = find_missing_observe_deps(actions)
    assert any("'author'" in f and "not referenced" in f for f in findings)


def test_drop_refs_do_not_satisfy_dep():
    # Only observe/passthrough load fields at runtime; drop does not.
    actions = {
        "consumer": {
            "dependencies": ["ground"],
            "context_scope": {"drop": ["ground.x"]},
        }
    }
    findings = find_missing_observe_deps(actions)
    assert any("'ground'" in f and "not referenced" in f for f in findings)


def test_version_base_dependency_satisfied_by_expanded_branches():
    # The loader expands a versioned producer into <base>_N actions and
    # rewrites the consumer's observe refs to the branch names, but leaves
    # dependencies on the base name. The runtime resolves this through
    # infer_dependencies — a raw string comparison false-positives here.
    actions = {
        "extract_raw_qa_1": {"context_scope": {"observe": ["source.*"]}},
        "extract_raw_qa_2": {"context_scope": {"observe": ["source.*"]}},
        "consumer": {
            "dependencies": ["extract_raw_qa"],
            "context_scope": {"observe": ["extract_raw_qa_1.*", "extract_raw_qa_2.*"]},
        },
    }
    assert find_missing_observe_deps(actions) == []


def test_version_base_dependency_with_unreferenced_branches_is_flagged():
    actions = {
        "extract_raw_qa_1": {"context_scope": {"observe": ["source.*"]}},
        "extract_raw_qa_2": {"context_scope": {"observe": ["source.*"]}},
        "consumer": {
            "dependencies": ["extract_raw_qa"],
            "context_scope": {"observe": ["source.*"]},
        },
    }
    findings = find_missing_observe_deps(actions)
    assert findings, "unreferenced version branches must still be flagged"
    assert all("extract_raw_qa" in f for f in findings)


def test_all_offenders_reported():
    actions = {
        "first": {
            "dependencies": ["ground", "author"],
            "context_scope": {"observe": ["author.stem"]},
        },
        "second": {
            "dependencies": ["ground"],
            "context_scope": {"observe": ["source.field"]},
        },
    }
    findings = find_missing_observe_deps(actions)
    assert any("first" in f and "'ground'" in f for f in findings)
    assert any("second" in f and "'ground'" in f for f in findings)
    assert len(findings) == 2


# flatten -> mid -> final, each reading the one before it.
CHAIN = {
    "flatten": {"context_scope": {"observe": ["source.page"]}},
    "mid": {"dependencies": ["flatten"], "context_scope": {"observe": ["flatten.x"]}},
    "final": {"dependencies": ["mid"], "context_scope": {"observe": ["mid.x"]}},
}


def _with_late(**late):
    return {**CHAIN, "late": late}


def test_a_name_downstream_of_the_readers_input_is_flagged():
    actions = _with_late(
        dependencies=["flatten"], context_scope={"observe": ["flatten.x", "final.x"]}
    )
    (finding,) = find_reads_not_upstream(actions)
    assert finding.startswith("late:") and "'final'" in finding


def test_a_name_on_another_branch_is_flagged():
    """It is on the reader's records only while that branch ends at an earlier level."""
    actions = {
        **_with_late(dependencies=["side"], context_scope={"observe": ["side.x", "mid.x"]}),
        "side": {"dependencies": ["flatten"], "context_scope": {"observe": ["flatten.x"]}},
    }
    (finding,) = find_reads_not_upstream(actions)
    assert "'mid'" in finding


def test_a_reader_with_no_dependencies_is_flagged():
    """It reads the staged input, which carries no action's namespace."""
    actions = _with_late(context_scope={"observe": ["flatten.x", "source.page"]})
    (finding,) = find_reads_not_upstream(actions)
    assert finding.startswith("late:") and "'flatten'" in finding


def test_a_name_in_the_prompt_is_a_read_too():
    actions = _with_late(
        dependencies=["flatten"],
        context_scope={"observe": ["flatten.x"]},
        prompt="Compare {{ flatten.x }} with {{ final.x }}",
    )
    (finding,) = find_reads_not_upstream(actions)
    assert "'final'" in finding


def test_a_name_upstream_through_the_dependencies_passes():
    actions = _with_late(
        dependencies=["final"],
        context_scope={"observe": ["final.x", "flatten.x"]},
        prompt="{{ mid.x }}",
    )
    assert find_reads_not_upstream(actions) == []


def test_framework_namespaces_are_not_actions():
    actions = _with_late(
        dependencies=["flatten"],
        context_scope={"observe": ["flatten.x", "source.page", "seed.rules"]},
    )
    assert find_reads_not_upstream(actions) == []


def test_a_version_base_in_the_dependencies_puts_every_branch_upstream():
    actions = {
        "ground": {"context_scope": {"observe": ["source.page"]}},
        "vote_1": {"dependencies": ["ground"], "context_scope": {"observe": ["ground.x"]}},
        "vote_2": {"dependencies": ["ground"], "context_scope": {"observe": ["ground.x"]}},
        "tally": {
            "dependencies": ["vote"],
            "context_scope": {"observe": ["vote_1.*", "vote_2.*", "ground.x"]},
        },
    }
    assert find_reads_not_upstream(actions) == []


def test_a_name_behind_a_version_merge_further_up_passes():
    """A version base expands wherever it sits on the way up, not only on the reader."""
    actions = {
        "ground": {"context_scope": {"observe": ["source.page"]}},
        "vote_1": {"dependencies": ["ground"], "context_scope": {"observe": ["ground.x"]}},
        "vote_2": {"dependencies": ["ground"], "context_scope": {"observe": ["ground.x"]}},
        "tally": {"dependencies": ["vote"], "context_scope": {"observe": ["vote_1.*", "vote_2.*"]}},
        "report": {
            "dependencies": ["tally"],
            "context_scope": {"observe": ["tally.x", "vote_1.x", "ground.x"]},
        },
    }
    assert find_reads_not_upstream(actions) == []


def test_a_version_merge_left_out_of_the_dependencies_is_reported_by_its_base():
    """The base is the name the author wrote, and the one `dependencies` takes."""
    actions = {
        "ground": {"context_scope": {"observe": ["source.page"]}},
        "vote_1": {
            "version_base_name": "vote",
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.x"]},
        },
        "vote_2": {
            "version_base_name": "vote",
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.x"]},
        },
        "tally": {"context_scope": {"observe": ["vote_1.*", "vote_2.*"]}},
    }
    (finding,) = find_reads_not_upstream(actions)
    assert finding.startswith("tally:") and "Add 'vote' to its dependencies" in finding


def test_one_branch_of_a_version_merge_is_reported_by_its_own_name():
    actions = {
        "ground": {"context_scope": {"observe": ["source.page"]}},
        "vote_1": {
            "version_base_name": "vote",
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.x"]},
        },
        "vote_2": {
            "version_base_name": "vote",
            "dependencies": ["ground"],
            "context_scope": {"observe": ["ground.x"]},
        },
        "tally": {
            "dependencies": ["vote_2"],
            "context_scope": {"observe": ["vote_1.*", "vote_2.*"]},
        },
    }
    (finding,) = find_reads_not_upstream(actions)
    assert "Add 'vote_1' to its dependencies" in finding


def test_a_switched_off_action_neither_reads_nor_is_read():
    """The run order leaves both out, as it leaves out every action switched off."""
    actions = {
        **_with_late(dependencies=["flatten"], context_scope={"observe": ["flatten.x", "off.x"]}),
        "off": {"is_operational": False, "context_scope": {"observe": ["final.x"]}},
    }
    assert find_reads_not_upstream(actions) == []


def test_every_name_outside_the_lineage_is_reported():
    actions = {
        **_with_late(dependencies=["flatten"], context_scope={"observe": ["final.x", "mid.x"]}),
        "other": {"dependencies": ["mid"], "context_scope": {"observe": ["mid.x", "late.x"]}},
    }
    findings = find_reads_not_upstream(actions)
    assert sorted((f.split(":")[0], f.split("'")[1]) for f in findings) == [
        ("late", "final"),
        ("late", "mid"),
        ("other", "late"),
    ]
