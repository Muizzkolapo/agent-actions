"""I-6: Coverage of CatalogGenerator.generate() — happy path and empty input."""

import json
from collections import Counter

from agent_actions.tooling.docs.generator import CatalogGenerator, _merge_event_tails
from agent_actions.tooling.docs.scanner import EVENT_TAIL_LIMIT
from agent_actions.tooling.docs.scanner.data_scanners import scan_runs


def _make_generator(workflows_data=None, project_path="/tmp"):
    return CatalogGenerator(workflows_data or {}, project_path)


def _empty_inputs():
    return dict(
        prompts_data={},
        schemas_data={},
        tool_functions_data={},
        runs_data={},
        logs_data={
            "events_path": None,
            "recent_invocations": [],
            "validation_errors": [],
            "validation_warnings": [],
        },
        vendors_data={},
        error_types_data=[],
        event_types_data=[],
        examples_data=[],
        data_loaders_data=[],
        processing_states_data=[],
        workflow_data={},
        readmes_data={},
    )


class TestCatalogGeneratorEmptyInput:
    """CatalogGenerator.generate() with all-empty inputs returns valid catalog structure."""

    def test_returns_dict(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        for key in ("metadata", "stats"):
            assert key in result, f"Missing key: {key}"

    def test_stats_are_zero_for_empty_input(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        stats = result["stats"]
        assert stats["total_workflows"] == 0
        assert stats["total_actions"] == 0

    def test_no_exception_on_empty_input(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert isinstance(result, dict)
        assert "metadata" in result


class TestCatalogGeneratorHappyPath:
    """CatalogGenerator.generate() with minimal real-ish input."""

    def test_workflow_count_reflected_in_stats(self, tmp_path):
        import yaml

        wf_yml = tmp_path / "my_workflow.yml"
        wf_yml.write_text(
            yaml.dump(
                {
                    "name": "my_workflow",
                    "description": "A test workflow",
                    "actions": [
                        {"name": "step_one", "intent": "Does something"},
                    ],
                }
            )
        )
        # workflows_data maps name -> {"rendered": path_or_none, "original": path}
        workflows_data = {"my_workflow": {"rendered": None, "original": str(wf_yml)}}
        gen = _make_generator(workflows_data)
        result = gen.generate(**_empty_inputs())
        stats = result["stats"]
        assert stats["total_workflows"] == 1

    def test_metadata_contains_generator_info(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert "metadata" in result
        assert "generated_at" in result["metadata"]

    def test_metadata_contains_project_name(self):
        gen = _make_generator(project_path="/home/user/my_project")
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] == "my_project"

    def test_metadata_project_name_none_without_path(self):
        gen = CatalogGenerator({}, project_path=None)
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] is None

    def test_metadata_project_name_root_path(self):
        gen = _make_generator(project_path="/")
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] == ""


def _stream_rows(source: str, level: str, count: int) -> list[dict]:
    """Rows as a scanner hands them over: oldest first, each with its own `seq`."""
    return [
        {
            "seq": i,
            "level": level,
            "message": f"{source} {level} {i}",
            "meta": {"timestamp": f"2026-09-22T10:00:{i % 60:02d}.{i:06d}Z"},
            "data": {},
        }
        for i in range(count)
    ]


def _wf_events(
    workflow: str,
    seqs: list[int],
    hour: int = 10,
    meta_wf: str | None = None,
    level: str = "info",
) -> dict:
    """A scanned log. `meta_wf` differs from the source name for the project log,
    whose rows name whichever workflow the invocation targeted."""
    return {
        "workflow_name": workflow,
        "latest_run": None,
        "action_metrics": {},
        "runtime_warnings": [],
        "events": [
            {
                "seq": s,
                "event_type": "ActionCompleteEvent",
                "code": "A002",
                "level": level,
                "category": "action",
                "diagnostic": False,
                "message": f"{workflow} step {s}",
                "meta": {
                    "timestamp": f"2026-09-22T{hour:02d}:00:00.{s:06d}Z",
                    "invocation_id": "inv1",
                    "workflow_name": meta_wf or workflow,
                },
                "data": {"action_name": f"step_{s}"},
            }
            for s in seqs
        ],
        "manifest": None,
    }


class TestCatalogGeneratorEventStream:
    """The Log Explorer reads catalog["logs"]["events"]."""

    def test_empty_input_yields_an_empty_stream(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert result["logs"]["events"] == []

    def test_events_are_merged_newest_first_across_workflows(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {
            "alpha": _wf_events("alpha", [0, 1], hour=10),
            "beta": _wf_events("beta", [0], hour=11),
        }
        result = gen.generate(**inputs)

        messages = [e["message"] for e in result["logs"]["events"]]
        assert messages == ["beta step 0", "alpha step 1", "alpha step 0"]

    def test_event_id_is_namespaced_by_workflow(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {"alpha": _wf_events("alpha", [7])}
        result = gen.generate(**inputs)

        assert result["logs"]["events"][0]["id"] == "workflow:alpha:7"

    def test_a_busy_log_does_not_crowd_out_a_quiet_one(self):
        """One workflow logging far more — and more recently — must not take the
        whole window, or its neighbours become undiagnosable."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {
            "alpha": _wf_events("alpha", list(range(EVENT_TAIL_LIMIT)), hour=11),
            "beta": _wf_events("beta", [0, 1], hour=9),
        }
        result = gen.generate(**inputs)

        events = result["logs"]["events"]
        assert len(events) == EVENT_TAIL_LIMIT
        sources = {e["id"].rsplit(":", 1)[0] for e in events}
        assert sources == {"workflow:alpha", "workflow:beta"}

    def test_the_project_log_shares_the_window_with_workflows(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["logs_data"] = {
            **inputs["logs_data"],
            "events": _wf_events("logs", list(range(EVENT_TAIL_LIMIT)), hour=12, meta_wf="alpha")[
                "events"
            ],
        }
        inputs["runs_data"] = {"alpha": _wf_events("alpha", [0, 1], hour=9)}
        result = gen.generate(**inputs)

        sources = {e["id"].rsplit(":", 1)[0] for e in result["logs"]["events"]}
        assert sources == {"project:logs", "workflow:alpha"}

    def test_the_window_keeps_each_log_s_newest_events(self):
        """Filling the shared budget from the oldest end would drop exactly the rows
        a tail exists to show."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {
            "alpha": _wf_events("alpha", list(range(EVENT_TAIL_LIMIT)), hour=11),
            "beta": _wf_events("beta", [0, 1], hour=9),
        }
        events = gen.generate(**inputs)["logs"]["events"]

        alpha = sorted(e["seq"] for e in events if e["id"].startswith("workflow:alpha:"))
        beta = sorted(e["seq"] for e in events if e["id"].startswith("workflow:beta:"))
        assert alpha[-1] == EVENT_TAIL_LIMIT - 1
        assert alpha[0] == 2
        assert beta == [0, 1]

    def test_a_workflow_named_logs_does_not_displace_the_project_log(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["logs_data"] = {**inputs["logs_data"], "events": _wf_events("logs", [0])["events"]}
        inputs["runs_data"] = {"logs": _wf_events("logs", [0], hour=11)}
        result = gen.generate(**inputs)

        ids = {e["id"] for e in result["logs"]["events"]}
        assert ids == {"project:logs:0", "workflow:logs:0"}

    def test_diagnostic_rows_survive_the_merge(self):
        """The explorer hides diagnostics behind a toggle; it cannot show what the
        catalog dropped."""
        gen = _make_generator()
        inputs = _empty_inputs()
        wf = _wf_events("alpha", [0, 1])
        wf["events"][0]["diagnostic"] = True
        inputs["runs_data"] = {"alpha": wf}
        events = gen.generate(**inputs)["logs"]["events"]

        assert sum(1 for e in events if e["diagnostic"]) == 1

    def test_the_tail_is_not_echoed_into_catalog_runs(self):
        """The stream is embedded once. Echoing every workflow's tail under runs
        doubled a megabyte-scale payload the dashboard never reads."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {"alpha": _wf_events("alpha", [0, 1])}
        result = gen.generate(**inputs)

        assert "events" not in result["runs"]["alpha"]
        assert result["runs"]["alpha"]["workflow_name"] == "alpha"
        assert len(result["logs"]["events"]) == 2


class TestCatalogGeneratorProblemsFirst:
    """A window that fills by recency alone is mostly debug, and the errors a
    reader came for sit outside it."""

    def test_an_old_error_beats_a_newer_debug_row_for_the_budget(self):
        """Each log's share is drained newest-first, so a log whose errors are its
        oldest rows loses every one of them to its own debug noise."""
        gen = _make_generator()
        inputs = _empty_inputs()
        alpha = _wf_events("alpha", list(range(2)), hour=9, level="error")
        alpha["events"] += _wf_events(
            "alpha", list(range(2, EVENT_TAIL_LIMIT)), hour=11, level="debug"
        )["events"]
        inputs["runs_data"] = {
            "alpha": alpha,
            "beta": _wf_events("beta", list(range(EVENT_TAIL_LIMIT)), hour=11, level="debug"),
        }
        events = gen.generate(**inputs)["logs"]["events"]

        assert len(events) == EVENT_TAIL_LIMIT
        assert sorted(e["seq"] for e in events if e["level"] == "error") == [0, 1]

    def test_errors_do_not_crowd_out_warnings_either(self):
        """Rarest-first must not become winner-takes-all. Once errors alone can
        fill the problem half, strict priority leaves no room for a warning —
        while routine rows keep the other half, which inverts the rule the
        per-log budgets exist to enforce."""
        sources = [
            (
                f"w{i}",
                _stream_rows(f"w{i}", "error", 500)
                + _stream_rows(f"w{i}", "warn", 500)
                + _stream_rows(f"w{i}", "debug", 500),
            )
            for i in range(15)
        ]

        levels = Counter(e["level"] for e in _merge_event_tails(sources, 2000))

        assert levels["error"] > 0
        assert levels["warn"] > 0

    def test_problems_cannot_spend_the_whole_window(self):
        """A problem-heavy project would otherwise fill the window with warnings
        and leave the page that promises recent events showing none."""
        gen = _make_generator()
        inputs = _empty_inputs()
        runs = {}
        for name in ("alpha", "beta", "gamma"):
            wf = _wf_events(name, list(range(EVENT_TAIL_LIMIT)), hour=9, level="warn")
            wf["events"] += _wf_events(
                name, list(range(EVENT_TAIL_LIMIT, 2 * EVENT_TAIL_LIMIT)), hour=11, level="info"
            )["events"]
            runs[name] = wf
        inputs["runs_data"] = runs

        events = gen.generate(**inputs)["logs"]["events"]
        levels = Counter(e["level"] for e in events)

        assert len(events) == EVENT_TAIL_LIMIT
        assert levels["warn"] > 0
        assert levels["info"] > 0

    def test_warnings_do_not_crowd_out_errors_across_logs(self):
        """Each log's own budget keeps its errors, and the merge must not undo
        that: warnings are newer and far more numerous, so draining a shared
        problem queue newest-first loses the errors a second time."""
        gen = _make_generator()
        inputs = _empty_inputs()
        runs = {}
        for name in ("alpha", "beta", "gamma"):
            wf = _wf_events(name, list(range(4)), hour=9, level="error")
            wf["events"] += _wf_events(
                name, list(range(4, 4 + EVENT_TAIL_LIMIT)), hour=11, level="warn"
            )["events"]
            runs[name] = wf
        inputs["runs_data"] = runs

        events = gen.generate(**inputs)["logs"]["events"]
        errors = Counter(e["id"].rsplit(":", 1)[0] for e in events if e["level"] == "error")

        assert errors == {"workflow:alpha": 4, "workflow:beta": 4, "workflow:gamma": 4}

    def test_a_quiet_project_still_fills_the_window_with_recent_rows(self):
        """The reserve works the other way too: a share nobody claims is not lost."""
        gen = _make_generator()
        inputs = _empty_inputs()
        wf = _wf_events("alpha", [0], hour=9, level="error")
        wf["events"] += _wf_events(
            "alpha", list(range(1, EVENT_TAIL_LIMIT + 50)), hour=11, level="info"
        )["events"]
        inputs["runs_data"] = {"alpha": wf}

        events = gen.generate(**inputs)["logs"]["events"]

        assert len(events) == EVENT_TAIL_LIMIT
        assert any(e["level"] == "error" for e in events)

    def test_a_row_with_no_timestamp_does_not_abort_the_merge(self):
        """The merge sorts on meta.timestamp. A row whose meta carries none is
        accepted by the scanner, and None against str takes the build down."""
        gen = _make_generator()
        inputs = _empty_inputs()
        wf = _wf_events("alpha", [0])
        wf["events"][0]["meta"] = {}
        wf["events"] += _wf_events("alpha", [1])["events"]
        inputs["runs_data"] = {"alpha": wf}

        events = gen.generate(**inputs)["logs"]["events"]

        assert sorted(e["seq"] for e in events) == [0, 1]

    def test_the_per_log_totals_are_not_shipped_twice(self):
        """They exist to be summed into stats.event_levels. Serialising the
        per-log copies as well puts bytes in every reader's download that no
        reader opens."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["logs_data"] = {**inputs["logs_data"], "level_counts": {"error": 3}}
        inputs["runs_data"] = {
            "alpha": {**_wf_events("alpha", [0]), "level_counts": {"warn": 1}},
        }
        catalog = gen.generate(**inputs)

        assert catalog["stats"]["event_levels"] == {"error": 3, "warn": 1}
        assert "level_counts" not in catalog["logs"]
        assert "level_counts" not in catalog["runs"]["alpha"]

    def test_a_quiet_log_keeps_its_errors_beside_a_busy_one(self):
        """The problems pass is shared round-robin, not first-come. A busy log
        holds enough errors to fill the half on its own, and the rare errors of
        a quiet workflow are the ones a reader came for."""
        gen = _make_generator()
        inputs = _empty_inputs()
        busy = _wf_events("busy", list(range(EVENT_TAIL_LIMIT)), hour=10, level="error")
        inputs["runs_data"] = {
            "busy": busy,
            "quiet": _wf_events("quiet", [0, 1, 2], hour=9, level="error"),
        }

        events = gen.generate(**inputs)["logs"]["events"]
        by_source = Counter(e["id"].rsplit(":", 1)[0] for e in events if e["level"] == "error")

        assert by_source["workflow:quiet"] == 3

    def test_problems_may_spend_the_share_recency_cannot_fill(self):
        """The reserve runs both ways. Tested the other way round elsewhere; a
        project with few routine rows must not lose retained problems to a half
        that has nothing to put in it."""
        gen = _make_generator()
        inputs = _empty_inputs()
        wf = _wf_events("alpha", list(range(EVENT_TAIL_LIMIT)), hour=9, level="warn")
        wf["events"] += _wf_events("alpha", [9001, 9002], hour=11, level="info")["events"]
        inputs["runs_data"] = {"alpha": wf}

        events = gen.generate(**inputs)["logs"]["events"]
        levels = Counter(e["level"] for e in events)

        assert levels["info"] == 2
        assert levels["warn"] > EVENT_TAIL_LIMIT // 2

    def test_a_log_with_no_timestamps_still_reads_newest_first(self):
        """Every row collapses to one sort key, so the order the merge hands the
        sort is the order that survives it."""
        gen = _make_generator()
        inputs = _empty_inputs()
        wf = _wf_events("alpha", [0, 1, 2])
        for row in wf["events"]:
            row["meta"] = {}
        inputs["runs_data"] = {"alpha": wf}

        seqs = [e["seq"] for e in gen.generate(**inputs)["logs"]["events"]]

        assert seqs == [2, 1, 0]

    def test_source_order_does_not_depend_on_dict_insertion(self):
        """Source order decides who wins a budget exhausted mid-cycle, so it is
        sorted rather than however the scanner happened to build its mapping."""
        gen = _make_generator()
        forward, backward = _empty_inputs(), _empty_inputs()
        wfs = {n: _wf_events(n, [0, 1]) for n in ("alpha", "beta", "gamma")}
        forward["runs_data"] = dict(wfs)
        backward["runs_data"] = dict(reversed(list(wfs.items())))

        assert [e["id"] for e in gen.generate(**forward)["logs"]["events"]] == [
            e["id"] for e in gen.generate(**backward)["logs"]["events"]
        ]

    def test_a_log_that_is_not_a_workflow_is_not_labelled_as_one(self):
        """A stray directory under a project yields a run entry named after it.
        Stamping that into an id makes the dashboard offer it as a workflow to
        filter by, and attributes its rows to a workflow that does not exist."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {"agent_io": {**_wf_events("agent_io", [0]), "is_workflow": False}}

        events = gen.generate(**inputs)["logs"]["events"]

        assert [e["id"].rsplit(":", 1)[0] for e in events] == ["project:agent_io"]

    def test_level_totals_describe_every_log_not_the_window(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["logs_data"] = {**inputs["logs_data"], "level_counts": {"error": 3, "debug": 7}}
        inputs["runs_data"] = {
            "alpha": {**_wf_events("alpha", [0]), "level_counts": {"error": 2, "warn": 1}},
        }
        stats = gen.generate(**inputs)["stats"]

        assert stats["event_levels"] == {"error": 5, "warn": 1, "debug": 7}

    def test_generate_does_not_mutate_the_caller_s_logs_data(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        logs_data = {**inputs["logs_data"], "events": _wf_events("logs", [0])["events"]}
        inputs["logs_data"] = logs_data

        gen.generate(**inputs)

        assert [e["seq"] for e in logs_data["events"]] == [0]
        assert "id" not in logs_data["events"][0]


class TestEventWindowInvariants:
    """Whatever the mix of levels across logs, the window holds at most the limit,
    each row once, newest first. The reserve arithmetic has to hold at the edges
    too — an all-problem project must not strand the recency half, and one rare
    error among routine rows must not claim it."""

    SHAPES = {
        "one empty source": [("a", [])],
        "a single log of nothing but problems": [("a", ("error", 500))],
        "a single log of nothing but routine rows": [("a", ("info", 500))],
        "problems in every log": [(f"w{i}", ("warn", 200)) for i in range(6)],
        "routine rows in every log": [(f"w{i}", ("debug", 200)) for i in range(6)],
        "the budget running out mid-cycle": [(f"w{i}", ("error", 7)) for i in range(30)],
        "one error among routine rows": [("a", ("error", 1)), ("b", ("info", 500))],
        "one routine row among problems": [("a", ("info", 1)), ("b", ("warn", 500))],
        "fewer rows than the limit": [("a", ("error", 3)), ("b", ("info", 4))],
    }

    def _sources(self, shape):
        out = []
        for name, spec in shape:
            if not spec:
                out.append((name, []))
                continue
            level, count = spec
            out.append((name, _stream_rows(name, level, count)))
        return out

    def test_the_window_holds_at_most_the_limit(self):
        for label, shape in self.SHAPES.items():
            sources = self._sources(shape)
            window = _merge_event_tails(sources, 100)
            assert len(window) == min(100, sum(len(r) for _, r in sources)), label

    def test_no_row_appears_twice_whatever_the_mix(self):
        for label, shape in self.SHAPES.items():
            ids = [e["id"] for e in _merge_event_tails(self._sources(shape), 100)]
            assert len(set(ids)) == len(ids), label

    def test_the_window_is_newest_first_whatever_the_mix(self):
        for label, shape in self.SHAPES.items():
            stamps = [e["meta"]["timestamp"] for e in _merge_event_tails(self._sources(shape), 100)]
            assert stamps == sorted(stamps, reverse=True), label

    def test_a_lone_error_survives_a_log_full_of_routine_rows(self):
        window = _merge_event_tails(self._sources(self.SHAPES["one error among routine rows"]), 100)
        levels = Counter(e["level"] for e in window)

        assert levels == {"info": 99, "error": 1}


class TestCatalogContractWithTheDashboard:
    """The dashboard reads catalog.json across a language boundary that has no
    test runner, and its transform defaults every absent key. Rename one here
    and the Logs screen still renders — every row reading level "info", every
    error tile reading zero — with nothing going red. These names are the
    contract; change them only together with the reader.

    The rows come from the real scanner, not a hand-built dict, so the fixture
    cannot drift away from what the framework writes.
    """

    ROW_KEYS = ("id", "seq", "event_type", "code", "level", "category", "message")
    META_KEYS = ("timestamp", "invocation_id", "correlation_id", "workflow_name")

    def _catalog(self, tmp_path):
        """A log shaped exactly as the framework writes one."""
        (tmp_path / "agent_config").mkdir()
        (tmp_path / "agent_config" / "wf.yml").write_text("name: wf\n")
        logs_dir = tmp_path / "agent_io" / "logs"
        logs_dir.mkdir(parents=True)
        rows = [
            {
                "event_type": "LogEvent",
                "code": "X000",
                "level": "error",
                "category": "workflow",
                "message": "it failed",
                "meta": {
                    "timestamp": "2026-06-23T08:00:15.162326+00:00",
                    "correlation_id": "99d78b46",
                    "invocation_id": "run_wf_5aa47355",
                    "thread_id": None,
                    "workflow_name": "wf",
                },
                "data": {},
            },
            {
                "event_type": "ActionCompleteEvent",
                "code": "A002",
                "level": "info",
                "category": "action",
                "message": "done",
                "diagnostic": False,
                "meta": {
                    "timestamp": "2026-06-23T08:00:16.000000+00:00",
                    "correlation_id": "99d78b46",
                    "invocation_id": "run_wf_5aa47355",
                    "thread_id": None,
                    "workflow_name": "wf",
                    "action_name": "step_one",
                },
                "data": {"action_name": "step_one", "execution_time": 1.0},
            },
        ]
        with open(logs_dir / "events.json", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        inputs = _empty_inputs()
        inputs["runs_data"] = scan_runs(tmp_path)
        return _make_generator().generate(**inputs)

    def test_the_stream_and_the_level_totals_keep_their_names(self, tmp_path):
        catalog = self._catalog(tmp_path)

        assert len(catalog["logs"]["events"]) == 2
        assert catalog["stats"]["event_levels"] == {"error": 1, "info": 1}

    def test_every_row_carries_the_keys_the_dashboard_reads(self, tmp_path):
        for row in self._catalog(tmp_path)["logs"]["events"]:
            assert all(k in row for k in self.ROW_KEYS), sorted(row)
            assert all(k in row["meta"] for k in self.META_KEYS), sorted(row["meta"])

    def test_an_action_row_names_its_action_where_both_readers_look(self, tmp_path):
        rows = self._catalog(tmp_path)["logs"]["events"]
        action = next(r for r in rows if r["event_type"] == "ActionCompleteEvent")

        assert action["data"]["action_name"] == "step_one"
        assert action["meta"]["action_name"] == "step_one"

    def test_ids_are_unique_across_logs(self, tmp_path):
        ids = [row["id"] for row in self._catalog(tmp_path)["logs"]["events"]]

        assert len(ids) == len(set(ids))
