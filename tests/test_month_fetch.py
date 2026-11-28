"""Concurrent month fetch: ordered, bounded, all-or-nothing (no network)."""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openaq_explorer import s3archive


def row(day):
    return {"datetime": f"2024-02-{day:02d}T00:00:00+00:00", "value": float(day)}


def test_rows_come_back_in_day_order_with_summed_rejections(monkeypatch):
    def fake(lid, y, m, d):
        time.sleep(0.02 if d % 2 else 0)   # later days can finish first
        return [row(d)], d % 3
    monkeypatch.setattr(s3archive, "fetch_day_counted", fake)
    rows, rejected = s3archive.fetch_month_counted(1, 2024, 2)
    assert [r["value"] for r in rows] == [float(d) for d in range(1, 30)]
    assert rejected == sum(d % 3 for d in range(1, 30))


def test_concurrency_is_bounded_and_real(monkeypatch):
    lock, state = threading.Lock(), {"now": 0, "peak": 0, "calls": 0}
    def fake(lid, y, m, d):
        with lock:
            state["now"] += 1; state["calls"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.03)
        with lock:
            state["now"] -= 1
        return [], 0
    monkeypatch.setattr(s3archive, "fetch_day_counted", fake)
    s3archive.fetch_month_counted(1, 2025, 1, workers=4)
    assert state["calls"] == 31          # January: one request per day file
    assert 2 <= state["peak"] <= 4


def test_one_failure_raises_and_returns_no_partial_month(monkeypatch):
    def fake(lid, y, m, d):
        if d == 3:
            raise ConnectionError("boom")
        return [row(d)], 0
    monkeypatch.setattr(s3archive, "fetch_day_counted", fake)
    with pytest.raises(ConnectionError):
        s3archive.fetch_month_counted(1, 2024, 2)


def test_failure_stops_unstarted_days(monkeypatch):
    calls = []
    def fake(lid, y, m, d):
        calls.append(d)
        if d == 1:
            raise OSError("down")
        time.sleep(0.05)
        return [], 0
    monkeypatch.setattr(s3archive, "fetch_day_counted", fake)
    with pytest.raises(OSError):
        s3archive.fetch_month_counted(1, 2025, 1, workers=2)
    assert len(calls) < 31


def test_single_worker_matches_serial_result(monkeypatch):
    monkeypatch.setattr(s3archive, "fetch_day_counted", lambda l, y, m, d: ([row(d)], 1))
    assert s3archive.fetch_month_counted(1, 2024, 2, workers=1) == \
           s3archive.fetch_month_counted(1, 2024, 2, workers=8)
