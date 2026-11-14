"""`agac run` refuses a `vendor_params` key the vendor's request does not take (1767).

Before, an unknown key in an action had no effect and drew no warning. Each run is an
`agac run` on a project whose action inherits `vendor_params` from `defaults:`.
"""

import json
import shutil
from pathlib import Path

from tests._support.agac_cli import run_agac

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "vendor_params_wf"

CONFIG = """name: vendor_params_wf
description: "an action that passes request parameters to its vendor"
version: "0.1.0"
defaults:
  model_vendor: {vendor}
  model_name: claude-haiku-5-5
  api_key: ANTHROPIC_API_KEY
  json_mode: true
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
  vendor_params: {{ {default_params} }}
actions:
  - name: write_quiz
    intent: "Write one question"
    prompt: "Write one question about {{{{ source.page_content }}}}"
    schema: {{ question: string }}
    vendor_params: {{ top_k: 40 }}
    context_scope: {{ observe: [source.page_content] }}
"""


def _run(tmp_path: Path, vendor: str, default_params: str):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(vendor=vendor, default_params=default_params)
    )
    (directory / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p0", "page_content": "tides"}])
    )
    result = run_agac(
        root, "run", "-a", WORKFLOW, "--fresh", env={"ANTHROPIC_API_KEY": "sk-not-used"}
    )
    return result, " ".join((result.stdout + result.stderr).split())


def test_a_misspelled_key_is_refused_before_any_request(tmp_path):
    result, output = _run(tmp_path, "anthropic", "thinkng: { type: disabled }")

    assert result.returncode == 1, output
    assert (
        "Action 'write_quiz': vendor_params for 'anthropic': 'thinkng' is not a request parameter"
        in output
    ), output
    assert "thinking" in output.split("valid keys:", 1)[1], output


def test_a_key_agac_sets_is_refused(tmp_path):
    result, output = _run(tmp_path, "anthropic", "model: claude-opus-5-5")

    assert result.returncode == 1, output
    assert "'model' is set by agac and cannot be passed through" in output, output


def test_the_mock_provider_runs_with_the_same_block(tmp_path):
    result, output = _run(tmp_path, "agac-provider", "thinking: { type: disabled }")

    assert result.returncode == 0, output
