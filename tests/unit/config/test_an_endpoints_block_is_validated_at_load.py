"""An `endpoints:` block in agent_actions.yml is validated beside its reader, like the other blocks.

`load_project_endpoints` validates the block and makes it the project's endpoint registry;
`ConfigManager` calls it where it reads the project defaults. Every refusal names the
endpoint and the key, reaches the user through `agac inspect` in the error block, and never
through the boot-time logging line. A refused block leaves no endpoint registered. The next
project load replaces the registry. A project with no block loads as before, and the plain
project-config helpers keep reading their own keys whatever the block says.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

from agent_actions.config.path_config import get_tool_dirs, load_project_config
from agent_actions.errors import ConfigurationError, ConfigValidationError
from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).resolve().parents[2] / "integration" / "fixtures" / "expectation_authors"

VALID = """
endpoints:
  lab-vllm:
    url: http://gpu-box:8000/v1
    auth: none
  azure-gpt:
    url: https://my-resource.openai.azure.com/openai/v1
    timeout_seconds: 30
    auth: { env: AZURE_OPENAI_KEY, header: api-key }
    headers: { api-version: "2024-10-21" }
  vertex-gemini:
    url: ${VERTEX_OPENAI_URL}
    auth:
      command: [gcloud, auth, application-default, print-access-token]
      refresh_seconds: 600
"""

VERTEX_URL = "https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi"
BAD_BLOCK = (
    "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n    format: custom\n"
)
URL_HINT = "give the base URL, for example http://gpu-box:8000/v1; agac adds /chat/completions"


def _project(tmp_path: Path, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_actions.yml").write_text(text)
    return tmp_path


@pytest.fixture
def endpoints():
    return importlib.import_module("agent_actions.llm.config.endpoints")


@pytest.fixture
def load(endpoints):
    """Load a project's config and its endpoints the way ConfigManager does."""

    def _load(root: Path):
        return endpoints.load_project_endpoints(load_project_config(root))

    return _load


def _refusal(load, tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigValidationError) as info:
        load(_project(tmp_path, text))
    return info.value.context["reason"]


def test_a_valid_block_loads_with_its_defaults(tmp_path, endpoints, load):
    loaded = load(_project(tmp_path, VALID))

    assert set(loaded) == {"lab-vllm", "azure-gpt", "vertex-gemini"}
    assert endpoints.project_endpoints() == loaded

    lab = loaded["lab-vllm"]
    assert lab.url == "http://gpu-box:8000/v1"
    assert lab.auth is None
    assert lab.timeout_seconds == 120
    assert lab.headers == {}

    azure = loaded["azure-gpt"]
    assert azure.timeout_seconds == 30
    assert azure.auth.env == "AZURE_OPENAI_KEY"
    assert azure.auth.command is None
    assert azure.auth.refresh_seconds is None
    assert azure.auth.header == "api-key"
    assert azure.auth.prefix == ""
    assert azure.headers == {"api-version": "2024-10-21"}

    vertex = loaded["vertex-gemini"]
    assert vertex.auth.env is None
    assert vertex.auth.command == ["gcloud", "auth", "application-default", "print-access-token"]
    assert vertex.auth.refresh_seconds == 600
    assert vertex.auth.header == "Authorization"
    assert vertex.auth.prefix == "Bearer "


def test_the_command_refresh_defaults_to_3000_seconds(tmp_path, load):
    text = "endpoints:\n  v:\n    url: http://h/v1\n    auth: { command: [cmd] }\n"

    assert load(_project(tmp_path, text))["v"].auth.refresh_seconds == 3000


def test_an_explicit_empty_prefix_on_authorization_is_kept(tmp_path, load):
    text = "endpoints:\n  v:\n    url: http://h/v1\n    auth: { env: K, prefix: '' }\n"

    assert load(_project(tmp_path, text))["v"].auth.prefix == ""


REFUSALS = [
    (BAD_BLOCK, "endpoints.lab-vllm: unknown key 'format'"),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n    1: x\n",
        "endpoints.lab-vllm: unknown key '1'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { env: A, true: x }\n",
        "endpoints.lab-vllm.auth: unknown key 'True'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n    name: x\n",
        "endpoints.lab-vllm: unknown key 'name'",
    ),
    (
        "endpoints:\n  openai:\n    url: http://gpu-box:8000/v1\n    auth: none\n",
        "endpoints.openai: 'openai' is a built-in vendor; choose another endpoint name",
    ),
    (
        "endpoints:\n  llamafile:\n    url: http://gpu-box:8000/v1\n    auth: none\n",
        "endpoints.llamafile: 'llamafile' is a built-in vendor; choose another endpoint name",
    ),
    (
        "endpoints:\n  google:\n    url: http://gpu-box:8000/v1\n    auth: none\n",
        "endpoints.google: 'google' is a built-in vendor; choose another endpoint name",
    ),
    (
        "endpoints:\n  Lab-VLLM:\n    url: http://gpu-box:8000/v1\n    auth: none\n",
        "endpoints.Lab-VLLM: use a lowercase name of letters, digits, '-' and '_'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    auth: none\n",
        "endpoints.lab-vllm: url is required",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: 8000\n    auth: none\n",
        "endpoints.lab-vllm.url: must be text",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n",
        "endpoints.lab-vllm: auth is required; write 'auth: none' for an endpoint "
        "that takes no credential",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: token\n",
        "endpoints.lab-vllm.auth: write 'auth: none', or a mapping with env or command",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth:\n",
        "endpoints.lab-vllm.auth: write 'auth: none', or a mapping with env or command",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n"
        "    auth: { env: A, command: [cmd] }\n",
        "endpoints.lab-vllm.auth: give exactly one of env or command, or write 'auth: none'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { header: X-Key }\n",
        "endpoints.lab-vllm.auth: give exactly one of env or command, or write 'auth: none'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { env: '' }\n",
        "endpoints.lab-vllm.auth.env: name the environment variable that holds the "
        "credential, for example AZURE_OPENAI_KEY",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { env: '${K}' }\n",
        "endpoints.lab-vllm.auth.env: name the environment variable that holds the "
        "credential, for example AZURE_OPENAI_KEY",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { command: [] }\n",
        "endpoints.lab-vllm.auth.command: give the command as a non-empty list of text, "
        "for example [gcloud, auth, print-access-token]",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { command: gcloud }\n",
        "endpoints.lab-vllm.auth.command: give the command as a non-empty list of text, "
        "for example [gcloud, auth, print-access-token]",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n"
        "    auth: { env: A, refresh_seconds: 60 }\n",
        "endpoints.lab-vllm.auth: refresh_seconds applies to command auth only",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n"
        "    auth: { command: [c], refresh_seconds: 0 }\n",
        "endpoints.lab-vllm.auth.refresh_seconds: must be a whole number greater than 0",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n"
        "    auth: { command: [c], refresh_seconds: true }\n",
        "endpoints.lab-vllm.auth.refresh_seconds: must be a whole number greater than 0",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1/chat/completions\n    auth: none\n",
        f"endpoints.lab-vllm.url: {URL_HINT}",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1/chat/completions/\n"
        "    auth: none\n",
        f"endpoints.lab-vllm.url: {URL_HINT}",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1/chat/completions?x=1\n"
        "    auth: none\n",
        f"endpoints.lab-vllm.url: {URL_HINT}",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://${GPU_HOST}:8000/v1\n    auth: none\n",
        "endpoints.lab-vllm.url: write the whole URL as one ${ENV_VAR}, or as a literal URL",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: gpu-box:8000/v1\n    auth: none\n",
        "endpoints.lab-vllm.url: must start with http:// or https://",
    ),
    (
        "endpoints:\n  azure-gpt:\n    url: https://r.openai.azure.com/openai/v1\n"
        "    auth: { env: AZURE_OPENAI_KEY, header: api-key }\n"
        "    headers: { X-Api-Key: abc123 }\n",
        "endpoints.azure-gpt.headers.X-Api-Key: write a credential as ${ENV_VAR}, "
        "not as a literal value",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers: { X-Auth-Token: abc123 }\n",
        "endpoints.lab-vllm.headers.X-Auth-Token: write a credential as ${ENV_VAR}, "
        "not as a literal value",
    ),
    (
        "endpoints:\n  azure-gpt:\n    url: https://r.openai.azure.com/openai/v1\n"
        "    auth: { env: AZURE_OPENAI_KEY, header: api-key }\n"
        "    headers:\n      API-Key: ${OTHER}\n",
        "endpoints.azure-gpt.headers.API-Key: this header is set by auth; remove it from headers",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers:\n      Authorization: ${TOKEN}\n",
        "endpoints.lab-vllm.headers.Authorization: this header is set by auth; "
        "remove it from headers",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers: [X-Trace]\n",
        "endpoints.lab-vllm.headers: must be a mapping",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers: { X-Trace: 1 }\n",
        "endpoints.lab-vllm.headers.X-Trace: must be text",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    timeout_seconds: 0\n",
        "endpoints.lab-vllm.timeout_seconds: must be a number greater than 0",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    timeout_seconds: .nan\n",
        "endpoints.lab-vllm.timeout_seconds: must be a number greater than 0",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    timeout_seconds: '30'\n",
        "endpoints.lab-vllm.timeout_seconds: must be a number greater than 0",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    timeout_seconds: true\n",
        "endpoints.lab-vllm.timeout_seconds: must be a number greater than 0",
    ),
    (
        "endpoints:\n  - lab-vllm\n",
        "endpoints: must be a mapping of endpoint name to its settings",
    ),
    (
        "endpoints:\n  lab-vllm: http://gpu-box:8000/v1\n",
        "endpoints.lab-vllm: must be a mapping with url and auth",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { command: [1] }\n",
        "endpoints.lab-vllm.auth.command: give the command as a non-empty list of text, "
        "for example [gcloud, auth, print-access-token]",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { command: ['', ''] }\n",
        "endpoints.lab-vllm.auth.command: give the command as a non-empty list of text, "
        "for example [gcloud, auth, print-access-token]",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { env: 123 }\n",
        "endpoints.lab-vllm.auth.env: name the environment variable that holds the "
        "credential, for example AZURE_OPENAI_KEY",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: { env: A, header: '' }\n",
        "endpoints.lab-vllm.auth.header: must be a header name",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers: { 1: x }\n",
        "endpoints.lab-vllm.headers: unknown key '1'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    headers: { '': x }\n",
        "endpoints.lab-vllm.headers: a header name must not be empty",
    ),
    (
        "endpoints:\n  8080:\n    url: http://gpu-box:8000/v1\n    auth: none\n",
        "endpoints: an endpoint name must be text; quote it, for example '8080'",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: 'http://gpu-box:8000/v1 '\n    auth: none\n",
        "endpoints.lab-vllm.url: must not contain whitespace",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: 'http://'\n    auth: none\n",
        "endpoints.lab-vllm.url: must name a host, for example http://gpu-box:8000/v1",
    ),
    (
        "endpoints:\n  a:\n    url: http://h/v1\n    auth: none\n"
        "  b:\n    url: http://h/v1/chat/completions\n    auth: none\n",
        f"endpoints.b.url: {URL_HINT}",
    ),
]


@pytest.mark.parametrize(("text", "reason"), REFUSALS, ids=[r[1][:48] for r in REFUSALS])
def test_each_load_refusal_names_the_endpoint_and_the_key(tmp_path, load, text, reason):
    assert _refusal(load, tmp_path, text) == reason


def test_a_refusal_is_a_single_error_with_no_pydantic_error_chained_under_it(tmp_path, load):
    with pytest.raises(ConfigValidationError) as info:
        load(_project(tmp_path, BAD_BLOCK))

    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_a_refused_block_leaves_no_endpoint_registered(tmp_path, endpoints, load):
    load(_project(tmp_path / "a", VALID))

    with pytest.raises(ConfigValidationError):
        load(_project(tmp_path / "b", BAD_BLOCK))

    assert endpoints.project_endpoints() == {}


def test_a_credential_header_written_as_an_env_var_is_accepted(tmp_path, load):
    text = (
        "endpoints:\n  acme:\n    url: https://llm.acme.internal/v1\n    auth: none\n"
        "    headers:\n      X-Api-Key: ${ACME_TOKEN}\n      anthropic-version: '2023-06-01'\n"
    )

    assert load(_project(tmp_path, text))["acme"].headers == {
        "X-Api-Key": "${ACME_TOKEN}",
        "anthropic-version": "2023-06-01",
    }


def test_a_url_env_var_resolves_when_set(tmp_path, load, monkeypatch):
    monkeypatch.setenv("VERTEX_OPENAI_URL", VERTEX_URL)
    loaded = load(_project(tmp_path, VALID))

    assert loaded["vertex-gemini"].url_env_var == "VERTEX_OPENAI_URL"
    assert loaded["vertex-gemini"].resolved_url() == VERTEX_URL
    assert loaded["lab-vllm"].url_env_var is None
    assert loaded["lab-vllm"].resolved_url() == "http://gpu-box:8000/v1"


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_a_url_env_var_that_is_unset_is_refused_when_resolved(tmp_path, load, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("VERTEX_OPENAI_URL", raising=False)
    else:
        monkeypatch.setenv("VERTEX_OPENAI_URL", value)
    loaded = load(_project(tmp_path, VALID))

    with pytest.raises(ConfigurationError) as info:
        loaded["vertex-gemini"].resolved_url()

    assert info.value.context["reason"] == (
        "endpoint 'vertex-gemini' reads its url from VERTEX_OPENAI_URL, which is not set"
    )


def test_a_resolved_url_obeys_the_same_rules_as_a_literal_one(tmp_path, load, monkeypatch):
    monkeypatch.setenv("VERTEX_OPENAI_URL", VERTEX_URL + "/chat/completions")
    loaded = load(_project(tmp_path, VALID))

    with pytest.raises(ConfigurationError) as info:
        loaded["vertex-gemini"].resolved_url()

    assert info.value.context["reason"] == f"endpoints.vertex-gemini.url: {URL_HINT}"


def test_a_project_with_no_block_loads_as_before_and_empties_the_registry(
    tmp_path, endpoints, load
):
    load(_project(tmp_path / "a", VALID))
    assert len(endpoints.project_endpoints()) == 3

    root = _project(tmp_path / "b", "tool_path: [tools]\n")
    assert load_project_config(root) == {"tool_path": ["tools"]}
    assert load(root) == {}
    assert endpoints.project_endpoints() == {}


def test_a_root_with_no_config_file_empties_the_registry(tmp_path, endpoints, load):
    load(_project(tmp_path / "a", VALID))
    (tmp_path / "b").mkdir()

    assert load(tmp_path / "b") == {}
    assert endpoints.project_endpoints() == {}


def test_loading_another_project_replaces_the_registry(tmp_path, endpoints, load):
    load(_project(tmp_path / "a", VALID))
    other = "endpoints:\n  other-one:\n    url: http://other:9000/v1\n    auth: none\n"
    load(_project(tmp_path / "b", other))

    assert set(endpoints.project_endpoints()) == {"other-one"}


def test_the_plain_project_helpers_still_read_their_keys_beside_a_bad_block(tmp_path, load):
    root = _project(tmp_path, "tool_path: [custom_tools]\n" + BAD_BLOCK)

    assert get_tool_dirs(root) == ["custom_tools"]
    assert load_project_config(root)["tool_path"] == ["custom_tools"]
    with pytest.raises(ConfigValidationError):
        load(root)


def test_the_refusal_reaches_the_user_through_agac_inspect_and_not_the_boot_line(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    base = project_file.read_text()

    # Positive control: a valid block does not change the inspect verdict.
    project_file.write_text(base + VALID)
    ok = run_agac(root, "inspect", "-a", "tool_action", env={"VERTEX_OPENAI_URL": VERTEX_URL})
    assert ok.returncode == 0, ok.stdout + ok.stderr

    project_file.write_text(base + BAD_BLOCK)
    refused = run_agac(root, "inspect", "-a", "tool_action")

    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "endpoints.lab-vllm: unknown key 'format'" in refused.stderr
    assert "Problem: Configuration validation failed for 'endpoints'" in refused.stderr
    assert "logging:" not in refused.stderr
    assert refused.stderr.count("endpoints.lab-vllm") == 1

    # A command that never reads the project is not told about the block.
    helped = run_agac(root, "--help")
    assert helped.returncode == 0
    assert "endpoints." not in helped.stdout + helped.stderr


def _manager(root: Path, user_config: dict, agent_name: str | None = None):
    from agent_actions.config.manager import ConfigManager

    manager = ConfigManager(
        constructor_path=str(root / "wf.yml"),
        default_path=str(root / "default.yml"),
        project_root=root,
    )
    manager.user_config = user_config
    manager.agent_name = agent_name
    return manager


LEGACY = {"legacy": {"agents": [{"agent_type": "flatten", "model_vendor": "tool"}]}}


def test_a_workflow_in_the_legacy_shape_is_held_to_the_block_too(tmp_path, endpoints):
    root = _project(tmp_path, BAD_BLOCK)

    with pytest.raises(ConfigValidationError) as info:
        _manager(root, LEGACY, "legacy").get_user_agents()

    assert info.value.context["reason"] == "endpoints.lab-vllm: unknown key 'format'"
    assert endpoints.project_endpoints() == {}


def test_a_workflow_in_the_legacy_shape_registers_a_valid_block(tmp_path, endpoints):
    root = _project(tmp_path, VALID)

    agents = _manager(root, LEGACY, "legacy").get_user_agents()

    assert agents == LEGACY["legacy"]["agents"]
    assert set(endpoints.project_endpoints()) == {"lab-vllm", "azure-gpt", "vertex-gemini"}


def test_a_project_refused_before_its_block_is_read_leaves_no_stale_registry(
    tmp_path, endpoints, load
):
    load(_project(tmp_path / "a", VALID))
    # max_iterations is bounded to 1-10, so this project is refused before endpoints are read.
    root = _project(
        tmp_path / "b", "default_agent_config:\n  expect: { max_iterations: 99 }\n" + VALID
    )

    with pytest.raises(ConfigurationError):
        _manager(root, {"name": "wf", "actions": []}).get_user_agents()

    assert endpoints.project_endpoints() == {}
