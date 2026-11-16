import { test, expect, Page, Route } from '@playwright/test';

// Increment 32: "Other pictures" shows candidates from every source; the clicked one is kept.
// Route-mocked, like picture_retry.spec.ts: no online sources, no DB writes.
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const RED = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const CANDIDATES = [
  { url: RED, attribution: '(c) goat photographer', source: 'iNaturalist' },
  { url: 'https://broken.invalid/x.jpg', attribution: 'broken', source: 'DuckDuckGo' },
];

function record(name: string) {
  return {
    scientific_name: name, taxon_rank: 'species', common_names: [], taxonomic_status: 'ACCEPTED',
    taxon_path: `Animalia|${name}`, primary_image_url: PIXEL, image_attribution: '© snake picture',
    provenance: {}, trait_eligible: true, traits_sourced: true, traits_estimated: true, current_name: null,
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(page: Page, candidates: (route: Route) => Promise<void> | void, puts: string[] = []) {
  await page.route(/\/api\/search\?/, route => {
    const q = new URL(route.request().url()).searchParams.get('q') || '';
    return json(route, [{ scientific_name: q, common_names: [], taxon_rank: 'species',
                          taxon_path: `Animalia|${q}`, taxonomic_status: 'ACCEPTED' }]);
  });
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, record(name));
  });
  await page.route(/\/api\/species\/[^/]+\/image$/, route => {
    if (route.request().method() !== 'PUT') return json(route, { detail: 'x' }, 404);
    puts.push(route.request().url());
    return json(route, route.request().postDataJSON());
  });
  await page.route(/\/api\/species\/[^/]+\/image\/candidates$/, candidates);
}

async function open(page: Page, name: string) {
  await page.fill('#search-input', name);
  await page.locator('#search-results li').first().click();
  await expect(page.locator('#sp-name')).toHaveText(name);
}

test('Other pictures shows candidates and keeps the one clicked', async ({ page }) => {
  const puts: string[] = [];
  await mockApi(page, route => json(route, { candidates: CANDIDATES, unavailable: false }), puts);
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await expect(page.locator('#sp-image')).toHaveAttribute('src', PIXEL);
  await page.locator('button[data-picture-choose]').click();
  const choice = page.locator('#sp-picture-choice');
  await expect(choice.locator('button[data-candidate]')).toHaveCount(1);   // the broken one is removed
  await expect(choice).toContainText('iNaturalist');
  await expect(page.locator('#sp-image')).toBeHidden();
  await choice.locator('button[data-candidate]').first().click();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', RED);
  await expect(page.locator('#sp-attr')).toHaveText('(c) goat photographer');
  await expect(choice).toBeHidden();
  expect(puts).toEqual([expect.stringContaining('/api/species/Oreamnos%20americanus/image')]);
});

test('no candidates says so, and Cancel brings the picture back', async ({ page }) => {
  await mockApi(page, route => json(route, { candidates: [], unavailable: false }));
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  await expect(page.locator('#sp-picture-choice')).toContainText('No other pictures found.');
  await page.locator('#sp-picture-choice button[data-picture-cancel]').click();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', PIXEL);
  await expect(page.locator('#sp-image')).toBeVisible();
  await expect(page.locator('#sp-attr')).toHaveText('© snake picture');
});

test('candidates that arrive after switching animals are not shown', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  await mockApi(page, async route => { await held; await json(route, { candidates: CANDIDATES, unavailable: false }); });
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  await expect(page.locator('#sp-picture-choice')).toContainText('Looking for pictures…');
  await open(page, 'Capra ibex');
  const late = page.waitForResponse(r => r.url().endsWith('/image/candidates'));
  release();
  await late;
  await expect(page.locator('#sp-picture-choice')).toBeHidden();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', PIXEL);
});

const GREEN = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';

test('a choice survives a slow first lookup that finishes afterwards', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  await mockApi(page, route => json(route, { candidates: CANDIDATES, unavailable: false }));
  // registered later, so these run first: no stored picture, and a slow automatic lookup
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, { ...record(name), primary_image_url: null, image_attribution: null });
  });
  await page.route(/\/api\/species\/[^/]+\/image(\?.*)?$/, async route => {
    if (route.request().method() === 'PUT') return route.fallback();
    await held;
    await json(route, { url: PIXEL, attribution: 'automatic' });
  });
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  await page.locator('#sp-picture-choice button[data-candidate]').first().click();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', RED);
  const lookup = page.waitForResponse(r => r.url().endsWith('/image') && r.request().method() === 'GET');
  release();
  await lookup;
  await expect(page.locator('#sp-image')).toHaveAttribute('src', RED);
  await expect(page.locator('#sp-attr')).toHaveText('(c) goat photographer');
});

test('two quick clicks keep one picture', async ({ page }) => {
  const puts: string[] = [];
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  await mockApi(page, route => json(route, { candidates: [
    { url: RED, attribution: 'red', source: 'iNaturalist' },
    { url: GREEN, attribution: 'green', source: 'Commons' }], unavailable: false }), puts);
  await page.route(/\/api\/species\/[^/]+\/image$/, async route => {
    if (route.request().method() !== 'PUT') return route.fallback();
    puts.push(route.request().url());
    await held;
    await json(route, route.request().postDataJSON());
  });
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  const items = page.locator('#sp-picture-choice button[data-candidate]');
  await expect(items).toHaveCount(2);
  await items.nth(0).click();
  await items.nth(1).click();
  release();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', RED);
  expect(puts.length).toBe(1);
});

// --- Increment 33 ---

test('a failed save keeps the thumbnails and says so', async ({ page }) => {
  await mockApi(page, route => json(route, { candidates: CANDIDATES, unavailable: false }));
  await page.route(/\/api\/species\/[^/]+\/image$/, route =>
    route.request().method() === 'PUT' ? json(route, { detail: 'x' }, 500) : route.fallback());
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  const choice = page.locator('#sp-picture-choice');
  await choice.locator('button[data-candidate]').first().click();
  await expect(choice.locator('[data-gallery-note]')).toHaveText("Couldn't keep that picture. Try again.");
  await expect(choice.locator('button[data-candidate]')).toHaveCount(1);
  await expect(page.locator('#sp-image')).toBeHidden();
});

test('pictures from the sources that answered in time come with a note', async ({ page }) => {
  await mockApi(page, route => json(route, { candidates: CANDIDATES, unavailable: true }));
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await page.locator('button[data-picture-choose]').click();
  const choice = page.locator('#sp-picture-choice');
  await expect(choice.locator('[data-gallery-note]')).toHaveText(
    'Some picture sources were too slow. Other pictures again may find more.');
  await expect(choice.locator('button[data-candidate]')).toHaveCount(1);
});

test('a stored picture that fails to load is skipped by the new lookup', async ({ page }) => {
  const DEAD = 'https://broken.invalid/dead.jpg';
  const lookups: string[] = [];
  await mockApi(page, route => json(route, { candidates: [], unavailable: false }));
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, { ...record(name), primary_image_url: DEAD });
  });
  await page.route(/\/api\/species\/[^/]+\/image\?/, route => {
    lookups.push(route.request().url());
    return json(route, { url: GREEN, attribution: 'replacement' });
  });
  await page.goto('/');
  await open(page, 'Oreamnos americanus');
  await expect(page.locator('#sp-image')).toHaveAttribute('src', GREEN);
  const params = new URL(lookups[0]).searchParams;
  expect(params.get('force')).toBe('true');
  expect(params.get('failed')).toBe(DEAD);
});
