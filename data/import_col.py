"""
Load one Catalogue of Life ColDP release into its own SQLite database, for the
trial comparison with the GBIF-based tree. Never touches species.db: a target
that already exists is refused.

Usage:
    python data/import_col.py <data dir>/col/col_xr_full_coldp.zip <data dir>/col/col_xr.db

The database mirrors the source instead of the app's schema:
- one row per name usage, so homonyms and synonyms keep separate rows;
- `lineage` is rebuilt from parentID ("domain:Eukaryota|kingdom:Animalia|..."), because
  the file's classification columns leave out levels such as domain and gigaclass.
  A synonym gets the lineage of its accepted taxon, without itself in it.

The files are plain tab-separated text with no quoting, so they are split on tabs:
csv's default dialect would treat a stray " in an authorship as the start of a
multi-line field and swallow the rows after it.
"""

import argparse
import io
import os
import re
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BATCH_SIZE = 50_000
PROGRESS_EVERY = 1_000_000
ACCEPTED_STATUSES = {"accepted", "provisionally accepted"}

SCHEMA = """
CREATE TABLE name_usage (
    id                   TEXT PRIMARY KEY,
    parent_id            TEXT,
    status               TEXT,
    rank                 TEXT,
    scientific_name      TEXT,
    authorship           TEXT,
    code                 TEXT,
    extinct              INTEGER,
    environment          TEXT,
    temporal_range_start TEXT,
    temporal_range_end   TEXT,
    source_id            TEXT,
    link                 TEXT,
    tax_group            TEXT,
    merged               INTEGER,
    lineage              TEXT
);
CREATE TABLE vernacular (
    taxon_id  TEXT,
    name      TEXT,
    language  TEXT,
    country   TEXT,
    preferred INTEGER,
    merged    INTEGER
);
CREATE TABLE import_meta (key TEXT PRIMARY KEY, value TEXT);
"""
INDEXES = """
CREATE INDEX idx_usage_name ON name_usage(scientific_name);
CREATE INDEX idx_usage_rank_status ON name_usage(rank, status);
CREATE INDEX idx_usage_parent ON name_usage(parent_id);
CREATE INDEX idx_vernacular_taxon ON vernacular(taxon_id);
"""


def _flag(value):
    """'true'/'false'/blank -> 1/0/NULL: "not extinct" and "not stated" differ."""
    return {"true": 1, "false": 0}.get((value or "").strip().lower())


def _read_tsv(archive, member):
    """Yield (row dict without the col:/clb: prefixes, field count was right)."""
    with archive.open(member) as raw:
        lines = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="\n")
        header = [name.split(":", 1)[-1] for name in next(lines).rstrip("\r\n").split("\t")]
        for line in lines:
            fields = line.rstrip("\r\n").split("\t")
            yield dict(zip(header, fields)), len(fields) == len(header)


class _Lineages:
    """Builds lineages from parent links, remembering each one (a tree this size
    is walked millions of times). A lineage is broken if its chain reaches a
    missing parent or a loop; the part that is known is still kept."""

    def __init__(self, nodes):
        self.nodes = nodes  # id -> (parent_id, rank, name), accepted usages only
        self.done = {}  # id -> (lineage, broken)

    def of_taxon(self, taxon_id):
        chain, seen = [], set()
        current = taxon_id
        lineage, broken = "", False
        while True:
            if current in self.done:
                lineage, broken = self.done[current]
                break
            if current in seen:
                broken = True
                break
            node = self.nodes.get(current)
            if node is None:
                broken = True
                break
            seen.add(current)
            chain.append(current)
            if not node[0]:
                break
            current = node[0]
        for node_id in reversed(chain):
            _, rank, name = self.nodes[node_id]
            step = f"{rank}:{name}"
            lineage = f"{lineage}|{step}" if lineage else step
            self.done[node_id] = (lineage, broken)
        return lineage, broken


def _usage_row(row, lineage):
    return (
        row.get("ID"), row.get("parentID") or None, row.get("status"), row.get("rank"),
        row.get("scientificName"), row.get("authorship") or None, row.get("code") or None,
        _flag(row.get("extinct")), row.get("environment") or None,
        row.get("temporalRangeStart") or None, row.get("temporalRangeEnd") or None,
        row.get("sourceID") or None, row.get("link") or None,
        row.get("taxGroup") or None, _flag(row.get("merged")), lineage,
    )


def _load_usages(archive, conn, summary):
    # First pass: a parent can appear after its children in the file.
    nodes = {}
    for row, complete in _read_tsv(archive, "NameUsage.tsv"):
        if complete and row["status"] in ACCEPTED_STATUSES:
            nodes[row["ID"]] = (row["parentID"], row["rank"], row["scientificName"])
    print(f"  {len(nodes):,} accepted taxa read; building lineages and writing rows", flush=True)

    lineages = _Lineages(nodes)
    insert = f"INSERT INTO name_usage VALUES ({','.join('?' * 16)})"
    batch = []
    t0 = time.monotonic()
    for row, complete in _read_tsv(archive, "NameUsage.tsv"):
        summary["usages"] += 1
        if not complete:
            summary["malformed_rows"] += 1
            lineage = None
        else:
            start = row["ID"] if row["status"] in ACCEPTED_STATUSES else row["parentID"]
            lineage, broken = lineages.of_taxon(start)
            summary["broken_lineages"] += broken
        batch.append(_usage_row(row, lineage))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(insert, batch)
            batch.clear()
        if summary["usages"] % PROGRESS_EVERY == 0:
            rate = summary["usages"] / (time.monotonic() - t0)
            print(f"  {summary['usages']:>10,} rows  [{rate:,.0f} rows/s]", flush=True)
    conn.executemany(insert, batch)


def _load_vernacular(archive, conn, summary):
    if "VernacularName.tsv" not in archive.namelist():
        return
    batch = []
    for row, _ in _read_tsv(archive, "VernacularName.tsv"):
        batch.append((
            row.get("taxonID"), row.get("name"), row.get("language") or "", row.get("country") or "",
            _flag(row.get("preferred")), _flag(row.get("merged")),
        ))
        summary["vernacular"] += 1
        if len(batch) >= BATCH_SIZE:
            conn.executemany("INSERT INTO vernacular VALUES (?,?,?,?,?,?)", batch)
            batch.clear()
    conn.executemany("INSERT INTO vernacular VALUES (?,?,?,?,?,?)", batch)


def _release_info(archive):
    """Top-level alias and version from metadata.yaml, for provenance."""
    if "metadata.yaml" not in archive.namelist():
        return {}
    text = archive.read("metadata.yaml").decode("utf-8", errors="replace")
    info = {}
    for key in ("alias", "version"):
        match = re.search(rf"^{key}:\s*(.+?)\s*$", text, re.MULTILINE)
        if match:
            info[key] = match.group(1).strip("'\"")
    return info


def import_release(zip_path, db_path):
    """Build db_path from a ColDP zip and return its summary counts. The database
    appears under its final name only once the import has completed."""
    if os.path.exists(db_path):
        raise FileExistsError(f"{db_path} already exists; refusing to overwrite it")
    partial = f"{db_path}.partial"
    if os.path.exists(partial):
        os.remove(partial)

    summary = {"usages": 0, "malformed_rows": 0, "broken_lineages": 0, "vernacular": 0}
    conn = sqlite3.connect(partial)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(SCHEMA)
        with zipfile.ZipFile(zip_path) as archive:
            _load_usages(archive, conn, summary)
            _load_vernacular(archive, conn, summary)
            meta = {
                **_release_info(archive),
                "source_file": Path(zip_path).name,
                "source_size": os.path.getsize(zip_path),
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **summary,
            }
        conn.executemany("INSERT INTO import_meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        print("  creating indexes", flush=True)
        conn.executescript(INDEXES)
        conn.commit()
    except BaseException:
        conn.close()
        os.remove(partial)
        raise
    conn.close()
    os.rename(partial, db_path)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Import a ColDP release into its own database")
    parser.add_argument("zip_path")
    parser.add_argument("db_path")
    args = parser.parse_args()
    t0 = time.monotonic()
    try:
        summary = import_release(args.zip_path, args.db_path)
    except FileExistsError as exc:
        sys.exit(f"ERROR: {exc}")
    print(f"Finished in {time.monotonic() - t0:,.0f} s")
    for key, value in summary.items():
        print(f"  {key}: {value:,}")


if __name__ == "__main__":
    main()
