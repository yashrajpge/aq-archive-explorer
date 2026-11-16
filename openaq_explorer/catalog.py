"""Station catalog: metadata harvested from the archive itself.

The OpenAQ v3 API needs an API key, so the catalog is bootstrapped from the
keyless S3 archive: for each sampled location id we read its month coverage
(one listing request) and one recent day file (one GET) to capture the
station name, coordinates and parameters. The result is stored in
data/catalog.json with the harvest date, and the explorer surfaces it as a
sample of the archive, not a complete directory.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field

from . import s3archive

# "Karve Road Pune, Pune - MPCB-3379567" -> station "Karve Road Pune",
# city "Pune", provider tag "MPCB-3379567"
_NAME_RE = re.compile(r"^(?P<station>.+?),\s*(?P<city>[^,]+?)\s+-\s+(?P<provider>.+)$")


@dataclass
class Station:
    location_id: int
    name: str
    station: str
    city: str
    provider: str
    lat: float
    lon: float
    parameters: list[str]
    first_month: str | None
    last_month: str | None
    n_months: int

    def to_json(self) -> dict:
        return asdict(self)


def parse_location_name(name: str) -> tuple[str, str, str]:
    """Split the archive's location display name into (station, city,
    provider). The provider tag can itself contain hyphens ("MPCB-3379567"),
    so split off the LAST ' - ' segment first, then the last comma segment
    of what remains is the city. Falls back to the whole string as station
    when the pattern does not hold."""
    name = name.strip()
    if " - " in name:
        left, provider = name.rsplit(" - ", 1)
    else:
        left, provider = name, ""
    if "," in left:
        station, city = left.rsplit(",", 1)
        city = re.sub(r"-\d{4,}$", "", city.strip())  # provider id glued to city
        return station.strip(), city.strip(), provider.strip()
    return left.strip(), "", provider.strip()


def probe_location(location_id: int) -> Station | None:
    """Harvest one location's metadata from the archive. None if it has no
    records or no readable day file in its most recent month."""
    cov = s3archive.get_coverage(location_id)
    if not cov.months:
        return None
    y, m = cov.last
    # find an existing day in the last month: try the 1st, then scan the listing
    days = _list_days(location_id, y, m)
    if not days:
        return None
    rows = s3archive.fetch_day(location_id, y, m, days[0])
    if not rows:
        return None
    name = rows[0]["location"]
    station, city, provider = parse_location_name(name)
    params = sorted({r["parameter"] for r in rows})
    return Station(
        location_id=location_id, name=name, station=station, city=city,
        provider=provider, lat=rows[0]["lat"], lon=rows[0]["lon"],
        parameters=params,
        first_month=f"{cov.first[0]}-{cov.first[1]:02d}",
        last_month=f"{cov.last[0]}-{cov.last[1]:02d}",
        n_months=len(cov.months),
    )


def _list_days(location_id: int, year: int, month: int) -> list[int]:
    import xml.etree.ElementTree as ET
    prefix = f"records/csv.gz/locationid={location_id}/year={year:04d}/month={month:02d}/"
    url = f"{s3archive.BUCKET}/?list-type=2&prefix={prefix}&max-keys=100"
    root = ET.fromstring(s3archive._get(url))
    days = []
    for key in root.iter(s3archive.NS + "Key"):
        base = key.text.rsplit("-", 1)[-1]  # yyyymmdd.csv.gz
        days.append(int(base[6:8]))
    return sorted(days)


def save_catalog(stations: list[Station], path: str, harvested_on: str) -> None:
    payload = {
        "source": "OpenAQ open-data archive (S3), keyless; v3 API not used (requires key)",
        "harvested_on": harvested_on,
        "note": ("Sample of archive locations. Coverage windows are month-granular and "
                 "reflect the archive at harvest time; re-probe for current coverage."),
        "stations": [s.to_json() for s in stations],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_catalog(path: str) -> list[Station]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    out = []
    for d in payload["stations"]:
        d = dict(d)
        out.append(Station(**d))
    return out
