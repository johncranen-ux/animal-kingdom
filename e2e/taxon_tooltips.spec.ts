import { test, expect } from '@playwright/test';

test.describe('Taxon hover descriptions', () => {

  test('phylum and class nodes show a description; moving away hides it', async ({ page }) => {
    await page.goto('/');

    const node = (id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);

    await node('Animalia').click();
    await node('Animalia|Arthropoda').waitFor({ timeout: 15_000 });

    const phylumText = page.getByText('The largest animal phylum');
    await node('Animalia|Arthropoda').hover();
    await expect(phylumText).toBeVisible();

    await node('Animalia|Arthropoda').click();
    await node('Animalia|Arthropoda|Insecta').waitFor({ timeout: 15_000 });

    const classText = page.getByText('six-legged arthropods');
    await node('Animalia|Arthropoda|Insecta').hover();
    await expect(classText).toBeVisible();

    await page.mouse.move(0, 0);
    await expect(classText).toBeHidden();
  });

  test('order nodes show a description', async ({ page }) => {
    await page.goto('/');

    const node = (id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);
    await node('Animalia').click();
    await node('Animalia|Chordata').click({ timeout: 15_000 });
    await node('Animalia|Chordata|Mammalia').click({ timeout: 15_000 });
    await node('Animalia|Chordata|Mammalia|Chiroptera').hover({ timeout: 15_000 });
    await expect(page.locator('body > div', { hasText: 'true and sustained flight' })).toBeVisible();
  });

  test('classes and orders new with Catalogue of Life show a description', async ({ page }) => {
    await page.goto('/');

    const node = (id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);
    await node('Animalia').click();
    await node('Animalia|Chordata').click({ timeout: 15_000 });

    await node('Animalia|Chordata|Teleostei').hover({ timeout: 15_000 });
    await expect(page.locator('body > div', { hasText: 'largest group of ray-finned fish' })).toBeVisible();

    await node('Animalia|Chordata|Aves').click();
    await node('Animalia|Chordata|Aves|Passeriformes').hover({ timeout: 15_000 });
    await expect(page.locator('body > div', { hasText: 'Perching birds' })).toBeVisible();
  });

  test('kingdoms, non-animal orders and families show a description', async ({ page }) => {
    await page.goto('/');

    const node = (id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);
    const tip = (text: string) => page.locator('body > div', { hasText: text });

    await node('Plantae').hover();
    await expect(tip('Plants')).toBeVisible();

    await node('Plantae').click();
    await node('Plantae|Tracheophyta').click({ timeout: 15_000 });
    await node('Plantae|Tracheophyta|Magnoliopsida').click({ timeout: 15_000 });
    await node('Plantae|Tracheophyta|Magnoliopsida|Rosales').hover({ timeout: 15_000 });
    await expect(tip('Roses, apples, strawberries')).toBeVisible();

    await node('Plantae|Tracheophyta|Magnoliopsida|Rosales').click();
    await node('Plantae|Tracheophyta|Magnoliopsida|Rosales|Rosaceae').hover({ timeout: 15_000 });
    await expect(tip('A family in the order Rosales')).toBeVisible();
  });

  test('a class described in the original table still shows its text', async ({ page }) => {
    await page.goto('/');

    const node = (id: string) => page.locator(`#tree-container svg g[data-node-id="${id}"]`);

    await node('Fungi').click();
    await node('Fungi|Chytridiomycota').waitFor({ timeout: 15_000 });
    await node('Fungi|Chytridiomycota').click();
    await node('Fungi|Chytridiomycota|Chytridiomycetes').waitFor({ timeout: 15_000 });

    await node('Fungi|Chytridiomycota|Chytridiomycetes').hover();
    await expect(page.getByText('Primitive aquatic fungi (chytrids)')).toBeVisible();
  });
});
