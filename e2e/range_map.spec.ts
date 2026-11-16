import { test, expect, Page, Route } from '@playwright/test';

// Increment 34: the species panel's range map. Route-mocked API (no DB, no online
// sources); the country outlines are the real frontend/data/world.json.
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const BOX = { lat_min: 27.55, lat_max: 49.87, lon_min: -122.47, lon_max: 103.9, records: 242 };
const RANGES: Record<string, unknown> = {
  'Panthera uncia': {
    native: [{ code: 'IN', name: 'India', records: 97 }, { code: 'CN', name: 'China', records: 59 },
             { code: 'MN', name: 'Mongolia', records: 45 }],
    elsewhere: [{ code: 'US', name: 'United States of America', records: 6 }],
  },
  'Panthera onca': { native: [], elsewhere: [] },
};

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(page: Page) {
  await page.route(/\/api\/search\?/, route => {
    const q = new URL(route.request().url()).searchParams.get('q');
    return json(route, [{ scientific_name: q, common_names: [], taxon_rank: 'species',
                          taxon_path: `Animalia|${q}`, taxonomic_status: 'ACCEPTED' }]);
  });
  await page.route(/\/api\/species\/[^/]+\/image/, route => json(route, { url: PIXEL, attribution: 'test image' }));
  await page.route(/\/api\/species\/[^/]+\/range$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').slice(-2)[0]);
    return json(route, RANGES[name]);
  });
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, {
      scientific_name: name, taxon_rank: 'species', common_names: [], taxonomic_status: 'ACCEPTED',
      taxon_path: `Animalia|${name}`, primary_image_url: null, geo_bounding_box: BOX, body_mass: 50,
      provenance: {}, trait_eligible: true, traits_sourced: true, traits_estimated: true,
    });
  });
}

async function open(page: Page, name: string) {
  await page.fill('#search-input', name);
  await page.locator('#search-results li').first().click();
  await expect(page.locator('#sp-name')).toHaveText(name);
}

test('the panel maps the native range and lists the strays instead of the range box', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await open(page, 'Panthera uncia');

  const map = page.locator('#sp-range svg.range-map');
  await expect(map).toBeVisible();
  await expect(page.locator('#sp-range path.range-native')).toHaveCount(3);
  await expect(page.locator('#sp-range path.range-stray[data-code="US"]')).toHaveCount(1);
  await expect(page.locator('#sp-range')).toContainText('Wild records in 3 countries: India (97), China (59), Mongolia (45)');
  await expect(page.locator('#sp-range')).toContainText('Also recorded in United States of America (6)');
  await expect(page.locator('#sp-fields')).not.toContainText('lat 27.55');
  await expect(page.locator('#sp-fields')).toContainText('Body mass');
});

test('a species without country records keeps the range box and gets no map', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await open(page, 'Panthera uncia');
  await expect(page.locator('#sp-range svg')).toBeVisible();

  await open(page, 'Panthera onca');
  await expect(page.locator('#sp-fields')).toContainText('lat 27.55');
  await expect(page.locator('#sp-range')).toHaveCount(0);
});
