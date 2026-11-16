import { test, expect, Page, Route } from '@playwright/test';

// Increment 31: a panel without a picture offers "Search again" (/image?retry=true).
// Route-mocked, like old_names.spec.ts: no online sources, no DB writes.
const PIXEL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';

function record(name: string) {
  return {
    scientific_name: name, taxon_rank: 'species', common_names: [], taxonomic_status: 'ACCEPTED',
    taxon_path: `Animalia|${name}`, primary_image_url: '__none__', image_attribution: '',
    provenance: {}, trait_eligible: true, traits_sourced: true, traits_estimated: true, current_name: null,
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function mockApi(page: Page, retry: (route: Route) => Promise<void> | void) {
  await page.route(/\/api\/search\?/, route => {
    const q = new URL(route.request().url()).searchParams.get('q') || '';
    return json(route, [{ scientific_name: q, common_names: [], taxon_rank: 'species',
                          taxon_path: `Animalia|${q}`, taxonomic_status: 'ACCEPTED' }]);
  });
  await page.route(/\/api\/species\/[^/]+\/image/, route =>
    route.request().url().includes('retry=true') ? retry(route) : json(route, { detail: 'No image available' }, 404));
  await page.route(/\/api\/species\/[^/?]+$/, route => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!);
    return json(route, record(name));
  });
}

async function open(page: Page, name: string) {
  await page.fill('#search-input', name);
  await page.locator('#search-results li').first().click();
  await expect(page.locator('#sp-name')).toHaveText(name);
}

test('a panel without a picture offers Search again and shows what it finds', async ({ page }) => {
  await mockApi(page, route => json(route, { url: PIXEL, attribution: '© X (CC BY 4.0) via GBIF (museum specimen)' }));
  await page.goto('/');
  await open(page, 'Anoxycalyx ijimai');
  await expect(page.locator('#sp-no-image')).toContainText('No picture found.');
  await page.locator('#sp-no-image button[data-picture-retry]').click();
  await expect(page.locator('#sp-image')).toHaveAttribute('src', PIXEL);
  await expect(page.locator('#sp-image')).toBeVisible();
  await expect(page.locator('#sp-attr')).toHaveText('© X (CC BY 4.0) via GBIF (museum specimen)');
  await expect(page.locator('#sp-no-image')).toBeHidden();
});

test('a retry that finds nothing says so and keeps the button', async ({ page }) => {
  await mockApi(page, route => json(route, { detail: { message: 'No image found', searched_again: '2026-11-12' } }, 404));
  await page.goto('/');
  await open(page, 'Neomonas viridis');
  await page.locator('#sp-no-image button[data-picture-retry]').click();
  await expect(page.locator('#sp-no-image')).toContainText('Still no picture after a wider search.');
  await expect(page.locator('#sp-no-image button[data-picture-retry]')).toBeEnabled();
  await expect(page.locator('#sp-image')).toBeHidden();
});

test('a retry answer for another animal is ignored', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  await mockApi(page, async route => { await held; await json(route, { url: PIXEL, attribution: 'late' }); });
  await page.goto('/');
  await open(page, 'Anoxycalyx ijimai');
  await page.locator('#sp-no-image button[data-picture-retry]').click();
  await expect(page.locator('#sp-no-image button[data-picture-retry]')).toBeDisabled();
  await open(page, 'Barbodes sirang');
  const late = page.waitForResponse(r => r.url().includes('retry=true'));
  release();
  await expect(page.locator('#sp-no-image')).toContainText('No picture found.');
  await late;
  await expect(page.locator('#sp-image')).toBeHidden();
  await expect(page.locator('#sp-attr')).not.toHaveText('late');
});

// Increment 33: no gallery beside a running Search again
test('Other pictures waits while Search again runs', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(r => { release = r; });
  await mockApi(page, async route => { await held; await json(route, { detail: { message: 'No image found', searched_again: '2026-11-13' } }, 404); });
  await page.goto('/');
  await open(page, 'Anoxycalyx ijimai');
  await expect(page.locator('button[data-picture-choose]')).toBeEnabled();
  await page.locator('#sp-no-image button[data-picture-retry]').click();
  await expect(page.locator('button[data-picture-choose]')).toBeDisabled();
  release();
  await expect(page.locator('#sp-no-image')).toContainText('Still no picture after a wider search.');
  await expect(page.locator('button[data-picture-choose]')).toBeEnabled();
});
