// The species panel's range map (Increment 34): countries with wild GBIF records,
// split by the backend into the native range and strays (zoos, misplaced records).
// Outlines: frontend/data/world.json, built by data/build_world_map.py from Natural Earth.
import * as d3 from 'd3';
import { escapeHtml } from './traits.js';

const LIST_MAX = 5;
const MIN_SPAN_LON = 40;
const MIN_SPAN_LAT = 25;
const MAX_LAT = 85;
const HUGE_SPAN_LON = 100;   // Russia, the USA with Alaska, Canada

export function rangeUrl(api, scientificName) {
  return `${api}/api/species/${encodeURIComponent(scientificName)}/range`;
}

export function hasRange(range) {
  return !!range?.native?.length;
}

// The backend names a country from places.json; tiny ones missing there (Gibraltar,
// Bouvet Island) come back as their code, so let the browser name them
let _regionNames = null;
export function countryName(row) {
  if (row.name && row.name !== row.code) return row.name;
  try {
    _regionNames ??= new Intl.DisplayNames(['en'], { type: 'region' });
    return _regionNames.of(row.code) || row.code;
  } catch {
    return row.code;
  }
}

const _num = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

function _list(rows) {
  const shown = rows.slice(0, LIST_MAX).map(r => `${escapeHtml(countryName(r))} (${_num(r.records)})`);
  const more = rows.length - LIST_MAX;
  return shown.join(', ') + (more > 0 ? ` and ${more} more` : '');
}

export function rangeCaptionHtml(range) {
  const n = range.native.length;
  let html = `<p class="text-gray-300">Wild records in ${n} ${n === 1 ? 'country' : 'countries'}: ${_list(range.native)}</p>`;
  if (range.elsewhere?.length) {
    html += `<p class="text-gray-400 mt-0.5">Also recorded in ${_list(range.elsewhere)}, `
          + `probably zoos or misplaced records</p>`;
  }
  return html;
}

// A box from d3.geoBounds with its east edge past 180° when it crosses that line
function _unwrap([[lon0, lat0], [lon1, lat1]]) {
  return [[lon0, lat0], [lon1 < lon0 ? lon1 + 360 : lon1, lat1]];
}

/**
 * [[lon0, lat0], [lon1, lat1]] to show around a range's bounds (d3.geoBounds),
 * padded to a minimum span; a range across the 180° line gets lon1 > 180. null =
 * show the whole world (the range covers more than half the globe).
 */
export function mapBounds(bounds) {
  const [[lon0, lat0], [lon1, lat1]] = _unwrap(bounds);
  if (lon1 - lon0 > 180) return null;
  const padLon = Math.max((MIN_SPAN_LON - (lon1 - lon0)) / 2, (lon1 - lon0) * 0.15);
  const padLat = Math.max((MIN_SPAN_LAT - (lat1 - lat0)) / 2, (lat1 - lat0) * 0.15);
  return [[lon0 - padLon, Math.max(-MAX_LAT, lat0 - padLat)],
          [lon1 + padLon, Math.min(MAX_LAT, lat1 + padLat)]];
}

const _span = f => { const [[x0], [x1]] = _unwrap(d3.geoBounds(f)); return x1 - x0; };

/**
 * What the map zooms to per native country: a country spread over the globe (the USA
 * with Alaska, the Aleutians and Hawaii) would zoom it out to the whole world, so it
 * counts with its largest part only; one still huge then (Russia) is left out unless
 * nothing else is left. Every native country is still shaded.
 */
export function zoomFeatures(features) {
  const compact = [];
  for (const f of features) {
    if (_span(f) <= HUGE_SPAN_LON) { compact.push(f); continue; }
    const parts = f.geometry.coordinates.map(rings => ({ type: 'Polygon', coordinates: rings }));
    const main = parts.reduce((a, b) => (d3.geoArea(b) > d3.geoArea(a) ? b : a));
    if (_span(main) <= HUGE_SPAN_LON) compact.push({ ...f, geometry: main });
  }
  return compact.length ? compact : features;
}

// A frame d3 can fit the projection to: the box's edges as points
function _frame([[x0, y0], [x1, y1]]) {
  const pts = [];
  for (let i = 0; i <= 8; i++) {
    const x = x0 + (x1 - x0) * i / 8, y = y0 + (y1 - y0) * i / 8;
    pts.push([x, y0], [x, y1], [x0, y], [x1, y]);
  }
  return { type: 'MultiPoint', coordinates: pts };
}

/**
 * The projection: turned so the range sits in the middle (a range across the 180°
 * line stays in one piece) and fitted to it, or to the whole world.
 */
export function mapProjection(world, range, width, height) {
  const codes = new Set(range.native.map(r => r.code));
  const nativeFeatures = world.features.filter(f => codes.has(f.properties.code));
  const raw = nativeFeatures.length
    ? d3.geoBounds({ type: 'FeatureCollection', features: zoomFeatures(nativeFeatures) })
    : null;
  const bounds = raw && mapBounds(raw);
  const [[x0], [x1]] = bounds || (raw ? _unwrap(raw) : [[0], [0]]);
  const centre = Number.isFinite(x0 + x1) ? (x0 + x1) / 2 : 0;
  return d3.geoNaturalEarth1()
    .rotate([-centre, 0])
    .fitExtent([[2, 2], [width - 2, height - 2]], bounds ? _frame(bounds) : { type: 'Sphere' });
}

export function drawRangeMap(el, world, range, { width = 256, height = 150 } = {}) {
  const records = new Map(range.native.map(r => [r.code, r]));
  const strays = new Map((range.elsewhere || []).map(r => [r.code, r]));
  const projection = mapProjection(world, range, width, height);
  const path = d3.geoPath(projection);

  const max = Math.max(...range.native.map(r => r.records), 1);
  const shade = d3.scaleSequentialLog([1, Math.max(max, 2)], d3.interpolateRgb('#134e4a', '#5eead4'));

  d3.select(el).selectAll('svg').remove();
  const svg = d3.select(el).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('width', '100%')
    .attr('class', 'range-map')
    .attr('role', 'img')
    .attr('aria-label', 'Map of the countries with wild records');
  svg.append('path').datum({ type: 'Sphere' }).attr('d', path).attr('class', 'range-sea');

  const kind = f => records.has(f.properties.code) ? 'native' : strays.has(f.properties.code) ? 'stray' : 'land';
  const order = { land: 0, stray: 1, native: 2 };   // shaded countries drawn on top
  const features = [...world.features].sort((a, b) => order[kind(a)] - order[kind(b)]);
  const sel = svg.selectAll('path.range-country').data(features).join('path')
    .attr('d', path)
    .attr('class', f => `range-country range-${kind(f)}`)
    .attr('data-code', f => f.properties.code || '')
    .attr('fill', f => kind(f) === 'native' ? shade(records.get(f.properties.code).records) : null);
  sel.filter(f => kind(f) !== 'land').append('title').text(f => {
    const r = records.get(f.properties.code) || strays.get(f.properties.code);
    return `${countryName(r)}: ${_num(r.records)} wild record${r.records === 1 ? '' : 's'}`
         + (kind(f) === 'stray' ? ' (outside the range)' : '');
  });
  return svg.node();
}

let _world = null;

export function _resetWorld() { _world = null; }

// The outlines, fetched once per page; null (and tried again next time) on a failure
export async function loadWorld(api, fetchImpl = fetch) {
  if (!_world) {
    _world = fetchImpl(`${api}/data/world.json`)
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null)
      .then(w => { if (!w) _world = null; return w; });
  }
  return _world;
}
