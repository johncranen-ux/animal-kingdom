"""
Enrich species records with physical traits from the AnAge database.

Downloads the AnAge dataset (no token required) and populates:
  body_mass (kg), max_lifespan (years), metabolic_rate (W)

Coverage: ~4,400 vertebrate species (mammals, birds, reptiles, fish, etc.)

Usage:
    python data/enrich_anage.py
    python data/enrich_anage.py --no-verify-ssl
"""

import argparse
import io
import json
import os
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database

ANAGE_URL  = "https://genomics.senescence.info/species/dataset.zip"
USER_AGENT = (
    "AnimalKingdomApp/1.0 (educational offline app; contact "
    + os.environ.get("AK_CONTACT_EMAIL", "add-your-email@example.com") + ")"
)


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _download_anage(ctx: ssl.SSLContext) -> tuple[list[dict], list[str]]:
    print(f"Downloading AnAge dataset from {ANAGE_URL} ...")
    req = urllib.request.Request(ANAGE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        raw = resp.read()

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        target = next((n for n in names if "anage_data" in n.lower()), names[0])
        content = zf.read(target).decode("utf-8", errors="replace")

    lines = content.splitlines()
    if not lines:
        return [], []

    header = [h.strip() for h in lines[0].split("\t")]
    rows   = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    print(f"  Loaded {len(rows):,} AnAge records  (columns: {len(header)})")
    return rows, header


def _find_col(header: list[str], *needles: str) -> str | None:
    """Return the first header whose lowercase text contains any needle."""
    for needle in needles:
        for h in header:
            if needle.lower() in h.lower():
                return h
    return None


def _to_float(val: str) -> float | None:
    try:
        f = float((val or "").strip())
        return f if f > 0 else None
    except ValueError:
        return None


def enrich(no_verify: bool) -> None:
    ctx          = _make_ssl_context(no_verify)
    rows, header = _download_anage(ctx)
    if not rows:
        print("ERROR: empty AnAge dataset — aborting")
        return

    col_genus   = _find_col(header, "genus")
    col_species = _find_col(header, "species")
    col_mass    = _find_col(header, "adult weight", "adult_weight")
    col_life    = _find_col(header, "maximum longevity", "max_longevity")
    col_meta    = _find_col(header, "metabolic rate", "metabolic_rate")

    print(f"\nColumn mapping:")
    print(f"  genus          = {col_genus}")
    print(f"  species        = {col_species}")
    print(f"  body_mass      = {col_mass} (g -> kg)")
    print(f"  max_lifespan   = {col_life}")
    print(f"  metabolic_rate = {col_meta}\n")

    if not col_genus or not col_species:
        print("ERROR: could not locate genus/species columns — aborting")
        return

    conn = database.get_connection()
    updated = not_found = skipped = 0

    for row in rows:
        genus = row.get(col_genus, "").strip()
        spp   = row.get(col_species, "").strip()
        if not genus or not spp or spp.lower() in ("sp.", "spp.", ""):
            skipped += 1
            continue

        sci_name = f"{genus} {spp}"

        mass     = _to_float(row.get(col_mass, ""))
        lifespan = _to_float(row.get(col_life, ""))
        meta     = _to_float(row.get(col_meta, ""))

        if mass is None and lifespan is None and meta is None:
            skipped += 1
            continue

        if mass is not None:
            mass = round(mass / 1000, 6)   # grams → kg

        exists = conn.execute(
            "SELECT 1 FROM species WHERE scientific_name = ?", (sci_name,)
        ).fetchone()
        if not exists:
            not_found += 1
            continue

        conn.execute(
            "UPDATE species SET body_mass=?, max_lifespan=?, metabolic_rate=? "
            "WHERE scientific_name=?",
            (mass, lifespan, meta, sci_name),
        )
        updated += 1

    conn.commit()
    conn.close()
    print(
        f"Done.\n"
        f"  Updated:        {updated:>6,}\n"
        f"  Not in DB:      {not_found:>6,}\n"
        f"  Skipped (empty):{skipped:>6,}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich species with AnAge physical traits (body_mass, max_lifespan, metabolic_rate)"
    )
    parser.add_argument("--no-verify-ssl", action="store_true",
                        help="Disable SSL certificate verification")
    args = parser.parse_args()
    enrich(args.no_verify_ssl)


if __name__ == "__main__":
    main()
