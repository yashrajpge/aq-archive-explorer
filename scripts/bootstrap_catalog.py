"""Harvest a station catalog from the keyless OpenAQ S3 archive.

Samples location ids from a seed list, probes each (coverage listing + one
recent day file = ~2 requests), keeps stations that have pm25 or pm10
records, and writes data/catalog.json. Run from the repo root:

    python scripts/bootstrap_catalog.py --sample 250 --seed 42
"""
import argparse, json, random, sys, os
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from openaq_explorer import catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=250)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ids-file", default=os.path.join(os.path.dirname(__file__), "../../location_ids.json"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "../data/catalog.json"))
    args = ap.parse_args()

    ids = json.load(open(args.ids_file))
    random.seed(args.seed)
    picked = random.sample(ids, min(args.sample, len(ids)))
    print(f"probing {len(picked)} sampled location ids ...")

    stations, empty, failed = [], 0, 0
    def probe(i):
        try:
            return catalog.probe_location(int(i))
        except Exception:
            return "ERR"
    with ThreadPoolExecutor(max_workers=8) as ex:
        for st in ex.map(probe, picked):
            if st == "ERR":
                failed += 1
            elif st is None:
                empty += 1
            elif any(p in ("pm25", "pm10") for p in st.parameters):
                stations.append(st)
    stations.sort(key=lambda s: (s.city or "~", s.station))
    from datetime import date
    catalog.save_catalog(stations, args.out, harvested_on=str(date.today()))
    cities = len({s.city for s in stations if s.city})
    print(f"kept {len(stations)} stations across {cities} parsed cities "
          f"(empty={empty}, failed={failed}) -> {args.out}")


if __name__ == "__main__":
    main()
