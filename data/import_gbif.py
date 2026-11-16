"""
Import GBIF Backbone Taxonomy into species.db.

Usage:
    # Point at the extracted backbone directory:
    python data/import_gbif.py /path/to/backbone/

    # Or point at the downloaded zip:
    python data/import_gbif.py /path/to/backbone.zip

    # Download then import (adds --no-verify-ssl if you have cert issues):
    python data/import_gbif.py --download [--output-dir E:/AnimalKingdomSystem/gbif] [--no-verify-ssl]

The backbone directory must contain Taxon.tsv (tab-separated).
VernacularName.tsv is loaded if present for English common names.

Download the backbone from GBIF:
  https://hosted-datasets.gbif.org/datasets/backbone/current/backbone.zip
"""

import argparse
import csv
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# GBIF TSV files can contain very large fields (e.g. long taxon remarks)
csv.field_size_limit(min(sys.maxsize, 2_147_483_647))

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database

CHUNK_SIZE = 10_000
GBIF_BACKBONE_URL = (
    "https://hosted-datasets.gbif.org/datasets/backbone/current/backbone.zip"
)

# GBIF uses lowercase rank names; stored as-is in our schema
_SPECIES_RANKS = {"species", "subspecies", "variety", "form", "infraspecies"}


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _build_taxon_path(row: dict) -> str:
    parts = []
    for field in ("kingdom", "phylum", "class", "order", "family", "genus"):
        val = (row.get(field) or "").strip()
        if val:
            parts.append(val)
    rank = (row.get("taxonRank") or "").lower()
    if rank in _SPECIES_RANKS:
        canonical = (row.get("canonicalName") or "").strip()
        if canonical and (not parts or parts[-1] != canonical):
            parts.append(canonical)
    return "|".join(parts)


_RANK_ORDER = ("kingdom", "phylum", "class", "order", "family", "genus",
               "species", "subspecies", "variety", "form")


def row_score(status: str, taxon_path: str, rank: str) -> int:
    """Which backbone row should own a name when several share it (higher wins).

    One row per name is stored, so homonyms and synonyms compete. Accepted animals
    beat everything else (this is an animal catalogue), then accepted taxa of other
    kingdoms, then synonyms; among equals the higher rank wins ("Proboscidea" is
    the elephant order, not a worm genus). Equal scores keep the first row."""
    path = taxon_path or ""
    animal = path == "Animalia" or path.startswith("Animalia|")
    tier = 2 if status == "ACCEPTED" and animal else 1 if status == "ACCEPTED" else 0
    r = (rank or "").lower()
    rank_bonus = len(_RANK_ORDER) - (_RANK_ORDER.index(r) if r in _RANK_ORDER else len(_RANK_ORDER))
    return tier * 100 + rank_bonus


def _map_status(gbif_status: str) -> str:
    return "ACCEPTED" if gbif_status.lower() == "accepted" else "SYNONYM"


def _load_vernacular_names(tsv_path: str) -> dict[str, list[str]]:
    """Return dict of taxonID → [English common names]. Empty dict if file absent."""
    names: dict[str, list[str]] = {}
    if not os.path.exists(tsv_path):
        print("  VernacularName.tsv not found — common names will be empty")
        return names
    print("  Loading VernacularName.tsv...")
    with open(tsv_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            lang = (row.get("language") or "").lower().strip()
            if lang not in ("", "eng", "en"):
                continue
            tid = (row.get("taxonID") or "").strip()
            name = (row.get("vernacularName") or "").strip()
            if tid and name:
                names.setdefault(tid, []).append(name)
    print(f"  {len(names):,} taxa with English vernacular names loaded")
    return names


def _find_taxon_tsv(directory: str) -> str:
    """Return path to Taxon.tsv, checking root and one level of subdirectories."""
    direct = os.path.join(directory, "Taxon.tsv")
    if os.path.exists(direct):
        return direct
    for entry in os.scandir(directory):
        if entry.is_dir():
            candidate = os.path.join(entry.path, "Taxon.tsv")
            if os.path.exists(candidate):
                return candidate
    sys.exit(f"ERROR: Taxon.tsv not found in {directory} or its subdirectories")


# A later row with the same name replaces the stored one only if it scores higher
# (row_score); a plain INSERT OR IGNORE let outdated synonyms shadow accepted
# animals, e.g. "Panthera" stored as a moth synonym.
UPSERT_SQL = """
    INSERT INTO species
      (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(scientific_name) DO UPDATE SET
      taxon_path = excluded.taxon_path,
      taxon_rank = excluded.taxon_rank,
      common_names = excluded.common_names,
      taxonomic_status = excluded.taxonomic_status
    WHERE row_score(excluded.taxonomic_status, excluded.taxon_path, excluded.taxon_rank)
        > row_score(species.taxonomic_status, species.taxon_path, species.taxon_rank)
"""


def import_from_dir(backbone_dir: str) -> None:
    taxon_tsv = _find_taxon_tsv(backbone_dir)
    root_dir = str(Path(taxon_tsv).parent)
    vernacular_tsv = os.path.join(root_dir, "VernacularName.tsv")

    print(f"Backbone directory: {root_dir}")
    vern = _load_vernacular_names(vernacular_tsv)

    conn = database.get_connection()
    conn.create_function("row_score", 3, row_score, deterministic=True)
    inserted = skipped = 0
    batch: list[tuple] = []
    t0 = time.monotonic()

    def flush() -> None:
        nonlocal inserted, skipped
        if not batch:
            return
        conn.executemany(UPSERT_SQL, batch)
        conn.commit()
        inserted += len(batch)

    print("Importing Taxon.tsv...")
    with open(taxon_tsv, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row_num, row in enumerate(reader, 1):
            canonical = (row.get("canonicalName") or "").strip()
            if not canonical:
                skipped += 1
                continue
            taxon_path = _build_taxon_path(row)
            if not taxon_path:
                skipped += 1
                continue
            tid = (row.get("taxonID") or "").strip()
            batch.append((
                canonical,
                taxon_path,
                (row.get("taxonRank") or "").strip(),
                database.serialize_common_names(vern.get(tid, [])),
                _map_status(row.get("taxonomicStatus") or ""),
            ))
            if len(batch) >= CHUNK_SIZE:
                flush()
                batch.clear()
            if row_num % 100_000 == 0:
                elapsed = time.monotonic() - t0
                rate = row_num / elapsed
                print(
                    f"  {row_num:>9,} rows — {inserted:>8,} inserted, "
                    f"{skipped:>6,} skipped  [{rate:,.0f} rows/s]"
                )

    flush()
    conn.close()
    elapsed = time.monotonic() - t0
    print(f"\nFinished in {elapsed:.1f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Skipped  : {skipped:,}")


def import_from_zip(zip_path: str) -> None:
    extract_dir = str(Path(zip_path).with_suffix(""))
    print(f"Extracting {zip_path} -> {extract_dir} ...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
    import_from_dir(extract_dir)


def download_backbone(output_dir: str, no_verify_ssl: bool) -> str:
    os.makedirs(output_dir, exist_ok=True)
    zip_path = os.path.join(output_dir, "backbone.zip")
    ctx = _make_ssl_context(no_verify_ssl)
    print(f"Downloading backbone taxonomy (~1-2 GB) to {zip_path}")
    print("This may take several minutes...")

    _last_pct = [-1]

    def _progress(block_count: int, block_size: int, total: int) -> None:
        downloaded = block_count * block_size
        if total > 0:
            pct = int(min(downloaded / total * 100, 100))
            if pct >= _last_pct[0] + 5:
                mb = downloaded / 1_048_576
                print(f"  {mb:,.0f} / {total/1_048_576:,.0f} MB  ({pct}%)", flush=True)
                _last_pct[0] = pct

    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(GBIF_BACKBONE_URL, zip_path, reporthook=_progress)
    print()
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import GBIF backbone taxonomy into species.db",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "backbone_path",
        nargs="?",
        help="Path to extracted backbone directory or backbone .zip file",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download backbone.zip from GBIF before importing",
    )
    parser.add_argument(
        "--output-dir",
        default=r"E:\AnimalKingdomSystem\gbif",
        help="Destination for --download (default: E:/AnimalKingdomSystem/gbif)",
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Skip SSL certificate verification (use if you see cert errors)",
    )
    args = parser.parse_args()

    if not args.download and not args.backbone_path:
        parser.error("Provide backbone_path or --download")

    if args.download:
        zip_path = download_backbone(args.output_dir, args.no_verify_ssl)
        import_from_zip(zip_path)
    elif args.backbone_path.endswith(".zip"):
        import_from_zip(args.backbone_path)
    else:
        import_from_dir(args.backbone_path)


if __name__ == "__main__":
    main()
