"""A fan-in over a branch that split its records pairs each one with the other branch.

A branch that returns several records per input gives each a new source id, so the
merge grouped every record alone: the fan-in ran once per record of each branch with
the other branch's fields empty, and the run reported success (#1430).
"""

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "fanin_probe"

TOOLS = """import os
from typing import Any

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


def _find(d: Any, key: str):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


@udf_tool
def tag_left(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "item_id"))}]


@udf_tool
def split_left(data: Any, *args) -> list[dict]:
    item = str(_find(data, "item_id"))
    return [{"left_tag": f"L-{item}-1"}, {"left_tag": f"L-{item}-2"}]


@udf_tool
def split_right(data: Any, *args) -> list[dict]:
    item = str(_find(data, "item_id"))
    return [{"right_tag": f"R-{item}-1"}, {"right_tag": f"R-{item}-2"}]


@udf_tool
def shout_right(data: Any, *args) -> list[dict]:
    return [{"loud_tag": str(_find(data, "right_tag")).upper()}]


@udf_tool
def join_tags(data: Any, *args) -> list[dict]:
    right = _find(data, "loud_tag") or _find(data, "right_tag")
    return [{"joined": f"{_find(data, 'left_tag')}|{right}"}]


@udf_tool
def shout_left(data: Any, *args) -> list[dict]:
    return [{"left_tag": str(_find(data, "left_tag")).upper()}]


@udf_tool
def expand(data: Any, *args) -> list[dict]:
    item = str(_find(data, "item_id"))
    return [{"part": f"{item}-1"}, {"part": f"{item}-2"}]


@udf_tool
def left_of_part(data: Any, *args) -> list[dict]:
    return [{"left_tag": "L-" + str(_find(data, "part"))}]


@udf_tool
def mid_of_part(data: Any, *args) -> list[dict]:
    return [{"mid_tag": "M-" + str(_find(data, "part"))}]


@udf_tool(granularity=Granularity.FILE)
def gather_right(data: list[dict], **kwargs) -> FileUDFResult:
    if os.environ.get("GATHER_FAILS"):
        raise RuntimeError("gather is down")
    by_item: dict[str, list[int]] = {}
    for position, record in enumerate(data):
        by_item.setdefault(str(record["right_tag"]).split("-")[1], []).append(position)
    return FileUDFResult(
        outputs=[
            {
                "source_index": positions,
                "data": {"right_tag": "+".join(str(data[p]["right_tag"]) for p in positions)},
            }
            for positions in by_item.values()
        ]
    )


@udf_tool
def join_three(data: Any, *args) -> list[dict]:
    tags = (_find(data, "left_tag"), _find(data, "mid_tag"), _find(data, "right_tag"))
    return [{"joined": "|".join(str(tag) for tag in tags if tag is not None)}]
"""

LEFT = """  - name: left
    kind: tool
    intent: "left branch"
    impl: {impl}
    schema: left_out
    context_scope: {{ observe: [source.item_id] }}
"""

RIGHT = """  - name: right
    kind: tool
    intent: "two records per input"
    impl: split_right
    schema: right_out
    context_scope: { observe: [source.item_id] }
"""

LOUD = """  - name: loud
    kind: tool
    intent: "one record per input, after the split"
    impl: shout_right
    schema: loud_out
    dependencies: [right]
    context_scope: { observe: [right.right_tag] }
"""


def _config(
    dependencies: str,
    *,
    left_impl: str = "tag_left",
    after_split: bool = False,
    left_guard: str = "",
) -> str:
    branch = "loud" if after_split else "right"
    field = "loud.loud_tag" if after_split else "right.right_tag"
    return (
        f"name: {WORKFLOW}\n"
        'description: "fan-in over a branch that splits each record in two"\n'
        'version: "0.1.0"\n'
        "defaults:\n"
        "  granularity: Record\n"
        "  run_mode: online\n"
        "  model_vendor: agac-provider\n"
        "  model_name: mock\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
        "actions:\n"
        + LEFT.format(impl=left_impl)
        + (f"    guard: {{ condition: '{left_guard}', on_false: filter }}\n" if left_guard else "")
        + RIGHT
        + (LOUD if after_split else "")
        + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_tags\n"
        "    schema: join_out\n"
        f"    dependencies: [{dependencies.replace('right', branch)}]\n"
        f"    context_scope: {{ observe: [left.left_tag, {field}] }}\n"
    )


def _project(root: Path, config: str) -> Path:
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: gpt-oss:120b-cloud\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    (workflow / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"item_id": "a"}, {"item_id": "b"}, {"item_id": "c"}])
    )
    (root / "tools" / WORKFLOW / "probe_tools.py").write_text(TOOLS)
    for action, field in (
        ("left", "left_tag"),
        ("right", "right_tag"),
        ("loud", "loud_tag"),
        ("join", "joined"),
        ("expand", "part"),
        ("mid", "mid_tag"),
    ):
        (root / "schema" / WORKFLOW / f"{action}_out.yml").write_text(
            f"name: {action}_out\nfields:\n  - id: {field}\n    type: string\n"
        )
    return root


def _rows(root: Path, action: str) -> list[dict]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    found = stored_rows(db, "select data from target_data where action_name = ?", action)
    return [record["content"][action] for (data,) in found for record in json.loads(data)]


def _joined(root: Path) -> list[str]:
    return sorted(row["joined"] for row in _rows(root, "join"))


PAIRED = sorted(f"L-{item}|R-{item}-{n}" for item in ("a", "b", "c") for n in (1, 2))


@pytest.mark.parametrize("dependencies", ["left, right", "right, left"])
def test_no_fan_in_record_is_missing_a_branch(tmp_path, dependencies):
    root = _project(tmp_path, _config(dependencies))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_rows(root, "left")) == 3
    assert len(_rows(root, "right")) == 6
    assert not [joined for joined in _joined(root) if "None" in joined]


@pytest.mark.parametrize("dependencies", ["left, right", "right, left"])
def test_each_split_record_is_paired_with_the_record_it_came_from(tmp_path, dependencies):
    root = _project(tmp_path, _config(dependencies))

    run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert _joined(root) == PAIRED


def test_a_split_branch_read_through_a_later_action_is_paired_too(tmp_path):
    root = _project(tmp_path, _config("left, right", after_split=True))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == sorted(
        f"L-{item}|R-{item.upper()}-{n}" for item in ("a", "b", "c") for n in (1, 2)
    )


def test_two_branches_split_from_one_record_fail_the_fan_in(tmp_path):
    root = _project(tmp_path, _config("left, right", left_impl="split_left"))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "join" in output
    assert "left" in output and "right" in output
    assert "None" not in " ".join(_joined(root))


def test_a_source_filtered_out_of_one_branch_drops_the_other_branchs_split_records(tmp_path):
    root = _project(tmp_path, _config("left, right", left_guard='source.item_id != "b"'))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == [joined for joined in PAIRED if "-b" not in joined]


HEADER = (
    f"name: {WORKFLOW}\n"
    'description: "fan-in over branches that split one source"\n'
    'version: "0.1.0"\n'
    "defaults:\n"
    "  granularity: Record\n"
    "  run_mode: online\n"
    "  model_vendor: agac-provider\n"
    "  model_name: mock\n"
    "  api_key: OLLAMA_API_KEY\n"
    "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
    "actions:\n"
)


def _keep_first(branch: str, field: str, prefix: str, impl: str, schema: str) -> str:
    """An action below a split branch that filters out the second record of each source."""
    kept = " and ".join(f'{branch}.{field} != "{prefix}-{item}-2"' for item in ("a", "b", "c"))
    return (
        f"  - name: keep_{branch}\n"
        "    kind: tool\n"
        '    intent: "the first record of each split"\n'
        f"    impl: {impl}\n"
        f"    schema: {schema}\n"
        f"    dependencies: [{branch}]\n"
        f"    context_scope: {{ observe: [{branch}.{field}] }}\n"
        f"    guard: {{ condition: '{kept}', on_false: filter }}\n"
    )


def _split_then_kept(*, keep_left: bool, keep_right: bool) -> str:
    """Both branches split each source; either may then keep one record of each split."""
    left = "keep_left" if keep_left else "left"
    right = "keep_right" if keep_right else "right"
    return (
        HEADER
        + LEFT.format(impl="split_left")
        + RIGHT
        + (_keep_first("left", "left_tag", "L", "shout_left", "left_out") if keep_left else "")
        + (_keep_first("right", "right_tag", "R", "shout_right", "loud_out") if keep_right else "")
        + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_tags\n"
        "    schema: join_out\n"
        f"    dependencies: [{left}, {right}]\n"
        f"    context_scope: {{ observe: [{left}.left_tag, "
        f"{right}.{'loud_tag' if keep_right else 'right_tag'}] }}\n"
    )


def _assert_refused(result, root: Path, *branches: str) -> None:
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "join" in output
    for branch in branches:
        assert branch in output
    assert "upstream of every branch" in output
    assert _joined(root) == []


@pytest.mark.parametrize(("keep_left", "keep_right"), [(True, False), (False, True), (True, True)])
def test_two_split_branches_fail_the_fan_in_after_keeping_one_record_of_a_split(
    tmp_path, keep_left, keep_right
):
    """Both branches split each source; a guard below one or both then keeps one record
    of each split. No record of one branch is any record of the other's, so nothing pairs."""
    root = _project(tmp_path, _split_then_kept(keep_left=keep_left, keep_right=keep_right))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    _assert_refused(
        result,
        root,
        "keep_left" if keep_left else "left",
        "keep_right" if keep_right else "right",
    )


EXPAND = """  - name: expand
    kind: tool
    intent: "two records per input, read by two branches"
    impl: expand
    schema: expand_out
    context_scope: { observe: [source.item_id] }
"""


def _over_expand(name: str, impl: str, schema: str) -> str:
    return (
        f"  - name: {name}\n"
        "    kind: tool\n"
        '    intent: "one record per part"\n'
        f"    impl: {impl}\n"
        f"    schema: {schema}\n"
        "    dependencies: [expand]\n"
        "    context_scope: { observe: [expand.part] }\n"
    )


def _expansion_beside_a_split(*, with_right: bool) -> str:
    """Two branches read one expansion of each source; a third may split the source itself."""
    deps = "left, mid, right" if with_right else "left, mid"
    observe = "left.left_tag, mid.mid_tag" + (", right.right_tag" if with_right else "")
    return (
        HEADER
        + EXPAND
        + _over_expand("left", "left_of_part", "left_out")
        + _over_expand("mid", "mid_of_part", "mid_out")
        + (RIGHT if with_right else "")
        + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_three\n"
        "    schema: join_out\n"
        f"    dependencies: [{deps}]\n"
        f"    context_scope: {{ observe: [{observe}] }}\n"
    )


def test_a_branch_that_splits_a_source_beside_branches_over_an_expansion_of_it_fails(tmp_path):
    """`left` and `mid` hold one expansion of each source and pair with each other;
    `right` split the same source on its own, so none of its records pairs with theirs."""
    root = _project(tmp_path, _expansion_beside_a_split(with_right=True))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    _assert_refused(result, root, "right")


def test_branches_over_one_expansion_pair_record_by_record(tmp_path):
    root = _project(tmp_path, _expansion_beside_a_split(with_right=False))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == sorted(
        f"L-{item}-{n}|M-{item}-{n}" for item in ("a", "b", "c") for n in (1, 2)
    )


GATHER = """  - name: gather
    kind: tool
    intent: "the split records of each source in one record"
    impl: gather_right
    granularity: File
    schema: right_out
    dependencies: [right]
    context_scope: { observe: [right.right_tag] }
"""


def _gathered(left_impl: str) -> str:
    """`gather` folds `right`'s split of each source into one record; `left` beside it."""
    config = _config("left, right", left_impl=left_impl)
    config = config.replace("  - name: join\n", GATHER + "  - name: join\n")
    config = config.replace("dependencies: [left, right]", "dependencies: [left, gather]")
    return config.replace(
        "observe: [left.left_tag, right.right_tag]", "observe: [left.left_tag, gather.right_tag]"
    )


GATHERED_BESIDE_A_SPLIT = sorted(
    f"L-{item}-{n}|R-{item}-1+R-{item}-2" for item in ("a", "b", "c") for n in (1, 2)
)


def test_a_split_gathered_into_one_record_pairs_with_another_split_of_its_source(tmp_path):
    """`gather` holds one record per source, built from every record `right` split from
    it, so it is that source's record: each of `left`'s split records pairs with it."""
    root = _project(tmp_path, _gathered("split_left"))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _joined(root) == GATHERED_BESIDE_A_SPLIT


def _stored(root: Path, action: str) -> list[dict]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    found = stored_rows(db, "select data from target_data where action_name = ?", action)
    return [record for (data,) in found for record in json.loads(data)]


def test_a_split_gathered_into_one_record_carries_the_identity_of_its_source(tmp_path):
    root = _project(tmp_path, _gathered("tag_left"))

    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    by_item = {
        row["content"]["left"]["left_tag"][2:]: row["source_guid"] for row in _stored(root, "left")
    }
    assert {
        row["content"]["gather"]["right_tag"][2]: row["source_guid"]
        for row in _stored(root, "gather")
    } == by_item
    assert _joined(root) == sorted(f"L-{item}|R-{item}-1+R-{item}-2" for item in ("a", "b", "c"))


def test_a_retry_of_a_failed_gather_pairs_it_with_the_other_split(tmp_path):
    root = _project(tmp_path, _gathered("split_left"))
    failed = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env={"GATHER_FAILS": "1"})
    assert _joined(root) == [], failed.stdout + failed.stderr

    result = run_agac(root, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_stored(root, "gather")) == 3
    assert _joined(root) == GATHERED_BESIDE_A_SPLIT


def test_a_retry_of_one_split_record_rewrites_the_gather_in_place(tmp_path):
    """A FILE tool is handed the whole file again; nothing lands beside the old rows."""
    root = _project(tmp_path, _gathered("split_left"))
    run_agac(root, "run", "-a", WORKFLOW, "--fresh", env={"GATHER_FAILS": "1"})
    record = next(row["source_guid"] for row in _stored(root, "right"))

    result = run_agac(root, "retry", "-a", WORKFLOW, "--from", "gather", "--record", record)

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_stored(root, "gather")) == 3
    assert len({row["source_guid"] for row in _stored(root, "gather")}) == 3
    assert _joined(root) == GATHERED_BESIDE_A_SPLIT
