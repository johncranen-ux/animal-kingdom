"""Image lookup helpers — 4-source chain used by both the species panel endpoint
and the LLM chat agent, plus a wide mode (the panel's "Search again") that also
tries an old name's current name and GBIF occurrence photos."""

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

_IMG_USER_AGENT = "AnimalKingdomApp/1.0 (educational offline project)"
_ssl_ctx = ssl.create_default_context()


class _SourceDown(Exception):
    """A source didn't answer (timeout, rate limit, server error): not a real miss."""


class ImagesUnavailable(Exception):
    """No picture found, and at least one source was down: don't record "no picture"."""


def _http_get(url: str) -> dict | None:
    """JSON from url; None when the source says the page doesn't exist (a 4xx
    other than 429); _SourceDown when it didn't answer properly."""
    req = urllib.request.Request(url, headers={"User-Agent": _IMG_USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 429:
            return None
        raise _SourceDown(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise _SourceDown(str(exc)) from exc


_WIKIMEDIA_FILE = re.compile(
    r"//(?:upload|thumb)\.wikimedia\.org/wikipedia/([^/]+)/(?:thumb/)?([0-9a-f]/[0-9a-f]{2}/[^/?#]+)")
_INATURALIST_PHOTO = re.compile(
    r"//(?:inaturalist-open-data\.s3\.amazonaws\.com|static\.inaturalist\.org)/photos/(\d+)/")


def picture_key(url: str) -> str:
    """One key per photo whatever its size: a Wikipedia thumbnail and the Commons
    original of one file, or iNaturalist's square/medium/original of one photo."""
    if m := _WIKIMEDIA_FILE.search(url or ""):
        return f"wikimedia:{m.group(1)}/{urllib.parse.unquote(m.group(2))}"
    if m := _INATURALIST_PHOTO.search(url or ""):
        return f"inaturalist:{m.group(1)}"
    return url


def _plain(name: str) -> str:
    """The name without a homonym key's " [Parent]" suffix."""
    return name.split(" [", 1)[0].strip()


def _wikipedia_image(scientific_name: str, must_mention: tuple[str, ...] = ()) -> tuple[str, str] | None:
    """Wikipedia REST summary thumbnail. With must_mention, the article's summary
    must name one of those taxa — otherwise it is about something else."""
    title = urllib.parse.quote(scientific_name.replace(" ", "_"))
    data  = _http_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
    if not data:
        return None
    if must_mention:
        extract = (data.get("extract") or "").lower()
        if not any(t.lower() in extract for t in must_mention):
            return None
    thumb = data.get("thumbnail") or {}
    src   = thumb.get("source")
    return (src, "© Wikipedia contributors (CC BY-SA)") if src else None


# Catalogue of Life ranks iNaturalist doesn't use: any iNaturalist rank may match
_ANY_RANK = {"unranked", "other", "infraspecific name"}


def _inaturalist_images(scientific_name: str, rank: str = "species",
                        limit: int = 4) -> list[tuple[str, str]]:
    """iNaturalist taxa API: exact name and the same rank (subspecies and higher
    ranks too; the rank keeps a same-named taxon of another rank out). The default
    photo, then (limit > 1) the taxon's other photos from /v1/taxa/{id}."""
    q    = urllib.parse.quote(scientific_name)
    data = _http_get(f"https://api.inaturalist.org/v1/taxa?q={q}&per_page=10")
    if not data:
        return []
    wanted = (rank or "species").lower()
    for taxon in data.get("results", []):
        if taxon.get("name", "").lower() != scientific_name.lower():
            continue
        if wanted not in _ANY_RANK and (taxon.get("rank") or "").lower() != wanted:
            continue
        photos = [taxon.get("default_photo") or {}]
        if limit > 1 and taxon.get("id"):
            detail = _http_get(f"https://api.inaturalist.org/v1/taxa/{taxon['id']}") or {}
            for t in detail.get("results", [])[:1]:
                photos += [tp.get("photo") or {} for tp in t.get("taxon_photos") or []]
        found: list[tuple[str, str]] = []
        for photo in photos:
            url = photo.get("medium_url") or photo.get("square_url")
            if url and url not in {u for u, _ in found}:
                found.append((url, photo.get("attribution") or "© iNaturalist contributors"))
        if found:
            return found[:limit]
    return []


def _inaturalist_image(scientific_name: str, rank: str = "species") -> tuple[str, str] | None:
    found = _inaturalist_images(scientific_name, rank, limit=1)
    return found[0] if found else None


def _wikimedia_images(scientific_name: str, must_name: str | None = None,
                      limit: int = 3) -> list[tuple[str, str]]:
    """Wikimedia Commons: full-text search, then the top hits whose
    title or categories name every word of `must_name` (default: the query; a
    one-word name is searched with an ancestor but only the name must match). Full-text search also
    matches long descriptions listing many animals: "Tapirus malayanus" found a
    Sumatran elephant photo whose caption lists the park's wildlife."""
    q = urllib.parse.quote(scientific_name)
    srlimit = 3 if limit <= 1 else 10
    search_data = _http_get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&list=search&srsearch={q}&srnamespace=6&srlimit={srlimit}&format=json"
    )
    if not search_data:
        return []
    titles = [r.get("title") for r in search_data.get("query", {}).get("search", []) if r.get("title")]
    if not titles:
        return []
    info_data = _http_get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote('|'.join(titles))}"
        f"&prop=imageinfo&iiprop=url|extmetadata|mediatype&iiurlwidth=800&format=json"
    )
    if not info_data:
        return []
    pages = {p.get("title"): p for p in info_data.get("query", {}).get("pages", {}).values()}
    words = (must_name or scientific_name).lower().split()
    _IMAGE_MEDIATYPES = {"BITMAP", "DRAWING"}
    found: list[tuple[str, str]] = []
    for title in titles:                       # search-rank order
        infos = (pages.get(title) or {}).get("imageinfo", [])
        if not infos:
            continue
        info = infos[0]
        if info.get("mediatype") not in _IMAGE_MEDIATYPES:
            continue
        url  = info.get("url")
        if not url:
            continue
        meta  = info.get("extmetadata", {})
        about = f"{title} {meta.get('Categories', {}).get('value', '')}".lower()
        about = re.sub(r"[-_+|/%]", " ", about)
        if not all(w in about for w in words):
            continue
        artist       = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        attribution  = f"© {artist} ({license_name})" if artist else license_name or "© Wikimedia Commons contributors"
        found.append((url, attribution))
        if len(found) >= limit:
            break
    return found


def _wikimedia_image(scientific_name: str, must_name: str | None = None) -> tuple[str, str] | None:
    found = _wikimedia_images(scientific_name, must_name, limit=1)
    return found[0] if found else None


def _duckduckgo_images(
    scientific_name: str,
    common_names: list[str] | None = None,
    limit: int = 3,
) -> list[tuple[str, str]]:
    """DuckDuckGo image search via ddgs package (unofficial, rate-limit aware)."""
    _WEB_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    queries = [scientific_name]
    if common_names:
        queries.append(common_names[0])
    found: list[tuple[str, str]] = []
    for query in queries:
        try:
            for r in DDGS().images(query, max_results=10):
                url = r.get("image") or ""
                ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
                if f".{ext}" not in _WEB_IMAGE_EXTS:
                    continue
                # Web search matches loosely ("ramsayi" alone finds a snake):
                # every word of the query must be in the title or page URL
                about = f"{r.get('title') or ''} {r.get('url') or ''}".lower()
                about = re.sub(r"[-_+/%]", " ", about)
                if not all(w in about for w in query.lower().split()):
                    continue
                if url in {u for u, _ in found}:
                    continue
                source = r.get("source") or r.get("url") or "DuckDuckGo"
                found.append((url, f"Source: {source}"))
                if len(found) >= limit:
                    return found
        except Exception:
            continue
    return found


def _duckduckgo_image(
    scientific_name: str,
    common_names: list[str] | None = None,
) -> tuple[str, str] | None:
    found = _duckduckgo_images(scientific_name, common_names, limit=1)
    return found[0] if found else None


def _licence(value: str | None) -> str:
    """Short licence name from a Creative Commons URL ("CC BY-NC 4.0", "CC0")."""
    v = (value or "").strip()
    m = re.search(r"creativecommons\.org/licenses/([a-z-]+)/([\d.]+)", v, re.I)
    if m:
        return f"CC {m.group(1).upper()} {m.group(2)}"
    if re.search(r"creativecommons\.org/publicdomain/zero", v, re.I):
        return "CC0"
    return v


def _gbif_images(scientific_name: str, limit: int = 3) -> list[tuple[str, str]]:
    """Photos attached to GBIF occurrence records of the name (GBIF matches the
    name, synonyms included), one per record: living animals (HUMAN_OBSERVATION)
    first, then museum specimens, labelled as such."""
    q = urllib.parse.quote(_plain(scientific_name))
    data = _http_get(f"https://api.gbif.org/v1/occurrence/search"
                     f"?scientificName={q}&mediaType=StillImage&limit=20")
    if not data:
        return []
    living: list[tuple[str, str]] = []
    specimens: list[tuple[str, str]] = []
    seen: set[str] = set()
    for record in data.get("results", []):
        for media in record.get("media") or []:
            url = media.get("identifier")
            fmt = media.get("format") or "image/"
            if media.get("type") != "StillImage" or not url or not fmt.startswith("image/"):
                continue
            # iNaturalist originals can be several MB; its medium size is what the
            # iNaturalist source returns, so the same photo also dedupes
            if "inaturalist-open-data" in url:
                url = url.replace("/original.", "/medium.")
            if url in seen:
                break
            seen.add(url)
            who = (media.get("creator") or media.get("rightsHolder") or record.get("rightsHolder")
                   or "GBIF contributors")
            licence = _licence(media.get("license") or record.get("license"))
            attribution = f"© {who} ({licence}) via GBIF" if licence else f"© {who} via GBIF"
            if record.get("basisOfRecord") == "HUMAN_OBSERVATION":
                living.append((url, attribution))
            else:
                specimens.append((url, f"{attribution} (museum specimen)"))
            break   # one photo per record is enough
    return (living + specimens)[:limit]


def _gbif_image(scientific_name: str) -> tuple[str, str] | None:
    """A GBIF record photo: a living animal first, otherwise a museum specimen."""
    found = _gbif_images(scientific_name, limit=1)
    return found[0] if found else None


def fetch_image(
    scientific_name: str,
    common_names: list[str] | None = None,
    taxon_path: str | None = None,
    *,
    rank: str | None = None,
    wide: bool = False,
    current_name: str | None = None,
    current_path: str | None = None,
    current_rank: str | None = None,
    exclude: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, str] | None:
    """Run the 4-source chain. Returns (url, attribution) or None.

    A one-word name (genus and up) is often also an everyday word or another
    animal's name ("Zebra" is a snail genus), so with a taxon_path the Wikipedia
    article must name an ancestor and the fuzzy searches are qualified by one.

    `wide` (the panel's "Search again"): after the four sources, the same four for
    `current_name` (an old name's accepted name, with its own lineage and rank:
    `current_path`, `current_rank`), then GBIF occurrence photos.
    Raises ImagesUnavailable when nothing was found and Wikipedia, iNaturalist,
    Commons or GBIF didn't answer; DuckDuckGo errors stay misses (it rate-limits often).
    `exclude`: pictures the user replaced; a hit on one counts as that source's miss.
    """
    down: list[str] = []
    excluded = {picture_key(u) for u in exclude}

    def ask(source, *args):
        try:
            found = source(*args)
        except _SourceDown:
            down.append(getattr(source, "__name__", "source"))
            return None
        return None if found and picture_key(found[0]) in excluded else found

    result = _chain(_plain(scientific_name), common_names, taxon_path, rank, ask)
    if not result and wide and current_name:
        found = _chain(_plain(current_name), None, current_path, current_rank or rank, ask)
        if found:
            result = (found[0], f"{found[1]} (picture of {_plain(current_name)})")
    if not result and wide:
        result = ask(_gbif_image, scientific_name)
    if not result and down:
        raise ImagesUnavailable(", ".join(down))
    return result


def _chain(name: str, common_names, taxon_path, rank, ask) -> tuple[str, str] | None:
    """The four sources in order; `ask` records a source that is down."""
    ancestors = tuple(t for t in (taxon_path or "").split("|")[1:]
                      if t and _plain(t) != name)
    if " " in name or not ancestors:
        result = ask(_wikipedia_image, name)
        query  = name
    else:
        result = ask(lambda n: _wikipedia_image(n, must_mention=ancestors), name)
        query  = f"{name} {_plain(ancestors[-1])}"
    if result:
        return result
    result = ask(lambda n: _inaturalist_image(n, rank=rank or "species"), name)
    if result:
        return result
    result = ask(lambda q: _wikimedia_image(q, must_name=name), query)
    if result:
        return result
    def duckduckgo(q, names):
        try:
            return _duckduckgo_image(q, names)
        except _SourceDown:   # DuckDuckGo errors stay misses: it rate-limits often
            return None
    return ask(duckduckgo, query, common_names)


# ── "Other pictures": candidates from every source at once ────────────────────

CANDIDATES_DEADLINE_S = 10.0   # the gallery shows what answered by then
_SOURCE_LIMITS = (("Wikipedia", 1), ("iNaturalist", 4), ("Commons", 3), ("GBIF", 3), ("DuckDuckGo", 3))


def _source_lists(name: str, common_names, taxon_path, rank, full: bool) -> dict:
    """Callables per source for one name; `full` = all five, else Wikipedia + iNaturalist."""
    ancestors = tuple(t for t in (taxon_path or "").split("|")[1:] if t and _plain(t) != name)
    if " " in name or not ancestors:
        wiki = lambda: _wikipedia_image(name)
        query = name
    else:
        wiki = lambda: _wikipedia_image(name, must_mention=ancestors)
        query = f"{name} {_plain(ancestors[-1])}"
    lists = {
        "Wikipedia": lambda: [r for r in [wiki()] if r],
        "iNaturalist": lambda: _inaturalist_images(name, rank=rank or "species", limit=4),
    }
    if full:
        lists["Commons"] = lambda: _wikimedia_images(query, must_name=name, limit=3)
        lists["GBIF"] = lambda: _gbif_images(name, limit=3)
        lists["DuckDuckGo"] = lambda: _duckduckgo_images(query, common_names, limit=3)
    return lists


def image_candidates(
    scientific_name: str,
    common_names: list[str] | None = None,
    taxon_path: str | None = None,
    *,
    rank: str | None = None,
    current_name: str | None = None,
    current_path: str | None = None,
    current_rank: str | None = None,
    exclude: frozenset[str] | set[str] = frozenset(),
    limit: int = 12,
    deadline: float = CANDIDATES_DEADLINE_S,
) -> tuple[list[dict], bool]:
    """Pictures to choose from: [{url, attribution, source}] in source order
    (Wikipedia, iNaturalist, Commons, GBIF, DuckDuckGo; then an old name's current
    name from Wikipedia and iNaturalist, "(picture of …)"), deduped, without
    `exclude`, at most `limit`. All sources are asked at once; one still busy after
    `deadline` seconds is left out. The bool is True when a source didn't answer or
    was too slow (DuckDuckGo errors and slowness stay misses)."""
    from concurrent.futures import ThreadPoolExecutor, wait

    jobs = [(src, "", fn) for src, fn in
            _source_lists(_plain(scientific_name), common_names, taxon_path, rank, True).items()]
    if current_name:
        cur = _plain(current_name)
        jobs += [(src, f" (picture of {cur})", fn) for src, fn in
                 _source_lists(cur, None, current_path, current_rank or rank, False).items()]

    def run(fn):
        try:
            return fn() or [], False
        except _SourceDown:
            return [], True

    # not a `with` block: that would wait for the slow sources after all
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    futures = [pool.submit(run, fn) for _, _, fn in jobs]
    wait(futures, timeout=deadline)
    pool.shutdown(wait=False, cancel_futures=True)   # a late source finishes on its own
    results = [f.result() if f.done() else ([], True) for f in futures]

    candidates: list[dict] = []
    seen = {picture_key(u) for u in exclude}
    down = False
    for (src, suffix, _), (found, failed) in zip(jobs, results):
        down = down or (failed and src != "DuckDuckGo")
        for url, attribution in found:
            if picture_key(url) in seen:
                continue
            seen.add(picture_key(url))
            candidates.append({"url": url, "attribution": f"{attribution}{suffix}", "source": src})
    return candidates[:limit], down
