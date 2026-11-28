"""Keyless access to the OpenAQ open-data archive on S3.

The archive (https://openaq-data-archive.s3.amazonaws.com) is part of the
AWS Open Data program: listing and object GETs need no credentials. The
OpenAQ v3 REST API, by contrast, requires an API key (401 without one) and
is NOT used here.

Record layout:
  records/csv.gz/locationid={id}/year={yyyy}/month={mm}/location-{id}-{yyyymmdd}.csv.gz

Each day file is a gzipped CSV with columns:
  location_id, sensors_id, location, datetime, lat, lon, parameter, units, value
"""
from __future__ import annotations

import gzip
import http.client
import io
import math
import time
from datetime import datetime
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

BUCKET = "https://openaq-data-archive.s3.amazonaws.com"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

UA = {"User-Agent": "aq-archive-explorer/0.1 (historical research; OpenAQ open-data archive)"}


@dataclass
class Coverage:
    """Archive coverage for one location: which year-months have day files."""
    location_id: int
    months: list[tuple[int, int]] = field(default_factory=list)  # sorted (year, month)

    @property
    def first(self) -> tuple[int, int] | None:
        return self.months[0] if self.months else None

    @property
    def last(self) -> tuple[int, int] | None:
        return self.months[-1] if self.months else None

    def window_str(self) -> str:
        if not self.months:
            return "no archive records"
        (y1, m1), (y2, m2) = self.months[0], self.months[-1]
        return f"{y1}-{m1:02d} through {y2}-{m2:02d}"


RETRY_STATUS = {429, 500, 502, 503, 504}   # S3 answers 503 SlowDown under load
ATTEMPTS = 3
_sleep = time.sleep


def _get(url: str, timeout: float = 30.0) -> bytes:
    """GET with up to ATTEMPTS tries on transient failures (timeouts, dropped
    connections, short reads, HTTP 429/5xx), backing off 0.5s then 1s. Other
    HTTP errors, including 404, are raised at once. After the last try the
    failure is raised as an OSError so callers see one error family."""
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == ATTEMPTS - 1:
                raise
        except (OSError, http.client.HTTPException) as e:
            if attempt == ATTEMPTS - 1:
                if isinstance(e, OSError):
                    raise
                raise ConnectionError(f"incomplete archive response: {e!r}") from e
        _sleep(0.5 * 2 ** attempt)
    raise AssertionError("unreachable")


def list_months(location_id: int) -> list[tuple[int, int]]:
    """All (year, month) prefixes with day files for a location.

    One HTTP request per pagination page (1000 keys/page; day files for one
    location rarely exceed that per page, so usually exactly 1 request).
    """
    prefix = f"records/csv.gz/locationid={location_id}/"
    months: set[tuple[int, int]] = set()
    token = ""
    while True:
        url = f"{BUCKET}/?list-type=2&prefix={prefix}&max-keys=1000"
        if token:
            url += f"&continuation-token={urllib.parse.quote(token)}"
        root = ET.fromstring(_get(url))
        for key in root.iter(NS + "Key"):
            parts = key.text.split("/")
            # records/csv.gz/locationid=ID/year=YYYY/month=MM/location-...csv.gz
            y = int(parts[3].split("=")[1])
            m = int(parts[4].split("=")[1])
            months.add((y, m))
        trunc = root.find(NS + "IsTruncated")
        if trunc is not None and trunc.text == "true":
            tok = root.find(NS + "NextContinuationToken")
            token = tok.text if tok is not None else ""
            if not token:
                break
        else:
            break
    return sorted(months)


def get_coverage(location_id: int) -> Coverage:
    return Coverage(location_id=location_id, months=list_months(location_id))


def fetch_day(location_id: int, year: int, month: int, day: int) -> list[dict]:
    """Valid rows only; see fetch_day_counted for the rejected-row count."""
    return fetch_day_counted(location_id, year, month, day)[0]


def fetch_day_counted(location_id: int, year: int, month: int, day: int) -> tuple[list[dict], int]:
    """Return (valid rows, rejected row count); a missing file gives ([], 0)."""
    key = (f"records/csv.gz/locationid={location_id}/year={year:04d}/"
           f"month={month:02d}/location-{location_id}-{year:04d}{month:02d}{day:02d}.csv.gz")
    url = f"{BUCKET}/{key}"
    try:
        raw = _get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], 0
        raise
    text = gzip.decompress(raw).decode("utf-8")
    return parse_day_csv_counted(text)


MONTH_WORKERS = 6   # bounded: polite to the public bucket, ~6x fewer serial waits


def fetch_month_counted(location_id: int, year: int, month: int,
                        workers: int = MONTH_WORKERS) -> tuple[list[dict], int]:
    """Fetch every day file of a month concurrently.

    Returns (rows in calendar-day order, total rejected rows). All-or-nothing:
    the first failure cancels the files not yet started and is raised, so a
    partial month is never returned.
    """
    import calendar
    from concurrent.futures import ThreadPoolExecutor
    days = range(1, calendar.monthrange(year, month)[1] + 1)
    rows, rejected = [], 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(fetch_day_counted, location_id, year, month, d) for d in days]
        try:
            for f in futures:
                day_rows, day_rejected = f.result()
                rows.extend(day_rows)
                rejected += day_rejected
        except BaseException:
            for f in futures:
                f.cancel()
            raise
    return rows, rejected


def parse_day_csv(text: str) -> list[dict]:
    """Valid rows only; see parse_day_csv_counted."""
    return parse_day_csv_counted(text)[0]


def parse_day_csv_counted(text: str) -> tuple[list[dict], int]:
    """Parse archive rows, skipping malformed or non-finite records.

    Require a timezone-aware ISO timestamp and finite values/coordinates.
    Preserve the local date and offset; do not convert timestamps to UTC.
    Negative finite measurements remain visible, not silently clipped.
    """
    import csv
    rows, rejected = [], 0
    reader = csv.DictReader(io.StringIO(text))
    for r in reader:
        try:
            timestamp = r["datetime"].strip()
            # Python 3.10 does not accept Z, so normalize only its spelling.
            timestamp = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                rejected += 1
                continue
            value, lat, lon = float(r["value"]), float(r["lat"]), float(r["lon"])
            if not all(math.isfinite(v) for v in (value, lat, lon)):
                rejected += 1
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                rejected += 1
                continue
            location_id = int(r["location_id"])
            parameter, units = r["parameter"].strip(), r["units"].strip()
            if location_id <= 0 or not parameter or not units:
                rejected += 1
                continue
            rows.append({
                "location_id": location_id,
                "location": r["location"],
                "datetime": parsed.isoformat(),
                "lat": lat,
                "lon": lon,
                "parameter": parameter,
                "units": units,
                "value": value,
            })
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            rejected += 1
            continue
    return rows, rejected


import urllib.parse  # noqa: E402  (kept at bottom to keep the header docs prominent)
