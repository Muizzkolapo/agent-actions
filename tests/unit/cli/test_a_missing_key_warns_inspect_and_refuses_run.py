"""A missing credential is a warning for a structural check and an error for a run."""

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.llm.config.endpoints import load_project_endpoints
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

ERROR = (
    "API key environment variable 'OPENAI_API_KEY' is not set "
    "(required by action 'summarize', vendor 'openai')"
)
WARNING = f"{ERROR}; connection check skipped"
HINT = "Set the environment variable: export OPENAI_API_KEY=..."
ACTION = {"model_vendor": "openai", "api_key": "OPENAI_API_KEY"}


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)


def _project(root: Path) -> str:
    wf = "demo"
    (root / "agent_actions.yml").write_text("version: '1.0'\nschema_path: schema\n")
    for name in ("templates", "rendered_workflows", "prompt_store", "schema"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "agent_workflow" / wf / "agent_io" / "staging").mkdir(parents=True)
    cfg_dir = root / "agent_workflow" / wf / "agent_config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / f"{wf}.yml").write_text(
        textwrap.dedent(f"""\
        name: {wf}
        description: demo
        defaults:
          json_mode: true
          granularity: Record
          run_mode: online
          model_name: gpt-4o-mini
          model_vendor: openai
          api_key: OPENAI_API_KEY
        actions:
          - name: summarize
            intent: summarize the source
            kind: llm
            context_scope:
              observe: ["source.*"]
            schema:
              fields:
                - id: summary
                  type: string
                  required: true
        """)
    )
    return wf


def _flat(text: str) -> str:
    return " ".join(text.split())


class TestTheCommandLine:
    @pytest.mark.parametrize("command", [["inspect"], ["schema"]], ids=["inspect", "schema"])
    def test_a_structural_command_passes_and_warns_of_the_missing_key(
        self, tmp_path, monkeypatch, command
    ):
        wf = _project(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, [*command, "-a", wf])

        output = _flat(result.output)
        assert result.exit_code == 0, result.output
        assert output.count(WARNING) == 1
        assert HINT in output

    def test_run_still_refuses_the_missing_key(self, tmp_path, monkeypatch):
        wf = _project(tmp_path)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["run", "-a", wf])

        output = _flat(result.output)
        assert result.exit_code != 0
        assert output.count(ERROR) == 1
        assert HINT in output
        assert "connection check skipped" not in output


class TestTheResolutionService:
    def test_a_check_that_sends_nothing_warns_with_the_hint(self):
        result = WorkflowResolutionService(
            action_configs={"summarize": ACTION}, sends_requests=False
        ).resolve_all()

        assert result.errors == []
        assert [(w.message, w.hint) for w in result.warnings] == [(WARNING, HINT)]

    def test_a_check_before_requests_are_sent_refuses_the_key(self):
        result = WorkflowResolutionService(
            action_configs={"summarize": ACTION}, sends_requests=True
        ).resolve_all()

        assert [(e.message, e.hint) for e in result.errors] == [(ERROR, HINT)]
        assert result.warnings == []

    def test_a_set_key_gives_neither_error_nor_warning(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        result = WorkflowResolutionService(
            action_configs={"summarize": ACTION}, sends_requests=False
        ).resolve_all()

        assert result.errors == []
        assert result.warnings == []


ENDPOINTS = {
    "lab-vllm": {"url": "${LAB_VLLM_URL}", "auth": {"env": "LAB_TOKEN", "header": "api-key"}},
    "vertex": {
        "url": "https://aiplatform.googleapis.com/v1/openapi",
        "auth": {"command": ["agac-no-such-command", "token"]},
    },
}
SCHEMA = {"name": "classify", "fields": [{"id": "label", "type": "string"}]}


def _endpoint_action(vendor: str) -> dict:
    return {"kind": "llm", "model_vendor": vendor, "model_name": "m", "schema": SCHEMA}


class TestADeclaredEndpoint:
    @pytest.fixture(autouse=True)
    def _endpoints(self, monkeypatch):
        load_project_endpoints({"endpoints": ENDPOINTS})
        monkeypatch.delenv("LAB_VLLM_URL", raising=False)
        monkeypatch.delenv("LAB_TOKEN", raising=False)

    def _resolve(self, sends_requests: bool):
        return WorkflowResolutionService(
            action_configs={
                "classify": _endpoint_action("lab-vllm"),
                "review": _endpoint_action("vertex"),
            },
            sends_requests=sends_requests,
        ).resolve_all()

    def test_an_absent_variable_or_command_warns_a_check_that_sends_nothing(self):
        result = self._resolve(sends_requests=False)

        assert result.errors == []
        assert [w.message for w in result.warnings] == [
            "Action 'classify': endpoint 'lab-vllm' reads its url from LAB_VLLM_URL, "
            "which is not set; connection check skipped",
            "Action 'classify': endpoint 'lab-vllm' reads LAB_TOKEN, which is not set; "
            "connection check skipped",
            "Action 'review': endpoint 'vertex' auth command 'agac-no-such-command' "
            "is not on PATH; connection check skipped",
        ]

    def test_an_absent_variable_or_command_refuses_a_run(self):
        result = self._resolve(sends_requests=True)

        assert result.warnings == []
        assert [e.message for e in result.errors] == [
            "Action 'classify': endpoint 'lab-vllm' reads its url from LAB_VLLM_URL, "
            "which is not set",
            "Action 'classify': endpoint 'lab-vllm' reads LAB_TOKEN, which is not set",
            "Action 'review': endpoint 'vertex' auth command 'agac-no-such-command' is not on PATH",
        ]

    def test_a_set_variable_with_a_bad_value_is_refused_in_both_modes(self, monkeypatch):
        monkeypatch.setenv("LAB_VLLM_URL", "gpu-box:8000/v1")
        monkeypatch.setenv("LAB_TOKEN", "token")

        for sends_requests in (False, True):
            result = WorkflowResolutionService(
                action_configs={"classify": _endpoint_action("lab-vllm")},
                sends_requests=sends_requests,
            ).resolve_all()

            assert [e.message for e in result.errors] == [
                "Action 'classify': endpoint 'lab-vllm' reads its url from LAB_VLLM_URL: "
                "must start with http:// or https://"
            ]
