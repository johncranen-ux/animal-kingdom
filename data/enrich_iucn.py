"""
Enrich species records with IUCN Red List conservation status.

Uses the IUCN Red List API v4.  Token can be supplied via:
  1. .env file in the project root:  IUCN_API_TOKEN=your_token
  2. Environment variable:           IUCN_API_TOKEN=your_token
  3. CLI flag:                       --token YOUR_TOKEN

Strategy — bulk category sweep (fast):
  For each Red List category (CR, EN, VU, NT, LC, DD, EW, EX, …) the API
  returns all latest assessments paginated at 100/page.  A single sweep
  covers all IUCN-assessed species in ~1,700 API calls (~15 min).

  Optional second pass (--fetch-trends) fetches population_trend from the
  individual assessment endpoint for every species that matched our DB.

Usage:
    python data/enrich_iucn.py
    python data/enrich_iucn.py --fetch-trends
    python data/enrich_iucn.py --missing-trends     # only species with no trend yet
    python data/enrich_iucn.py --token YOUR_TOKEN --no-verify-ssl
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.paths import data_path  # noqa: E402
from app import database

IUCN_BASE  = "https://api.iucnredlist.org/api/v4"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_DELAY   = 0.5   # seconds between calls
PAGE_SIZE       = 100   # items per page (fixed by API)
CHECKPOINT_FILE = str(data_path("iucn_checkpoint.json"))

# All current IUCN Red List category codes
CATEGORIES = ["EX", "EW", "CR", "EN", "VU", "NT", "LC", "DD"]

# population_trend code → human-readable (verified against API v4 responses
# 2026-11-03; an earlier map was off by one and stored Unknown as Increasing)
TREND_MAP = {"0": "Increasing", "1": "Decreasing", "2": "Stable", "3": "Unknown"}


def _trend(trend_obj: dict) -> str | None:
    """Prefer the API's own English label; fall back to the code map."""
    label = ((trend_obj.get("description") or {}).get("en") or "").strip().capitalize()
    if label in TREND_MAP.values():
        return label
    return TREND_MAP.get(str(trend_obj.get("code", "")).strip())

_VALID_STATUSES = set(CATEGORIES) | {"NE", "LR/lc", "LR/nt", "LR/cd"}


def _read_token_from_env_file() -> str | None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("IUCN_API_TOKEN="):
            return line[len("IUCN_API_TOKEN="):].strip().strip('"').strip("'")
    return None


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get(url: str, token: str, ctx: ssl.SSLContext, retries: int = 4) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": token,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    wait = 10
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                return json.loads(r.read())
        except urllib.request.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429:
                if attempt < retries:
                    print(f"    429 rate-limit — retrying in {wait}s …", flush=True)
                    time.sleep(wait)
                    wait = min(wait * 2, 120)
                    continue
                print(f"    429 rate-limit — max retries exhausted, skipping.", flush=True)
                return None
            raise
        except Exception:
            return None
    return None


def _load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"done_categories": [], "matched": {}}


def _save_checkpoint(cp: dict) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f)


# ── Phase 1: bulk category sweep ─────────────────────────────────────────────

def sweep_categories(token: str, ctx: ssl.SSLContext, no_verify: bool) -> None:
    cp   = _load_checkpoint()
    conn = database.get_connection()

    done_cats = set(cp.get("done_categories", []))
    matched   = cp.get("matched", {})   # scientific_name -> assessment_id

    total_updated = 0

    for cat in CATEGORIES:
        if cat in done_cats:
            print(f"  [{cat}] already done — skipping")
            continue

        page    = 1   # API is 1-indexed
        cat_upd = 0
        cat_tot = 0

        while True:
            url  = f"{IUCN_BASE}/red_list_categories/{cat}?page={page}&latest=true"
            data = _get(url, token, ctx)
            time.sleep(REQUEST_DELAY)

            if not data:
                break
            assessments = data.get("assessments", [])
            if not assessments:
                break

            cat_tot += len(assessments)

            for a in assessments:
                sci  = a.get("taxon_scientific_name", "").strip()
                code = a.get("red_list_category_code", "").strip()
                aid  = a.get("assessment_id")

                if not sci or code not in _VALID_STATUSES:
                    continue

                exists = conn.execute(
                    "SELECT 1 FROM species WHERE scientific_name = ?", (sci,)
                ).fetchone()
                if not exists:
                    continue

                conn.execute(
                    "UPDATE species SET iucn_status = ? WHERE scientific_name = ?",
                    (code, sci),
                )
                cat_upd += 1
                if aid:
                    matched[sci] = aid

            conn.commit()
            page += 1

        done_cats.add(cat)
        cp["done_categories"] = sorted(done_cats)
        cp["matched"]         = matched
        _save_checkpoint(cp)
        total_updated += cat_upd
        print(f"  [{cat}]  pages={page}  records={cat_tot}  db_matches={cat_upd}", flush=True)

    conn.close()
    print(f"\nPhase 1 done.  Total DB updates: {total_updated:,}  "
          f"Matched for trend lookup: {len(matched):,}\n")


# ── Phase 2: per-assessment trend lookup ─────────────────────────────────────

PHASE2_COMMIT_EVERY = 100   # commit frequently to release write lock for other writers

def fetch_trends(token: str, ctx: ssl.SSLContext) -> None:
    cp      = _load_checkpoint()
    matched = cp.get("matched", {})
    if not matched:
        print("No matched species found — run Phase 1 first.")
        return

    start_pos = cp.get("phase2_pos", 0)
    conn      = database.get_connection()
    updated   = errors = 0
    items     = list(matched.items())
    total     = len(items)
    print(f"Fetching population trends for {total:,} matched species …")
    if start_pos:
        print(f"  Resuming from position {start_pos:,} ({start_pos/total*100:.1f}%)\n")
    else:
        print()

    for i, (sci, aid) in enumerate(items):
        if i < start_pos:
            continue

        url  = f"{IUCN_BASE}/assessment/{aid}"
        data = _get(url, token, ctx)
        time.sleep(REQUEST_DELAY)

        if not data:
            errors += 1
        else:
            trend = _trend(data.get("population_trend") or {})

            if trend:
                conn.execute(
                    "UPDATE species SET population_trend = ? WHERE scientific_name = ?",
                    (trend, sci),
                )
                updated += 1

        if (i + 1) % PHASE2_COMMIT_EVERY == 0:
            conn.commit()
            cp["phase2_pos"] = i + 1
            _save_checkpoint(cp)
            pct = (i + 1) / total * 100
            print(f"  {i+1:>7,}/{total:,} ({pct:.1f}%)  "
                  f"updated={updated:,}  errors={errors:,}", flush=True)

    conn.commit()
    cp["phase2_pos"] = total   # mark fully done
    _save_checkpoint(cp)
    conn.close()
    print(f"\nPhase 2 done.  Trends updated: {updated:,}  Errors: {errors:,}\n")


def fetch_missing_trends(token: str, ctx: ssl.SSLContext) -> None:
    """Re-fetch population_trend for matched species whose trend is still NULL.

    Selects from the DB each run, so it is safely re-runnable without a checkpoint.
    """
    matched = _load_checkpoint().get("matched", {})
    conn    = database.get_connection()
    missing = {r[0] for r in conn.execute(
        "SELECT scientific_name FROM species "
        "WHERE iucn_status IS NOT NULL AND population_trend IS NULL"
    )}
    items   = [(sci, aid) for sci, aid in matched.items() if sci in missing]
    total   = len(items)
    updated = errors = 0
    print(f"Fetching population trends for {total:,} species with no trend …\n")

    for i, (sci, aid) in enumerate(items):
        data = _get(f"{IUCN_BASE}/assessment/{aid}", token, ctx)
        time.sleep(REQUEST_DELAY)
        if not data:
            errors += 1
        else:
            trend = _trend(data.get("population_trend") or {})
            if trend:
                conn.execute(
                    "UPDATE species SET population_trend = ? WHERE scientific_name = ?",
                    (trend, sci),
                )
                updated += 1
        if (i + 1) % PHASE2_COMMIT_EVERY == 0:
            conn.commit()
            print(f"  {i+1:>7,}/{total:,} ({(i+1)/total*100:.1f}%)  "
                  f"updated={updated:,}  errors={errors:,}", flush=True)

    conn.commit()
    conn.close()
    print(f"\nMissing-trend pass done.  Trends updated: {updated:,}  Errors: {errors:,}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich species with IUCN Red List status (API v4)"
    )
    parser.add_argument(
        "--token", default=None,
        help="IUCN API v4 token (falls back to IUCN_API_TOKEN in .env or environment)",
    )
    parser.add_argument(
        "--fetch-trends", action="store_true",
        help="Phase 2: fetch population_trend for matched species (slower, ~0.5 s/species)",
    )
    parser.add_argument(
        "--missing-trends", action="store_true",
        help="Re-fetch population_trend only for matched species where it is NULL",
    )
    parser.add_argument("--no-verify-ssl", action="store_true")
    args = parser.parse_args()

    token = (
        args.token
        or os.environ.get("IUCN_API_TOKEN")
        or _read_token_from_env_file()
    )
    if not token:
        print(
            "ERROR: no IUCN token found.\n"
            "  Option 1 — add to .env:          IUCN_API_TOKEN=your_token\n"
            "  Option 2 — pass on command line: --token YOUR_TOKEN\n"
            "  Get a free token at: https://api.iucnredlist.org"
        )
        sys.exit(1)

    ctx = _make_ssl_context(args.no_verify_ssl)

    if args.missing_trends:
        print("=== Phase 2b: missing population trends ===\n")
        fetch_missing_trends(token, ctx)
    elif args.fetch_trends:
        print("=== Phase 2: population trend lookup ===\n")
        fetch_trends(token, ctx)
    else:
        print("=== Phase 1: IUCN category sweep ===\n")
        sweep_categories(token, ctx, args.no_verify_ssl)
        print("Run again with --fetch-trends to populate population_trend.\n")


if __name__ == "__main__":
    main()
