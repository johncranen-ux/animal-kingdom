"""
Enrich species records with geographic bounding boxes via the GBIF Occurrence API.

No authentication required. For each species:
  1. Resolves the GBIF usage key via the species-match endpoint.
  2. Fetches up to 300 georeferenced occurrence records.
  3. Derives lat/lon bounding box and stores it in geo_bounding_box.

Default scope: species that already have a wikipedia_abstract (~7,000 notable
species, ≈ 2 hours at the default 0.5 s delay).  Use --all-accepted to expand
to every accepted species (can take many hours; use --limit to cap per run).

Usage:
    python data/enrich_gbif_occurrences.py
    python data/enrich_gbif_occurrences.py --all-accepted --limit 50000
    python data/enrich_gbif_occurrences.py --no-verify-ssl --delay 1.0

Progress is checkpointed to E:/AnimalKingdomSystem/gbif_bbox_checkpoint.json.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database

GBIF_MATCH      = "https://api.gbif.org/v1/species/match"
GBIF_OCCURRENCE = "https://api.gbif.org/v1/occurrence/search"
CHECKPOINT_FILE = r"E:\AnimalKingdomSystem\gbif_bbox_checkpoint.json"
REQUEST_DELAY   = 0.5    # 0.5 s per call → ≤ 2 req/s, well within GBIF fair-use
OCC_LIMIT       = 300    # occurrence records to sample per species
USER_AGENT      = (
    "AnimalKingdomApp/1.0 (educational offline app; contact "
    + os.environ.get("AK_CONTACT_EMAIL", "add-your-email@example.com") + ")"
)
MIN_CONFIDENCE  = 90     # reject fuzzy species-match results below this score


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _load_checkpoint() -> set[str]:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return set(json.load(f))
    return set()


def _save_checkpoint(done: set[str]) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(sorted(done), f)


def _fetch_json(url: str, ctx: ssl.SSLContext) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _get_usage_key(name: str, ctx: ssl.SSLContext) -> int | None:
    url  = f"{GBIF_MATCH}?name={urllib.parse.quote(name)}&verbose=false"
    data = _fetch_json(url, ctx)
    if not data:
        return None
    match_type = data.get("matchType", "NONE")
    if match_type == "NONE":
        return None
    if match_type == "FUZZY" and data.get("confidence", 0) < MIN_CONFIDENCE:
        return None
    return data.get("usageKey")


def _get_bbox(usage_key: int, ctx: ssl.SSLContext) -> dict | None:
    url  = (
        f"{GBIF_OCCURRENCE}?taxonKey={usage_key}"
        f"&hasCoordinate=true&limit={OCC_LIMIT}"
    )
    data = _fetch_json(url, ctx)
    if not data:
        return None
    results = data.get("results", [])
    lats = [r["decimalLatitude"]  for r in results if "decimalLatitude"  in r]
    lons = [r["decimalLongitude"] for r in results if "decimalLongitude" in r]
    if not lats:
        return None
    return {
        "lat_min": round(min(lats), 4),
        "lat_max": round(max(lats), 4),
        "lon_min": round(min(lons), 4),
        "lon_max": round(max(lons), 4),
    }


def enrich(all_accepted: bool, limit: int, no_verify: bool, delay: float) -> None:
    ctx  = _make_ssl_context(no_verify)
    done = _load_checkpoint()
    conn = database.get_connection()

    if all_accepted:
        where = (
            "taxonomic_status = 'ACCEPTED' AND taxon_rank = 'species' "
            "AND geo_bounding_box IS NULL"
        )
    else:
        where = "wikipedia_abstract IS NOT NULL AND geo_bounding_box IS NULL"

    rows = conn.execute(
        f"SELECT scientific_name FROM species WHERE {where} LIMIT ?", (limit,)
    ).fetchall()

    total = len(rows)
    print(f"Processing {total:,} species for bounding boxes")
    print(f"  scope: {'all accepted species-rank' if all_accepted else 'wikipedia-enriched species'}")
    print(f"  ({len(done):,} already checkpointed from previous runs)\n")

    updated = no_match = no_occ = errors = 0

    for i, row in enumerate(rows):
        name = row["scientific_name"]
        if name in done:
            continue

        # Step 1 — resolve GBIF usage key
        try:
            usage_key = _get_usage_key(name, ctx)
        except Exception as e:
            errors += 1
            done.add(name)
            continue
        time.sleep(delay)

        if not usage_key:
            no_match += 1
            done.add(name)
            continue

        # Step 2 — compute bounding box from occurrences
        try:
            bbox = _get_bbox(usage_key, ctx)
        except Exception:
            errors += 1
            done.add(name)
            continue
        time.sleep(delay)

        if bbox:
            conn.execute(
                "UPDATE species SET geo_bounding_box = ? WHERE scientific_name = ?",
                (database.serialize_geo_bbox(bbox), name),
            )
            conn.commit()
            updated += 1
        else:
            no_occ += 1

        done.add(name)

        if (i + 1) % 100 == 0:
            _save_checkpoint(done)
            pct = (i + 1) / total * 100
            print(
                f"  {i+1:>6,}/{total:,}  ({pct:.1f}%)  "
                f"bbox={updated:,}  no_match={no_match:,}  "
                f"no_occ={no_occ:,}  err={errors:,}",
                flush=True,
            )

    _save_checkpoint(done)
    conn.close()
    print(
        f"\nDone.\n"
        f"  Bounding boxes added: {updated:>6,}\n"
        f"  No GBIF match:        {no_match:>6,}\n"
        f"  No occurrences found: {no_occ:>6,}\n"
        f"  Errors:               {errors:>6,}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich species with GBIF occurrence-based geographic bounding boxes"
    )
    parser.add_argument(
        "--all-accepted", action="store_true",
        help="Process all accepted species-rank entries (slow) instead of just wikipedia-enriched ones",
    )
    parser.add_argument(
        "--limit", type=int, default=10_000,
        help="Max species to process per run (default: 10000)",
    )
    parser.add_argument(
        "--delay", type=float, default=REQUEST_DELAY,
        help=f"Seconds between each API call (default: {REQUEST_DELAY})",
    )
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="Disable SSL certificate verification")
    args = parser.parse_args()
    enrich(args.all_accepted, args.limit, args.no_verify_ssl, args.delay)


if __name__ == "__main__":
    main()
