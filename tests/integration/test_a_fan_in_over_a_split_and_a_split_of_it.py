"""A fan-in over a split and a split of that split pairs every record of the deeper split.

`right` splits each source in two and `resplit` splits each of those in two again. A
fan-in reading both (and `left`, one record per source) pooled records of one split
beside records split from them. With `resplit` read first it paired each `right` record
with `left` and dropped every `resplit` record, exiting 0; read last, it failed saying
the two branches split one source on their own (#1440).
"""

from itertools import permutations
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.integration import test_a_fan_in_pairs_a_split_branch_by_its_source as probe

RESPLIT = """  - name: resplit
    kind: tool
    intent: "split each split record again"
    impl: split_again
    schema: again_out
    dependencies: [right]
    context_scope: { observe: [right.right_tag] }
"""

TOOLS = """

@udf_tool
def split_again(data: Any, *args) -> list[dict]:
    tag = str(_find(data, "right_tag"))
    return [{"again_tag": f"{tag}-x"}, {"again_tag": f"{tag}-y"}]


@udf_tool
def join_all(data: Any, *args) -> list[dict]:
    tags = (_find(data, "left_tag"), _find(data, "right_tag"), _find(data, "again_tag"))
    return [{"joined": "|".join(str(tag) for tag in tags)}]
"""

OBSERVED = {"left": "left.left_tag", "right": "right.right_tag", "resplit": "resplit.again_tag"}


def _project(root: Path, branches: tuple[str, ...]) -> Path:
    config = (
        probe.HEADER
        + probe.LEFT.format(impl="tag_left")
        + probe.RIGHT
        + RESPLIT
        + "  - name: join\n"
        "    kind: tool\n"
        '    intent: "fan-in"\n'
        "    impl: join_all\n"
        "    schema: join_out\n"
        f"    dependencies: [{', '.join(branches)}]\n"
        f"    context_scope: {{ observe: [{', '.join(OBSERVED[b] for b in branches)}] }}\n"
    )
    probe._project(root, config)
    tools = root / "tools" / probe.WORKFLOW / "probe_tools.py"
    tools.write_text(tools.read_text() + TOOLS)
    (root / "schema" / probe.WORKFLOW / "again_out.yml").write_text(
        "name: again_out\nfields:\n  - id: again_tag\n    type: string\n"
    )
    return root


def _paired(left: bool) -> list[str]:
    return sorted(
        f"{f'L-{item}' if left else None}|R-{item}-{n}|R-{item}-{n}-{end}"
        for item in ("a", "b", "c")
        for n in (1, 2)
        for end in ("x", "y")
    )


@pytest.mark.parametrize("branches", list(permutations(("left", "right", "resplit"))))
def test_each_record_of_the_deeper_split_is_paired_with_its_split_and_its_source(
    tmp_path, branches
):
    root = _project(tmp_path, branches)

    result = run_agac(root, "run", "-a", probe.WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert len(probe._rows(root, "resplit")) == 12
    assert probe._joined(root) == _paired(left=True)


@pytest.mark.parametrize("branches", [("right", "resplit"), ("resplit", "right")])
def test_a_split_and_its_own_split_pair_without_the_source(tmp_path, branches):
    root = _project(tmp_path, branches)

    result = run_agac(root, "run", "-a", probe.WORKFLOW, "--fresh")

    assert result.returncode == 0, result.stdout + result.stderr
    assert probe._joined(root) == _paired(left=False)
