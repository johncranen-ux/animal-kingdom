"""
Enrich species records with Wikipedia abstracts and thumbnail image URLs.

Uses the Wikipedia REST API (no token required). Respects a conservative
rate limit to avoid being blocked.

Usage:
    python data/enrich_wikipedia.py
    python data/enrich_wikipedia.py --batch-size 10000 --no-verify-ssl
    python data/enrich_wikipedia.py --only-with-common-names --animals-only --batch-size 200000

Stop it any time (Ctrl+C or end the process) and run the same command again to
resume: species that got an abstract drop out of the selection.
A Wikipedia thumbnail only fills a species that has no image yet.

Progress is checkpointed to <data dir>/wikipedia_checkpoint.json.
The checkpoint records only confirmed successes and confirmed 404s.
Transient failures (429, timeouts) are NOT checkpointed, so they are retried
on the next run.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.paths import data_path  # noqa: E402
from app import database

WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary"
CHECKPOINT_FILE = str(data_path("wikipedia_checkpoint.json"))
REQUEST_DELAY = 0.5   # ~2 req/s — stays well under Wikipedia's 200 req/s limit
RETRY_DELAY   = 60    # seconds to wait after a 429
MAX_RETRIES   = 3
# Wikimedia's User-Agent policy asks for contact details and throttles anonymous
# clients hard (2026-11-11: 14 rate limits in 20 min without them). The user
# approved sending their address to Wikipedia only.
USER_AGENT = (
    "AnimalKingdomApp/1.0 (educational offline app; contact "
    + os.environ.get("AK_CONTACT_EMAIL", "add-your-email@example.com") + ")"
)


def _load_checkpoint() -> set[str]:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return set(json.load(f))
    return set()


def _save_checkpoint(done: set[str]) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(sorted(done), f)


def _make_ssl_context(no_verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if no_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SENTINEL_NOT_FOUND = object()   # confirmed 404/disambiguation
_SENTINEL_TRANSIENT  = object()  # rate-limit or network error — do NOT checkpoint


def _fetch_summary(name: str, ctx: ssl.SSLContext):
    """Return a dict on success, _SENTINEL_NOT_FOUND for genuine 404/disambiguation,
    or _SENTINEL_TRANSIENT for errors that should be retried."""
    url = f"{WIKIPEDIA_API}/{urllib.parse.quote(name)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                data = json.loads(resp.read())
            if data.get("type") in ("disambiguation", "no-extract"):
                return _SENTINEL_NOT_FOUND
            abstract = data.get("extract") or None
            image_url = (data.get("thumbnail") or {}).get("source") or None
            attribution = data.get("content_urls", {}).get("desktop", {}).get("page") or None
            return {"abstract": abstract, "image_url": image_url, "attribution": attribution}

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return _SENTINEL_NOT_FOUND
            if e.code == 429:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"\n  [429] rate-limited — waiting {wait}s …", flush=True)
                time.sleep(wait)
                continue   # retry
            # Other HTTP errors (5xx etc.) — treat as transient
            return _SENTINEL_TRANSIENT

        except Exception:
            return _SENTINEL_TRANSIENT

    # All retries exhausted after 429s
    return _SENTINEL_TRANSIENT


def select_names(conn, batch_size: int, only_with_common_names: bool, animals_only: bool) -> list[str]:
    """Accepted species without an abstract, in table order."""
    extra = ""
    if only_with_common_names:
        extra += " AND common_names IS NOT NULL AND common_names != '[]' AND common_names != ''"
    if animals_only:
        extra += " AND taxon_path LIKE 'Animalia|%'"
    rows = conn.execute(
        f"""
        SELECT scientific_name FROM species
        WHERE taxonomic_status = 'ACCEPTED'
          AND taxon_rank = 'species'
          AND wikipedia_abstract IS NULL
          {extra}
        LIMIT ?
        """,
        (batch_size,),
    ).fetchall()
    return [r[0] for r in rows]


def save_result(conn, name: str, result: dict) -> None:
    """Write the abstract; the thumbnail only fills a species that has no image yet."""
    conn.execute(
        """
        UPDATE species
        SET wikipedia_abstract = ?,
            image_attribution = CASE WHEN primary_image_url IS NULL AND ? IS NOT NULL
                                     THEN ? ELSE image_attribution END,
            primary_image_url = COALESCE(primary_image_url, ?)
        WHERE scientific_name = ?
        """,
        (result["abstract"], result["image_url"], result["attribution"], result["image_url"], name),
    )
    conn.commit()


def enrich(batch_size: int, no_verify_ssl: bool, only_with_common_names: bool,
           delay: float = REQUEST_DELAY, animals_only: bool = False) -> None:
    ctx = _make_ssl_context(no_verify_ssl)
    done = _load_checkpoint()
    conn = database.get_connection()
    rows = select_names(conn, batch_size, only_with_common_names, animals_only)

    total = len(rows)
    print(f"Processing {total:,} species without Wikipedia abstract")
    print(f"({len(done):,} already checkpointed from previous runs)\n")
    updated = no_article = skipped = transient = 0

    for i, name in enumerate(rows):
        if name in done:
            skipped += 1
            continue

        result = _fetch_summary(name, ctx)

        if result is _SENTINEL_TRANSIENT:
            # Do NOT add to checkpoint — will be retried next run
            transient += 1
        elif result is _SENTINEL_NOT_FOUND:
            no_article += 1
            done.add(name)   # confirmed miss — no point retrying
        elif result and result["abstract"]:
            save_result(conn, name, result)
            updated += 1
            done.add(name)
        else:
            # Got a response but no extract text (rare edge case)
            no_article += 1
            done.add(name)

        if (i + 1) % 1_000 == 0:
            _save_checkpoint(done)
            pct = (i + 1) / total * 100
            print(
                f"  {i+1:>7,}/{total:,}  ({pct:.1f}%)  "
                f"updated={updated:,}  no_article={no_article:,}  transient_err={transient:,}",
                flush=True,
            )
        time.sleep(delay)

    _save_checkpoint(done)
    conn.close()
    print(
        f"\nDone. Updated: {updated:,}  No article: {no_article:,}  "
        f"Transient errors (will retry): {transient:,}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich species with Wikipedia abstracts and images"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100_000,
        help="Max species to process per run (default: 100000)",
    )
    parser.add_argument("--no-verify-ssl", action="store_true")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY,
        help=f"Seconds between requests (default: {REQUEST_DELAY})",
    )
    parser.add_argument(
        "--only-with-common-names",
        action="store_true",
        help="Only enrich species that already have at least one common name recorded",
    )
    parser.add_argument(
        "--animals-only",
        action="store_true",
        help="Only enrich species in Animalia",
    )
    args = parser.parse_args()
    enrich(args.batch_size, args.no_verify_ssl, args.only_with_common_names, args.delay,
           animals_only=args.animals_only)


if __name__ == "__main__":
    main()
