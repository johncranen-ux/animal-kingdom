"""
Validate the species database after import.

Checks:
  - Total row count >= 1,700,000
  - No nulls/empty strings in required fields
  - Rank distribution
  - Random sample of accepted species

Usage:
    python data/validate_import.py
    python data/validate_import.py --min-rows 500000   # lower threshold for partial imports
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate species.db after import")
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1_700_000,
        help="Minimum expected row count (default: 1700000)",
    )
    args = parser.parse_args()

    conn = database.get_connection()
    failures: list[str] = []

    # --- Row counts ---
    total = conn.execute("SELECT COUNT(*) FROM species").fetchone()[0]
    accepted = conn.execute(
        "SELECT COUNT(*) FROM species WHERE taxonomic_status='ACCEPTED'"
    ).fetchone()[0]
    synonyms = total - accepted
    print("=" * 60)
    print("ROW COUNTS")
    print(f"  Total rows    : {total:>12,}")
    print(f"  Accepted      : {accepted:>12,}")
    print(f"  Synonyms/other: {synonyms:>12,}")
    if total < args.min_rows:
        msg = f"Total rows {total:,} < expected {args.min_rows:,}"
        print(f"  FAIL: {msg}")
        failures.append(msg)
    else:
        print(f"  OK: meets minimum threshold of {args.min_rows:,}")

    # --- Null checks ---
    print("\nREQUIRED FIELD NULLS")
    for field in ("scientific_name", "taxon_rank", "taxon_path"):
        nulls = conn.execute(
            f"SELECT COUNT(*) FROM species WHERE {field} IS NULL OR trim({field})=''"
        ).fetchone()[0]
        if nulls == 0:
            print(f"  {field:<22} OK")
        else:
            msg = f"{field} has {nulls:,} null/empty rows"
            print(f"  {field:<22} FAIL — {nulls:,} nulls")
            failures.append(msg)

    # --- Rank distribution ---
    print("\nRANK DISTRIBUTION (top 12)")
    for row in conn.execute(
        "SELECT taxon_rank, COUNT(*) AS n FROM species "
        "GROUP BY taxon_rank ORDER BY n DESC LIMIT 12"
    ).fetchall():
        print(f"  {(row['taxon_rank'] or '(none)'):<25} {row['n']:>10,}")

    # --- Enrichment coverage (informational) ---
    with_iucn = conn.execute(
        "SELECT COUNT(*) FROM species WHERE iucn_status IS NOT NULL"
    ).fetchone()[0]
    with_abstract = conn.execute(
        "SELECT COUNT(*) FROM species WHERE wikipedia_abstract IS NOT NULL"
    ).fetchone()[0]
    with_image = conn.execute(
        "SELECT COUNT(*) FROM species WHERE primary_image_url IS NOT NULL"
    ).fetchone()[0]
    print("\nENRICHMENT COVERAGE")
    print(f"  IUCN status      : {with_iucn:>10,}  ({with_iucn/max(total,1)*100:.1f}%)")
    print(f"  Wikipedia abstract: {with_abstract:>9,}  ({with_abstract/max(total,1)*100:.1f}%)")
    print(f"  Image URL        : {with_image:>10,}  ({with_image/max(total,1)*100:.1f}%)")

    # --- Random sample ---
    print("\nRANDOM SAMPLE — 20 accepted species")
    rows = conn.execute(
        """
        SELECT scientific_name, taxon_rank, taxon_path
        FROM species
        WHERE taxonomic_status='ACCEPTED' AND taxon_rank='species'
        ORDER BY RANDOM()
        LIMIT 20
        """
    ).fetchall()
    if rows:
        for row in rows:
            path_preview = row["taxon_path"]
            if len(path_preview) > 60:
                path_preview = "..." + path_preview[-57:]
            print(f"  {row['scientific_name']:<35} {path_preview}")
    else:
        msg = "No accepted species rows found — import may not have run"
        print(f"  FAIL: {msg}")
        failures.append(msg)

    conn.close()

    # --- Final verdict ---
    print("\n" + "=" * 60)
    if failures:
        print(f"VALIDATION FAILED ({len(failures)} issue(s)):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
