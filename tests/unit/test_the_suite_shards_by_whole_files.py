"""`pytest --shard N/M` runs whole test files, balanced by their recorded durations.

CI runs the suite as several shards at once, so every file must land in exactly one
shard, and one shard must not hold most of the time.
"""

import pytest

from tests._support.sharding import assign, shard_of, updated


def test_every_file_lands_in_exactly_one_shard():
    files = [f"tests/t{n}.py" for n in range(50)]

    shards = assign(files, {f: float(i % 7 + 1) for i, f in enumerate(files)}, 4)

    dealt = [name for shard in shards for name in shard]
    assert sorted(dealt) == sorted(files)
    assert len(dealt) == len(set(dealt))


def test_the_longest_files_are_spread_first():
    durations = {"a.py": 100.0, "b.py": 90.0, "c.py": 10.0, "d.py": 10.0, "e.py": 5.0}

    shards = assign(list(durations), durations, 2)

    loads = sorted(sum(durations[f] for f in shard) for shard in shards)
    assert loads == [105.0, 110.0]
    assert {"a.py", "b.py"} not in [set(shard) for shard in shards]


def test_a_file_with_no_recorded_time_counts_as_the_median():
    durations = {"a.py": 1.0, "b.py": 3.0, "c.py": 5.0}

    shards = assign([*durations, "new.py"], durations, 2)

    assert sorted(len(shard) for shard in shards) == [2, 2]


def test_the_deal_is_the_same_on_every_runner():
    files = [f"tests/t{n}.py" for n in range(20)]

    assert assign(files, {}, 3) == assign(list(reversed(files)), {}, 3)


@pytest.mark.parametrize(
    ("spec", "said"), [("two", "takes N/M"), ("5/4", "from 1 to M"), ("0/0", "from 1 to M")]
)
def test_a_shard_that_names_no_part_of_the_suite_is_refused(spec, said):
    with pytest.raises(pytest.UsageError, match=said):
        shard_of(spec)


def test_a_shard_is_read_as_its_number_and_count():
    assert shard_of("2/4") == (2, 4)


def test_a_partial_run_updates_the_files_it_ran_and_keeps_the_rest():
    recorded = {"a.py": 1.0, "b.py": 2.0}

    assert updated(recorded, {"b.py": 5.0, "c.py": 3.0}) == {"a.py": 1.0, "b.py": 5.0, "c.py": 3.0}
