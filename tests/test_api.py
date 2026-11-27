"""Offline API regression tests for pollutant-safe reference comparisons."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as web


@pytest.fixture
def client(monkeypatch):
    def no_network(*args):
        raise AssertionError("invalid request reached archive")
    monkeypatch.setattr(web.s3archive, "fetch_day_counted", no_network)
    return web.app.test_client()


@pytest.mark.parametrize("path", [
    "/2025/0?standard=us_24h", "/2025/13?standard=us_24h",
    "/0/1?standard=us_24h", "/10000/1?standard=us_24h",
    "/2025/1?standard=unknown",
    "/2025/1?parameter=pm10&standard=us_24h",
    "/2025/1?parameter=pm25&standard=india_24h_pm10",
    "/2025/1?parameter=no2&standard=us_24h",
])
def test_invalid_comparisons_rejected_before_network(client, path):
    response = client.get("/api/station/1/month" + path)
    assert response.status_code == 400
    assert response.is_json and response.json["error"]


@pytest.mark.parametrize("parameter,standard,threshold", [
    ("pm25", "us_24h", 35.), ("pm25", "india_24h", 60.),
    ("pm10", "india_24h_pm10", 100.), ("pm10", "us_24h_pm10", 150.),
])
def test_matching_parameter_and_threshold(client, monkeypatch, parameter, standard, threshold):
    calls = []
    def fetch(lid, year, month, day):
        calls.append(day)
        if day != 1:
            return []
        return [dict(datetime=f"2024-02-01T{h:02d}:00:00+00:00", parameter=p,
                     units="µg/m³", value=threshold + (1 if p == parameter else 1000))
                for p in ("pm25", "pm10") for h in range(24)]
    monkeypatch.setattr(web.s3archive, "fetch_day_counted", lambda *a: (fetch(*a), 0))
    response = client.get(f"/api/station/1/month/2024/2?parameter={parameter}&standard={standard}")
    assert response.status_code == 200
    data = response.json
    assert len(calls) == 29  # leap-year month, no invalid day requests
    assert data["standard"]["parameter"] == parameter
    assert data["standard"]["threshold"] == threshold
    assert data["n_exceedance"] == data["n_valid_days"] == 1
    assert data["days"][0]["mean"] == threshold + 1
    assert all(d["parameter"] == parameter for d in data["days"])


def test_no_standard_remains_supported(client, monkeypatch):
    monkeypatch.setattr(web.s3archive, "fetch_day_counted", lambda *args: ([], 0))
    response = client.get("/api/station/1/month/2025/2?parameter=no2")
    assert response.status_code == 200
    assert response.json["days"] == [] and "standard" not in response.json


def test_rejected_rows_summed_across_days(client, monkeypatch):
    monkeypatch.setattr(web.s3archive, "fetch_day_counted",
                        lambda lid, y, m, d: ([], 2 if d in (1, 2) else 0))
    response = client.get("/api/station/1/month/2025/2?parameter=pm25")
    assert response.json["n_rejected_rows"] == 4


def test_other_unit_series_excluded_from_standard_comparison(client, monkeypatch):
    def fetch(lid, y, m, d):
        if d != 1:
            return []
        return [dict(datetime=f"2025-03-01T{h:02d}:00:00+00:00", parameter="pm25",
                     units=u, value=v) for u, v in (("µg/m³", 10.0), ("ppm", 500.0))
                for h in range(24)]
    monkeypatch.setattr(web.s3archive, "fetch_day_counted", lambda *a: (fetch(*a), 0))
    r = client.get("/api/station/1/month/2025/3?parameter=pm25&standard=us_24h").json
    assert r["n_days"] == 1 and r["days"][0]["units"] == "µg/m³"
    assert r["n_days_other_units"] == 1 and r["n_exceedance"] == 0
    plain = client.get("/api/station/1/month/2025/3?parameter=pm25").json
    assert plain["n_days"] == 2 and plain["n_days_other_units"] == 0


@pytest.mark.parametrize("exc", [
    OSError("connection reset"), TimeoutError("slow"), EOFError("truncated gzip"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte"), __import__("zlib").error("bad data"),
])
def test_archive_failures_return_json_502(client, monkeypatch, exc):
    def broken(*args):
        raise exc
    monkeypatch.setattr(web.s3archive, "fetch_day_counted", broken)
    monkeypatch.setattr(web.s3archive, "get_coverage", broken)
    for path in ("/api/station/1/month/2025/3?parameter=pm25", "/api/station/1/coverage"):
        r = client.get(path)
        assert r.status_code == 502 and r.is_json and r.json["error"]


def test_non_archive_errors_keep_normal_handling(client):
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/station/x/coverage").status_code == 404
    assert client.get("/api/station/1/month/2025/13?parameter=pm25").status_code == 400
