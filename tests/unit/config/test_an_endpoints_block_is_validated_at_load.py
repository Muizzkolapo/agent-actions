"""An `endpoints:` block in agent_actions.yml is validated when the project config loads.

Every refusal names the endpoint and the key, and reaches the user through `agac inspect`.
The loaded endpoints form a per-project registry that the next project load replaces.
A project with no block loads as before.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

from agent_actions.config.path_config import load_project_config
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


def _project(tmp_path: Path, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_actions.yml").write_text(text)
    return tmp_path


def _refusal(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigValidationError) as info:
        load_project_config(_project(tmp_path, text))
    return info.value.context["reason"]


@pytest.fixture
def endpoints():
    return importlib.import_module("agent_actions.llm.config.endpoints")


def test_a_valid_block_loads_with_its_defaults(tmp_path, endpoints):
    config = load_project_config(_project(tmp_path, VALID))
    loaded = endpoints.project_endpoints()

    assert set(loaded) == {"lab-vllm", "azure-gpt", "vertex-gemini"}
    assert set(config["endpoints"]) == set(loaded)

    lab = loaded["lab-vllm"]
    assert lab.url == "http://gpu-box:8000/v1"
    assert lab.auth is None
    assert lab.timeout_seconds == 120
    assert lab.headers == {}

    azure = loaded["azure-gpt"]
    assert azure.timeout_seconds == 30
    assert azure.auth.env == "AZURE_OPENAI_KEY"
    assert azure.auth.command is None
    assert azure.auth.header == "api-key"
    assert azure.auth.prefix == ""
    assert azure.headers == {"api-version": "2024-10-21"}

    vertex = loaded["vertex-gemini"]
    assert vertex.auth.env is None
    assert vertex.auth.command == ["gcloud", "auth", "application-default", "print-access-token"]
    assert vertex.auth.refresh_seconds == 600
    assert vertex.auth.header == "Authorization"
    assert vertex.auth.prefix == "Bearer "


def test_the_command_refresh_defaults_to_3000_seconds(tmp_path, endpoints):
    text = "endpoints:\n  v:\n    url: http://h/v1\n    auth: { command: [cmd] }\n"
    load_project_config(_project(tmp_path, text))

    assert endpoints.project_endpoints()["v"].auth.refresh_seconds == 3000


REFUSALS = [
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    format: custom\n",
        "endpoints.lab-vllm: unknown key 'format'",
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
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n",
        "endpoints.lab-vllm: auth is required; write 'auth: none' for an endpoint "
        "that takes no credential",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: token\n",
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
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n"
        "    auth: { env: A, refresh_seconds: 60 }\n",
        "endpoints.lab-vllm.auth: refresh_seconds applies to command auth only",
    ),
    (
        "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1/chat/completions\n    auth: none\n",
        "endpoints.lab-vllm.url: give the base URL, for example http://gpu-box:8000/v1; "
        "agac adds /chat/completions",
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
        "    timeout_seconds: 0\n",
        "endpoints.lab-vllm.timeout_seconds: must be greater than 0",
    ),
    (
        "endpoints:\n  - lab-vllm\n",
        "endpoints: must be a mapping of endpoint name to its settings",
    ),
    (
        "endpoints:\n  lab-vllm: http://gpu-box:8000/v1\n",
        "endpoints.lab-vllm: must be a mapping with url and auth",
    ),
]


@pytest.mark.parametrize(("text", "reason"), REFUSALS, ids=[r[1][:40] for r in REFUSALS])
def test_each_load_refusal_names_the_endpoint_and_the_key(tmp_path, text, reason):
    assert _refusal(tmp_path, text) == reason


def test_a_credential_header_written_as_an_env_var_is_accepted(tmp_path, endpoints):
    text = (
        "endpoints:\n  acme:\n    url: https://llm.acme.internal/v1\n    auth: none\n"
        "    headers:\n      X-Api-Key: ${ACME_TOKEN}\n      anthropic-version: '2023-06-01'\n"
    )
    load_project_config(_project(tmp_path, text))

    assert endpoints.project_endpoints()["acme"].headers == {
        "X-Api-Key": "${ACME_TOKEN}",
        "anthropic-version": "2023-06-01",
    }


def test_a_url_env_var_resolves_when_set(tmp_path, endpoints, monkeypatch):
    monkeypatch.setenv("VERTEX_OPENAI_URL", VERTEX_URL)
    load_project_config(_project(tmp_path, VALID))
    loaded = endpoints.project_endpoints()

    assert loaded["vertex-gemini"].url_env_var == "VERTEX_OPENAI_URL"
    assert loaded["vertex-gemini"].resolved_url() == VERTEX_URL
    assert loaded["lab-vllm"].url_env_var is None
    assert loaded["lab-vllm"].resolved_url() == "http://gpu-box:8000/v1"


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_a_url_env_var_that_is_unset_is_refused_when_resolved(
    tmp_path, endpoints, monkeypatch, value
):
    if value is None:
        monkeypatch.delenv("VERTEX_OPENAI_URL", raising=False)
    else:
        monkeypatch.setenv("VERTEX_OPENAI_URL", value)
    load_project_config(_project(tmp_path, VALID))

    with pytest.raises(ConfigurationError) as info:
        endpoints.project_endpoints()["vertex-gemini"].resolved_url()

    assert info.value.context["reason"] == (
        "endpoint 'vertex-gemini' reads its url from VERTEX_OPENAI_URL, which is not set"
    )


def test_a_resolved_url_obeys_the_same_rules_as_a_literal_one(tmp_path, endpoints, monkeypatch):
    monkeypatch.setenv("VERTEX_OPENAI_URL", VERTEX_URL + "/chat/completions")
    load_project_config(_project(tmp_path, VALID))

    with pytest.raises(ConfigurationError) as info:
        endpoints.project_endpoints()["vertex-gemini"].resolved_url()

    assert info.value.context["reason"] == (
        "endpoints.vertex-gemini.url: give the base URL, for example http://gpu-box:8000/v1; "
        "agac adds /chat/completions"
    )


def test_a_project_with_no_block_loads_as_before_and_empties_the_registry(tmp_path, endpoints):
    load_project_config(_project(tmp_path / "a", VALID))
    assert len(endpoints.project_endpoints()) == 3

    (tmp_path / "b").mkdir()
    config = load_project_config(_project(tmp_path / "b", "tool_path: [tools]\n"))

    assert config == {"tool_path": ["tools"]}
    assert endpoints.project_endpoints() == {}


def test_loading_another_project_replaces_the_registry(tmp_path, endpoints):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    load_project_config(_project(tmp_path / "a", VALID))
    other = "endpoints:\n  other-one:\n    url: http://other:9000/v1\n    auth: none\n"
    load_project_config(_project(tmp_path / "b", other))

    assert set(endpoints.project_endpoints()) == {"other-one"}


def test_the_refusal_reaches_the_user_through_agac_inspect(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    base = project_file.read_text()

    # Positive control: a valid block does not change the inspect verdict.
    project_file.write_text(base + VALID)
    ok = run_agac(root, "inspect", "-a", "tool_action", env={"VERTEX_OPENAI_URL": VERTEX_URL})
    assert ok.returncode == 0, ok.stdout + ok.stderr

    project_file.write_text(
        base + "endpoints:\n  lab-vllm:\n    url: http://gpu-box:8000/v1\n    auth: none\n"
        "    format: custom\n"
    )
    refused = run_agac(root, "inspect", "-a", "tool_action")
    output = refused.stdout + refused.stderr

    assert refused.returncode == 1, output
    assert "endpoints.lab-vllm: unknown key 'format'" in output
