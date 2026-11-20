"""Harvest a station catalog from the keyless OpenAQ S3 archive.

Samples location ids from a seed list, probes each (coverage listing + one
recent day file = ~2 requests), keeps stations that have pm25 or pm10
records, and writes data/catalog.json. Run from the repo root:

    python scripts/bootstrap_catalog.py --sample 250 --seed 42

Resume mode grows an existing catalog in bounded batches: ids already probed
(recorded in a checkpoint file) are skipped, new keepers are merged in, and
both files are saved after every completed batch. An interrupted batch is
re-probed on the next run; transient probe failures are never checkpointed:

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


def summarize_batch(existing, outcomes):
    """Merge (requested_id, probe_result) pairs; checkpoint only answered probes.

    Accepted counts are probe outcomes, while added/refreshed count unique station
    IDs. A retryable error is not evidence that a location has no archive data.
    """
    accepted, completed = [], set()
    counts = dict(attempted=0, accepted=0, empty=0, skipped=0, failed=0)
    for requested_id, result in outcomes:
        counts["attempted"] += 1
        if result == "ERR":
            counts["failed"] += 1
            continue
        completed.add(int(requested_id))
        if result is None:
            counts["empty"] += 1
        elif any(p in ("pm25", "pm10") for p in result.parameters):
            accepted.append(result)
            counts["accepted"] += 1
        else:
            counts["skipped"] += 1
    old_ids = {s.location_id for s in existing}
    accepted_ids = {s.location_id for s in accepted}
    counts["added"] = len(accepted_ids - old_ids)
    counts["refreshed"] = len(accepted_ids & old_ids)
    counts["duplicates"] = len(accepted) - len(accepted_ids)
    return merge(existing, accepted), completed, counts


def select_ids(ids, probed, sample, seed):
    """Normalize and deduplicate seed IDs before deterministic sampling."""
    if sample < 0:
        raise ValueError("sample must be non-negative")
    shuffled = list(dict.fromkeys(int(i) for i in ids))
    random.Random(seed).shuffle(shuffled)
    return [i for i in shuffled if i not in probed][:sample]


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
    if args.sample < 0:
        ap.error("--sample must be non-negative")

    ids = [int(i) for i in json.load(open(args.ids_file))]
    probed, stations = set(), []
    if args.resume:
        if os.path.exists(args.checkpoint):
            probed = {int(i) for i in json.load(open(args.checkpoint))}
        if os.path.exists(args.out):
            stations = catalog.load_catalog(args.out)
        print(f"resume: {len(probed)} ids already probed, {len(stations)} stations in catalog")

    picked = select_ids(ids, probed, args.sample, args.seed)
    print(f"probing {len(picked)} location ids ...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        outcomes = zip(picked, ex.map(probe, picked))
        stations, completed, counts = summarize_batch(stations, outcomes)

    probed.update(completed)
    from datetime import date
    catalog.save_catalog(stations, args.out, harvested_on=str(date.today()))
    if args.resume:
        json.dump(sorted(probed), open(args.checkpoint, "w"))
    cities = len({s.city for s in stations if s.city})
    print(f"attempted={counts['attempted']}, accepted_pm={counts['accepted']}, "
          f"added={counts['added']}, refreshed={counts['refreshed']}, "
          f"duplicate_results={counts['duplicates']}, empty={counts['empty']}, "
          f"skipped_non_pm={counts['skipped']}, failed_retryable={counts['failed']}; "
          f"catalog now {len(stations)} stations across {cities} parsed cities -> {args.out}; "
          f"total checkpointed {len(probed)}")


if __name__ == "__main__":
    main()
