import { test, expect, Page, Route } from '@playwright/test';

// Route-mocked: the panel's trait loading is exercised without IUCN/GBIF/Ollama.
const EST = 'Estimated from Wikipedia description';
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

function record(name: string) {
  return {
    scientific_name: name, taxon_rank: 'species', common_names: [], taxonomic_status: 'ACCEPTED',
    taxon_path: `Animalia|${name}`, primary_image_url: null, provenance: {},
    trait_eligible: true, traits_sourced: false, traits_estimated: false,
  };
}

function traits(name: string, habitat: string) {
  return {
    scientific_name: name,
    values: { habitat_type: habitat, activity_period: 'nocturnal' },
    provenance: {
      habitat_type: { source: 'IUCN Red List', estimated: false },
      activity_period: { source: EST, estimated: true },
    },
    traits_sourced: true, traits_estimated: true, trait_eligible: true,
  };
}

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

async function mockSpecies(page: Page, names: string[]) {
  await page.route(/\/api\/search\?/, route => {
    const q = new URL(route.request().url()).searchParams.get('q') ?? '';
    return json(route, names.filter(n => n.toLowerCase().startsWith(q.toLowerCase()))
      .map(n => ({ scientific_name: n, common_names: [], taxon_rank: 'species', taxon_path: `Animalia|${n}` })));
  });
  await page.route(/\/api\/species\/[^/]+\/image/, route => json(route, { url: PIXEL, attribution: 'test image' }));
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, record(name));
  });
}

async function openSpecies(page: Page, name: string) {
  await page.fill('#search-input', name);
  const item = page.locator('#search-results li', { hasText: name }).first();
  await item.waitFor();
  await item.click();
  await expect(page.locator('#sp-name')).toHaveText(name);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.locator('#tree-container svg circle').first().waitFor({ timeout: 15_000 });
});

test('loading line, est. badge, source on hover, image still loads', async ({ page }) => {
  await mockSpecies(page, ['Panthera leo']);
  let release!: () => void;
  const gate = new Promise<void>(r => { release = r; });
  await page.route(/\/traits\?stage=/, async route => { await gate; return json(route, traits('Panthera leo', 'Savanna')); });

  await openSpecies(page, 'Panthera leo');
  await expect(page.locator('#sp-traits-loading')).toBeVisible();
  release();
  await expect(page.locator('#sp-traits-loading')).toHaveCount(0);

  const habitat = page.locator('#sp-fields > div', { hasText: 'Savanna' });
  const activity = page.locator('#sp-fields > div', { hasText: 'nocturnal' });
  await expect(habitat).toHaveAttribute('title', 'Source: IUCN Red List');
  await expect(habitat.locator('.trait-est')).toHaveCount(0);
  await expect(activity.locator('.trait-est')).toHaveText('est.');
  await expect(activity).toHaveAttribute('title', `Source: ${EST} (estimated)`);
  await activity.hover();

  await expect(page.locator('#sp-image')).toHaveAttribute('src', PIXEL);
  await expect(page.locator('#sp-image-wrap')).toBeVisible();
});

test('switching species mid-load shows only the second species traits', async ({ page }) => {
  await mockSpecies(page, ['Panthera leo', 'Ursus maritimus']);
  let releaseLion!: () => void;
  const lionGate = new Promise<void>(r => { releaseLion = r; });
  await page.route(/\/traits\?stage=/, async route => {
    if (route.request().url().includes('Panthera')) {
      await lionGate;
      return json(route, traits('Panthera leo', 'Savanna'));
    }
    return json(route, traits('Ursus maritimus', 'Marine Oceanic'));
  });

  await openSpecies(page, 'Panthera leo');
  await openSpecies(page, 'Ursus maritimus');
  await expect(page.locator('#sp-fields')).toContainText('Marine Oceanic');
  releaseLion();
  await page.waitForTimeout(500);
  await expect(page.locator('#sp-fields')).not.toContainText('Savanna');
  await expect(page.locator('#sp-fields')).toContainText('Marine Oceanic');
});
