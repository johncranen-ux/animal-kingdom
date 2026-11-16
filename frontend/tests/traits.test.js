import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  escapeHtml, formatTraitValue, traitRowsHtml, nextTraitStage, traitsUrl,
  panelShows, loadTraits, TRAITS_FETCH_TIMEOUT_MS, searchResultLabel, extinctLabel, rankLine, currentNameHtml,
} from '../js/traits.js';

const EST = 'Estimated from Wikipedia description';

function rowsDom(sp, provenance) {
  const div = document.createElement('div');
  div.innerHTML = traitRowsHtml(sp, provenance);
  return div;
}

function okJson(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

afterEach(() => { vi.useRealTimers(); document.body.innerHTML = ''; });

// ── Rendering ─────────────────────────────────────────────────────────────────

describe('traitRowsHtml', () => {
  it('escapes untrusted values', () => {
    const html = traitRowsHtml({ habitat_type: '<img src=x onerror=alert(1)>' }, {});
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img');
  });

  it('marks estimated values and shows source in title', () => {
    const div = rowsDom(
      { activity_period: 'nocturnal', habitat_type: 'Savanna' },
      { activity_period: { source: EST, estimated: true },
        habitat_type: { source: 'IUCN Red List', estimated: false } },
    );
    const rows = [...div.querySelectorAll('[title]')];
    const habitat = rows.find(r => r.textContent.includes('Savanna'));
    const activity = rows.find(r => r.textContent.includes('nocturnal'));
    expect(habitat.getAttribute('title')).toBe('Source: IUCN Red List');
    expect(habitat.querySelector('.trait-est')).toBeNull();
    expect(activity.getAttribute('title')).toBe(`Source: ${EST} (estimated)`);
    expect(activity.querySelector('.trait-est').textContent).toBe('est.');
  });

  it('hides rows with no value', () => {
    const div = rowsDom({ habitat_type: 'Savanna', trophic_level: null, body_mass: '' }, {});
    expect(div.textContent).toContain('Habitat');
    expect(div.textContent).not.toContain('Trophic level');
    expect(div.textContent).not.toContain('Body mass');
  });

  it('escapes quotes in title attributes', () => {
    const html = traitRowsHtml({ habitat_type: 'x' }, { habitat_type: { source: 'A "quoted" src', estimated: false } });
    expect(html).toContain('title="Source: A &quot;quoted&quot; src"');
    const div = rowsDom({ habitat_type: 'x' }, { habitat_type: { source: 'A "quoted" src', estimated: false } });
    expect(div.querySelector('[title]').getAttribute('title')).toBe('Source: A "quoted" src');
  });

  it('row order and labels unchanged for stored-only record', () => {
    const sp = {
      taxonomic_status: 'ACCEPTED', iucn_status: 'VU', population_trend: 'Decreasing',
      habitat_type: 'Savanna', trophic_level: 'carnivore', activity_period: 'nocturnal',
      elevation_limits: '0–4,200 m', body_mass: 190, body_length: 2.5, max_lifespan: 16,
      metabolic_rate: 1.5, reproduction_strategy: 'live birth',
      geo_bounding_box: { lat_min: -35, lat_max: 10, lon_min: -18, lon_max: 51 },
    };
    const labels = [...rowsDom(sp, undefined).querySelectorAll('.trait-label')].map(e => e.textContent);
    expect(labels).toEqual([
      'Taxonomic status', 'IUCN status', 'Population trend', 'Habitat', 'Trophic level',
      'Activity period', 'Elevation limits', 'Body mass (kg)', 'Body length (m)',
      'Max lifespan (yr)', 'Metabolic rate', 'Reproduction', 'Range',
    ]);
    expect(rowsDom(sp).textContent).toContain('lat -35–10, lon -18–51');
    expect(rowsDom(sp).querySelector('[title]')).toBeNull();
  });

  it('shows a latitude-only range without longitude', () => {
    const text = rowsDom({ geo_bounding_box: { lat_min: 51.6, lat_max: 83, records: 4892 } }).textContent;
    expect(text).toContain('lat 51.6–83, longitude not recorded (range crosses the 180° line) (4,892 wild records)');
    expect(text).not.toMatch(/undefined|null/);
  });

  it('adds the wild record count to a full range', () => {
    expect(rowsDom({ geo_bounding_box: { lat_min: 1, lat_max: 2, lon_min: 3, lon_max: 4, records: 12 } })
      .textContent).toContain('lat 1–2, lon 3–4 (12 wild records)');
  });

  it('hides a range without latitudes', () => {
    expect(rowsDom({ geo_bounding_box: { lat_min: 0 } }).textContent).not.toContain('lat');
  });

  it('range row carries the bounding-box source', () => {
    const div = rowsDom({ geo_bounding_box: { lat_min: 1, lat_max: 2, lon_min: 3, lon_max: 4 } },
                        { geo_bounding_box: { source: 'GBIF occurrences', estimated: false } });
    expect(div.querySelector('[title]').getAttribute('title')).toBe('Source: GBIF occurrences');
  });
});

describe('formatTraitValue', () => {
  it('formats numbers to 3 significant figures', () => {
    expect(formatTraitValue(0.175823)).toBe('0.176');
    expect(formatTraitValue(188)).toBe('188');
    expect(formatTraitValue(1.2e-7)).toBe('0.00000012');
    expect(formatTraitValue(43.8)).toBe('43.8');
    expect(formatTraitValue(4500)).toBe('4500');
    expect(formatTraitValue('Savanna')).toBe('Savanna');
  });
});

describe('escapeHtml', () => {
  it('escapes all HTML-significant characters and tolerates non-strings', () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe('&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;');
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml(12)).toBe('12');
  });
});

// ── Stage selection and URL ──────────────────────────────────────────────────

describe('nextTraitStage', () => {
  it('nextTraitStage order', () => {
    expect(nextTraitStage({ trait_eligible: true })).toBe('sourced');
    expect(nextTraitStage({ trait_eligible: true, traits_sourced: true })).toBe('estimated');
    expect(nextTraitStage({ trait_eligible: true, traits_sourced: true, traits_estimated: true })).toBeNull();
    expect(nextTraitStage({ trait_eligible: false })).toBeNull();
  });
});

describe('traitsUrl', () => {
  it('encodes the scientific name', () => {
    expect(traitsUrl('http://h', 'Apis cerana × mellifera', 'sourced'))
      .toBe('http://h/api/species/Apis%20cerana%20%C3%97%20mellifera/traits?stage=sourced');
  });
});

// ── Loading loop ──────────────────────────────────────────────────────────────

describe('loadTraits', () => {
  const base = { scientific_name: 'Panthera leo', trait_eligible: true };

  it('fetches sourced then estimated and merges each response', async () => {
    const fetchImpl = vi.fn()
      .mockReturnValueOnce(okJson({ values: { habitat_type: 'Savanna' },
        provenance: { habitat_type: { source: 'IUCN Red List', estimated: false } },
        traits_sourced: true, traits_estimated: false, trait_eligible: true }))
      .mockReturnValueOnce(okJson({ values: { habitat_type: 'Savanna', activity_period: 'nocturnal' },
        provenance: { activity_period: { source: EST, estimated: true } },
        traits_sourced: true, traits_estimated: true, trait_eligible: true }));
    const renders = [];
    const done = vi.fn();
    await loadTraits({ ...base }, {
      api: 'http://h', fetchImpl, isCurrent: () => true,
      onData: sp => renders.push(structuredClone(sp)), onDone: done,
    });
    expect(fetchImpl.mock.calls.map(c => c[0])).toEqual([
      'http://h/api/species/Panthera%20leo/traits?stage=sourced',
      'http://h/api/species/Panthera%20leo/traits?stage=estimated',
    ]);
    expect(renders[0].habitat_type).toBe('Savanna');
    expect(renders[1].activity_period).toBe('nocturnal');
    expect(renders[1].provenance.activity_period.estimated).toBe(true);
    expect(done).toHaveBeenCalledOnce();
  });

  it('stops after an incomplete sourced stage instead of asking for estimates', async () => {
    // The server cannot estimate without the sourced stage's abstract; asking
    // would only re-run the slow sourced stage. The next panel open retries.
    const incomplete = { values: {}, provenance: {}, traits_sourced: false, traits_estimated: false, trait_eligible: true };
    const fetchImpl = vi.fn(() => okJson(incomplete));
    const onDone = vi.fn();
    await loadTraits({ ...base }, { api: '', fetchImpl, isCurrent: () => true, onData: () => {}, onDone });
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(fetchImpl.mock.calls[0][0]).toContain('stage=sourced');
    expect(onDone).toHaveBeenCalledOnce();
  });

  it('ignores a stale response after the panel switched species', async () => {
    document.body.innerHTML = '<span id="sp-name">Panthera leo</span>';
    let resolveA;
    const fetchImpl = vi.fn()
      .mockReturnValueOnce(new Promise(r => { resolveA = r; }))
      .mockReturnValue(okJson({ values: { habitat_type: 'Marine' }, provenance: {},
        traits_sourced: true, traits_estimated: true, trait_eligible: true }));
    const shown = [];
    const opts = name => ({ api: '', fetchImpl, isCurrent: () => panelShows(name), onData: sp => shown.push(sp), onDone: () => {} });

    const loadA = loadTraits({ ...base }, opts('Panthera leo'));
    document.getElementById('sp-name').textContent = 'Ursus maritimus';   // user opens B
    await loadTraits({ scientific_name: 'Ursus maritimus', trait_eligible: true }, opts('Ursus maritimus'));
    resolveA({ ok: true, json: () => Promise.resolve({ values: { habitat_type: 'Savanna' }, provenance: {},
      traits_sourced: true, traits_estimated: true, trait_eligible: true }) });
    await loadA;
    expect(shown.map(s => s.habitat_type)).toEqual(['Marine']);
  });

  it('removes loading line after fetch timeout', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn((url, { signal }) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    const done = vi.fn();
    const p = loadTraits({ ...base }, { api: '', fetchImpl, isCurrent: () => true, onData: () => {}, onDone: done });
    await vi.advanceTimersByTimeAsync(TRAITS_FETCH_TIMEOUT_MS + 10);
    await expect(p).resolves.toBeUndefined();
    expect(done).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledOnce();   // a timed-out stage ends the loop
  });

  it('network errors end quietly', async () => {
    const done = vi.fn();
    await loadTraits({ ...base }, { api: '', fetchImpl: () => Promise.reject(new TypeError('offline')),
      isCurrent: () => true, onData: () => {}, onDone: done });
    expect(done).toHaveBeenCalledOnce();
  });

  it('no errors when panel is closed mid-load', async () => {
    document.body.innerHTML = '<span id="sp-name">Panthera leo</span>';
    let resolve;
    const fetchImpl = vi.fn(() => new Promise(r => { resolve = r; }));
    const onData = vi.fn();
    const onDone = vi.fn();
    const p = loadTraits({ ...base }, { api: '', fetchImpl, isCurrent: () => panelShows('Panthera leo'), onData, onDone });
    document.body.innerHTML = '';                // panel removed
    resolve({ ok: true, json: () => Promise.resolve({ values: {}, provenance: {}, traits_sourced: true }) });
    await expect(p).resolves.toBeUndefined();
    expect(onData).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it('does nothing for an ineligible record', async () => {
    const fetchImpl = vi.fn();
    const onDone = vi.fn();
    await loadTraits({ scientific_name: 'Panthera', trait_eligible: false },
                     { api: '', fetchImpl, isCurrent: () => true, onData: () => {}, onDone });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledOnce();
  });
});

// ── Search dropdown ──────────────────────────────────────────────────────────

describe('searchResultLabel', () => {
  it('tags ranks other than species', () => {
    expect(searchResultLabel({ scientific_name: 'Vombatidae', taxon_rank: 'family', common_names: ['wombats'] }))
      .toBe('wombats — <em class="text-gray-300">Vombatidae</em> <span class="text-gray-400">(family)</span>');
    expect(searchResultLabel({ scientific_name: 'Zebra', taxon_rank: 'genus', common_names: [] }))
      .toBe('<em>Zebra</em> <span class="text-gray-400">(genus)</span>');
  });

  it('leaves species and unknown ranks untagged', () => {
    expect(searchResultLabel({ scientific_name: 'Equus zebra', taxon_rank: 'species', common_names: ['Mountain zebra'] }))
      .toBe('Mountain zebra — <em class="text-gray-300">Equus zebra</em>');
    expect(searchResultLabel({ scientific_name: 'Equus zebra', common_names: [] })).toBe('<em>Equus zebra</em>');
  });

  it('escapes names', () => {
    expect(searchResultLabel({ scientific_name: 'X<b>', taxon_rank: 'species', common_names: ['<img>'] }))
      .not.toContain('<img>');
  });
});

// ── Extinct marker ───────────────────────────────────────────────────────────

describe('extinctLabel', () => {
  it('uses IUCN status first, then the GBIF flag', () => {
    expect(extinctLabel({ iucn_status: 'EX' })).toBe('extinct');
    expect(extinctLabel({ iucn_status: 'EW' })).toBe('extinct in the wild');
    expect(extinctLabel({ extinct: true })).toBe('extinct');
    expect(extinctLabel({ extinct: 1 })).toBe('extinct');          // raw value from /traits
    expect(extinctLabel({ iucn_status: 'LC', extinct: false })).toBe('');
    expect(extinctLabel({})).toBe('');
  });
});

describe('searchResultLabel with extinct taxa', () => {
  it('tags extinct species, and joins with the rank', () => {
    expect(searchResultLabel({ scientific_name: 'Sceparnodon ramsayi', taxon_rank: 'species', common_names: [], extinct: true }))
      .toBe('<em>Sceparnodon ramsayi</em> <span class="text-gray-400">(extinct)</span>');
    expect(searchResultLabel({ scientific_name: 'Raphus', taxon_rank: 'genus', common_names: [], iucn_status: 'EX' }))
      .toBe('<em>Raphus</em> <span class="text-gray-400">(genus, extinct)</span>');
  });
});

describe('rankLine', () => {
  it('appends the extinct marker to the rank', () => {
    expect(rankLine({ taxon_rank: 'species', extinct: true })).toBe('species · extinct');
    expect(rankLine({ taxon_rank: 'species', iucn_status: 'EW' })).toBe('species · extinct in the wild');
    expect(rankLine({ taxon_rank: 'genus' })).toBe('genus');
    expect(rankLine({})).toBe('');
  });
});

// ── Increment 30: old names ──────────────────────────────────────────────────

describe('old names', () => {
  it('tags a search result that is an old name', () => {
    expect(searchResultLabel({ scientific_name: 'Tapirus indicus', taxon_rank: 'species',
      common_names: ['Malayan Tapir'], taxonomic_status: 'SYNONYM', accepted_name: 'Acrocodia indica' }))
      .toBe('Malayan Tapir — <em class="text-gray-300">Tapirus indicus</em> '
        + '<span class="text-gray-400">(old name of Acrocodia indica)</span>');
    expect(searchResultLabel({ scientific_name: 'Wombatus', taxon_rank: 'genus', common_names: [],
      accepted_name: 'Vombatus' }))
      .toBe('<em>Wombatus</em> <span class="text-gray-400">(genus, old name of Vombatus)</span>');
  });

  it('shows no current-name row for a current name', () => {
    expect(currentNameHtml({ scientific_name: 'Acrocodia indica', current_name: null })).toBe('');
    expect(currentNameHtml({ scientific_name: 'Acrocodia indica' })).toBe('');
  });

  it('links an old name to its current name with the source', () => {
    const html = currentNameHtml({ scientific_name: 'Tapirus malayanus', current_name: {
      scientific_name: 'Acrocodia indica', common_name: 'Malayan tapir', taxon_path: 'A|Acrocodia indica',
      taxon_rank: 'species', source: 'Wikidata' } });
    const div = document.createElement('div');
    div.innerHTML = html;
    const link = div.querySelector('a[data-current-name]');
    expect(link.textContent).toBe('Malayan tapir — Acrocodia indica');
    expect(div.textContent).toContain('Current name');
    expect(div.textContent).toContain('(Wikidata)');
  });

  it('escapes the linked names', () => {
    const html = currentNameHtml({ current_name: { scientific_name: '<b>x</b>', common_name: '<img>', source: 'Wikidata' } });
    expect(html).not.toContain('<img>');
    expect(html).not.toContain('<b>');
  });
});

describe('loadTraits and old names', () => {
  it('takes the current name a trait stage found', async () => {
    const link = { scientific_name: 'Acrocodia indica', source: 'Wikidata' };
    const fetchImpl = vi.fn().mockReturnValueOnce(okJson({ values: {}, provenance: {},
      traits_sourced: true, traits_estimated: false, trait_eligible: true, current_name: link }))
      .mockReturnValueOnce(okJson({ values: {}, provenance: {},
        traits_sourced: true, traits_estimated: true, trait_eligible: true, current_name: link }));
    const renders = [];
    await loadTraits({ scientific_name: 'Tapirus malayanus', trait_eligible: true }, {
      api: 'http://h', fetchImpl, isCurrent: () => true,
      onData: sp => renders.push(structuredClone(sp)), onDone: () => {},
    });
    expect(renders[0].current_name).toEqual(link);
  });
});
