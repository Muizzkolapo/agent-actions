"""`model_vendor: google` is what the configuration reference says Gemini is called.

The reference gives `google` for Gemini in its Model Fields row and its Vendor Support
table, and `ollama` for Ollama. A workflow that wrote either did not load: `VendorType`
held `google` as an enum alias of `gemini`, which shares the value, so the list of
accepted names never held it. Pre-flight maps `google` to the Gemini config, but the
load refused the name before pre-flight ran.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.expander import ActionExpander
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "docs.agent-actions/docs/reference/configuration/index.md"
FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "vendor_name"

_CONFIG = """\
name: vendor_name
description: "One action, a vendor written the way the reference writes it"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: {vendor}
  model_name: gemini-2.0-flash
  api_key: GEMINI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: {{ summary: string }}
    prompt: "Summarise the page."
    context_scope: {{ observe: [source.page_content] }}
"""


def _expand(vendor: str, *, on_action: bool = False) -> dict:
    defaults = {"model_name": "gemini-2.0-flash", "api_key": "k"}
    action = {"name": "a1", "intent": "i", "prompt": "p"}
    if on_action:
        action["model_vendor"] = vendor
        defaults["model_vendor"] = "openai"
    else:
        defaults["model_vendor"] = vendor
    expanded = ActionExpander.expand_actions_to_agents(
        {"name": "wf", "actions": [action], "defaults": defaults}
    )
    return expanded["wf"][0]


def _vendors_the_reference_lists() -> list[str]:
    text = REFERENCE.read_text()
    row = re.search(r"^\|\s*`model_vendor`\s*\|[^|]*\|\s*Provider:\s*([^|]+)\|", text, re.M)
    assert row, "the Model Fields row naming the providers is gone"
    listed = {name.strip() for name in row.group(1).split(",")}

    table = text.split("## Vendor Support", 1)[1].split("\n## ", 1)[0]
    body = re.split(r"^\|[-|]+\|\s*$", table, maxsplit=1, flags=re.M)[1]
    listed |= set(re.findall(r"^\|[^|]*\|\s*`([a-z_-]+)`\s*\|", body, re.M))
    return sorted(listed)


class TestTheNameTheReferenceGivesForGemini:
    def test_google_set_in_defaults_reaches_the_agent_as_gemini(self):
        """One name from here on, so every later lookup — the batch client factory
        registers only `gemini` — finds the vendor."""
        assert _expand("google")["model_vendor"] == "gemini"

    def test_google_set_on_the_action_reaches_the_agent_as_gemini(self):
        assert _expand("google", on_action=True)["model_vendor"] == "gemini"

    def test_gemini_is_unchanged(self):
        assert _expand("gemini")["model_vendor"] == "gemini"


class TestEveryNameTheReferenceListsLoads:
    def test_each_listed_vendor_is_accepted(self):
        if not REFERENCE.exists():
            pytest.skip("docs not present")

        refused = []
        for vendor in _vendors_the_reference_lists():
            try:
                _expand(vendor)
            except ConfigValidationError as error:
                refused.append(f"{vendor}: {error}")

        assert refused == [], refused

    def test_the_reference_lists_vendors_it_can_be_read_for(self):
        """Control: the parse above is not vacuous."""
        if not REFERENCE.exists():
            pytest.skip("docs not present")

        listed = _vendors_the_reference_lists()

        assert {"openai", "anthropic", "groq", "cohere"} <= set(listed)


class TestAnUnknownVendorIsStillRefused:
    def test_a_name_that_is_nobodys_vendor_is_refused_with_the_accepted_names(self):
        with pytest.raises(ConfigValidationError) as raised:
            _expand("nonesuch")

        assert "Unknown vendor 'nonesuch'" in str(raised.value)
        assert "gemini" in raised.value.context["supported_vendors"]


class TestAWorkflowThatWritesGoogleRunsThroughTheCli:
    @pytest.fixture
    def project(self, tmp_path):
        root = tmp_path / "project"
        shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
        workflow = root / "agent_workflow" / WORKFLOW
        (workflow / "agent_config").mkdir(parents=True)
        (workflow / "agent_io" / "staging").mkdir(parents=True)
        (workflow / "agent_io" / "staging" / "pages.json").write_text(
            '[{"page_id": "p1", "page_content": "A."}]'
        )
        (root / ".env").write_text("GEMINI_API_KEY=not-used\n")

        def write(vendor: str) -> None:
            (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
                _CONFIG.format(vendor=vendor)
            )

        return root, write

    def test_inspect_loads_and_validates_a_workflow_whose_vendor_is_google(self, project):
        root, write = project
        write("google")

        result = run_agac(root, "inspect", "-a", WORKFLOW, env={"COLUMNS": "240"})
        output = result.stdout + result.stderr

        assert result.returncode == 0, output
        assert "validated" in output, output

    def test_the_same_workflow_written_gemini_loads_alike(self, project):
        """Control: only the name differs, so the CLI case above is not passing
        because the project around it is lenient."""
        root, write = project
        write("gemini")

        result = run_agac(root, "inspect", "-a", WORKFLOW, env={"COLUMNS": "240"})
        output = result.stdout + result.stderr

        assert result.returncode == 0, output
        assert "validated" in output, output
