"""A reader skipped because its upstream holds nothing holds nothing either (1230).

A skip never rewrites the reader's output, so whatever it stored before stands
unless the skip removes it. Rows made from upstream output that no longer exists
are removed; rows made from upstream output a failed run carried are not.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _backend,
    chained,  # noqa: F401
    project,  # noqa: F401
)

THIRD_ACTION = """  - name: recap
    kind: tool
    dependencies: [enrich]
    intent: "Recap"
    schema: tool_action_output
    impl: tag_density
    context_scope: { observe: [enrich.summary] }
    expect: { repair: none }
"""


BROKEN_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def flatten_broken(data: Any, *args) -> list[dict]:
    raise RuntimeError("down")
"""


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _add_guard(root, impl, guard):
    config = _config(root)
    config.write_text(
        config.read_text().replace(f"    impl: {impl}\n", f"    impl: {impl}\n    guard: {guard}\n")
    )


def _filter_everything_upstream_and_reset_readers(root):
    """Edit the upstream so it filters every record, and edit its readers so they reset."""
    _add_guard(
        root,
        "flatten_pages",
        '{ condition: \'source.page_content == "none"\', on_false: "filter" }',
    )
    _add_guard(root, "tag_density", "{ condition: 'true', on_false: \"skip\" }")


def _rows(root, action):
    backend = _backend(root)
    try:
        return sum(
            len(backend._read_target_raw(action, path))
            for path in backend.list_target_files(action)
        )
    finally:
        backend.close()


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
    assert result.exit_code == 0, result.output
    return result


def test_a_reset_reader_skipped_under_an_empty_upstream_keeps_no_rows(chained):  # noqa: F811
    _filter_everything_upstream_and_reset_readers(chained)

    _run()

    assert _rows(chained, ACTION) == 0
    assert _rows(chained, SECOND) == 0


def test_a_second_run_keeps_it_empty_and_lifting_the_filter_restores_it(chained):  # noqa: F811
    _filter_everything_upstream_and_reset_readers(chained)
    _run()
    _run()
    assert _rows(chained, SECOND) == 0

    config = _config(chained)
    config.write_text(
        "".join(line for line in config.read_text().splitlines(True) if "guard:" not in line)
    )
    _run()

    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS


def test_the_drop_reaches_a_reader_of_the_reader(chained):  # noqa: F811
    config = _config(chained)
    config.write_text(config.read_text().rstrip("\n") + "\n" + THIRD_ACTION)
    _run("--fresh")
    assert _rows(chained, "recap") == RECORDS

    _filter_everything_upstream_and_reset_readers(chained)
    _run()

    assert _rows(chained, SECOND) == 0
    assert _rows(chained, "recap") == 0


def test_a_reader_of_an_upstream_that_failed_but_kept_its_rows_keeps_its_own(chained):  # noqa: F811
    # A new module: the tool already imported in this process would not see an edit.
    (chained / "tools" / WORKFLOW / "broken.py").write_text(BROKEN_TOOL)
    config = _config(chained)
    config.write_text(config.read_text().replace("impl: flatten_pages", "impl: flatten_broken"))
    _add_guard(chained, "flatten_broken", "{ condition: 'true', on_false: \"skip\" }")
    _add_guard(chained, "tag_density", "{ condition: 'true', on_false: \"skip\" }")

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert "Upstream dependency 'flatten' failed" in result.output, result.output
    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
