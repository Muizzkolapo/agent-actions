"""A project resource is a listed file itself: never `.env` or stored data through a link."""

import pytest

from agent_actions.tooling.mcp.app import PROJECT_SCHEME, _project_file, _project_files


@pytest.fixture
def project(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    (tmp_path / ".env").write_text("SECRET_KEY=sk-topsecret\n")
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "wf.md").write_text("{prompt Ask}\n")
    return tmp_path


def test_the_files_that_define_a_workflow_are_listed(project):
    assert sorted(_project_files(project)) == [
        PROJECT_SCHEME + "agent_actions.yml",
        PROJECT_SCHEME + "prompt_store/wf.md",
    ]


def test_a_link_to_a_file_of_the_project_is_not_listed(project):
    (project / "prompt_store" / "leak.md").symlink_to(project / ".env")

    assert PROJECT_SCHEME + "prompt_store/leak.md" not in _project_files(project)


def test_a_linked_project_folder_is_still_served(project, tmp_path_factory):
    link = tmp_path_factory.mktemp("elsewhere") / "linked"
    link.symlink_to(project, target_is_directory=True)

    assert PROJECT_SCHEME + "agent_actions.yml" in _project_files(link)


def test_a_read_finds_each_listed_file_and_nothing_else(project):
    (project / "schema" / "wf" / "deep").mkdir(parents=True)
    (project / "schema" / "wf" / "deep" / "a.yml").write_text("fields: []\n")
    (project / "prompt_store" / "nested").mkdir()
    (project / "prompt_store" / "nested" / "b.md").write_text("x\n")
    (project / "prompt_store" / "leak.md").symlink_to(project / ".env")

    listed = _project_files(project)

    assert {uri: _project_file(project, uri) for uri in listed} == listed
    for uri in (
        PROJECT_SCHEME + ".env",
        PROJECT_SCHEME + "prompt_store/nested/b.md",
        PROJECT_SCHEME + "prompt_store/leak.md",
        PROJECT_SCHEME + "prompt_store/../.env",
        PROJECT_SCHEME + "/etc/passwd",
        PROJECT_SCHEME + "prompt_store/missing.md",
    ):
        assert _project_file(project, uri) is None, uri
