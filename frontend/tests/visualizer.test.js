import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { loadNode, searchSpecies, nodeLabel, treeLabel, visibleChildren, RANK_COLOR, initTree,
         highlightNodes, expandToNode, setNodeExtinct, refreshAncestorFlags, taxonDescription,
         getPathToNode, openDomain, nodeDescription, nodeDot, renderLegend, clearSelection } from '../js/visualizer.js';
import { ORDER_DESCRIPTIONS } from '../js/order_descriptions.js';
import { OTHER_ORDER_DESCRIPTIONS } from '../js/order_descriptions_other.js';

// ── fetch mock ──────────────────────────────────────────────────────────────

function mockFetch(data) {
  return vi.fn().mockResolvedValue({ ok: true, json: async () => data });
}

// Re-renders animate transforms, and jsdom has no SVG transform list. Stays for the
// whole file: animation timers can fire after the test that started them has ended.
beforeAll(() => {
  Object.defineProperty(SVGElement.prototype, 'transform', {
    configurable: true,
    value: { baseVal: { consolidate: () => null } },
  });
});

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  // Clear any SVG appended to body during initTree tests
  document.body.innerHTML = '';
});

// ── Order descriptions ──────────────────────────────────────────────────────

describe('order descriptions', () => {
  it('describes an order at order rank', () => {
    expect(taxonDescription('Araneae', 'order')).toContain('Spiders');
    expect(taxonDescription('Myxiniformes', 'order')).toContain('Hagfish');
  });

  it('does not lend order text to another rank with the same name', () => {
    expect(taxonDescription('Araneae', 'genus')).toBeUndefined();
    expect(taxonDescription('Araneae')).toBeUndefined();
  });

  it('keeps showing phylum and class text', () => {
    expect(taxonDescription('Arthropoda', 'phylum')).toContain('jointed legs');
    expect(taxonDescription('Insecta', 'class')).toBeTruthy();
  });

  it('keeps its text for phyla Catalogue of Life names differently', () => {
    for (const [now, before] of [['Dictyoglomerota', 'Dictyoglomota'], ['Nanobdellota', 'Nanoarchaeota'],
                                 ['Promethearchaeota', 'Asgardarchaeota']]) {
      expect(taxonDescription(now, 'phylum')).toBeTruthy();
      expect(taxonDescription(now, 'phylum')).toBe(taxonDescription(before, 'phylum'));
    }
  });

  it('has no text for an order it does not know', () => {
    expect(taxonDescription('Notarealorder', 'order')).toBeUndefined();
    expect(taxonDescription('constructor', 'order')).toBeUndefined();
  });

  it('covers the 789 animal orders, each with one short sentence', () => {
    const texts = Object.values(ORDER_DESCRIPTIONS);
    expect(texts).toHaveLength(789);
    for (const t of texts) {
      expect(t.length).toBeGreaterThan(10);
      expect(t.length).toBeLessThanOrEqual(170);
    }
  });

  it('covers the 1432 orders outside the animals, each with one short sentence', () => {
    const texts = Object.values(OTHER_ORDER_DESCRIPTIONS);
    expect(texts).toHaveLength(1432);
    for (const t of texts) {
      expect(t.length).toBeGreaterThan(10);
      expect(t.length).toBeLessThanOrEqual(170);
    }
    expect(Object.keys(OTHER_ORDER_DESCRIPTIONS).filter(k => Object.hasOwn(ORDER_DESCRIPTIONS, k))).toEqual([]);
  });

  it('describes orders of plants, fungi, chromists, bacteria and viruses at order rank only', () => {
    expect(taxonDescription('Rosales', 'order')).toContain('Roses');
    expect(taxonDescription('Agaricales', 'order')).toBeTruthy();
    expect(taxonDescription('Laminariales', 'order')).toContain('Kelps');
    expect(taxonDescription('Rosales', 'genus')).toBeUndefined();
  });

  it('describes the larger and renamed orders Catalogue of Life introduced', () => {
    const orders = `Ammonoidea Passeriformes Crassiclitellata Gobiiformes Cichliformes Tubificida Blenniiformes
      Polycladida Productida Balanomorpha Enchytraeida Eulipotyphla Scalpellomorpha Spiriferida Acanthuriformes
      Chaetonotida Ophiurida Nacellida Acerentomata Ellesmeroceratida Centrarchiformes Philodinida Apogoniformes
      Macrodasyida Scombriformes Acropomatiformes Orthida Eosentomata Endoceratida Saurischia Carangiformes
      Anabantiformes Lumbriculida Callionymiformes Strophomenida Notoptera Reculida Spiriferinida Pseudorthoceratida
      Moniligastrida Bisonoceratida Athyridida Atrypida Orthoceratida Mulliformes Acrotretida Alepocephaliformes
      Orthotetida Oncoceratida Cnemidolestida Ceriantharia Verrucomorpha Calanticomorpha Patellida Actinoceratida
      Pollicipedomorpha Holocentriformes Argentiniformes Pentamerida Roveacrinida Collothecaceae Baeriida Adinetida
      Dactylopteriformes Pterocliformes Philodinavida Pilosa Sepiolida Xiphosura`.split(/\s+/);
    expect(orders).toHaveLength(69);
    for (const name of orders) expect(taxonDescription(name, 'order'), name).toBeTruthy();
  });
});

describe('incertae sedis description', () => {
  it.each([
    ['incertae sedis', 'unranked'],
    ['Incertae Sedis', 'kingdom'],
    ['Siluriformes_incertae_sedis', 'family'],
    ['Family-incertae', 'family'],
  ])('explains the placeholder node %s', (name, rank) => {
    expect(taxonDescription(name, rank)).toContain('uncertain placement');
  });

  it.each([
    ['Tamerlania incertae', 'species'],
    ['Perfectononion incertaeformis', 'species'],
    ['Tolypammina incertae', 'subspecies'],
    ['Incertaea', 'genus'],
    ['Incertaea', 'family'],
  ])('leaves the real taxon %s without it', (name, rank) => {
    expect(taxonDescription(name, rank)).toBeUndefined();
  });
});

describe('nodeDescription: automatic line where no text is written', () => {
  // A d3 hierarchy node: data plus a parent chain
  const chain = (...levels) => levels.reduce(
    (parent, [name, rank, common_names = []]) => ({ data: { name, rank, common_names }, parent }), null);

  it('places a family in its order, with the order\'s common name', () => {
    const node = chain(['Animalia', 'kingdom'], ['Arthropoda', 'phylum'], ['Insecta', 'class'],
                       ['Coleoptera', 'order', ['Beetles']], ['Carabidae', 'family']);
    expect(nodeDescription(node)).toBe('A family in the order Coleoptera (Beetles).');
  });

  it('skips letter groups and in-between levels to the nearest main rank', () => {
    const node = chain(['Coleoptera', 'order'], ['Carabidae', 'family'], ['[H] (300)', 'alpha'],
                       ['Harpalinae', 'subfamily'], ['Harpalini', 'tribe']);
    expect(nodeDescription(node)).toBe('A tribe in the family Carabidae.');
  });

  it('uses "an" and drops the code part of rank names', () => {
    expect(nodeDescription(chain(['Insecta', 'class'], ['Coleoptera', 'order'], ['Elateriformia', 'infraorder'])))
      .toBe('An infraorder in the order Coleoptera.');
    expect(nodeDescription(chain(['Mollusca', 'phylum'], ['Gastropoda', 'class'], ['Abc', 'section zoology'])))
      .toBe('A section in the class Gastropoda.');
    expect(nodeDescription(chain(['Mollusca', 'phylum'], ['Gastropoda', 'class'], ['Abc', 'unranked'])))
      .toBe('A group in the class Gastropoda.');
  });

  it('falls back to the nearest named parent when no main rank is above', () => {
    expect(nodeDescription(chain(['Viruses', 'unranked'], ['Testviria', 'realm'])))
      .toBe('A realm in Viruses.');
  });

  it('explains letter groups and [Unclassified] nodes', () => {
    expect(nodeDescription(chain(['Coleoptera', 'order', ['Beetles']], ['Carabidae', 'family'], ['[H] (300)', 'alpha'])))
      .toBe('Members of Carabidae starting with H, grouped by letter because there are too many to show at once.');
    expect(nodeDescription(chain(['Animalia', 'kingdom'], ['Chordata', 'phylum'], ['[Unclassified] (46)', 'unclassified'])))
      .toBe('Members of Chordata that sit directly beneath it, without the level in between that the classification normally has.');
  });

  it('prefers written text, and adds nothing for genera and species', () => {
    expect(nodeDescription(chain(['Insecta', 'class'], ['Araneae', 'order']))).toContain('Spiders');
    expect(nodeDescription(chain(['Carabidae', 'family'], ['Carabus', 'genus']))).toBeUndefined();
    expect(nodeDescription(chain(['Carabus', 'genus'], ['Carabus auratus', 'species']))).toBeUndefined();
    expect(nodeDescription(chain(['Carabidae', 'family'], ['Carabus', 'subgenus']))).toBeUndefined();
  });
});

describe('kingdom and realm descriptions', () => {
  it('describes every kingdom in the tree', () => {
    const kingdoms = `Animalia Chromista Fungi Plantae Protozoa Bacillati Pseudomonadati Thermotogati
      Fusobacteriati Methanobacteriati Nanobdellati Promethearchaeati Thermoproteati Orthornavirae
      Pararnavirae Bamfordvirae Heunggongvirae Helvetiavirae Loebvirae Sangervirae Shotokuvirae
      Trapavirae Zilligvirae Abadenavirae`.split(/\s+/);
    for (const k of kingdoms) expect(taxonDescription(k, 'kingdom'), k).toBeTruthy();
    expect(taxonDescription('Riboviria', 'realm')).toContain('RNA');
    expect(taxonDescription('Harosa', 'subkingdom')).toContain('SAR');
  });

  it('never labels a genus with a kingdom text', () => {
    expect(taxonDescription('Fungi', 'genus')).toBeUndefined();
  });
});

describe('class descriptions Catalogue of Life introduced', () => {
  it('describes every new animal class', () => {
    const classes = `Teleostei Reptilia Enoplea Octocorallia Thecostraca Strophomenata Branchiura Chondrostei
      Pentastomida Holostei Appendicularia Chileata Euthycarcinoidea Kutorginata Cladistii Paterinata
      Cephalaspidomorphi Archaeocyatha Stromatoporoidea Mystacocarida Obolellata Heteractinida`.split(/\s+/);
    expect(classes).toHaveLength(22);
    for (const name of classes) expect(taxonDescription(name, 'class'), name).toBeTruthy();
  });

  it('does not lend class text to a genus with the same name', () => {
    // Branchiura is also a genus of worms, Appendicularia also a plant genus
    expect(taxonDescription('Branchiura', 'class')).toContain('lice');
    expect(taxonDescription('Branchiura', 'genus')).toBeUndefined();
    expect(taxonDescription('Appendicularia', 'genus')).toBeUndefined();
    expect(taxonDescription('Appendicularia', 'species')).toBeUndefined();
  });

  it('still shows class text on an order that was a class before', () => {
    expect(taxonDescription('Squamata', 'order')).toContain('Scaled reptiles');
  });
});

// ── Domains ─────────────────────────────────────────────────────────────────

describe('domains', () => {
  const node = (node_id, rank, children = []) =>
    ({ node_id, name: node_id.split('|').pop(), rank, common_names: [], children });

  const root = () => [
    node('Bacteria', 'domain'),
    node('Eukarya', 'domain', [node('Animalia', 'kingdom'), node('Plantae', 'kingdom')]),
    node('Viruses', 'kingdom'),
  ];

  const g = id => document.querySelector(`g[data-node-id="${id}"]`);
  const click = id => g(id).dispatchEvent(new MouseEvent('click', { bubbles: true }));
  // Microtasks only: a real timer would run D3 transitions, which jsdom can't
  const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

  async function setup(zoom = {}) {
    global.fetch = vi.fn().mockImplementation(url => {
      if (url.includes('/root')) return Promise.resolve({ ok: true, json: async () => root() });
      const id = new URL(url).searchParams.get('node_id') || '';
      const body = url.includes('/taxonomy/node') ? node(id, 'phylum') : (zoom[id] ?? []);
      return Promise.resolve({ ok: true, json: async () => body });
    });
    document.body.innerHTML = '<div id="dom-tree" style="width:800px;height:600px"></div>';
    await initTree('dom-tree');
  }

  it('shows the kingdoms under Eukarya on load, without fetching them', async () => {
    await setup();
    expect(g('Animalia')).not.toBeNull();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('search reaches a species through Eukarya, adding no root-level duplicate', async () => {
    await setup({ 'Animalia|Chordata': [node('Animalia|Chordata|Mammalia', 'class')] });
    await expandToNode('Animalia|Chordata|Mammalia');
    expect(document.querySelectorAll('g[data-node-id="Animalia"]')).toHaveLength(1);
    expect(getPathToNode('Animalia|Chordata|Mammalia').map(s => s.node_id))
      .toEqual(['Eukarya', 'Animalia', 'Animalia|Chordata', 'Animalia|Chordata|Mammalia']);
  });

  it('closing the branch of the selected species lifts the dimming but keeps the panel', async () => {
    await setup({ Animalia: [node('Animalia|Panthera leo', 'species')] });
    clearSelection();                                     // module state: no selection from an earlier test
    click('Animalia');
    await settle();
    click('Animalia|Panthera leo');                       // a leaf: selects it and dims the rest
    await settle();
    expect(g('Plantae').getAttribute('opacity')).toBe('0.12');
    const events = [];
    document.addEventListener('species-selected', e => events.push(e.detail));
    click('Animalia');                                    // close the branch holding the selection
    await settle();
    expect(g('Plantae').getAttribute('opacity')).toBe('1');
    expect(events).toEqual([]);                           // no "deselected" event: the panel stays open
  });

  it('selecting a species keeps its sister species visible, dims the rest', async () => {
    await setup({ Animalia: [node('Animalia|Panthera leo', 'species'), node('Animalia|Panthera onca', 'species')] });
    clearSelection();
    click('Animalia');
    await settle();
    click('Animalia|Panthera leo');
    await settle();
    expect(g('Animalia|Panthera onca').getAttribute('opacity')).toBe('1');
    expect(g('Plantae').getAttribute('opacity')).toBe('0.12');
  });

  it('a species opened from search keeps its sister species visible', async () => {
    await setup({ Animalia: [node('Animalia|Panthera leo', 'species'), node('Animalia|Panthera onca', 'species'),
                             node('Animalia|Felidae', 'family')] });
    clearSelection();
    click('Animalia');
    await settle();
    highlightNodes(['Animalia|Panthera leo']);
    expect(g('Animalia|Panthera onca').getAttribute('opacity')).toBe('1');
    expect(g('Animalia|Felidae').getAttribute('opacity')).toBe('0.12');   // a sister group, not a species
  });

  it('a variety keeps its sister varieties and forms visible', async () => {
    await setup({ Plantae: [node('Plantae|Nymphaea nouchali var. caerulea', 'variety'),
                            node('Plantae|Nymphaea nouchali var. ovalifolia', 'variety'),
                            node('Plantae|Nymphaea nouchali f. alba', 'form'),
                            node('Plantae|Nymphaeaceae', 'family')] });
    clearSelection();
    click('Plantae');
    await settle();
    highlightNodes(['Plantae|Nymphaea nouchali var. caerulea']);
    expect(g('Plantae|Nymphaea nouchali var. ovalifolia').getAttribute('opacity')).toBe('1');
    expect(g('Plantae|Nymphaea nouchali f. alba').getAttribute('opacity')).toBe('1');
    expect(g('Plantae|Nymphaeaceae').getAttribute('opacity')).toBe('0.12');
  });

  it('a search with several results lights only the matches', async () => {
    await setup({ Animalia: [node('Animalia|Panthera leo', 'species'), node('Animalia|Panthera onca', 'species'),
                             node('Animalia|Panthera pardus', 'species')] });
    clearSelection();
    click('Animalia');
    await settle();
    highlightNodes(['Animalia|Panthera leo', 'Animalia|Panthera onca']);
    expect(g('Animalia|Panthera pardus').getAttribute('opacity')).toBe('0.12');
  });

  it('closing an unrelated branch keeps the selection dimming', async () => {
    await setup({ Animalia: [node('Animalia|Panthera leo', 'species')],
                  Plantae: [node('Plantae|Quercus', 'genus')] });
    clearSelection();
    click('Plantae');
    await settle();
    click('Animalia');
    await settle();
    click('Animalia|Panthera leo');
    await settle();
    expect(g('Bacteria').getAttribute('opacity')).toBe('0.12');
    click('Plantae');                                     // collapse a branch without the selection
    await settle();
    expect(g('Bacteria').getAttribute('opacity')).toBe('0.12');
  });

  it('search reopens a collapsed Eukarya with all its kingdoms', async () => {
    await setup({ Animalia: [node('Animalia|Chordata', 'phylum')] });
    click('Eukarya');
    await expandToNode('Animalia|Chordata');
    // jsdom never finishes exit transitions, so read the bound data, not the DOM
    const eukarya = g('Eukarya').__data__.data;
    expect(eukarya.children.map(c => c.node_id).sort()).toEqual(['Animalia', 'Plantae']);
    expect(eukarya._children).toBeNull();
  });

  it('search reaches a bacterial phylum from the root', async () => {
    await setup({ Bacteria: [node('Bacteria|Aquificota', 'phylum')] });
    await expandToNode('Bacteria|Aquificota');
    expect(g('Bacteria|Aquificota')).not.toBeNull();
  });

  it('keeps Eukarya lit when a highlighted path runs through it', async () => {
    await setup();
    highlightNodes(['Animalia|Chordata']);
    expect(g('Eukarya').getAttribute('opacity')).toBe('1');
    expect(g('Bacteria').getAttribute('opacity')).toBe('0.12');
  });

  it('a stick insect highlight does not light the Bacteria domain', async () => {
    await setup();
    highlightNodes(['Animalia|Arthropoda|Insecta|Phasmida|Diapheromeridae|Bacteria']);
    expect(g('Bacteria').getAttribute('opacity')).toBe('0.12');
  });

  it('clicking a homonym opens its own row, not the namesake that holds the plain name', async () => {
    const homonym = { ...node('Plantae|Acrocodia', 'genus'), scientific_name: 'Acrocodia [Plantae]' };
    await setup({ Plantae: [homonym] });
    click('Plantae');
    await settle();
    const selected = vi.fn();
    document.addEventListener('species-selected', selected);
    click('Plantae|Acrocodia');
    await settle();
    document.removeEventListener('species-selected', selected);
    expect(selected.mock.calls[0][0].detail.scientific_name).toBe('Acrocodia [Plantae]');
  });

  it('clicking a domain with no children does not open a species panel', async () => {
    await setup();
    const selected = vi.fn();
    document.addEventListener('species-selected', selected);
    click('Bacteria');
    await settle();
    document.removeEventListener('species-selected', selected);
    expect(selected).not.toHaveBeenCalled();
  });

  it('openDomain loads and shows the domain\'s children', async () => {
    await setup({ Bacteria: [node('Bacteria|Aquificota', 'phylum')] });
    await openDomain('Bacteria');
    expect(g('Bacteria|Aquificota')).not.toBeNull();
  });

  it('openDomain reopens a collapsed domain without fetching', async () => {
    await setup();
    click('Eukarya');
    const calls = global.fetch.mock.calls.length;
    await openDomain('Eukarya');
    expect(g('Animalia')).not.toBeNull();
    expect(global.fetch.mock.calls.length).toBe(calls);
  });

  it('describes a domain only at domain rank, not its namesake genus', () => {
    expect(taxonDescription('Bacteria', 'domain')).toContain('three domains');
    expect(taxonDescription('Archaea', 'domain')).toContain('three domains');
    expect(taxonDescription('Eukarya', 'domain')).toContain('three domains');
    expect(taxonDescription('Bacteria', 'genus')).toBeUndefined();
    expect(taxonDescription('Archaea', 'genus')).toBeUndefined();
  });

  it('says viruses belong to no domain', () => {
    expect(taxonDescription('Viruses', 'kingdom')).toContain('not part of any domain');
  });

  it('gives domains their own colour', () => {
    expect(RANK_COLOR.domain).toMatch(/^#/);
  });
});

// ── loadNode ────────────────────────────────────────────────────────────────

describe('loadNode', () => {
  it('calls /api/taxonomy/root for empty taxon path', async () => {
    global.fetch = mockFetch([]);
    await loadNode('');
    expect(global.fetch).toHaveBeenCalledWith('http://localhost:8000/api/taxonomy/root');
  });

  it('calls zoom endpoint with encoded taxon path', async () => {
    global.fetch = mockFetch([]);
    await loadNode('Animalia');
    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/taxonomy/zoom?node_id=Animalia&depth=1',
    );
  });

  it('URL-encodes taxon paths containing pipe characters', async () => {
    global.fetch = mockFetch([]);
    await loadNode('Animalia|Chordata');
    const url = global.fetch.mock.calls[0][0];
    expect(url).toContain('Animalia%7CChordata');
  });

  it('returns empty array when response is not ok', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
    const result = await loadNode('');
    expect(result).toEqual([]);
  });

  it('returns parsed JSON on success', async () => {
    const data = [{ node_id: 'Animalia', name: 'Animalia', rank: 'kingdom' }];
    global.fetch = mockFetch(data);
    const result = await loadNode('');
    expect(result).toEqual(data);
  });

  it('routes __alpha__ node to /api/taxonomy/alpha with parent and letter', async () => {
    global.fetch = mockFetch([]);
    await loadNode('__alpha__Animalia|Arthropoda|Insecta|Hymenoptera|Apidae|A');
    const url = global.fetch.mock.calls[0][0];
    expect(url).toContain('/api/taxonomy/alpha');
    expect(url).toContain('node_id=');
    expect(url).toContain('Apidae');
    expect(url).toContain('letter=A');
  });

  it('routes __alpha____unclassified__ node to /api/taxonomy/unclassified with letter', async () => {
    global.fetch = mockFetch([]);
    await loadNode('__alpha____unclassified__Viruses|A');
    const url = global.fetch.mock.calls[0][0];
    expect(url).toContain('/api/taxonomy/unclassified');
    expect(url).toContain('node_id=Viruses');
    expect(url).toContain('letter=A');
  });
});

// ── searchSpecies ────────────────────────────────────────────────────────────

describe('searchSpecies', () => {
  it('calls /api/search with the query', async () => {
    global.fetch = mockFetch([]);
    await searchSpecies('lion');
    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/search?q=lion&limit=20',
    );
  });

  it('returns empty array for queries shorter than 2 chars', async () => {
    global.fetch = mockFetch([]);
    expect(await searchSpecies('l')).toEqual([]);
    expect(await searchSpecies('')).toEqual([]);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('trims whitespace before searching', async () => {
    global.fetch = mockFetch([]);
    await searchSpecies('  lion  ');
    const url = global.fetch.mock.calls[0][0];
    expect(url).toContain('q=lion');
  });

  it('returns empty array when response is not ok', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false });
    expect(await searchSpecies('lion')).toEqual([]);
  });
});

// ── nodeLabel ────────────────────────────────────────────────────────────────

describe('nodeLabel', () => {
  it('returns first common name when available', () => {
    expect(nodeLabel({ name: 'Panthera leo', common_names: ['Lion', 'African lion'] }))
      .toBe('Lion');
  });

  it('falls back to scientific name when common_names is empty', () => {
    expect(nodeLabel({ name: 'Panthera leo', common_names: [] })).toBe('Panthera leo');
  });

  it('falls back to scientific name when common_names is null', () => {
    expect(nodeLabel({ name: 'Panthera leo', common_names: null })).toBe('Panthera leo');
  });
});

// ── RANK_COLOR ──────────────────────────────────────────────────────────────

describe('RANK_COLOR', () => {
  it('has a colour for each standard rank', () => {
    for (const rank of ['kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']) {
      expect(RANK_COLOR[rank]).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});

// ── nodeDot / renderLegend ──────────────────────────────────────────────────

describe('nodeDot', () => {
  it('fills an open or unopened node with its rank colour', () => {
    expect(nodeDot({ node_id: 1, rank: 'kingdom' }, null))
      .toEqual({ fill: RANK_COLOR.kingdom, stroke: '#111827', width: 1.5 });
  });

  it('keeps the rank colour on a closed node with loaded branches, as a ring', () => {
    const dot = nodeDot({ node_id: 1, rank: 'kingdom', _children: [{}] }, null);
    expect(dot.stroke).toBe(RANK_COLOR.kingdom);
    expect(dot.fill).toBe('#111827');
  });

  it('draws a search-path node as a ring too', () => {
    expect(nodeDot({ node_id: 1, rank: 'order', _pathOnly: true }, null).stroke).toBe(RANK_COLOR.order);
  });

  it('greys a node whose rank has no colour', () => {
    expect(nodeDot({ node_id: 1, rank: 'unranked' }, null).fill).toBe('#9ca3af');
  });

  it('marks the selected node amber', () => {
    expect(nodeDot({ node_id: 7, rank: 'species', _children: [{}] }, 7).fill).toBe('#f59e0b');
  });
});

describe('renderLegend', () => {
  it('lists every rank colour, the grey and the ring', () => {
    const el = document.createElement('div');
    renderLegend(el);
    const text = el.textContent;
    for (const word of ['Domain', 'Kingdom', 'Phylum', 'Class', 'Order', 'Family', 'Genus', 'Species',
                        'Other rank', 'Closed, opened before', 'Selected']) {
      expect(text).toContain(word);
    }
    const fills = [...el.querySelectorAll('circle')].map(c => c.getAttribute('fill'));
    for (const color of Object.values(RANK_COLOR)) expect(fills).toContain(color);
  });
});

// ── highlightNodes ──────────────────────────────────────────────────────────

describe('highlightNodes', () => {
  it('does not throw when called before initTree', () => {
    expect(() => highlightNodes(['Animalia|Chordata|Mamm'])).not.toThrow();
  });

  it('highlights exact-match nodes and dims others after initTree', async () => {
    const kingdoms = [
      { node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [] },
      { node_id: 'Plantae',  name: 'Plantae',  rank: 'kingdom', common_names: [], children: [] },
    ];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => kingdoms });
    document.body.innerHTML = '<div id="hl-tree" style="width:800px;height:600px"></div>';
    await initTree('hl-tree');

    // Highlight Animalia — it is an ancestor of the full path, so it should be bright
    highlightNodes(['Animalia|Chordata|Mammalia']);
    const groups = document.querySelectorAll('#hl-tree g[data-rank]');
    const opacities = Array.from(groups).map(g => g.getAttribute('opacity') ?? '1');
    // At least the Animalia node should be at full opacity (ancestor match)
    expect(opacities.some(op => op === '1' || op === null)).toBe(true);
  });

  it('restores full opacity when called with empty array', async () => {
    if (!document.querySelector('#hl-tree')) {
      const kingdoms = [
        { node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [] },
      ];
      global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => kingdoms });
      document.body.innerHTML = '<div id="hl-tree" style="width:800px;height:600px"></div>';
      await initTree('hl-tree');
    }
    highlightNodes(['Animalia|Chordata']);
    highlightNodes([]);
    const groups = document.querySelectorAll('#hl-tree g[data-rank]');
    Array.from(groups).forEach(g => {
      const op = g.getAttribute('opacity');
      expect(op === null || op === '1').toBe(true);
    });
  });
});

// ── expandToNode ────────────────────────────────────────────────────────────

describe('expandToNode', () => {
  it('returns without error when path segment is not in the tree', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    await expect(expandToNode('NonexistentKingdom|SomePhylum')).resolves.toBeUndefined();
  });

  it('expands an ancestor node and calls loadNode for it', async () => {
    const kingdoms = [
      { node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [] },
    ];
    const phyla = [
      { node_id: 'Animalia|Chordata', name: 'Chordata', rank: 'phylum', common_names: [], children: [] },
    ];
    let callCount = 0;
    global.fetch = vi.fn().mockImplementation((url) => {
      callCount++;
      if (url.includes('root')) return Promise.resolve({ ok: true, json: async () => kingdoms });
      return Promise.resolve({ ok: true, json: async () => phyla });
    });

    document.body.innerHTML = '<div id="expand-tree" style="width:800px;height:600px"></div>';
    await initTree('expand-tree');

    // Reset count after initTree's initial fetch
    const countAfterInit = callCount;
    await expandToNode('Animalia|Chordata|Mammalia');
    // Should have fetched Animalia's children (to reveal Chordata)
    expect(callCount).toBeGreaterThan(countAfterInit);
  });

  it('marks intermediate ancestors as _pathOnly to avoid loading all siblings', async () => {
    // Animalia is loaded as a kingdom; Arthropoda, Insecta are not yet expanded.
    // Searching for a deep species should NOT load all siblings at every level.
    const kingdoms = [
      { node_id: 'K', name: 'K', rank: 'kingdom', common_names: [], children: [] },
    ];
    // /api/taxonomy/node responses for injected ancestors
    const nodeResponses = {
      'K|P':     { node_id: 'K|P', name: 'P', rank: 'phylum',  common_names: [], children: [] },
      'K|P|C':   { node_id: 'K|P|C', name: 'C', rank: 'class', common_names: [], children: [] },
      'K|P|C|G': { node_id: 'K|P|C|G', name: 'G', rank: 'genus', common_names: [], children: [] },
      // target leaf
      'K|P|C|G|Sp': { node_id: 'K|P|C|G|Sp', name: 'Sp', rank: 'species', common_names: [], children: [] },
    };
    // direct parent (G) zoom response
    const genusZoom = [
      { node_id: 'K|P|C|G|Sp', name: 'Sp', rank: 'species', common_names: [], children: [] },
      { node_id: 'K|P|C|G|Sp2', name: 'Sp2', rank: 'species', common_names: [], children: [] },
    ];
    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('root')) return Promise.resolve({ ok: true, json: async () => kingdoms });
      // Direct parent load (zoom for genus G)
      if (url.includes('zoom') && url.includes('K%7CP%7CC%7CG'))
        return Promise.resolve({ ok: true, json: async () => genusZoom });
      // Node lookups for ancestors
      for (const [id, data] of Object.entries(nodeResponses)) {
        if (url.includes(encodeURIComponent(id)))
          return Promise.resolve({ ok: true, json: async () => data });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    document.body.innerHTML = '<div id="pt-tree" style="width:800px;height:600px"></div>';
    await initTree('pt-tree');

    await expandToNode('K|P|C|G|Sp');

    // The K kingdom node in the root should now have only P as a child
    // (focused navigation — siblings of K were not loaded)
    const rootKingdom = (await import('../js/visualizer.js')).default;
    // We can't easily inspect _rootData directly, but we verify via fetch:
    // zoom should only have been called ONCE (for the direct parent G), not for P or C
    const zoomCalls = global.fetch.mock.calls.filter(([url]) => url.includes('zoom') && !url.includes('root'));
    expect(zoomCalls).toHaveLength(1);
    expect(zoomCalls[0][0]).toContain('K%7CP%7CC%7CG');
  });

  it('drills through alpha group automatically when navigating to a species', async () => {
    const kingdoms = [{ node_id: 'K', name: 'K', rank: 'kingdom', common_names: [], children: [] }];
    const kAlpha   = [{ node_id: '__alpha__K|A', name: '[A] (2)', rank: 'alpha', common_names: [], children: [] }];
    const alphaA   = [{ node_id: 'K|Apis', name: 'Apis', rank: 'genus', common_names: [], children: [] }];
    const apisKids = [
      { node_id: 'K|Apis|Apis cerana',    name: 'Apis cerana',    rank: 'species', common_names: [], children: [] },
      { node_id: 'K|Apis|Apis mellifera', name: 'Apis mellifera', rank: 'species', common_names: [], children: [] },
    ];

    global.fetch = vi.fn().mockImplementation((url) => {
      if (url.includes('root'))
        return Promise.resolve({ ok: true, json: async () => kingdoms });
      if (url.includes('zoom') && url.includes('node_id=K&'))
        return Promise.resolve({ ok: true, json: async () => kAlpha });
      if (url.includes('alpha') && url.includes('letter=A'))
        return Promise.resolve({ ok: true, json: async () => alphaA });
      if (url.includes('zoom') && url.includes('K%7CApis'))
        return Promise.resolve({ ok: true, json: async () => apisKids });
      // node injection fallback
      return Promise.resolve({ ok: true, json: async () => apisKids[0] });
    });

    document.body.innerHTML = '<div id="alpha-drill" style="width:800px;height:600px"></div>';
    await initTree('alpha-drill');

    await expandToNode('K|Apis|Apis cerana');

    // /api/taxonomy/alpha must have been called for letter A
    const alphaCalls = global.fetch.mock.calls.filter(([url]) => url.includes('/api/taxonomy/alpha'));
    expect(alphaCalls.length).toBeGreaterThanOrEqual(1);
    expect(alphaCalls[0][0]).toContain('letter=A');

    // zoom for direct parent Apis must have been called once
    const parentCalls = global.fetch.mock.calls.filter(
      ([url]) => url.includes('zoom') && url.includes('K%7CApis') && !url.includes('K%7CApis%7C')
    );
    expect(parentCalls).toHaveLength(1);
  });
});

// ── initTree (integration smoke test) ───────────────────────────────────────

describe('initTree', () => {
  it('appends an SVG into the container and renders kingdom nodes', async () => {
    const kingdoms = [
      { node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [] },
      { node_id: 'Plantae',  name: 'Plantae',  rank: 'kingdom', common_names: [], children: [] },
    ];
    global.fetch = mockFetch(kingdoms);

    document.body.innerHTML = '<div id="tree" style="width:800px;height:600px"></div>';
    await initTree('tree');

    // SVG should exist
    expect(document.querySelector('#tree svg')).not.toBeNull();
    // At least one circle rendered (root + kingdoms)
    const circles = document.querySelectorAll('#tree circle');
    expect(circles.length).toBeGreaterThanOrEqual(2);
  });
});

// ── Extinct taxa (Increment 13) ─────────────────────────────────────────────

describe('treeLabel', () => {
  it('prefixes extinct taxa with a dagger', () => {
    expect(treeLabel({ name: 'Tapirus merriami', common_names: [], extinct: true }))
      .toBe('† Tapirus merriami');
  });

  it('leaves living and unknown taxa unmarked', () => {
    expect(treeLabel({ name: 'Tapirus terrestris', common_names: ['Lowland Tapir'], extinct: false }))
      .toBe('Lowland Tapir');
    expect(treeLabel({ name: 'Tapirus webbi', common_names: [], extinct: null })).toBe('Tapirus webbi');
  });

  it('uses the scientific name for path-only nodes', () => {
    expect(treeLabel({ name: 'Teleolophus', common_names: ['x'], _pathOnly: true, extinct: true }))
      .toBe('† Teleolophus');
  });
});

describe('visibleChildren', () => {
  const kid = (id, extinct) => ({ node_id: `T|${id}`, name: id, extinct });
  const parent = { node_id: 'T', children: [kid('a', true), kid('b', false), kid('c', null), kid('d', true)] };

  it('returns all children when not hiding', () => {
    expect(visibleChildren(parent, false)).toBe(parent.children);
  });

  it('drops extinct children and adds a placeholder with the count', () => {
    const out = visibleChildren(parent, true);
    expect(out.map(c => c.name)).toEqual(['b', 'c', '† 2 extinct hidden']);
    expect(out[2]).toMatchObject({ node_id: '__hidden__T', rank: 'hidden', children: null });
  });

  it('keeps an extinct child that is on the selected path', () => {
    const out = visibleChildren(parent, true, ['T|d|species']);
    expect(out.map(c => c.name)).toEqual(['b', 'c', 'd', '† 1 extinct hidden']);
  });

  it('adds no placeholder when nothing is extinct', () => {
    const living = { node_id: 'L', children: [kid('x', false)] };
    expect(visibleChildren(living, true)).toBe(living.children);
  });

  it('passes collapsed nodes through', () => {
    expect(visibleChildren({ node_id: 'Z', children: null }, true)).toBeNull();
  });
});

describe('setNodeExtinct', () => {
  beforeEach(async () => {
    const kingdoms = [{ node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [] }];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => kingdoms });
    document.body.innerHTML = '<div id="ext-tree" style="width:800px;height:600px"></div>';
    await initTree('ext-tree');
  });

  const label = () => document.querySelector('g[data-node-id="Animalia"] text').textContent;

  it('adds the dagger to a loaded node once its flag is learned', () => {
    expect(setNodeExtinct('Animalia', true)).toBe(true);
    expect(label()).toBe('† Animalia');
  });

  it('ignores unknown values and unchanged flags', () => {
    expect(setNodeExtinct('Animalia', null)).toBe(false);
    expect(setNodeExtinct('Animalia', false)).toBe(true);
    expect(setNodeExtinct('Animalia', false)).toBe(false);
    expect(label()).toBe('Animalia');
  });

  it('ignores nodes that are not loaded', () => {
    expect(setNodeExtinct('Animalia|Chordata', true)).toBe(false);
  });
});

describe('refreshAncestorFlags', () => {
  const tree = (extinctByPath) => vi.fn(async (url) => {
    if (url.endsWith('/api/taxonomy/root')) {
      return { ok: true, json: async () => [{
        node_id: 'Animalia', name: 'Animalia', rank: 'kingdom', common_names: [], children: [
          { node_id: 'Animalia|Fam', name: 'Fam', rank: 'family', common_names: [], children: [
            { node_id: 'Animalia|Fam|Gen', name: 'Gen', rank: 'genus', common_names: [], children: [] }] }] }] };
    }
    const id = decodeURIComponent(url.split('node_id=')[1]);
    return { ok: true, json: async () => ({ node_id: id, extinct: extinctByPath[id] ?? null }) };
  });
  const label = id => document.querySelector(`g[data-node-id="${id}"] text`).textContent;

  async function init(extinctByPath) {
    global.fetch = tree(extinctByPath);
    document.body.innerHTML = '<div id="anc-tree" style="width:800px;height:600px"></div>';
    await initTree('anc-tree');
  }

  it('marks ancestors the backend now reports as extinct, nearest first', async () => {
    await init({ 'Animalia|Fam|Gen': true, 'Animalia|Fam': false });
    await refreshAncestorFlags('Animalia|Fam|Gen|Gen sp');
    expect(label('Animalia|Fam|Gen')).toBe('† Gen');
    expect(label('Animalia|Fam')).toBe('Fam');
  });

  it('stops at the first living ancestor and never asks about the kingdom', async () => {
    await init({ 'Animalia|Fam|Gen': false });
    await refreshAncestorFlags('Animalia|Fam|Gen|Gen sp');
    const asked = global.fetch.mock.calls.map(c => c[0]).filter(u => u.includes('/node?'));
    expect(asked).toHaveLength(1);
  });
});

// ── taxonDescription ────────────────────────────────────────────────────────

describe('taxonDescription', () => {
  it('describes a class, whatever the case of the name', () => {
    expect(taxonDescription('Insecta')).toMatch(/insects/i);
    expect(taxonDescription('insecta')).toBe(taxonDescription('Insecta'));
  });

  it('still describes phyla', () => {
    expect(taxonDescription('Arthropoda')).toMatch(/largest animal phylum/);
  });

  it('keeps class entries that predate the class table', () => {
    expect(taxonDescription('Chytridiomycetes')).toMatch(/chytrids/);
  });

  it('returns undefined for taxa with no description', () => {
    expect(taxonDescription('Apidae')).toBeUndefined();
    expect(taxonDescription('')).toBeUndefined();
    expect(taxonDescription(undefined)).toBeUndefined();
  });

  it('does not treat Object.prototype members as descriptions', () => {
    expect(taxonDescription('constructor')).toBeUndefined();
  });

  it.each(['Bacteroidota', 'Desulfobacterota', 'Dicyemida', 'Ochrophyta', 'Sipuncula',
           'Spirochaetota', 'Thermoproteota'])('describes the phylum %s', (name) => {
    expect(taxonDescription(name)).toEqual(expect.any(String));
  });

  it('finds Krumholzibacteriota under its database spelling', () => {
    expect(taxonDescription('Krumholzibacteriota')).toEqual(expect.any(String));
    expect(taxonDescription('Krumholzbacteriota')).toBeUndefined();
  });
});
