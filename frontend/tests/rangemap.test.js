import { describe, it, expect, vi, afterEach } from 'vitest';
import * as d3 from 'd3';
import { countryName, rangeCaptionHtml, rangeUrl, hasRange, mapBounds, zoomFeatures, mapProjection, drawRangeMap, loadWorld, _resetWorld } from '../js/rangemap.js';

const sq = (code, x0, y0, x1, y1) => ({
  type: 'Feature', properties: { code, name: `Land ${code}` },
  // clockwise outer ring (d3-geo winding)
  geometry: { type: 'MultiPolygon', coordinates: [[[[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]]] },
});
const WORLD = { type: 'FeatureCollection', features: [
  sq('IN', 70, 10, 90, 30), sq('CN', 90, 20, 120, 45), sq('US', -120, 30, -80, 48), sq('BR', -70, -30, -40, 0),
] };
const SNOW = {
  native: [{ code: 'IN', name: 'India', records: 97 }, { code: 'CN', name: 'China', records: 59 }],
  elsewhere: [{ code: 'US', name: 'United States of America', records: 6 }],
};

afterEach(() => { document.body.innerHTML = ''; _resetWorld(); });

describe('rangeUrl / hasRange', () => {
  it('encodes the row key', () => {
    expect(rangeUrl('http://x', 'Bacteria laesa [Phasmatidae]'))
      .toBe('http://x/api/species/Bacteria%20laesa%20%5BPhasmatidae%5D/range');
  });
  it('needs at least one native country', () => {
    expect(hasRange(SNOW)).toBe(true);
    expect(hasRange({ native: [], elsewhere: SNOW.elsewhere })).toBe(false);
    expect(hasRange(null)).toBe(false);
  });
});

describe('countryName', () => {
  it('keeps the backend name and names a bare code', () => {
    expect(countryName({ code: 'IN', name: 'India' })).toBe('India');
    expect(countryName({ code: 'GI', name: 'GI' })).toBe('Gibraltar');
    expect(countryName({ code: 'QQ', name: 'QQ' })).toBeTruthy();
  });
});

describe('rangeCaptionHtml', () => {
  it('names the native countries with records and the strays', () => {
    const html = rangeCaptionHtml(SNOW);
    expect(html).toContain('Wild records in 2 countries');
    expect(html).toContain('India (97)');
    expect(html).toContain('China (59)');
    expect(html).toContain('Also recorded in');
    expect(html).toContain('United States of America (6)');
  });

  it('shortens long lists and uses the singular', () => {
    const many = { native: Array.from({ length: 9 }, (_, i) => ({ code: `C${i}`, name: `Land ${i}`, records: 100 - i })),
                   elsewhere: [] };
    const html = rangeCaptionHtml(many);
    expect(html).toContain('Land 0 (100)');
    expect(html).toContain('and 4 more');
    expect(html).not.toContain('Land 8');
    expect(html).not.toContain('Also recorded');
    expect(rangeCaptionHtml({ native: [SNOW.native[0]], elsewhere: [] })).toContain('Wild records in 1 country:');
  });

  it('formats thousands and escapes names', () => {
    const html = rangeCaptionHtml({ native: [{ code: 'XX', name: '<b>X</b>', records: 12345 }], elsewhere: [] });
    expect(html).toContain('&lt;b&gt;X&lt;/b&gt; (12,345)');
  });
});

describe('mapBounds', () => {
  it('pads a small range to a minimum span', () => {
    const [[x0, y0], [x1, y1]] = mapBounds([[70, 10], [90, 30]]);
    expect(x1 - x0).toBeGreaterThanOrEqual(40);
    expect(y1 - y0).toBeGreaterThanOrEqual(25);
    expect(x0).toBeLessThan(70); expect(x1).toBeGreaterThan(90);
  });
  it('keeps a range across the 180° line in one piece', () => {
    const [[x0], [x1]] = mapBounds([[170, -20], [-170, 10]]);
    expect(x0).toBeLessThan(170); expect(x1).toBeGreaterThan(190);
    expect(x1 - x0).toBeLessThan(60);
  });
  it('gives the whole world for a range wider than half the globe', () => {
    expect(mapBounds([[-170, -50], [175, 70]])).toBeNull();
    expect(mapBounds([[95, -11], [-67, 50]])).toBeNull();   // Indonesia to the USA
  });
  it('stays inside the latitudes of the map', () => {
    const [[, y0], [, y1]] = mapBounds([[-60, 60], [-20, 84]]);
    expect(y1).toBeLessThanOrEqual(85); expect(y0).toBeGreaterThanOrEqual(-85);
  });
});

describe('zoomFeatures', () => {
  it('leaves out huge countries unless nothing else is left', () => {
    const ru = sq('RU', 27, 41, 179, 77);
    expect(zoomFeatures([sq('IN', 70, 10, 90, 30), ru]).map(f => f.properties.code)).toEqual(['IN']);
    expect(zoomFeatures([ru])).toEqual([ru]);
  });
  it('zooms to the main part of a country spread over the globe', () => {
    // Mainland USA plus the Aleutians across the 180° line
    const us = { type: 'Feature', properties: { code: 'US' }, geometry: { type: 'MultiPolygon', coordinates: [
      sq('US', -125, 25, -67, 49).geometry.coordinates[0],
      sq('US', 172, 51, 179, 53).geometry.coordinates[0],
    ] } };
    const zoom = zoomFeatures([us, sq('ID', 95, -11, 141, 6)]);
    expect(zoom.length).toBe(2);
    const [[x0], [x1]] = d3.geoBounds(zoom[0]);
    expect([Math.round(x0), Math.round(x1)]).toEqual([-125, -67]);
  });
  it('keeps a small country across the 180° line', () => {
    const fj = sq('FJ', 177, -18, 181, -16);
    expect(zoomFeatures([fj])).toEqual([fj]);
  });
});

describe('mapProjection', () => {
  const inside = (proj, pt, w = 256, h = 150) => {
    const [x, y] = proj(pt);
    return x >= 0 && x <= w && y >= 0 && y <= h;
  };
  it('shows every native country, also across the Pacific', () => {
    const world = { type: 'FeatureCollection', features: [
      sq('US', -125, 25, -67, 49), sq('ID', 95, -11, 141, 6), sq('PH', 117, 5, 127, 19), sq('BR', -70, -30, -40, 0)] };
    const range = { native: [{ code: 'US', records: 125 }, { code: 'ID', records: 22 }, { code: 'PH', records: 5 }] };
    const proj = mapProjection(world, range, 256, 150);
    for (const pt of [[-96, 37], [118, -2], [122, 12]]) expect(inside(proj, pt)).toBe(true);
  });
  it('centres a range across the 180° line', () => {
    const world = { type: 'FeatureCollection', features: [sq('FJ', 177, -18, 181, -16), sq('IN', 70, 10, 90, 30)] };
    const proj = mapProjection(world, { native: [{ code: 'FJ', records: 3 }] }, 256, 150);
    const [x] = proj([179, -17]);
    expect(Math.abs(x - 128)).toBeLessThan(20);
    expect(inside(proj, [80, 20])).toBe(false);
  });
});

describe('drawRangeMap', () => {
  it('shades native countries, outlines strays and labels them on hover', () => {
    const el = document.createElement('div');
    drawRangeMap(el, WORLD, SNOW, { width: 256, height: 150 });
    const native = el.querySelectorAll('path.range-native');
    const stray = el.querySelectorAll('path.range-stray');
    expect(native.length).toBe(2);
    expect(stray.length).toBe(1);
    expect(el.querySelectorAll('path.range-land').length).toBe(1);   // BR
    const titles = [...el.querySelectorAll('path.range-native title')].map(t => t.textContent);
    expect(titles).toContain('India: 97 wild records');
    // more records, stronger colour
    const fill = code => [...native].find(p => p.dataset.code === code).getAttribute('fill');
    expect(fill('IN')).not.toBe(fill('CN'));
  });

  it('replaces an earlier map', () => {
    const el = document.createElement('div');
    drawRangeMap(el, WORLD, SNOW, { width: 256, height: 150 });
    drawRangeMap(el, WORLD, SNOW, { width: 256, height: 150 });
    expect(el.querySelectorAll('svg').length).toBe(1);
  });
});

describe('loadWorld', () => {
  it('fetches the outlines once', async () => {
    const fetchImpl = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(WORLD) }));
    await loadWorld('http://x', fetchImpl);
    const again = await loadWorld('http://x', fetchImpl);
    expect(again).toBe(WORLD);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledWith('http://x/data/world.json');
  });
  it('tries again after a failure', async () => {
    const bad = vi.fn(() => Promise.resolve({ ok: false, status: 500 }));
    expect(await loadWorld('http://x', bad)).toBeNull();
    const good = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(WORLD) }));
    expect(await loadWorld('http://x', good)).toBe(WORLD);
  });
});
