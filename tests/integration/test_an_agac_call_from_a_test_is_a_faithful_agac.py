"""A `run_agac` call costs a fork, not an interpreter start, and still behaves as `agac`.

The warm child must look like a fresh `agac` process to the code it runs. Each control
below hands two calls different values, so a child that kept the warm process's value,
or the previous call's, fails it.
"""

import json
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time

import pytest

from tests._support.agac_cli import (
    AGAC,
    REPO,
    RUNNER,
    WarmProcessError,
    _startup_settings,
    run_agac,
    run_in_warm_process,
    warm_process_pid,
)

PROBE = "tests._support.agac_child_probe"


def _probe(cwd, name, *args, env=None, timeout=30):
    return run_in_warm_process(cwd, *args, env=env, entry=f"{PROBE}:{name}", timeout=timeout)


def _report(cwd, env=None):
    result = _probe(cwd, "report", env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(
    RUNNER == "fresh", reason="AGAC_TEST_RUNNER=fresh starts an interpreter per call"
)
def test_a_call_that_does_no_work_is_five_times_faster_than_a_fresh_interpreter(tmp_path):
    def median_seconds(calls, **options):
        durations = []
        for _ in range(calls):
            started = time.perf_counter()
            result = run_agac(tmp_path, "--help", **options)
            durations.append(time.perf_counter() - started)
            assert result.returncode == 0, result.stderr
        return statistics.median(durations)

    run_agac(tmp_path, "--help")
    warm = median_seconds(20)
    fresh = median_seconds(5, fresh_process=True)

    # Measured against a fresh start in the same test, so a loaded machine slows both.
    print(f"run_agac --help: median {warm:.3f} s warm, {fresh:.3f} s fresh (limit fresh / 5)")
    assert warm < fresh / 5


@pytest.mark.parametrize(
    "args",
    [["--help"], ["--version"], ["no-such-command"], ["run", "-a", "no_such_workflow"]],
    ids=["help", "version", "unknown-command", "run-outside-a-project"],
)
def test_a_command_answers_as_it_does_from_a_fresh_interpreter(tmp_path, args):
    warm = run_agac(tmp_path, *args)
    fresh = run_agac(tmp_path, *args, fresh_process=True)

    def without_clock(text):
        return re.sub(r"\b\d\d:\d\d:\d\d\b", "HH:MM:SS", text)

    assert warm.returncode == fresh.returncode
    assert without_clock(warm.stdout) == without_clock(fresh.stdout)
    assert without_clock(warm.stderr) == without_clock(fresh.stderr)


def test_a_variable_set_for_one_call_is_gone_in_the_next(tmp_path):
    assert _report(tmp_path, env={"PROBE_ONLY_HERE": "1"})["env"] == {"PROBE_ONLY_HERE": "1"}
    assert _report(tmp_path)["env"] == {}


def test_an_endpoint_url_read_from_the_environment_follows_each_call(tmp_path):
    first = _report(tmp_path, env={"PROBE_URL": "http://127.0.0.1:1/first"})
    second = _report(tmp_path, env={"PROBE_URL": "http://127.0.0.1:2/second"})

    assert first["endpoint_url"] == "http://127.0.0.1:1/first"
    assert second["endpoint_url"] == "http://127.0.0.1:2/second"


def test_each_call_runs_in_its_own_folder(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    assert _report(tmp_path / "a")["cwd"] == str((tmp_path / "a").resolve())
    assert _report(tmp_path / "b")["cwd"] == str((tmp_path / "b").resolve())


def test_the_child_has_the_argv_import_path_and_stdin_of_the_console_script(tmp_path):
    report = _probe(tmp_path, "report", "list-udfs", "-u", "tools")
    seen = json.loads(report.stdout)

    assert seen["argv"] == [str(AGAC), "list-udfs", "-u", "tools"]
    assert seen["path0"] == os.path.dirname(os.path.realpath(AGAC))
    assert seen["stdin"] == ""


def test_the_temp_dir_and_time_zone_follow_each_call(tmp_path):
    (tmp_path / "t1").mkdir()
    (tmp_path / "t2").mkdir()

    # POSIX zone strings, so the test needs no zoneinfo database.
    first = _report(tmp_path, env={"TMPDIR": str(tmp_path / "t1"), "TZ": "AAA+03"})
    second = _report(tmp_path, env={"TMPDIR": str(tmp_path / "t2"), "TZ": "BBB-04"})

    assert (first["tempdir"], first["tz"]) == (str(tmp_path / "t1"), "AAA")
    assert (second["tempdir"], second["tz"]) == (str(tmp_path / "t2"), "BBB")


def test_two_calls_draw_different_random_numbers(tmp_path):
    assert _report(tmp_path)["random"] != _report(tmp_path)["random"]


def test_large_stdout_and_stderr_come_back_whole_and_apart(tmp_path):
    size = 2 * 1024 * 1024
    result = _probe(tmp_path, "write_much", str(size))

    assert result.stdout == "o" * size
    assert result.stderr == "e" * size


@pytest.mark.parametrize(
    ("entry", "args", "returncode", "in_stderr"),
    [
        ("exit_with_argument", ["3"], 3, ""),
        ("exit_with_message", [], 1, "probe: a message instead of a code"),
        ("raise_error", [], 1, "RuntimeError: probe: an uncaught error"),
        ("kill_itself", [], -signal.SIGKILL, ""),
    ],
    ids=["code", "message", "uncaught-error", "killed"],
)
def test_the_exit_status_is_the_one_a_process_gives(tmp_path, entry, args, returncode, in_stderr):
    result = _probe(tmp_path, entry, *args)

    assert result.returncode == returncode
    assert in_stderr in result.stderr


def test_a_normal_exit_joins_threads_then_runs_atexit_handlers(tmp_path):
    result = _probe(tmp_path, "exit_cleanly")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "thread finished\natexit ran\n"


def test_a_call_past_its_timeout_raises_and_its_child_is_killed(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        _probe(tmp_path, "sleep_for_argument", "30", timeout=2)

    pid = int((tmp_path / "pid").read_text())
    assert _gone_within(pid, 5), f"the child {pid} still runs after its call timed out"


def test_two_calls_run_at_the_same_time(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    results = {}

    def call(mine, other):
        results[mine] = _probe(tmp_path / mine, "meet_the_other", mine, other)

    threads = [threading.Thread(target=call, args=pair) for pair in (("a", "b"), ("b", "a"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # A call run after the other finished waits 20 s for a marker that never comes.
    assert [results[name].returncode for name in ("a", "b")] == [0, 0]


def _gone_within(pid, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_caller_that_dies_mid_call_takes_its_child_with_it(tmp_path):
    caller = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; "
            "from tests._support.agac_cli import run_in_warm_process; "
            "run_in_warm_process(Path(sys.argv[1]), '60', "
            f"entry='{PROBE}:sleep_for_argument', timeout=120)",
            str(tmp_path),
        ],
        cwd=REPO,
    )
    pid_file = tmp_path / "pid"
    deadline = time.monotonic() + 60
    while not pid_file.exists() or not pid_file.read_text():
        assert time.monotonic() < deadline, "the child never started"
        assert caller.poll() is None, f"the caller exited with {caller.returncode}"
        time.sleep(0.05)
    child = int(pid_file.read_text())

    caller.kill()
    caller.wait()

    assert _gone_within(child, 5), f"the child {child} outlived the caller that started it"


def test_path_like_arguments_and_values_reach_the_child_as_text(tmp_path):
    from pathlib import Path

    result = run_in_warm_process(
        tmp_path,
        Path("an-argument"),
        env={"PROBE_PATH": Path("/a/value")},
        entry=f"{PROBE}:report",
        timeout=30,
    )
    seen = json.loads(result.stdout)

    assert seen["argv"][1:] == ["an-argument"]
    assert seen["env"] == {"PROBE_PATH": "/a/value"}


def test_a_dead_warm_process_fails_the_call_that_finds_it_and_the_next_call_starts_another(
    tmp_path,
):
    dead = warm_process_pid()
    os.kill(dead, signal.SIGKILL)
    time.sleep(0.2)

    with pytest.raises(WarmProcessError, match=rf"pid {dead}, exit status -9"):
        _report(tmp_path)

    assert _report(tmp_path)["cwd"] == str(tmp_path.resolve())
    assert warm_process_pid() != dead


def test_a_call_with_its_own_interpreter_settings_gets_a_fresh_interpreter(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text("import sys\nsys.stderr.write('sitecustomize ran\\n')\n")

    fresh = run_agac(tmp_path, "--help", env={"PYTHONPATH": str(site)})
    warm = run_agac(tmp_path, "--help")

    assert "sitecustomize ran" in fresh.stderr
    assert "sitecustomize ran" not in warm.stderr


@pytest.mark.parametrize("fresh_process", [False, True], ids=["warm", "fresh"])
def test_a_missing_folder_raises_before_anything_runs(tmp_path, fresh_process):
    (tmp_path / "a_file").write_text("")

    with pytest.raises(FileNotFoundError):
        run_agac(tmp_path / "missing", "--help", fresh_process=fresh_process)
    with pytest.raises(NotADirectoryError):
        run_agac(tmp_path / "a_file", "--help", fresh_process=fresh_process)


def test_a_relative_folder_is_read_from_the_caller_s_cwd(tmp_path, monkeypatch):
    (tmp_path / "here").mkdir()
    monkeypatch.chdir(tmp_path)

    assert _report("here")["cwd"] == str((tmp_path / "here").resolve())


def test_the_interpreter_startup_settings_are_the_python_and_locale_variables():
    env = {"PYTHONHASHSEED": "0", "LANG": "C", "LC_ALL": "C", "HOME": "/h", "PATH": "/bin"}

    assert _startup_settings(env) == {"PYTHONHASHSEED": "0", "LANG": "C", "LC_ALL": "C"}
