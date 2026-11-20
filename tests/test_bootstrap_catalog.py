"""Offline harvest tests: truthful accounting and resumable failures."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import bootstrap_catalog as harvest
from openaq_explorer.catalog import Station, load_catalog


def station(location_id, parameter="pm25", name="Station", city="City"):
    return Station(location_id, name, name, city, "Provider", 1., 2.,
                   [parameter], "2020-01", "2025-01", 2)


def test_all_probe_outcomes_accounted_for():
    existing = [station(1, name="Old")]
    results = [(101, station(1, name="Refreshed")), (2, station(2)),
               (3, None), (4, station(4, "no2")), (5, "ERR")]
    merged, done, counts = harvest.summarize_batch(existing, results)
    assert counts == dict(attempted=5, accepted=2, added=1, refreshed=1,
                          duplicates=0, empty=1, skipped=1, failed=1)
    assert done == {101, 2, 3, 4}  # requested IDs, not returned metadata IDs
    assert {s.location_id for s in merged} == {1, 2}
    assert next(s for s in merged if s.location_id == 1).name == "Refreshed"
    assert counts["attempted"] == sum(counts[k] for k in
                                      ("accepted", "empty", "skipped", "failed"))


def test_duplicate_metadata_is_not_counted_as_two_new_stations():
    merged, done, counts = harvest.summarize_batch(
        [], [(9, station(2, name="First")), (10, station(2, name="Last"))])
    assert len(merged) == 1 and merged[0].name == "Last"
    assert done == {9, 10}
    assert counts["accepted"] == 2 and counts["added"] == 1
    assert counts["duplicates"] == 1


def test_empty_batch_retains_existing():
    old = [station(1)]
    merged, done, counts = harvest.summarize_batch(old, [])
    assert merged == old and done == set()
    assert all(v == 0 for v in counts.values())


def test_selection_normalizes_deduplicates_and_skips_checkpoint():
    picked = harvest.select_ids(["1", 1, "2", 3, 3], {2}, 20, 42)
    assert len(picked) == 2 and set(picked) == {1, 3}
    assert picked == harvest.select_ids(["1", 1, "2", 3, 3], {2}, 20, 42)
    assert harvest.select_ids([1, 2], set(), 0, 42) == []
    with pytest.raises(ValueError):
        harvest.select_ids([1, 2], set(), -1, 42)


def test_main_retries_only_failed_probes_and_loads_string_checkpoint(tmp_path, monkeypatch, capsys):
    ids = tmp_path / "ids.json"
    checkpoint = tmp_path / "checkpoint.json"
    out = tmp_path / "catalog.json"
    ids.write_text(json.dumps([1, "1", 2, 3, 4, 5]))
    checkpoint.write_text(json.dumps(["5"]))
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--resume", "--sample", "20",
        "--ids-file", str(ids), "--checkpoint", str(checkpoint), "--out", str(out)])
    seen = []

    def initial_probe(i):
        seen.append(i)
        return {1: station(1), 2: "ERR", 3: None, 4: station(4, "no2")}[i]

    monkeypatch.setattr(harvest, "probe", initial_probe)
    harvest.main()
    assert set(seen) == {1, 2, 3, 4} and len(seen) == 4
    assert json.loads(checkpoint.read_text()) == [1, 3, 4, 5]
    assert [s.location_id for s in load_catalog(str(out))] == [1]
    log = capsys.readouterr().out
    for expected in ("attempted=4", "added=1", "empty=1", "skipped_non_pm=1", "failed_retryable=1"):
        assert expected in log

    seen.clear()
    def recovered_probe(i):
        seen.append(i)
        return station(i)
    monkeypatch.setattr(harvest, "probe", recovered_probe)
    harvest.main()
    assert seen == [2]
    assert json.loads(checkpoint.read_text()) == [1, 2, 3, 4, 5]
    assert {s.location_id for s in load_catalog(str(out))} == {1, 2}
    log = capsys.readouterr().out
    assert "attempted=1" in log and "added=1" in log and "failed_retryable=0" in log


def test_probe_exception_is_retryable(monkeypatch):
    def broken(_):
        raise OSError("simulated transient failure")
    monkeypatch.setattr(harvest.catalog, "probe_location", broken)
    assert harvest.probe(1) == "ERR"


def test_negative_sample_fails_before_any_io(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--sample", "-1"])
    with pytest.raises(SystemExit) as error:
        harvest.main()
    assert error.value.code == 2
