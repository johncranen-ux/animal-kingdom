// Species-panel trait rows and the on-demand trait lookup (Increment 12).
// Pure helpers live here so they can be unit-tested; app.js wires them to the DOM.

// Covers the slowest server path: sourced stage (8 s) + LLM estimate (60 s) + lock waits
export const TRAITS_FETCH_TIMEOUT_MS = 90000;

const STAGES = ['sourced', 'estimated'];

// [label, field] in panel order — keep in sync with what users already know
const TRAIT_ROWS = [
  ['Taxonomic status',  'taxonomic_status'],
  ['IUCN status',       'iucn_status'],
  ['Population trend',  'population_trend'],
  ['Habitat',           'habitat_type'],
  ['Trophic level',     'trophic_level'],
  ['Activity period',   'activity_period'],
  ['Elevation limits',  'elevation_limits'],
  ['Body mass (kg)',    'body_mass'],
  ['Body length (m)',   'body_length'],
  ['Max lifespan (yr)', 'max_lifespan'],
  ['Metabolic rate',    'metabolic_rate'],
  ['Reproduction',      'reproduction_strategy'],
  ['Range',             'geo_bounding_box'],
];

const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, ch => HTML_ESCAPES[ch]);
}

// IUCN status first; fossils have none, so fall back to the GBIF flag
export function extinctLabel(sp) {
  if (sp.iucn_status === 'EX') return 'extinct';
  if (sp.iucn_status === 'EW') return 'extinct in the wild';
  return sp.extinct ? 'extinct' : '';
}

// Panel subtitle under the name: "species · extinct"
export function rankLine(sp) {
  return [sp.taxon_rank, extinctLabel(sp)].filter(Boolean).join(' · ');
}

// Search dropdown entry; ranks other than species, extinct taxa and old names are
// tagged ("wombats — Vombatidae (family)", "Tapirus indicus (old name of Acrocodia indica)")
export function searchResultLabel(item) {
  const name = escapeHtml(item.scientific_name);
  const tags = [item.taxon_rank !== 'species' && item.taxon_rank, extinctLabel(item),
                item.accepted_name && `old name of ${item.accepted_name}`].filter(Boolean);
  const tag  = tags.length ? ` <span class="text-gray-400">(${escapeHtml(tags.join(', '))})</span>` : '';
  return item.common_names?.length
    ? `${escapeHtml(item.common_names[0])} — <em class="text-gray-300">${name}</em>${tag}`
    : `<em>${name}</em>${tag}`;
}

// Panel row linking an old name to the taxon it now belongs to (Increment 30);
// app.js opens the link like a search result. '' for a current name.
export function currentNameHtml(sp) {
  const cur = sp?.current_name;
  if (!cur?.scientific_name) return '';
  const sci  = `<em>${escapeHtml(cur.scientific_name)}</em>`;
  const text = cur.common_name ? `${escapeHtml(cur.common_name)} — ${sci}` : sci;
  const src  = cur.source ? ` <span class="text-gray-400">(${escapeHtml(cur.source)})</span>` : '';
  return `<div class="flex gap-1.5">
       <span class="text-gray-400 shrink-0 w-28">Current name</span>
       <span class="text-gray-200 break-words"><a href="#" class="taxon-link" data-current-name>${text}</a>${src}</span>
     </div>`;
}

// Three significant figures without exponent notation (Wikidata 6.2 oz → 0.176 kg)
export function formatTraitValue(v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return v == null ? '' : String(v);
  if (v === 0) return '0';
  const decimals = Math.max(0, 2 - Math.floor(Math.log10(Math.abs(v))));
  const text = v.toFixed(decimals);
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text;
}

// Same text as the chat's lookup (llm_agent._range_text). A range across the
// 180° line keeps only its latitudes.
function _rangeText(v) {
  if (v == null || v.lat_min == null || v.lat_max == null) return null;
  let text = `lat ${v.lat_min}–${v.lat_max}`;
  text += v.lon_min != null && v.lon_max != null
    ? `, lon ${v.lon_min}–${v.lon_max}`
    : ', longitude not recorded (range crosses the 180° line)';
  if (v.records) text += ` (${String(v.records).replace(/\B(?=(\d{3})+(?!\d))/g, ',')} wild records)`;
  return text;
}

function _displayValue(sp, field) {
  const v = sp[field];
  if (field === 'geo_bounding_box') return _rangeText(v);
  return v == null || v === '' ? null : formatTraitValue(v);
}

// hide: fields shown another way (the range box once the range map is up)
export function traitRowsHtml(sp, provenance = {}, hide = []) {
  provenance = provenance || {};
  return TRAIT_ROWS.map(([label, field]) => {
    if (hide.includes(field)) return '';
    const val = _displayValue(sp, field);
    if (val == null || val === '') return '';
    const prov  = provenance[field];
    const title = prov
      ? ` title="${escapeHtml(`Source: ${prov.source}${prov.estimated ? ' (estimated)' : ''}`)}"`
      : '';
    const badge = prov?.estimated ? ' <span class="trait-est">est.</span>' : '';
    return `<div class="flex gap-1.5"${title}>
         <span class="trait-label text-gray-400 shrink-0 w-28">${escapeHtml(label)}</span>
         <span class="text-gray-200 break-words">${escapeHtml(val)}${badge}</span>
       </div>`;
  }).join('');
}

export function nextTraitStage(sp) {
  if (!sp?.trait_eligible) return null;
  if (!sp.traits_sourced) return 'sourced';
  if (!sp.traits_estimated) return 'estimated';
  return null;
}

export function traitsUrl(api, scientificName, stage) {
  return `${api}/api/species/${encodeURIComponent(scientificName)}/traits?stage=${stage}`;
}

// True while the species panel still shows `name` (guards against stale responses)
export function panelShows(name, doc = document) {
  const el = doc.getElementById('sp-name');
  return !!el && el.textContent === name;
}

async function _fetchJson(fetchImpl, url) {
  const ctrl  = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TRAITS_FETCH_TIMEOUT_MS);
  try {
    const resp = await fetchImpl(url, { signal: ctrl.signal });
    return resp.ok ? await resp.json() : null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Fill missing traits: request each outstanding stage once, in order, merging
 * every response into `sp` and handing it to onData. Stops quietly on a network
 * error or timeout; does nothing at all once isCurrent() turns false.
 */
export async function loadTraits(sp, { api, fetchImpl = fetch, isCurrent, onData, onDone }) {
  for (const stage of STAGES) {
    if (!sp.trait_eligible) break;
    if (stage === 'sourced' && sp.traits_sourced) continue;
    if (stage === 'estimated' && sp.traits_estimated) continue;
    // Estimates read the abstract the sourced stage fetches — retry on next open
    if (stage === 'estimated' && !sp.traits_sourced) break;
    let data;
    try {
      data = await _fetchJson(fetchImpl, traitsUrl(api, sp.scientific_name, stage));
    } catch {
      data = null;
    }
    if (!isCurrent()) return;
    if (!data) break;
    Object.assign(sp, data.values || {});
    sp.provenance       = { ...(sp.provenance || {}), ...(data.provenance || {}) };
    sp.traits_sourced   = !!data.traits_sourced;
    sp.traits_estimated = !!data.traits_estimated;
    sp.trait_eligible   = data.trait_eligible ?? sp.trait_eligible;
    // Wikidata may link an old name the Catalogue of Life keeps as accepted
    sp.current_name     = data.current_name ?? sp.current_name;
    onData(sp);
  }
  onDone();
}
