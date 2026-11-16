"""
Enrich species records with images from the iNaturalist API.

No authentication required.  For each species the script:
  1. Queries iNaturalist taxa endpoint by scientific name.
  2. Verifies the top result is an exact name match.
  3. Stores the taxon's default photo URL + attribution in the DB.

Scope flags (only species-rank ACCEPTED records without an existing image):
  (default)        species with wikipedia_abstract   (~7k,  ~1.4 h)
  --iucn-matched   species with iucn_status          (~175k, ~34 h)
  --all-accepted   every accepted species-rank row   (~1.78M, days)

Usage:
    python data/enrich_images.py
    python data/enrich_images.py --iucn-matched
    python data/enrich_images.py --all-accepted --delay 1.0
    python data/enrich_images.py --no-verify-ssl
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
from app.paths import data_path  # noqa: E402
from app import database

INAT_API      = "https://api.inaturalist.org/v1/taxa"
CHECKPOINT    = str(data_path("images_checkpoint.json"))
REQUEST_DELAY = 0.7   # iNaturalist allows 100 req/min unauthenticated; 0.7 s ≈ 86/min
USER_AGENT    = (
    "AnimalKingdomApp/1.0 (educational offline project; contact "
    + os.environ.get("AK_CONTACT_EMAIL", "add-your-email@example.com") + ")"
)


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _load_checkpoint() -> set[str]:
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            return set(json.load(f))
    return set()


def _save_checkpoint(done: set[str]) -> None:
    with open(CHECKPOINT, "w") as f:
        json.dump(sorted(done), f)


def _fetch_inaturalist(name: str, ctx: ssl.SSLContext) -> tuple[str, str] | None:
    """Return (image_url, attribution) for an exact species name match, or None."""
    url = f"{INAT_API}?q={urllib.parse.quote(name)}&per_page=5&rank=species"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return None

    for taxon in data.get("results", []):
        if taxon.get("name", "").lower() != name.lower():
            continue
        photo = taxon.get("default_photo") or {}
        img_url = photo.get("medium_url") or photo.get("square_url")
        if img_url:
            attribution = photo.get("attribution") or "© iNaturalist contributors"
            return img_url, attribution
    return None


def enrich(scope: str, limit: int, no_verify: bool, delay: float) -> None:
    ctx  = _make_ssl_context(no_verify)
    done = _load_checkpoint()
    conn = database.get_connection()

    if scope == "all-accepted":
        where = (
            "taxonomic_status = 'ACCEPTED' AND taxon_rank = 'species' "
            "AND primary_image_url IS NULL"
        )
    elif scope == "iucn-matched":
        where = "iucn_status IS NOT NULL AND primary_image_url IS NULL"
    else:
        where = "wikipedia_abstract IS NOT NULL AND primary_image_url IS NULL"

    rows = conn.execute(
        f"SELECT scientific_name FROM species WHERE {where} LIMIT ?", (limit,)
    ).fetchall()

    total = len(rows)
    print(f"Processing {total:,} species for images  (scope: {scope})")
    print(f"  {len(done):,} already checkpointed from previous runs\n")

    found = no_match = errors = 0

    for i, row in enumerate(rows):
        name = row["scientific_name"]
        if name in done:
            continue

        try:
            result = _fetch_inaturalist(name, ctx)
        except Exception:
            errors += 1
            done.add(name)
            continue
        time.sleep(delay)

        if result:
            img_url, attribution = result
            conn.execute(
                "UPDATE species SET primary_image_url = ?, image_attribution = ? "
                "WHERE scientific_name = ?",
                (img_url, attribution, name),
            )
            conn.commit()
            found += 1
        else:
            no_match += 1

        done.add(name)

        if (i + 1) % 100 == 0:
            _save_checkpoint(done)
            pct = (i + 1) / total * 100
            print(
                f"  {i+1:>7,}/{total:,} ({pct:.1f}%)  "
                f"found={found:,}  no_match={no_match:,}  err={errors:,}",
                flush=True,
            )

    _save_checkpoint(done)
    conn.close()
    print(
        f"\nDone.\n"
        f"  Images found:   {found:>7,}\n"
        f"  No iNat match:  {no_match:>7,}\n"
        f"  Errors:         {errors:>7,}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich species with images from iNaturalist"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--iucn-matched", action="store_true",
        help="Process all species with iucn_status (no image) — ~175k, ~34 h",
    )
    group.add_argument(
        "--all-accepted", action="store_true",
        help="Process all accepted species-rank records (no image) — ~1.78M, days",
    )
    parser.add_argument("--limit", type=int, default=500_000,
                        help="Max species per run (default: 500000)")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY,
                        help=f"Seconds between API calls (default: {REQUEST_DELAY})")
    parser.add_argument("--no-verify-ssl", action="store_true")
    args = parser.parse_args()

    if args.all_accepted:
        scope = "all-accepted"
    elif args.iucn_matched:
        scope = "iucn-matched"
    else:
        scope = "wikipedia"

    enrich(scope, args.limit, args.no_verify_ssl, args.delay)


if __name__ == "__main__":
    main()
