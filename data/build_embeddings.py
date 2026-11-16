"""Stream species abstracts from SQLite and embed them into ChromaDB.

Usage:
    python data/build_embeddings.py [--batch-size 500] [--limit N]

Skips species that are already embedded (checks existing ChromaDB IDs).
Safe to run multiple times — uses upsert.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import database, vector_db


def _existing_ids(col) -> set[str]:
    count = col.count()
    if count == 0:
        return set()
    all_items = col.get(include=[])
    return set(all_items["ids"])


def run(batch_size: int = 500, limit: int | None = None) -> None:
    col = vector_db.get_collection()
    existing = _existing_ids(col)
    print(f"Already embedded: {len(existing):,}")

    conn = database.get_connection()
    sql = """
        SELECT scientific_name, wikipedia_abstract, common_names, taxon_rank
        FROM species
        WHERE wikipedia_abstract IS NOT NULL
          AND wikipedia_abstract != ''
    """
    if limit:
        sql += f" LIMIT {limit}"

    cursor = conn.execute(sql)
    batch: list[dict] = []
    total_new = 0
    total_skipped = 0

    while True:
        rows = cursor.fetchmany(batch_size * 2)
        if not rows:
            break
        for row in rows:
            sid = row["scientific_name"]
            if sid in existing:
                total_skipped += 1
                continue
            batch.append(
                {
                    "scientific_name": sid,
                    "wikipedia_abstract": row["wikipedia_abstract"],
                    "common_names": database.parse_common_names(row["common_names"]),
                    "taxon_rank": row["taxon_rank"],
                }
            )
            if len(batch) >= batch_size:
                vector_db.embed_batch(batch)
                total_new += len(batch)
                print(f"  Embedded {total_new:,} new | skipped {total_skipped:,}")
                batch = []

    if batch:
        vector_db.embed_batch(batch)
        total_new += len(batch)

    conn.close()
    print(f"\nDone. Embedded {total_new:,} new records ({total_skipped:,} already existed).")
    print(f"Total in collection: {col.count():,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=None,
                        help="Embed at most N records (for testing)")
    args = parser.parse_args()
    run(batch_size=args.batch_size, limit=args.limit)
