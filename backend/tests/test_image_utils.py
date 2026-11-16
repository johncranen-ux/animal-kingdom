"""Unit tests for image_utils — 4-source image lookup chain."""

import sys
import types
import pytest
from app import image_utils


def test_fetch_image_returns_wikipedia_result(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image',
        lambda name: ('https://upload.wikimedia.org/img.jpg', '© Wikipedia contributors (CC BY-SA)'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://upload.wikimedia.org/img.jpg', '© Wikipedia contributors (CC BY-SA)')


def test_fetch_image_stops_at_first_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(image_utils, '_wikipedia_image',
        lambda name: ('https://wiki.org/img.jpg', '© Wikipedia'))
    monkeypatch.setattr(image_utils, '_inaturalist_image',
        lambda name: calls.append('inat') or None)
    result = image_utils.fetch_image('Apis mellifera')
    assert result[0] == 'https://wiki.org/img.jpg'
    assert 'inat' not in calls   # inat was not reached


def test_fetch_image_falls_through_to_wikimedia(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name, rank='species': None)
    monkeypatch.setattr(image_utils, '_wikimedia_image',
        lambda name, must_name=None: ('https://commons.wikimedia.org/img.jpg', '© Jane Doe (CC BY-SA 4.0)'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://commons.wikimedia.org/img.jpg', '© Jane Doe (CC BY-SA 4.0)')


def test_fetch_image_falls_through_to_duckduckgo(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name, rank='species': None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name, must_name=None: None)
    monkeypatch.setattr(image_utils, '_duckduckgo_image',
        lambda name, common_names=None: ('https://example.com/bee.jpg', 'Source: example.com'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://example.com/bee.jpg', 'Source: example.com')


def test_fetch_image_passes_common_names_to_duckduckgo(monkeypatch):
    received = {}
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name, rank='species': None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name, must_name=None: None)
    def capture_ddg(name, common_names=None):
        received['common_names'] = common_names
        return None
    monkeypatch.setattr(image_utils, '_duckduckgo_image', capture_ddg)
    image_utils.fetch_image('Apis mellifera', common_names=['Honey bee'])
    assert received['common_names'] == ['Honey bee']


def test_fetch_image_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name, rank='species': None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name, must_name=None: None)
    monkeypatch.setattr(image_utils, '_duckduckgo_image',
        lambda name, common_names=None: None)
    result = image_utils.fetch_image('Unknown xyz 99999')
    assert result is None


def test_wikimedia_image_returns_none_when_no_search_results(monkeypatch):
    def fake_http_get(url):
        if 'list=search' in url:
            return {'query': {'search': []}}
        return None
    monkeypatch.setattr(image_utils, '_http_get', fake_http_get)
    result = image_utils._wikimedia_image('Unknown xyz 99999')
    assert result is None


def test_wikimedia_image_returns_none_when_http_fails(monkeypatch):
    monkeypatch.setattr(image_utils, '_http_get', lambda url: None)
    result = image_utils._wikimedia_image('Apis mellifera')
    assert result is None


def test_duckduckgo_image_returns_none_when_ddgs_not_installed(monkeypatch):
    # Setting sys.modules['ddgs'] = None makes Python raise ImportError on import,
    # even when the package is physically installed (popping alone allows reimport).
    monkeypatch.setitem(sys.modules, 'ddgs', None)
    result = image_utils._duckduckgo_image('Apis mellifera')
    assert result is None


def test_duckduckgo_image_returns_none_on_ratelimit(monkeypatch):
    fake_mod = types.ModuleType('ddgs')
    class _FakeDDGS:
        def images(self, query, max_results=5):
            raise Exception('RatelimitException: rate limited')
    fake_mod.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, 'ddgs', fake_mod)
    result = image_utils._duckduckgo_image('Apis mellifera')
    assert result is None


def test_duckduckgo_image_skips_non_web_extensions(monkeypatch):
    fake_mod = types.ModuleType('ddgs')
    class _FakeDDGS:
        def images(self, query, max_results=10):
            return [
                {'image': 'https://example.com/photo.ppm', 'title': 'Cygnus pristinus', 'source': 'example.com'},
                {'image': 'https://example.com/photo.tiff', 'title': 'Cygnus pristinus', 'source': 'example.com'},
                {'image': 'https://example.com/photo.jpg', 'title': 'Cygnus pristinus', 'source': 'example.com'},
            ]
    fake_mod.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, 'ddgs', fake_mod)
    result = image_utils._duckduckgo_image('Cygnus pristinus')
    # Must skip .ppm and .tiff and return the first valid .jpg
    assert result is not None
    assert result[0] == 'https://example.com/photo.jpg'


def test_wikimedia_image_skips_non_image_mediatypes(monkeypatch):
    def fake_http_get(url):
        if 'list=search' in url:
            return {'query': {'search': [{'title': 'File:Some document maxima.pdf'}]}}
        # imageinfo response — mediatype is OFFICE (PDF), not BITMAP
        return {'query': {'pages': {'-1': {'imageinfo': [{
            'url': 'https://upload.wikimedia.org/some.pdf',
            'mediatype': 'OFFICE',
            'extmetadata': {},
        }]}}}}
    monkeypatch.setattr(image_utils, '_http_get', fake_http_get)
    result = image_utils._wikimedia_image('Felis maxima')
    assert result is None


# --- one-word names (genus and up) are checked against the lineage ---

SNAIL_PATH = "Animalia|Mollusca|Gastropoda|Stylommatophora|Orthalicidae|Orthalicus"


def _summary(extract):
    return {"extract": extract, "thumbnail": {"source": "https://img/x.jpg"}}


def test_wikipedia_image_rejects_article_about_another_animal(monkeypatch):
    # en.wikipedia "Zebra" is the mammal, not the snail genus Zebra
    monkeypatch.setattr(image_utils, '_http_get', lambda url: _summary(
        "Zebras are African equines with distinctive black-and-white striped coats."))
    assert image_utils._wikipedia_image('Zebra', must_mention=('Mollusca', 'Orthalicidae')) is None


def test_wikipedia_image_accepts_article_naming_the_lineage(monkeypatch):
    monkeypatch.setattr(image_utils, '_http_get', lambda url: _summary(
        "Panthera is a genus within the family Felidae."))
    assert image_utils._wikipedia_image('Panthera', must_mention=('Felidae',)) == (
        "https://img/x.jpg", "© Wikipedia contributors (CC BY-SA)")


def test_fetch_image_one_word_name_checks_lineage_and_qualifies_searches(monkeypatch):
    seen = {}
    def fake_wiki(name, must_mention=()):
        seen['wiki'] = (name, must_mention)
        return None
    monkeypatch.setattr(image_utils, '_wikipedia_image', fake_wiki)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name, rank='species': None)
    monkeypatch.setattr(image_utils, '_wikimedia_image',
                        lambda q, must_name=None: seen.setdefault('commons', (q, must_name)) and None)
    monkeypatch.setattr(image_utils, '_duckduckgo_image',
                        lambda q, common_names=None: seen.setdefault('ddg', q) and None)
    image_utils.fetch_image('Zebra', None, taxon_path=SNAIL_PATH)
    assert seen['wiki'] == ('Zebra', ('Mollusca', 'Gastropoda', 'Stylommatophora',
                                      'Orthalicidae', 'Orthalicus'))
    assert seen['commons'] == ('Zebra Orthalicus', 'Zebra')
    assert seen['ddg'] == 'Zebra Orthalicus'


def test_fetch_image_binomial_unchanged_with_taxon_path(monkeypatch):
    calls = []
    monkeypatch.setattr(image_utils, '_wikipedia_image',
                        lambda name: calls.append(name) or ("u", "a"))
    assert image_utils.fetch_image('Equus zebra', None,
                                   taxon_path="Animalia|Equidae|Equus|Equus zebra") == ("u", "a")
    assert calls == ['Equus zebra']


# --- DuckDuckGo results must be about the searched name ---

def _fake_ddgs(monkeypatch, results):
    fake_mod = types.ModuleType('ddgs')
    class _FakeDDGS:
        def images(self, query, max_results=10):
            return results.get(query, [])
    fake_mod.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, 'ddgs', fake_mod)


def test_duckduckgo_image_rejects_result_matching_only_the_epithet(monkeypatch):
    # "ramsayi" alone found a copperhead snake for the fossil wombat Sceparnodon ramsayi
    _fake_ddgs(monkeypatch, {'Sceparnodon ramsayi': [
        {'image': 'https://ag.example/snake.jpg', 'title': 'Copperhead snake Austrelaps ramsayi',
         'url': 'https://ag.example/fact-file-copperhead-snake-austrelaps-labialis-ramsayi/'},
    ]})
    assert image_utils._duckduckgo_image('Sceparnodon ramsayi') is None


def test_duckduckgo_image_accepts_name_in_title_or_page_url(monkeypatch):
    _fake_ddgs(monkeypatch, {
        'Sceparnodon ramsayi': [
            {'image': 'https://m.example/a.jpg', 'title': 'Giant wombat skull', 'url': 'https://m.example/sceparnodon-ramsayi'},
        ],
        'Vombatus ursinus': [
            {'image': 'https://m.example/b.jpg', 'title': 'Vombatus Ursinus at dusk', 'url': 'https://m.example/x'},
        ],
    })
    assert image_utils._duckduckgo_image('Sceparnodon ramsayi')[0] == 'https://m.example/a.jpg'
    assert image_utils._duckduckgo_image('Vombatus ursinus')[0] == 'https://m.example/b.jpg'


def test_duckduckgo_image_common_name_query_needs_the_common_name(monkeypatch):
    _fake_ddgs(monkeypatch, {'Giant wombat': [
        {'image': 'https://m.example/c.jpg', 'title': 'Giant panda', 'url': 'https://m.example/panda'},
        {'image': 'https://m.example/d.jpg', 'title': 'The giant wombat Phascolonus', 'url': 'https://m.example/y'},
    ]})
    assert image_utils._duckduckgo_image('Nope nope', ['Giant wombat'])[0] == 'https://m.example/d.jpg'


# --- Commons hits must be filed under the searched name ---

def _commons(monkeypatch, files):
    """files: [(title, categories, mediatype)] in search-rank order."""
    def fake_http_get(url):
        if 'list=search' in url:
            return {'query': {'search': [{'title': t} for t, _, _ in files]}}
        return {'query': {'pages': {str(i): {'title': t, 'imageinfo': [{
            'url': f'https://upload.wikimedia.org/{i}.jpg', 'mediatype': mt,
            'extmetadata': {'Categories': {'value': cats}, 'Artist': {'value': 'Jane'},
                            'LicenseShortName': {'value': 'CC BY-SA 4.0'}},
        }]} for i, (t, cats, mt) in enumerate(files)}}}
    monkeypatch.setattr(image_utils, '_http_get', fake_http_get)


def test_wikimedia_image_rejects_photo_only_mentioning_the_name_in_its_caption(monkeypatch):
    # "Tapirus malayanus" found a Sumatran elephant calf (caption lists the park's wildlife)
    _commons(monkeypatch, [('File:Gajah Sumatera di kawasan Suaka Margasatwa.jpg',
                            'Elephas maximus (juvenile)|Elephants of Indonesia', 'BITMAP')])
    assert image_utils._wikimedia_image('Tapirus malayanus') is None


def test_wikimedia_image_accepts_name_in_categories(monkeypatch):
    _commons(monkeypatch, [('File:036 South American tapir in Encontro das Aguas.jpg',
                            'Tapirus terrestris|Self-published work', 'BITMAP')])
    assert image_utils._wikimedia_image('Tapirus terrestris') == (
        'https://upload.wikimedia.org/0.jpg', '© Jane (CC BY-SA 4.0)')


def test_wikimedia_image_takes_the_first_on_topic_hit(monkeypatch):
    _commons(monkeypatch, [
        ('File:EU Regulation 2017-160.pdf', 'European Union Regulations', 'BITMAP'),
        ('File:Tapirus pinchaque 182788089.jpg', 'Media from iNaturalist', 'BITMAP'),
    ])
    assert image_utils._wikimedia_image('Tapirus pinchaque')[0] == 'https://upload.wikimedia.org/1.jpg'


def test_wikimedia_image_one_word_name_needs_only_the_name(monkeypatch):
    # searched as "Tapirus Tapiridae"; the file is filed under Tapirus terrestris
    _commons(monkeypatch, [('File:South American tapir (Tapirus terrestris).JPG',
                            'Tapirus terrestris|Photographs by Charlesjsharp', 'BITMAP')])
    assert image_utils._wikimedia_image('Tapirus Tapiridae') is None
    assert image_utils._wikimedia_image('Tapirus Tapiridae', must_name='Tapirus') is not None


# --- Increment 31: outages aren't misses; wide search; iNaturalist ranks; GBIF photos ---

import io
import urllib.error

URL = "https://img.example/photo.jpg"


def _no_sources(monkeypatch, **over):
    """Every source misses unless overridden."""
    fakes = {
        '_wikipedia_image': lambda name, must_mention=(): None,
        '_inaturalist_image': lambda name, rank='species': None,
        '_wikimedia_image': lambda name, must_name=None: None,
        '_duckduckgo_image': lambda name, common_names=None: None,
        '_gbif_image': lambda name: None,
    }
    fakes.update(over)
    for attr, fn in fakes.items():
        monkeypatch.setattr(image_utils, attr, fn, raising=False)


def _down(*a, **k):
    raise image_utils._SourceDown("timeout")


def test_http_get_returns_none_on_404(monkeypatch):
    def fake_urlopen(req, context=None, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(image_utils.urllib.request, "urlopen", fake_urlopen)
    assert image_utils._http_get("https://en.wikipedia.org/x") is None


def test_http_get_raises_source_down_on_timeout(monkeypatch):
    def fake_urlopen(req, context=None, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(image_utils.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(image_utils._SourceDown):
        image_utils._http_get("https://en.wikipedia.org/x")


def test_http_get_raises_source_down_on_server_error(monkeypatch):
    def fake_urlopen(req, context=None, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "Busy", {}, io.BytesIO(b""))
    monkeypatch.setattr(image_utils.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(image_utils._SourceDown):
        image_utils._http_get("https://api.inaturalist.org/x")


def test_http_get_raises_source_down_on_rate_limit(monkeypatch):
    def fake_urlopen(req, context=None, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
    monkeypatch.setattr(image_utils.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(image_utils._SourceDown):
        image_utils._http_get("https://api.inaturalist.org/x")


def test_fetch_image_raises_unavailable_when_a_source_was_down(monkeypatch):
    _no_sources(monkeypatch, _wikipedia_image=_down)
    with pytest.raises(image_utils.ImagesUnavailable):
        image_utils.fetch_image("Panthera leo")


def test_fetch_image_down_source_does_not_hide_a_later_hit(monkeypatch):
    _no_sources(monkeypatch, _wikipedia_image=_down,
                _inaturalist_image=lambda name, rank='species': (URL, "© iNat"))
    assert image_utils.fetch_image("Panthera leo") == (URL, "© iNat")


def test_fetch_image_duckduckgo_error_is_a_miss(monkeypatch):
    _no_sources(monkeypatch, _duckduckgo_image=_down)
    assert image_utils.fetch_image("Panthera leo") is None


def test_fetch_image_passes_the_rank_to_inaturalist(monkeypatch):
    seen = {}
    _no_sources(monkeypatch,
                _inaturalist_image=lambda name, rank='species': seen.setdefault('rank', rank) and None)
    image_utils.fetch_image("Tyto furcata bondi", rank="subspecies")
    assert seen['rank'] == "subspecies"


def test_fetch_image_strips_homonym_suffix(monkeypatch):
    seen = []
    _no_sources(monkeypatch, _wikipedia_image=lambda name, must_mention=(): seen.append(name) or None)
    image_utils.fetch_image("Bacteria laesa [Phasmatidae]")
    assert seen == ["Bacteria laesa"]


def test_inaturalist_image_matches_subspecies_rank(monkeypatch):
    seen = []
    def fake(url):
        seen.append(url)
        return {"results": [{"name": "Tyto furcata bondi", "rank": "subspecies",
                             "default_photo": {"medium_url": URL, "attribution": "© A"}}]}
    monkeypatch.setattr(image_utils, "_http_get", fake)
    assert image_utils._inaturalist_image("Tyto furcata bondi", rank="subspecies") == (URL, "© A")
    assert "rank=" not in seen[0]


def test_inaturalist_image_rejects_same_name_other_rank(monkeypatch):
    monkeypatch.setattr(image_utils, "_http_get", lambda url: {"results": [
        {"name": "Zebra", "rank": "genus", "default_photo": {"medium_url": URL}}]})
    assert image_utils._inaturalist_image("Zebra", rank="species") is None


def _gbif(results, seen=None):
    def fake(url):
        if seen is not None:
            seen.append(url)
        return {"results": results}
    return fake


SPECIMEN = {
    "basisOfRecord": "PRESERVED_SPECIMEN",
    "media": [{"type": "StillImage", "format": "image/jpeg", "identifier": "https://nhm.example/a.jpg",
               "license": "http://creativecommons.org/licenses/by/4.0/",
               "rightsHolder": "The Trustees of the Natural History Museum, London"}],
}
OBSERVATION = {
    "basisOfRecord": "HUMAN_OBSERVATION",
    "media": [{"type": "StillImage", "format": "image/jpeg", "identifier": "https://inat.example/b.jpg",
               "license": "http://creativecommons.org/licenses/by-nc/4.0/", "creator": "Anuar Acosta"}],
}


def test_gbif_image_prefers_a_living_animal_photo(monkeypatch):
    monkeypatch.setattr(image_utils, "_http_get", _gbif([SPECIMEN, OBSERVATION]))
    assert image_utils._gbif_image("Tyto furcata bondi") == (
        "https://inat.example/b.jpg", "© Anuar Acosta (CC BY-NC 4.0) via GBIF")


def test_gbif_image_falls_back_to_a_labelled_specimen(monkeypatch):
    monkeypatch.setattr(image_utils, "_http_get", _gbif([SPECIMEN]))
    assert image_utils._gbif_image("Anoxycalyx ijimai") == (
        "https://nhm.example/a.jpg",
        "© The Trustees of the Natural History Museum, London (CC BY 4.0) via GBIF (museum specimen)")


def test_gbif_image_skips_media_without_identifier_or_not_still_image(monkeypatch):
    monkeypatch.setattr(image_utils, "_http_get", _gbif([
        {"basisOfRecord": "HUMAN_OBSERVATION", "media": [
            {"type": "Sound", "format": "audio/mpeg", "identifier": "https://x/s.mp3"},
            {"type": "StillImage", "format": "image/jpeg"},
            {"type": "StillImage", "format": "application/pdf", "identifier": "https://x/d.pdf"}]}]))
    assert image_utils._gbif_image("Panthera leo") is None


def test_gbif_image_public_domain_licence(monkeypatch):
    rec = {"basisOfRecord": "PRESERVED_SPECIMEN", "media": [
        {"type": "StillImage", "identifier": "https://cas.example/c.jpg",
         "license": "http://creativecommons.org/publicdomain/zero/1.0/"}]}
    monkeypatch.setattr(image_utils, "_http_get", _gbif([rec]))
    assert image_utils._gbif_image("Barbodes sirang") == (
        "https://cas.example/c.jpg", "© GBIF contributors (CC0) via GBIF (museum specimen)")


def test_gbif_image_uses_scientific_name_parameter(monkeypatch):
    seen = []
    monkeypatch.setattr(image_utils, "_http_get", _gbif([], seen))
    image_utils._gbif_image("Barbodes sirang")
    assert "scientificName=Barbodes%20sirang" in seen[0] and "&q=" not in seen[0]
    assert "mediaType=StillImage" in seen[0]


def test_gbif_image_strips_homonym_suffix(monkeypatch):
    seen = []
    monkeypatch.setattr(image_utils, "_http_get", _gbif([], seen))
    image_utils._gbif_image("Bacteria laesa [Phasmatidae]")
    assert "scientificName=Bacteria%20laesa&" in seen[0]


def test_fetch_image_wide_tries_current_name_then_gbif(monkeypatch):
    gbif_calls = []
    _no_sources(monkeypatch,
                _wikipedia_image=lambda name, must_mention=():
                    (URL, "© Wikipedia") if name == "Acrocodia indica" else None,
                _gbif_image=lambda name: gbif_calls.append(name) or None)
    assert image_utils.fetch_image("Tapirus indicus", wide=True, current_name="Acrocodia indica") == (
        URL, "© Wikipedia (picture of Acrocodia indica)")
    assert gbif_calls == []


def test_fetch_image_wide_ends_with_gbif(monkeypatch):
    _no_sources(monkeypatch, _gbif_image=lambda name: (URL, "© X (CC BY 4.0) via GBIF"))
    assert image_utils.fetch_image("Anoxycalyx ijimai", wide=True) == (URL, "© X (CC BY 4.0) via GBIF")


def test_fetch_image_wide_gbif_down_is_an_outage(monkeypatch):
    _no_sources(monkeypatch, _gbif_image=_down)
    with pytest.raises(image_utils.ImagesUnavailable):
        image_utils.fetch_image("Anoxycalyx ijimai", wide=True)


def test_fetch_image_not_wide_never_calls_gbif(monkeypatch):
    calls = []
    _no_sources(monkeypatch, _gbif_image=lambda name: calls.append(name) or (URL, "x"))
    assert image_utils.fetch_image("Anoxycalyx ijimai") is None
    assert calls == []


def test_fetch_image_wide_searches_current_name_with_its_lineage_and_rank(monkeypatch):
    seen = {}
    def wiki(name, must_mention=()):
        seen.setdefault('wiki', []).append((name, must_mention))
        return None
    def inat(name, rank='species'):
        seen.setdefault('inat', []).append((name, rank))
        return None
    _no_sources(monkeypatch, _wikipedia_image=wiki, _inaturalist_image=inat)
    image_utils.fetch_image("Oldgenus", taxon_path="Animalia|Mollusca|Oldgenus", rank="genus", wide=True,
                            current_name="Zebra", current_path=SNAIL_PATH.replace("Orthalicus", "Zebra"),
                            current_rank="genus")
    assert seen['wiki'][1] == ("Zebra", ("Mollusca", "Gastropoda", "Stylommatophora", "Orthalicidae"))
    assert seen['inat'][1] == ("Zebra", "genus")


def test_fetch_image_wide_current_name_uses_its_own_rank(monkeypatch):
    seen = []
    _no_sources(monkeypatch, _inaturalist_image=lambda name, rank='species': seen.append((name, rank)) or None)
    image_utils.fetch_image("Tyto alba oldsub", rank="subspecies", wide=True,
                            current_name="Tyto alba", current_rank="species")
    assert seen == [("Tyto alba oldsub", "subspecies"), ("Tyto alba", "species")]


def test_inaturalist_image_unranked_row_accepts_any_rank(monkeypatch):
    monkeypatch.setattr(image_utils, "_http_get", lambda url: {"results": [
        {"name": "Foo bar", "rank": "species", "default_photo": {"medium_url": URL}}]})
    for rank in ("unranked", "other", "infraspecific name"):
        assert image_utils._inaturalist_image("Foo bar", rank=rank)[0] == URL


# --- Increment 32: candidate lists for "Other pictures" ---

def _photo(n):
    return {"medium_url": f"https://inat.example/{n}.jpg", "attribution": f"(c) user{n}"}


def test_inaturalist_images_lists_taxon_photos(monkeypatch):
    def fake(url):
        if "/taxa/42" in url:
            return {"results": [{"id": 42, "taxon_photos": [
                {"photo": _photo(1)}, {"photo": _photo(2)}, {"photo": _photo(3)}]}]}
        return {"results": [{"id": 42, "name": "Oreamnos americanus", "rank": "species",
                             "default_photo": _photo(1)}]}
    monkeypatch.setattr(image_utils, "_http_get", fake)
    got = image_utils._inaturalist_images("Oreamnos americanus", limit=3)
    assert got == [("https://inat.example/1.jpg", "(c) user1"), ("https://inat.example/2.jpg", "(c) user2"),
                   ("https://inat.example/3.jpg", "(c) user3")]


def test_inaturalist_image_single_needs_one_request(monkeypatch):
    seen = []
    def fake(url):
        seen.append(url)
        return {"results": [{"id": 42, "name": "Oreamnos americanus", "rank": "species",
                             "default_photo": _photo(1)}]}
    monkeypatch.setattr(image_utils, "_http_get", fake)
    assert image_utils._inaturalist_image("Oreamnos americanus")[0] == "https://inat.example/1.jpg"
    assert len(seen) == 1


def _commons_list(titles):
    def fake(url):
        if "list=search" in url:
            return {"query": {"search": [{"title": t} for t in titles]}}
        return {"query": {"pages": {str(i): {"title": t, "imageinfo": [{
            "url": f"https://commons.example/{i}.jpg", "mediatype": "BITMAP",
            "extmetadata": {"Artist": {"value": "A"}, "LicenseShortName": {"value": "CC BY 4.0"}}}]}
            for i, t in enumerate(titles)}}}
    return fake


def test_wikimedia_images_returns_several_on_topic_hits(monkeypatch):
    seen = []
    fake = _commons_list(["File:Oreamnos americanus 1.jpg", "File:Snake.jpg", "File:Oreamnos americanus 2.jpg"])
    monkeypatch.setattr(image_utils, "_http_get", lambda url: seen.append(url) or fake(url))
    got = image_utils._wikimedia_images("Oreamnos americanus", limit=3)
    assert [u for u, _ in got] == ["https://commons.example/0.jpg", "https://commons.example/2.jpg"]
    assert "srlimit=10" in seen[0]


def test_gbif_images_living_first_then_specimens(monkeypatch):
    obs2 = {"basisOfRecord": "HUMAN_OBSERVATION", "media": [
        {"type": "StillImage", "identifier": "https://inat.example/c.jpg", "creator": "C"}]}
    monkeypatch.setattr(image_utils, "_http_get", _gbif([SPECIMEN, OBSERVATION, obs2]))
    got = image_utils._gbif_images("Tyto furcata", limit=3)
    assert [u for u, _ in got] == ["https://inat.example/b.jpg", "https://inat.example/c.jpg",
                                   "https://nhm.example/a.jpg"]
    assert got[2][1].endswith("(museum specimen)")


def test_duckduckgo_images_several(monkeypatch):
    _fake_ddgs(monkeypatch, {"Oreamnos americanus": [
        {"image": f"https://web.example/{i}.jpg", "title": "Oreamnos americanus photo", "source": "web.example"}
        for i in range(5)]})
    got = image_utils._duckduckgo_images("Oreamnos americanus", limit=3)
    assert [u for u, _ in got] == [f"https://web.example/{i}.jpg" for i in range(3)]


def _lists(monkeypatch, **over):
    fakes = {
        "_wikipedia_image": lambda name, must_mention=(): None,
        "_inaturalist_images": lambda name, rank="species", limit=4: [],
        "_wikimedia_images": lambda name, must_name=None, limit=3: [],
        "_gbif_images": lambda name, limit=3: [],
        "_duckduckgo_images": lambda name, common_names=None, limit=3: [],
    }
    fakes.update(over)
    for attr, fn in fakes.items():
        monkeypatch.setattr(image_utils, attr, fn)


def test_image_candidates_merges_in_source_order_and_dedupes(monkeypatch):
    _lists(monkeypatch,
           _wikipedia_image=lambda name, must_mention=(): ("https://w/1.jpg", "© Wikipedia contributors (CC BY-SA)"),
           _inaturalist_images=lambda name, rank="species", limit=4: [("https://i/1.jpg", "(c) a"), ("https://w/1.jpg", "dup")],
           _gbif_images=lambda name, limit=3: [("https://g/1.jpg", "© X via GBIF")],
           _duckduckgo_images=lambda name, common_names=None, limit=3: [("https://d/1.jpg", "Source: d")])
    cands, down = image_utils.image_candidates("Oreamnos americanus")
    assert [(c["url"], c["source"]) for c in cands] == [
        ("https://w/1.jpg", "Wikipedia"), ("https://i/1.jpg", "iNaturalist"),
        ("https://g/1.jpg", "GBIF"), ("https://d/1.jpg", "DuckDuckGo")]
    assert cands[0]["attribution"] == "© Wikipedia contributors (CC BY-SA)"
    assert down is False


def test_image_candidates_leaves_out_excluded_urls(monkeypatch):
    _lists(monkeypatch, _inaturalist_images=lambda name, rank="species", limit=4: [
        ("https://i/1.jpg", "a"), ("https://i/2.jpg", "b")])
    cands, _ = image_utils.image_candidates("Oreamnos americanus", exclude={"https://i/1.jpg"})
    assert [c["url"] for c in cands] == ["https://i/2.jpg"]


def test_image_candidates_adds_current_name_pictures(monkeypatch):
    _lists(monkeypatch, _inaturalist_images=lambda name, rank="species", limit=4:
           [("https://i/acro.jpg", "(c) a")] if name == "Acrocodia indica" else [])
    cands, _ = image_utils.image_candidates("Tapirus indicus", current_name="Acrocodia indica",
                                            current_rank="species")
    assert cands == [{"url": "https://i/acro.jpg", "attribution": "(c) a (picture of Acrocodia indica)",
                      "source": "iNaturalist"}]


def test_image_candidates_reports_a_down_source(monkeypatch):
    _lists(monkeypatch, _gbif_images=_down,
           _duckduckgo_images=lambda name, common_names=None, limit=3: [("https://d/1.jpg", "Source: d")])
    cands, down = image_utils.image_candidates("Oreamnos americanus")
    assert [c["url"] for c in cands] == ["https://d/1.jpg"] and down is True


def test_image_candidates_caps_at_limit(monkeypatch):
    _lists(monkeypatch, _inaturalist_images=lambda name, rank="species", limit=4:
           [(f"https://i/{n}.jpg", "a") for n in range(limit)],
           _duckduckgo_images=lambda name, common_names=None, limit=3:
           [(f"https://d/{n}.jpg", "b") for n in range(limit)])
    cands, _ = image_utils.image_candidates("Oreamnos americanus", limit=5)
    assert len(cands) == 5


def test_image_candidates_strips_homonym_suffix(monkeypatch):
    seen = []
    _lists(monkeypatch, _inaturalist_images=lambda name, rank="species", limit=4: seen.append(name) or [])
    image_utils.image_candidates("Bacteria laesa [Phasmatidae]")
    assert seen == ["Bacteria laesa"]


def test_fetch_image_skips_an_excluded_hit(monkeypatch):
    _no_sources(monkeypatch,
                _wikipedia_image=lambda name, must_mention=(): ("https://w/snake.jpg", "© W"),
                _inaturalist_image=lambda name, rank="species": ("https://i/goat.jpg", "© I"))
    assert image_utils.fetch_image("Oreamnos americanus", exclude={"https://w/snake.jpg"}) == (
        "https://i/goat.jpg", "© I")


def test_gbif_images_use_inaturalist_medium_size(monkeypatch):
    rec = {"basisOfRecord": "HUMAN_OBSERVATION", "media": [{"type": "StillImage", "creator": "A",
           "identifier": "https://inaturalist-open-data.s3.amazonaws.com/photos/80682793/original.jpg"}]}
    monkeypatch.setattr(image_utils, "_http_get", _gbif([rec]))
    assert image_utils._gbif_images("Tyto furcata bondi")[0][0] == \
        "https://inaturalist-open-data.s3.amazonaws.com/photos/80682793/medium.jpg"


# --- Increment 32 review: the same photo at another size is the same picture ---

THUMB = ("https://thumb.wikimedia.org/wikipedia/commons/thumb/2/23/Mountain_Goat%2C_Enchantments_Basin.jpg/"
         "330px-Mountain_Goat%2C_Enchantments_Basin.jpg?utm_source=en.wikipedia.org")
ORIGINAL = "https://upload.wikimedia.org/wikipedia/commons/2/23/Mountain_Goat%2C_Enchantments_Basin.jpg"


def test_picture_key_matches_sizes_of_one_photo():
    key = image_utils.picture_key
    assert key(THUMB) == key(ORIGINAL)
    assert key("https://inaturalist-open-data.s3.amazonaws.com/photos/80682793/original.jpg") == \
        key("https://inaturalist-open-data.s3.amazonaws.com/photos/80682793/medium.jpg") == \
        key("https://static.inaturalist.org/photos/80682793/square.jpg")
    assert key("https://web.example/a.jpg") == "https://web.example/a.jpg"
    assert key(ORIGINAL) != key("https://upload.wikimedia.org/wikipedia/commons/3/33/Other.jpg")


def test_fetch_image_excludes_the_same_photo_at_another_size(monkeypatch):
    _no_sources(monkeypatch,
                _wikimedia_image=lambda name, must_name=None: (ORIGINAL, "© R"),
                _duckduckgo_image=lambda name, common_names=None: ("https://d/goat.jpg", "Source: d"))
    assert image_utils.fetch_image("Oreamnos americanus", exclude={THUMB}) == ("https://d/goat.jpg", "Source: d")


def test_image_candidates_excludes_and_dedupes_across_sizes(monkeypatch):
    _lists(monkeypatch,
           _inaturalist_images=lambda name, rank="species", limit=4:
               [("https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg", "(c) a")],
           _wikimedia_images=lambda name, must_name=None, limit=3: [(ORIGINAL, "© R")],
           _gbif_images=lambda name, limit=3:
               [("https://static.inaturalist.org/photos/1/medium.jpeg", "© a via GBIF")])
    cands, _ = image_utils.image_candidates("Oreamnos americanus", exclude={THUMB})
    assert [c["url"] for c in cands] == ["https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg"]


# --- Increment 33: the gallery shows what answered within its deadline ---

def test_image_candidates_skips_a_source_slower_than_the_deadline(monkeypatch):
    import time
    def slow(name, limit=3):
        time.sleep(1.5)
        return [("https://g/late.jpg", "late")]
    _lists(monkeypatch, _gbif_images=slow,
           _inaturalist_images=lambda name, rank="species", limit=4: [("https://i/1.jpg", "a")])
    start = time.monotonic()
    cands, down = image_utils.image_candidates("Oreamnos americanus", deadline=0.3)
    assert time.monotonic() - start < 1.0
    assert [c["url"] for c in cands] == ["https://i/1.jpg"]
    assert down is True   # a slow source counts as one that didn't answer


def test_image_candidates_a_slow_duckduckgo_is_a_miss(monkeypatch):
    import time
    def slow(name, common_names=None, limit=3):
        time.sleep(1.5)
        return [("https://d/late.jpg", "late")]
    _lists(monkeypatch, _duckduckgo_images=slow)
    cands, down = image_utils.image_candidates("Oreamnos americanus", deadline=0.3)
    assert cands == [] and down is False
