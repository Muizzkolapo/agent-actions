"""A guard UDF that writes to its input gives no answer, so its action stops, naming it.

The UDF is handed a read-only view of the record, and the view refuses a write by raising.
A guard whose UDF raises passes its record, so a refused write applied no guard at all:
every record went to the action, with one warning per evaluation, and an author learned
of the write only by reading the log.
"""

import pytest

from agent_actions.errors import ConfigurationError, is_action_fatal
from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.utils.udf_management.registry import udf_tool

_CONTEXTS = pytest.mark.parametrize(
    "context", [None, {"source": {}}], ids=["no_context", "with_context"]
)


def _a1(data):
    return data["a1"] if "a1" in data else data["content"]["a1"]


def guard_probe_tidies_its_input(data):
    namespace = _a1(data)
    namespace["tier"] = namespace["tier"].strip().lower()
    return namespace["tier"] == "keep"


def guard_probe_appends_to_a_slice(data):
    head = _a1(data)["items"][:1]
    head.append({"n": 2})
    return _a1(data)["tier"] == "keep"


def guard_probe_marks_its_input_seen(data):
    data["seen"] = True
    return False


def guard_probe_sets_a_default_on_its_input(data):
    data.setdefault("opts", {})
    return False


def guard_probe_merges_into_its_input(data):
    data.update(seen=True)
    return False


def guard_probe_pops_from_its_input(data):
    data.pop("source_guid", None)
    return False


def guard_probe_raises_while_handling_the_refusal(data):
    try:
        _a1(data)["tier"] = "keep"
    except TypeError as error:
        raise ValueError("could not tidy the record") from error
    return True


def guard_probe_copies_after_the_refusal_then_misses_a_field(data):
    namespace = _a1(data)
    try:
        namespace["tier"] = namespace["tier"].strip().lower()
    except TypeError:
        namespace = namespace.copy()
        namespace["tier"] = namespace["tier"].strip().lower()
        return namespace["threshold"] > 1
    return namespace["tier"] == "keep"


def guard_probe_defaults_a_missing_field(data):
    namespace = _a1(data)
    try:
        threshold = namespace["threshold"]
    except KeyError:
        namespace["threshold"] = 0
        threshold = 0
    return threshold > 1


def guard_probe_catches_the_refusal(data):
    namespace = _a1(data)
    try:
        namespace["tier"] = namespace["tier"].strip().lower()
    except TypeError:
        pass
    return namespace["tier"].strip().lower() == "keep"


def guard_probe_reads_a_missing_field(data):
    return _a1(data)["threshold"] > 1


def guard_probe_adds_none_to_a_number(data):
    return len(_a1(data)["tier"]) + None > 1


_TOP_LEVEL_WRITES = pytest.mark.parametrize(
    "udf",
    [
        guard_probe_marks_its_input_seen,
        guard_probe_sets_a_default_on_its_input,
        guard_probe_merges_into_its_input,
        guard_probe_pops_from_its_input,
    ],
    ids=lambda udf: udf.__name__.removeprefix("guard_probe_"),
)


@pytest.fixture(autouse=True)
def _register_probes():
    """Registered per test: an earlier test clearing the registry would leave the guard
    naming a missing UDF, which raises before the UDF can write anything."""
    for fn in (
        guard_probe_tidies_its_input,
        guard_probe_appends_to_a_slice,
        guard_probe_marks_its_input_seen,
        guard_probe_sets_a_default_on_its_input,
        guard_probe_merges_into_its_input,
        guard_probe_pops_from_its_input,
        guard_probe_raises_while_handling_the_refusal,
        guard_probe_copies_after_the_refusal_then_misses_a_field,
        guard_probe_defaults_a_missing_field,
        guard_probe_catches_the_refusal,
        guard_probe_reads_a_missing_field,
        guard_probe_adds_none_to_a_number,
    ):
        udf_tool(fn)


def _item(tier: str = " Drop "):
    return {"source_guid": "g1", "content": {"a1": {"tier": tier, "items": [{"n": 1}]}}}


def _evaluate(udf, item, context):
    return GuardEvaluator().evaluate(item, None, context=context, conditional_clause=udf.__name__)


class TestARefusedWriteStopsTheAction:
    @_CONTEXTS
    def test_the_guard_raises_naming_the_udf_and_what_to_do_instead(self, context, caplog):
        item = _item()

        with pytest.raises(ConfigurationError) as raised:
            _evaluate(guard_probe_tidies_its_input, item, context)

        message = str(raised.value)
        assert "guard_probe_tidies_its_input" in message
        assert "wrote to its input" in message
        assert "return a value instead of mutating the input" in message
        assert "raised" not in message, "the write is all the UDF raised; nothing else to name"
        assert item == _item(), "the refusal must still keep the write off the record"
        assert "passing record" not in caplog.text, "the action stops; nothing is passed"

    @_CONTEXTS
    def test_the_error_is_fatal_to_the_action(self, context):
        """Taken as one file's failure, the file's records would go missing while the
        action completed: the guard is wrong for every record, not for this one."""
        with pytest.raises(ConfigurationError) as raised:
            _evaluate(guard_probe_tidies_its_input, _item(), context)

        assert is_action_fatal(raised.value)

    @_CONTEXTS
    def test_a_guard_that_would_admit_the_record_stops_it_too(self, context):
        """The write comes before the answer, so the guard has no answer either way."""
        with pytest.raises(ConfigurationError, match="wrote to its input"):
            _evaluate(guard_probe_tidies_its_input, _item(" Keep "), context)

    @_CONTEXTS
    @_TOP_LEVEL_WRITES
    def test_a_write_to_the_top_level_of_the_input_stops_it_too(self, udf, context):
        """The top level is the Bus the guard is handed, which refuses a write itself:
        no namespace is involved, so the Bus's refusal has to be told apart as well."""
        item = _item()

        with pytest.raises(ConfigurationError, match="wrote to its input") as raised:
            _evaluate(udf, item, context)

        assert udf.__name__ in str(raised.value)
        assert is_action_fatal(raised.value)
        assert item == _item()

    @_CONTEXTS
    def test_a_write_to_a_slice_of_a_list_in_the_input_is_refused_the_same_way(self, context):
        """A slice of a list in the view is read-only too."""
        item = _item()

        with pytest.raises(ConfigurationError, match="guard_probe_appends_to_a_slice"):
            _evaluate(guard_probe_appends_to_a_slice, item, context)

        assert item == _item()

    @_CONTEXTS
    def test_an_error_raised_in_answer_to_the_refusal_is_the_refusal(self, context):
        """The UDF gave up because its write was refused; passing the record would hide
        the write behind an error of the author's own wording."""
        with pytest.raises(ConfigurationError, match="wrote to its input") as raised:
            _evaluate(guard_probe_raises_while_handling_the_refusal, _item(), context)

        assert "raised ValueError: could not tidy the record" in str(raised.value)

    @_CONTEXTS
    def test_an_error_raised_while_handling_the_refusal_counts_and_is_named(self, context):
        """Unchained, as most handlers raise. Python records the refusal as the error being
        handled, and a handler that catches TypeError for its own reasons and then raises
        leaves the guard with no answer just the same. Here a bug of the UDF's own fires
        inside the handler, so the message names it as well as the write."""
        with pytest.raises(ConfigurationError, match="wrote to its input") as raised:
            _evaluate(guard_probe_copies_after_the_refusal_then_misses_a_field, _item(), context)

        assert "raised KeyError: 'threshold'" in str(raised.value)

    @_CONTEXTS
    def test_a_write_made_while_handling_another_error_is_refused_the_same_way(self, context):
        """The refusal is what the UDF raised, carrying the KeyError it was handling: the
        write is found where it is, not only at the root of the chain."""
        item = _item()

        with pytest.raises(ConfigurationError, match="guard_probe_defaults_a_missing_field"):
            _evaluate(guard_probe_defaults_a_missing_field, item, context)

        assert item == _item()


class TestWhatTheGuardPathStillAllows:
    @_CONTEXTS
    @pytest.mark.parametrize(("tier", "should_execute"), [(" Keep ", True), (" Drop ", False)])
    def test_a_udf_that_catches_the_refusal_still_decides(self, tier, should_execute, context):
        """The refusal is still a TypeError, so a UDF that guards its write keeps working,
        and its answer applies."""
        result = _evaluate(guard_probe_catches_the_refusal, _item(tier), context)

        assert result.should_execute is should_execute

    @_CONTEXTS
    @pytest.mark.parametrize(
        "udf",
        [guard_probe_reads_a_missing_field, guard_probe_adds_none_to_a_number],
        ids=["KeyError", "TypeError"],
    )
    def test_a_udf_that_raises_its_own_error_still_passes_its_record(self, udf, context, caplog):
        """Documented: a UDF condition passes its record when the function raises, and the
        config refuses `passthrough_on_error: false` on one. Only the view's refusal is singled
        out, not every TypeError: the UDF's own TypeError is a bug like any other."""
        result = _evaluate(udf, _item(), context)

        assert result.should_execute is True
        assert "passing record" in caplog.text
