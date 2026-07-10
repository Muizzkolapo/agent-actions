"""Unit tests for the dependency/observe preflight checker."""

from agent_actions.validation.dep_observe_validator import find_missing_observe_deps


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
