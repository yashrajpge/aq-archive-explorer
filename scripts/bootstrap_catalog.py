"""Harvest a station catalog from the keyless OpenAQ S3 archive.

Samples location ids from a seed list, probes each (coverage listing + one
recent day file = ~2 requests), keeps stations that have pm25 or pm10
records, and writes data/catalog.json. Run from the repo root:

    python scripts/bootstrap_catalog.py --sample 250 --seed 42

Resume mode grows an existing catalog in bounded batches: ids already probed
(recorded in a checkpoint file) are skipped, new keepers are merged in, and
both files are saved after every batch, so a killed run loses nothing:

    python scripts/bootstrap_catalog.py --resume --sample 300
"""
import argparse, json, random, sys, os
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from openaq_explorer import catalog

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def probe(i):
    try:
        return catalog.probe_location(int(i))
    except Exception:
        return "ERR"


def merge(existing, new):
    by_id = {s.location_id: s for s in existing}
    for s in new:
        by_id[s.location_id] = s
    stations = sorted(by_id.values(), key=lambda s: (s.city or "~", s.station))
    return stations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=250, help="ids to probe this run")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true",
                    help="skip ids in the checkpoint file and merge into the existing catalog")
    ap.add_argument("--checkpoint", default=os.path.join(REPO_ROOT, "../harvest_checkpoint.json"))
    ap.add_argument("--ids-file", default=os.path.join(REPO_ROOT, "../location_ids.json"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "data/catalog.json"))
    args = ap.parse_args()

    ids = [int(i) for i in json.load(open(args.ids_file))]
    probed, stations = set(), []
    if args.resume:
        if os.path.exists(args.checkpoint):
            probed = set(json.load(open(args.checkpoint)))
        if os.path.exists(args.out):
            stations = catalog.load_catalog(args.out)
        print(f"resume: {len(probed)} ids already probed, {len(stations)} stations in catalog")

    # Deterministic order across runs: one seeded shuffle of the full id list,
    # then take the first un-probed slice. Probing is the only random part.
    rng = random.Random(args.seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    picked = [i for i in shuffled if i not in probed][:args.sample]
    print(f"probing {len(picked)} location ids ...")

    kept, empty, failed = [], 0, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for st in ex.map(probe, picked):
            if st == "ERR":
                failed += 1
            elif st is None:
                empty += 1
            elif any(p in ("pm25", "pm10") for p in st.parameters):
                kept.append(st)

    probed.update(picked)
    stations = merge(stations, kept)
    from datetime import date
    catalog.save_catalog(stations, args.out, harvested_on=str(date.today()))
    if args.resume:
        json.dump(sorted(probed), open(args.checkpoint, "w"))
    cities = len({s.city for s in stations if s.city})
    print(f"kept {len(kept)} new this batch (empty={empty}, failed={failed}); "
          f"catalog now {len(stations)} stations across {cities} parsed cities -> {args.out}; "
          f"total probed {len(probed)}")


if __name__ == "__main__":
    main()
