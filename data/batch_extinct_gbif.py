"""
Fill unknown extinct flags from GBIF species profiles, in bulk (network; resumable).

Covers the fossils data/backfill_extinct.py can't see: species from checklists
other than the Paleobiology Database (ZooBank, single-paper fossil datasets, ...).

Candidates: accepted Animalia species with extinct = NULL in a genus that already
holds a known extinct species (where fossils hide). The local backbone's taxonID is
GBIF's species key, so each species costs one API call (/species/{key}/speciesProfiles).
Same rule as the species panel (trait_utils.extinct_from_profiles): profiles that
agree give 1 or 0; none or disagreement stays NULL. Writes go through
database.update_species_traits, so provenance is recorded and genera / families are
flagged as soon as their last species is (live roll-up).

Resumable: every checked name is appended to the checkpoint file; stop any time
(Ctrl+C or shutdown) and re-run to continue. Each write is its own short
transaction, so the app keeps working while it runs.

Usage:
    python data/batch_extinct_gbif.py --sample 300      # measure speed, write nothing
    python data/batch_extinct_gbif.py                   # run / resume
    python data/batch_extinct_gbif.py --workers 6
"""

import argparse
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.paths import data_path  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))
from app import database, trait_utils           # noqa: E402
from backfill_extinct import taxon_path          # noqa: E402  (same path rule as the import)

DATA_DIR    = data_path()
BACKBONE    = DATA_DIR / "gbif/backbone/Taxon.tsv"
CANDIDATES  = DATA_DIR / "extinct_batch_candidates.tsv"
CHECKPOINT  = DATA_DIR / "extinct_batch_done.txt"
LOG_EVERY_S = 60
_TAXON_ID, _CANONICAL, _STATUS, _KINGDOM, _GENUS = 0, 7, 14, 17, 22


# ── Candidates ────────────────────────────────────────────────────────────────

def candidate_names(conn) -> dict[str, str]:
    """{name: taxon_path} of unknown accepted species in genera with a known fossil."""
    genera_with_fossil: set[str] = set()
    unknown: dict[str, str] = {}
    for name, path, extinct in conn.execute(
        "SELECT scientific_name, taxon_path, extinct FROM species "
        "WHERE taxon_rank = 'species' AND taxonomic_status = 'ACCEPTED' AND taxon_path LIKE 'Animalia|%'"
    ):
        genus = path.rsplit("|", 1)[0]
        if extinct == 1:
            genera_with_fossil.add(genus)
        elif extinct is None:
            unknown[name] = path
    return {n: p for n, p in unknown.items() if p.rsplit("|", 1)[0] in genera_with_fossil}


def gbif_keys(wanted: dict[str, str], tsv: Path = BACKBONE) -> list[tuple[str, int]]:
    """(name, GBIF key) for wanted names whose backbone row has the same path."""
    out = []
    with open(tsv, encoding="utf-8", errors="replace", newline="") as f:
        next(f)
        for line in f:
            cols = line.rstrip("\r\n").split("\t")
            if len(cols) <= _GENUS or cols[_KINGDOM] != "Animalia" or cols[_STATUS] != "accepted":
                continue
            name = cols[_CANONICAL].strip()
            if name in wanted and taxon_path(cols) == wanted[name] and cols[_TAXON_ID].isdigit():
                out.append((name, int(cols[_TAXON_ID])))
                del wanted[name]          # first match wins, as in import_gbif.py
    return out


def load_candidates(conn) -> list[tuple[str, int]]:
    if CANDIDATES.exists():
        rows = [l.split("\t") for l in CANDIDATES.read_text(encoding="utf-8").splitlines() if l]
        return [(n, int(k)) for n, k in rows]
    print("Building candidate list (one-off, ~2 min)...", flush=True)
    found = gbif_keys(candidate_names(conn))
    CANDIDATES.write_text("".join(f"{n}\t{k}\n" for n, k in found), encoding="utf-8")
    return found


# ── Lookup ────────────────────────────────────────────────────────────────────

def lookup(key: int, retries: int = 5) -> trait_utils.TraitValue | None:
    """Extinct flag from GBIF profiles; retries with backoff when GBIF is busy."""
    for attempt in range(retries):
        try:
            data = trait_utils._get_json(f"{trait_utils._GBIF_API}/species/{key}/speciesProfiles")
            return trait_utils.extinct_from_profiles((data or {}).get("results") or [])
        except trait_utils.SourceUnavailable:
            time.sleep(2 ** attempt * 2)
    raise trait_utils.SourceUnavailable(f"GBIF busy for key {key}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sample", type=int, help="time this many lookups; write nothing")
    args = ap.parse_args()

    conn = database.get_connection()
    try:
        todo = load_candidates(conn)
    finally:
        conn.close()
    done = set(CHECKPOINT.read_text(encoding="utf-8").splitlines()) if CHECKPOINT.exists() else set()
    todo = [(n, k) for n, k in todo if n not in done]
    if args.sample:
        todo = todo[:args.sample]
    print(f"{len(done):,} already checked, {len(todo):,} to go, {args.workers} workers", flush=True)

    stats, lock, t0, last = Counter(), threading.Lock(), time.monotonic(), [time.monotonic()]
    ckpt = None if args.sample else open(CHECKPOINT, "a", encoding="utf-8")

    def work(name: str, key: int) -> tuple[str, str]:
        tv = lookup(key)
        if tv is None:
            return name, "unknown"
        if not args.sample:
            ok = database.update_species_traits(name, {"extinct": tv}, "sourced", completed=False)
            if not ok:
                return name, "write_skipped"      # DB busy: leave out of checkpoint, retried next run
        return name, "extinct" if tv.value == 1 else "living"

    pool = ThreadPoolExecutor(args.workers)
    try:
        futures = [pool.submit(work, n, k) for n, k in todo]
        for fut in as_completed(futures):
            try:
                name, outcome = fut.result()
            except trait_utils.SourceUnavailable:
                stats["gbif_busy"] += 1
                continue
            stats[outcome] += 1
            if ckpt and outcome != "write_skipped":
                ckpt.write(name + "\n")
            n = sum(stats.values())
            now = time.monotonic()
            if now - last[0] >= LOG_EVERY_S or n == len(todo):
                with lock:
                    last[0] = now
                    rate = n / (now - t0)
                    eta_h = (len(todo) - n) / rate / 3600 if rate else 0
                    print(f"{n:,}/{len(todo):,}  {rate:.1f}/s  ETA {eta_h:.1f} h  {dict(stats)}", flush=True)
                    if ckpt:
                        ckpt.flush()
    except KeyboardInterrupt:
        print("\nStopped; re-run to resume.", flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)   # finish in-flight, drop the queue
        if ckpt:
            ckpt.close()
    elapsed = time.monotonic() - t0
    n = sum(stats.values())
    print(f"done: {n:,} in {elapsed / 60:.1f} min ({n / elapsed if elapsed else 0:.1f}/s)  {dict(stats)}")


if __name__ == "__main__":
    main()
