"""
Request the two GBIF SQL occurrence downloads the app imports, check on them, and save them.

    ranges     per-species range edges (0.5% / 99.5% latitude and longitude percentiles)
               -> import_gbif_ranges.py
    countries  wild records per species per country -> import_gbif_countries.py

Usage (from the project root):
    python data/gbif_download.py ranges validate              # check the SQL, no account needed
    python data/gbif_download.py ranges submit [taxonKey]     # prints the download key
    python data/gbif_download.py ranges status <key>          # status, DOI, size
    python data/gbif_download.py ranges fetch <key> <out.zip> # save when SUCCEEDED
    (the same with "countries"; taxonKey limits a test run to one group, e.g. a family)

Both use wild observations only (no zoo, museum or fossil records), status DETECTED,
with coordinates and no geospatial issues, animals only. GBIF runs SQL downloads in its
own queue; a full run took a few hours in November 2026. Unzip the result into the data
folder and point the importer at the .csv with --csv. Cite the download's DOI when
you publish anything made from it.

Needs a free GBIF account: set GBIF_USER and GBIF_PASSWORD, or put
{"user": "...", "password": "..."} in <data dir>/gbif_credentials.json (outside the repo).
Credentials are never printed.

Notes from the original runs (2026-11-11/12):
- Taxa are filtered through occurrence.gbif_classification: the flat kingdomKey /
  familyKey / speciesKey columns matched nothing in SQL downloads.
- occurrencestatus is 'DETECTED', not 'PRESENT'.
- The countries query also counts records marked captive, released, vagrant and so on
  (n_excluded). GBIF marks only ~52k of 2.75 billion animal records that way, so the
  import doesn't use the column.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.paths import data_path  # noqa: E402

API = "https://api.gbif.org/v1/"
USER_AGENT = "AnimalKingdomApp/1.0"
_CLS = "occurrence.gbif_classification"
_WILD = (
    "occurrence.basisofrecord IN ('HUMAN_OBSERVATION','MACHINE_OBSERVATION') "
    "AND occurrence.occurrencestatus = 'DETECTED' AND occurrence.hascoordinate = TRUE "
    "AND occurrence.hasgeospatialissues = FALSE "
    f"AND GBIF_STRINGARRAYCONTAINS({_CLS}.taxonkeys, '1', TRUE) "   # 1 = Animalia
    f"AND {_CLS}.specieskey IS NOT NULL"
)


def _percentile(q: float, field: str) -> str:
    return f"PERCENTILE_CONT({q}) WITHIN GROUP (ORDER BY {field})"


def ranges_sql(taxon_key: str | None = None) -> str:
    extra = f" AND GBIF_STRINGARRAYCONTAINS({_CLS}.taxonkeys, '{int(taxon_key)}', TRUE)" if taxon_key else ""
    lat, lon = "occurrence.decimallatitude", "occurrence.decimallongitude"
    return (
        f"SELECT {_CLS}.specieskey AS specieskey, {_CLS}.species AS species, COUNT(*) AS n, "
        "COUNT(DISTINCT occurrence.countrycode) AS countries, "
        f"{_percentile(0.005, lat)} AS lat_min, {_percentile(0.995, lat)} AS lat_max, "
        f"{_percentile(0.005, lon)} AS lon_min, {_percentile(0.995, lon)} AS lon_max "
        f"FROM occurrence WHERE {_WILD}{extra} "
        f"GROUP BY {_CLS}.specieskey, {_CLS}.species"
    )


def countries_sql(taxon_key: str | None = None) -> str:
    extra = f" AND GBIF_STRINGARRAYCONTAINS({_CLS}.taxonkeys, '{int(taxon_key)}', TRUE)" if taxon_key else ""
    return (
        f"SELECT {_CLS}.specieskey AS specieskey, {_CLS}.species AS species, "
        "occurrence.countrycode AS countrycode, COUNT(*) AS n, "
        # Not living wild there: zoo / captive, released, escaped (casual, failing) or a
        # vagrant; established introduced populations (foxes in Australia) stay
        "SUM(CASE WHEN occurrence.degreeofestablishment.concept IN "
        "('captive','cultivated','released','failing','casual','managed') "
        "OR occurrence.establishmentmeans.concept = 'vagrant' THEN 1 ELSE 0 END) AS n_excluded "
        f"FROM occurrence WHERE {_WILD} AND occurrence.countrycode IS NOT NULL{extra} "
        f"GROUP BY {_CLS}.specieskey, {_CLS}.species, occurrence.countrycode"
    )


QUERIES = {"ranges": ranges_sql, "countries": countries_sql}


def credentials(environ=os.environ, creds_file: Path | None = None) -> tuple[str, str]:
    user, password = environ.get("GBIF_USER"), environ.get("GBIF_PASSWORD")
    if user and password:
        return user, password
    path = creds_file or data_path("gbif_credentials.json")
    try:
        c = json.loads(path.read_text(encoding="utf-8-sig"))
        return c["user"], c["password"]
    except (OSError, ValueError, KeyError):
        sys.exit(f"No GBIF account: set GBIF_USER and GBIF_PASSWORD, or create {path}")


def call(path: str, data: dict | None = None, auth: tuple[str, str] | None = None):
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        headers["Authorization"] = "Basic " + token
    req = urllib.request.Request(
        API + path, data=json.dumps(data).encode() if data is not None else None,
        headers=headers, method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[0] not in QUERIES:
        sys.exit(__doc__)
    query, cmd, rest = QUERIES[argv[0]], argv[1], argv[2:]
    if cmd == "validate":
        code, body = call("occurrence/download/request/validate",
                          {"format": "SQL_TSV_ZIP", "sql": query(rest[0] if rest else None)})
        print(code, body.decode()[:300])
    elif cmd == "submit":
        auth = credentials()
        code, body = call("occurrence/download/request",
                          {"sendNotification": False, "format": "SQL_TSV_ZIP",
                           "sql": query(rest[0] if rest else None), "creator": auth[0]},
                          auth=auth)
        print(code, body.decode()[:300])
    elif cmd == "status" and rest:
        code, body = call(f"occurrence/download/{rest[0]}")
        d = json.loads(body)
        print(code, {k: d.get(k) for k in ("status", "doi", "totalRecords", "size", "created", "modified")})
    elif cmd == "fetch" and len(rest) == 2:
        code, body = call(f"occurrence/download/request/{rest[0]}.zip")
        if code == 200:
            Path(rest[1]).write_bytes(body)
            print("saved", len(body), "bytes")
        else:
            print(code, body[:300])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
