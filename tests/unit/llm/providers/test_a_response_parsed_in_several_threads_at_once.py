"""Records answered at once parse their responses at once, and each parse must succeed.

The openai, anthropic and groq SDKs can build their pydantic response models on first
use, and pydantic's rebuild is not thread-safe: a thread that reads a model while
another builds it can find the base class's placeholder and raise "BaseModel cannot be
instantiated directly". A window of `record_concurrency` records parses its first
answers on several threads together, so one record of the window failed.

Each case runs in a new interpreter, because only the first parse in a process builds
the models. A short thread switch interval and a barrier put every thread in the build
together.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests._support.agac_cli import REPO

THREADS = 16
ATTEMPTS = 3

_RACE = """
import json, sys, threading
import {client}
from {sdk}._models import construct_type
from {response_module} import {response_class} as Response

payload = json.loads(sys.argv[1])
sys.setswitchinterval(1e-6)
barrier = threading.Barrier({threads})
errors = []

def parse():
    barrier.wait()
    try:
        construct_type(type_=Response, value=payload)
    except Exception as error:
        errors.append(f"{{type(error).__name__}}: {{str(error).splitlines()[0]}}")

threads = [threading.Thread(target=parse) for _ in range({threads})]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(json.dumps(errors))
"""

_CHAT_COMPLETION = {
    "id": "c",
    "object": "chat.completion",
    "created": 1,
    "model": "m",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@pytest.mark.parametrize(
    ("client", "sdk", "response_module", "response_class", "payload"),
    [
        pytest.param(
            "agent_actions.llm.providers.openai.client",
            "openai",
            "openai.types.chat",
            "ChatCompletion",
            _CHAT_COMPLETION,
            id="openai",
        ),
        pytest.param(
            "agent_actions.llm.providers.anthropic.client",
            "anthropic",
            "anthropic.types",
            "Message",
            {
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "m",
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            id="anthropic",
        ),
        pytest.param(
            "agent_actions.llm.providers.groq.client",
            "groq",
            "groq.types.chat",
            "ChatCompletion",
            _CHAT_COMPLETION,
            id="groq",
        ),
    ],
)
def test_every_thread_parses_the_first_response_of_a_process(
    client, sdk, response_module, response_class, payload
):
    script = _RACE.format(
        client=client,
        sdk=sdk,
        response_module=response_module,
        response_class=response_class,
        threads=THREADS,
    )
    env = {key: value for key, value in os.environ.items() if key != "DEFER_PYDANTIC_BUILD"}
    env["PYTHONPATH"] = str(REPO)

    for _ in range(ATTEMPTS):
        done = subprocess.run(
            [sys.executable, "-c", script, json.dumps(payload)],
            capture_output=True,
            text=True,
            cwd=REPO,
            env=env,
            timeout=120,
        )
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout) == []
