"""Daily aggregation of archive day-file rows.

A day is summarized per parameter with the observed coverage fraction so
that downstream surfaces never present a thin day as a full one.
"""
from __future__ import annotations

from dataclasses import dataclass

# expected samples per day by observed sampling interval; the archive stores
# each location's native cadence. We derive coverage from distinct timestamps
# relative to the day's maximum possible for hourly (24) or sub-hourly data:
# coverage = distinct_timestamps / max_possible where max_possible is chosen
# from the median spacing of that day (falls back to hourly = 24).
HOURLY_DAY = 24


@dataclass
class DayStat:
    date: str            # local date (YYYY-MM-DD) from the timestamp's own offset
    parameter: str
    units: str
    n_samples: int
    expected_samples: int
    coverage: float      # n_samples / expected_samples, capped at 1.0
    mean: float
    vmin: float
    vmax: float
    suspect: bool     # full-coverage day with a single constant reading (stuck-sensor sign)


def expected_samples(datetimes: list[str]) -> int:
    """Estimate the day's scheduled sample count from observed spacing.

    Hourly cadence -> 24; 30-min -> 48; 15-min -> 96. Falls back to 24 when
    spacing cannot be determined (single sample days count as 1/24 by design;
    callers should treat low coverage as 'thin day')."""
    if len(datetimes) < 3:
        return HOURLY_DAY
    from datetime import datetime as _dt
    ts = sorted(_dt.fromisoformat(t) for t in datetimes)
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:]) if (b - a).total_seconds() > 0]
    if not gaps:
        return HOURLY_DAY
    gaps.sort()
    med = gaps[len(gaps) // 2]
    if med <= 960:      # ~15 min
        return 96
    if med <= 1920:     # ~30 min
        return 48
    return HOURLY_DAY


def daily_stats(rows: list[dict], parameter: str | None = None) -> list[DayStat]:
    """Aggregate raw day-file rows into per-date, per-parameter stats.

    rows: output of s3archive.parse_day_csv (may span parameters and, for
    concatented fetches, multiple days - grouping is by the local date in
    each row's own timezone offset)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if parameter is not None and r["parameter"] != parameter:
            continue
        date = r["datetime"][:10]  # ISO local date, offset preserved in string
        groups.setdefault((date, r["parameter"]), []).append(r)
    out: list[DayStat] = []
    for (date, param), rs in sorted(groups.items()):
        vals = [r["value"] for r in rs]
        # Weight each timestamp once: repeated rows (re-uploads or parallel
        # sensors at the same instant) are averaged per timestamp so they
        # cannot pull the daily mean toward one instant. Min and max still
        # use every archived value.
        by_ts: dict[str, list[float]] = {}
        for r in rs:
            by_ts.setdefault(r["datetime"], []).append(r["value"])
        dts = sorted(by_ts)
        ts_means = [sum(v) / len(v) for v in by_ts.values()]
        exp = expected_samples(dts)
        n = len(dts)
        constant = max(vals) == min(vals)
        out.append(DayStat(
            date=date, parameter=param, units=rs[0]["units"],
            n_samples=n, expected_samples=exp,
            coverage=min(1.0, n / exp),
            mean=sum(ts_means) / len(ts_means), vmin=min(vals), vmax=max(vals),
            suspect=constant and n >= 0.9 * exp,
        ))
    return out


def exceedance_days(stats: list[DayStat], threshold: float,
                    min_coverage: float = 2 / 3) -> list[DayStat]:
    """Days whose mean exceeds `threshold`, counting only days with at least
    `min_coverage` of the day's scheduled samples (default 2/3, mirroring the
    >=16-of-24h convention used by CPCB for 24h sub-indices)."""
    return [s for s in stats if s.coverage >= min_coverage and s.mean > threshold]
