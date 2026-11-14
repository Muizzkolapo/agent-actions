"""Entries that report what a warm `agac` child was handed, for the control tests.

Each runs in the child in place of the CLI, through `run_in_warm_process(entry=...)`.
"""

from __future__ import annotations

import atexit
import json
import os
import random
import signal
import sys
import tempfile
import threading
import time


def report() -> int:
    from agent_actions.llm.config.endpoints import Endpoint

    url = (
        Endpoint(name="probe", url="${PROBE_URL}").resolved_url()
        if "PROBE_URL" in os.environ
        else None
    )
    print(
        json.dumps(
            {
                "argv": sys.argv,
                "cwd": os.getcwd(),
                "env": {
                    key: os.environ[key] for key in sorted(os.environ) if key.startswith("PROBE_")
                },
                "endpoint_url": url,
                "path0": sys.path[0],
                "stdin": sys.stdin.read(),
                "tempdir": tempfile.gettempdir(),
                "random": random.random(),
                "tz": time.tzname[0],
            }
        )
    )
    return 0


def exit_with_argument() -> int:
    return int(sys.argv[1])


def exit_with_message() -> None:
    sys.exit("probe: a message instead of a code")


def raise_error() -> None:
    raise RuntimeError("probe: an uncaught error")


def kill_itself() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def sleep_for_argument() -> int:
    with open("pid", "w") as pid_file:
        pid_file.write(str(os.getpid()))
    time.sleep(float(sys.argv[1]))
    return 0


def meet_the_other() -> int:
    """Leave a marker, then wait for the other call's: only calls that overlap can meet."""
    mine, other = sys.argv[1], sys.argv[2]
    open(os.path.join("..", f"{mine}.here"), "w").close()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if os.path.exists(os.path.join("..", f"{other}.here")):
            return 0
        time.sleep(0.01)
    return 3


def write_much() -> int:
    size = int(sys.argv[1])
    sys.stdout.write("o" * size)
    sys.stderr.write("e" * size)
    return 0


def exit_cleanly() -> int:
    """A non-daemon thread and an atexit handler both run before a normal interpreter exits."""
    threading.Thread(target=lambda: (time.sleep(0.2), print("thread finished", flush=True))).start()
    atexit.register(print, "atexit ran")
    return 0


def do_nothing() -> int:
    return 0


def exit_at_once() -> None:
    os._exit(0)
