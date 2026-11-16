import { test, expect, Page, Route } from '@playwright/test';

// Increment 30: an old name is tagged in search and links to its current name in
// the panel. Route-mocked, like traits_panel.spec.ts: no online sources, no DB writes.
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const CURRENT = {
  scientific_name: 'Acrocodia indica', common_name: 'Malayan tapir', taxon_rank: 'species',
  taxon_path: 'Animalia|Acrocodia indica', source: 'Catalogue of Life',
};

function record(name: string) {
  const old = name === 'Tapirus indicus';
  return {
    scientific_name: name, taxon_rank: 'species', common_names: old ? ['Malayan Tapir'] : ['Malayan tapir'],
    taxonomic_status: old ? 'SYNONYM' : 'ACCEPTED', taxon_path: `Animalia|${name}`, primary_image_url: null,
    provenance: {}, trait_eligible: true, traits_sourced: true, traits_estimated: true,
    current_name: old ? CURRENT : null,
  };
}

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(page: Page) {
  await page.route(/\/api\/search\?/, route => json(route, [{
    scientific_name: 'Tapirus indicus', common_names: ['Malayan Tapir'], taxon_rank: 'species',
    taxon_path: 'Animalia|Tapirus indicus', taxonomic_status: 'SYNONYM', accepted_name: 'Acrocodia indica',
  }]));
  await page.route(/\/api\/species\/[^/]+\/image/, route => json(route, { url: PIXEL, attribution: 'test image' }));
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, record(name));
  });
}

test('an old name is tagged in search and its panel opens the current name', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await page.fill('#search-input', 'Tapirus indicus');
  const hit = page.locator('#search-results li').first();
  await expect(hit).toContainText('(old name of Acrocodia indica)');
  await hit.click();

  await expect(page.locator('#sp-name')).toHaveText('Tapirus indicus');
  const link = page.locator('#sp-fields a[data-current-name]');
  await expect(link).toHaveText('Malayan tapir — Acrocodia indica');
  await expect(page.locator('#sp-fields')).toContainText('(Catalogue of Life)');

  await link.click();
  await expect(page.locator('#sp-name')).toHaveText('Acrocodia indica');
  await expect(page.locator('#sp-fields a[data-current-name]')).toHaveCount(0);
});
