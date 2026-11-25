"""Air Quality Archive Explorer - Flask app.

Serves the single-page UI and a small JSON API over the keyless OpenAQ
open-data archive (historical records only - every station surface shows
the archive's actual coverage window, never a 'live' claim).

Run:  python app.py  ->  http://localhost:5000
"""
import os
from flask import Flask, jsonify, request, send_file

from openaq_explorer import aggregate, catalog, s3archive, standards

BASE = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(BASE, "data", "catalog.json")

app = Flask(__name__)


def _catalog():
    if not os.path.exists(CATALOG_PATH):
        return []
    return catalog.load_catalog(CATALOG_PATH)


@app.get("/")
def index():
    return send_file(os.path.join(BASE, "ui.html"))


@app.get("/api/standards")
def api_standards():
    return jsonify({k: v for k, v in standards.STANDARDS.items()})


@app.get("/api/stations")
def api_stations():
    """Stations from the harvested catalog, optional ?q= name/city filter."""
    q = (request.args.get("q") or "").strip().lower()
    out = []
    for s in _catalog():
        if q and q not in s.name.lower() and q not in s.city.lower():
            continue
        out.append(s.to_json())
    total = len(out)
    # Cap listings so the landing page stays light on big catalogs; a search
    # query is how you reach stations beyond the first page.
    limit = min(total, 200) if q else min(total, 60)
    return jsonify({"count": total, "shown": limit, "stations": out[:limit]})


@app.get("/api/station/<int:lid>/coverage")
def api_coverage(lid: int):
    """Live month-granular coverage straight from the archive."""
    cov = s3archive.get_coverage(lid)
    return jsonify({
        "location_id": lid,
        "window": cov.window_str(),
        "n_months": len(cov.months),
        "months": [f"{y}-{m:02d}" for (y, m) in cov.months],
    })


@app.get("/api/station/<int:lid>/month/<int:year>/<int:month>")
def api_month(lid: int, year: int, month: int):
    """Daily aggregates for one station-month, one parameter.

    Fetches each UTC day file and regroups by each row's local date; edge
    days at month boundaries can be partial and show a lower coverage.
    """
    param = request.args.get("parameter", "pm25")
    standard = request.args.get("standard")
    # Reject invalid comparisons before doing any archive requests.
    if not (1 <= year <= 9999 and 1 <= month <= 12):
        return jsonify(error="year must be 1-9999 and month must be 1-12"), 400
    st = None
    if standard:
        try:
            st = standards.get(standard)
        except KeyError:
            return jsonify(error="unknown standard", choices=sorted(standards.STANDARDS)), 400
        if st["parameter"] != param:
            return jsonify(error="standard does not match requested parameter",
                           parameter=param, standard_parameter=st["parameter"]), 400
    rows, rejected = [], 0
    import calendar as cal
    for day in range(1, cal.monthrange(year, month)[1] + 1):
        day_rows, day_rejected = s3archive.fetch_day_counted(lid, year, month, day)
        rows.extend(day_rows)
        rejected += day_rejected
    stats = [s for s in aggregate.daily_stats(rows) if s.parameter == param]
    n_other_units = 0
    if st is not None:
        # A threshold in one unit must never be compared with values in another.
        matching = [s for s in stats if aggregate.same_units(s.units, st["units"])]
        n_other_units = len(stats) - len(matching)
        stats = matching
    out = {
        "location_id": lid, "year": year, "month": month, "parameter": param,
        "days": [s.__dict__ for s in stats],
        "n_days": len(stats),
        # all parameters in the month files, not only the requested one
        "n_rejected_rows": rejected,
        "n_days_other_units": n_other_units,
    }
    out["n_suspect"] = sum(1 for s in stats if s.suspect)
    if st is not None:
        exc = aggregate.exceedance_days(stats, st["threshold"])
        out["standard"] = st
        out["exceedance_days"] = [s.date for s in exc]
        out["n_exceedance"] = len(exc)
        out["n_valid_days"] = sum(1 for s in stats if s.coverage >= 2 / 3)
        out["n_suspect_exceedance"] = sum(1 for s in exc if s.suspect)
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
