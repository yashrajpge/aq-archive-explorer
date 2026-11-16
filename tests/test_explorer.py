"""Unit tests for the explorer engine (no network)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openaq_explorer import aggregate, catalog, standards
from openaq_explorer.s3archive import parse_day_csv, Coverage


def row(dt, value, param="pm25", name="Test Station, Testville - TEST-1"):
    return {"location_id": 1, "location": name, "datetime": dt,
            "lat": 1.0, "lon": 2.0, "parameter": param,
            "units": "µg/m³", "value": value}


def hourly_day(date, value):
    return [row(f"{date}T{h:02d}:00:00+00:00", value) for h in range(24)]


def test_parse_day_csv_skips_malformed():
    text = ('"location_id","sensors_id","location","datetime","lat","lon","parameter","units","value"\n'
            '1,9,"A, B - C-1","2025-01-01T00:00:00+00:00","1.0","2.0","pm25","µg/m³","10.5"\n'
            '1,9,"A, B - C-1","2025-01-01T01:00:00+00:00","1.0","2.0","pm25","µg/m³","oops"\n')
    rows = parse_day_csv(text)
    assert len(rows) == 1 and rows[0]["value"] == 10.5 and rows[0]["city" if False else "location"] == "A, B - C-1"


def test_daily_stats_full_hourly_day():
    stats = aggregate.daily_stats(hourly_day("2025-03-10", 40.0))
    assert len(stats) == 1
    s = stats[0]
    assert s.expected_samples == 24 and s.n_samples == 24
    assert s.coverage == 1.0 and s.mean == 40.0 and s.vmin == s.vmax == 40.0


def test_daily_stats_quarter_hourly():
    rows = [row(f"2025-03-10T{h:02d}:{m:02d}:00+00:00", 10.0)
            for h in range(24) for m in (0, 15, 30, 45)]
    s = aggregate.daily_stats(rows)[0]
    assert s.expected_samples == 96 and s.coverage == 1.0


def test_exceedance_respects_coverage_floor():
    full = hourly_day("2025-03-10", 40.0)
    thin = [row(f"2025-03-11T{h:02d}:00:00+00:00", 100.0) for h in range(4)]  # 4/24 < 2/3
    stats = aggregate.daily_stats(full + thin)
    exc = aggregate.exceedance_days(stats, 35.0)
    assert [s.date for s in exc] == ["2025-03-10"]  # thin day excluded despite mean 100


def test_exceedance_threshold_boundary():
    stats = aggregate.daily_stats(hourly_day("2025-03-10", 35.0))
    assert aggregate.exceedance_days(stats, 35.0) == []  # strictly greater


def test_parse_location_name_hyphenated_provider():
    st, city, prov = catalog.parse_location_name("Karve Road Pune, Pune - MPCB-3379567")
    assert (st, city, prov) == ("Karve Road Pune", "Pune", "MPCB-3379567")


def test_parse_location_name_fallback():
    st, city, prov = catalog.parse_location_name("Plain Station")
    assert (st, city, prov) == ("Plain Station", "", "")


def test_coverage_window_str():
    c = Coverage(location_id=1, months=[(2018, 3), (2018, 4), (2025, 5)])
    assert c.window_str() == "2018-03 through 2025-05"
    assert Coverage(location_id=2).window_str() == "no archive records"


def test_flatline_day_flagged_suspect():
    stuck = hourly_day("2025-05-01", 100.0)
    s = aggregate.daily_stats(stuck)[0]
    assert s.suspect is True
    varying = [row(f"2025-05-02T{h:02d}:00:00+00:00", 50.0 + h) for h in range(24)]
    assert aggregate.daily_stats(varying)[0].suspect is False


def test_standards_registry():
    s = standards.get("us_24h")
    assert s["threshold"] == 35.0 and s["parameter"] == "pm25" and s["source_url"].startswith("https://")
    try:
        standards.get("nope")
        assert False
    except KeyError:
        pass
