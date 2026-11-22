"""Malformed archive records must not poison valid daily summaries."""
import csv
import io
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openaq_explorer import aggregate
from openaq_explorer.s3archive import parse_day_csv


def csv_text(*records):
    output = io.StringIO()
    fields = ["location_id", "location", "datetime", "lat", "lon", "parameter", "units", "value"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for overrides in records:
        row = dict(location_id="1", location="Test", datetime="2025-03-01T00:00:00+05:30",
                   lat="18.5", lon="73.8", parameter="pm25", units="µg/m³", value="12.5")
        row.update(overrides)
        writer.writerow(row)
    return output.getvalue()


@pytest.mark.parametrize("field,value", [
    ("value", "NaN"), ("value", "inf"), ("value", "-inf"),
    ("lat", "NaN"), ("lon", "Infinity"),
    ("lat", "90.01"), ("lat", "-90.01"), ("lon", "180.01"),
    ("datetime", "not-a-date"), ("datetime", "2025-02-30T12:00:00+00:00"),
    ("datetime", "2025-03-01T12:00:00"), ("datetime", "2025-03-01"),
    ("parameter", " "), ("units", ""), ("location_id", "0"),
])
def test_invalid_record_skipped_without_losing_valid_neighbor(field, value):
    rows = parse_day_csv(csv_text({field: value}, {}))
    assert len(rows) == 1
    assert rows[0]["value"] == 12.5
    stats = aggregate.daily_stats(rows)
    assert len(stats) == 1 and math.isfinite(stats[0].mean)


def test_offsets_and_local_dates_preserved_and_z_normalized():
    rows = parse_day_csv(csv_text(
        {"datetime": "2025-03-01T00:30:00+05:30"},
        {"datetime": "2025-02-28T23:30:00-03:00"},
        {"datetime": "2025-03-01T10:00:00Z"}))
    assert rows[0]["datetime"] == "2025-03-01T00:30:00+05:30"
    assert rows[1]["datetime"] == "2025-02-28T23:30:00-03:00"
    assert rows[2]["datetime"] == "2025-03-01T10:00:00+00:00"
    assert {s.date for s in aggregate.daily_stats(rows)} == {"2025-02-28", "2025-03-01"}


def test_finite_negative_values_and_coordinate_boundaries_not_clipped():
    rows = parse_day_csv(csv_text({"value": "-1.5", "lat": "-90", "lon": "180"}))
    assert rows[0]["value"] == -1.5
    assert rows[0]["lat"] == -90 and rows[0]["lon"] == 180


def test_invalid_rows_do_not_create_exceedances_or_coverage():
    good = [{"datetime": f"2025-03-01T{h:02d}:00:00+00:00", "value": "20"}
            for h in range(24)]
    bad = [{"value": "NaN"}, {"value": "inf"}, {"datetime": "bad"}]
    stats = aggregate.daily_stats(parse_day_csv(csv_text(*(good + bad))))
    assert len(stats) == 1 and stats[0].n_samples == 24
    assert stats[0].mean == 20 and stats[0].coverage == 1
    assert aggregate.exceedance_days(stats, 35) == []
