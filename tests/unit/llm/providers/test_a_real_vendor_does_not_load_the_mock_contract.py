"""Loading the online client registry does not load the mock's contract stack.

Every vendor goes through the registry, which names the agac client. The contract it uses
reads the expectation suite, so it is loaded only when the mock answers a request.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
MOCK_ONLY = ("agent_actions.llm.providers.agac.contract", "agent_actions.expectations.runner")


def test_the_registry_loads_no_contract_module():
    code = (
        "import json, sys\n"
        "import agent_actions.llm.realtime.services.invocation\n"
        f"print(json.dumps([m for m in {MOCK_ONLY!r} if m in sys.modules]))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )

    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
