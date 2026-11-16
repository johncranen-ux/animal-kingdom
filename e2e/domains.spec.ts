import { test, expect } from '@playwright/test';

test.describe('Domains in the taxonomy tree', () => {
  const node = (page: any, id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await node(page, 'Eukarya').waitFor({ timeout: 15_000 });
  });

  test('top level shows the three domains and Viruses, with Eukarya open', async ({ page }) => {
    for (const id of ['Bacteria', 'Archaea', 'Eukarya', 'Viruses', 'Animalia', 'Plantae', 'Fungi', 'Chromista', 'Protozoa']) {
      await expect(node(page, id)).toBeVisible();
    }
  });

  test('every branch line from the initial load becomes visible', async ({ page }) => {
    const opacities = () => page.locator('#tree-container svg path').evaluateAll(
      els => els.map(e => Number(e.getAttribute('opacity'))));
    await expect(async () => {
      const values = await opacities();
      expect(values.length).toBeGreaterThanOrEqual(9); // Life→4 top nodes, Eukarya→5 kingdoms
      expect(Math.min(...values)).toBe(1);
    }).toPass({ timeout: 3_000 });
  });

  test('sibling labels line up, with expanded nodes to the right of their dot too', async ({ page }) => {
    const gaps = await page.locator('#tree-container svg g[data-rank="domain"]').evaluateAll(
      els => els.map(g => {
        const dot = g.querySelector('circle')!.getBoundingClientRect();
        const label = g.querySelector('text')!.getBoundingClientRect();
        return label.left - dot.right;
      }));
    expect(gaps).toHaveLength(3);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...gaps) - Math.min(...gaps)).toBeLessThanOrEqual(2); // letter shapes vary slightly
  });

  test('Bacteria opens to its kingdoms, not stick insects', async ({ page }) => {
    await node(page, 'Bacteria').click();
    await expect(node(page, 'Bacteria|Bacillati')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeHidden();
  });

  test('Archaea opens to its kingdoms', async ({ page }) => {
    await node(page, 'Archaea').click();
    await expect(node(page, 'Archaea|Thermoproteati')).toBeVisible({ timeout: 15_000 });
  });

  test('domains and bacterial phyla have hover text', async ({ page }) => {
    const tip = page.locator('body > div', { hasText: 'three domains' });
    await node(page, 'Bacteria').hover();
    await expect(tip).toBeVisible();

    await node(page, 'Bacteria').click();
    await node(page, 'Bacteria|Bacillati').click({ timeout: 15_000 });
    await node(page, 'Bacteria|Bacillati|Actinomycetota').hover({ timeout: 15_000 });
    await expect(page.locator('body > div', { hasText: 'antibiotics' })).toBeVisible();
  });

  test('searching Bacteria offers the domain and the stick insect genus', async ({ page }) => {
    await page.locator('#search-input').fill('Bacteria');
    const results = page.locator('#search-results li');
    await expect(results.first()).toContainText('domain', { timeout: 15_000 });
    await expect(results.filter({ hasText: 'genus' }).first()).toBeVisible();

    await results.first().click();
    await expect(node(page, 'Bacteria|Bacillati')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeHidden();
  });

  test('searching an animal still reaches it through Eukarya', async ({ page }) => {
    await page.locator('#search-input').fill('Panthera leo');
    await page.locator('#search-results li').first().click({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toContainText('Eukarya');
    await expect(node(page, 'Animalia')).toHaveCount(1);
  });

  test('a level standing in for a missing order is a real node on the way to the species', async ({ page }) => {
    await page.locator('#search-input').fill('Cerithideopsis californica');
    await page.locator('#search-results li').first().click({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeVisible({ timeout: 15_000 });
    const family = 'Animalia|Mollusca|Gastropoda|Cerithioidea|Potamididae';
    await expect(node(page, 'Animalia|Mollusca|Gastropoda|Cerithioidea')).toBeVisible({ timeout: 15_000 });
    await expect(node(page, family)).toBeVisible();
    await expect(node(page, `${family}|Cerithideopsis|Cerithideopsis californica`)).toBeVisible();
  });

  test('a land snail sits under the order the sources confirmed by majority', async ({ page }) => {
    await page.locator('#search-input').fill('Acusta ravida');
    await page.locator('#search-results li').first().click({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeVisible({ timeout: 15_000 });
    const family = 'Animalia|Mollusca|Gastropoda|Stylommatophora|Camaenidae';
    await expect(node(page, 'Animalia|Mollusca|Gastropoda|Stylommatophora')).toBeVisible({ timeout: 15_000 });
    await expect(node(page, `${family}|Acusta|Acusta ravida`)).toBeVisible();
  });

  test('a fossil Catalogue of Life lacks opens from search but is not in the tree', async ({ page }) => {
    await page.locator('#search-input').fill('Tapirus merriami');
    await page.locator('#search-results li').first().click({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#sp-name')).toHaveText('Tapirus merriami');
    await expect(page.locator('#tree-container svg g[data-node-id$="Tapirus merriami"]')).toHaveCount(0);
  });
});
