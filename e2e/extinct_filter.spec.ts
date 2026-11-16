import { test, expect } from '@playwright/test';

// Increment 13 — fossils marked † in the tree, "Hide extinct" toggle.
// Needs the real DB (Catalogue of Life flags Tapirus webbi, a fossil, as extinct).

const TAPIRUS = 'Animalia|Chordata|Mammalia|Perissodactyla|Tapiridae|Tapirus';
const node = (name: string) => `#tree-container svg g[data-node-id="${TAPIRUS}|${name}"]`;

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => localStorage.removeItem('ak.hideExtinct'));
  await page.reload();
  await page.locator('#tree-container svg circle').first().waitFor({ timeout: 15_000 });

  // Open the Tapirus genus via search for a living tapir
  await page.locator('#search-input').pressSequentially('Tapirus terrestris');
  await page.locator('#search-results li').first().click();
  await page.locator('#sp-close').click();
});

test('extinct taxa carry a dagger, living ones do not', async ({ page }) => {
  await expect(page.locator(`${node('Tapirus webbi')} text`)).toContainText('†', { timeout: 15_000 });
  await expect(page.locator(`${node('Tapirus terrestris')} text`)).not.toContainText('†');
});

test('hide extinct removes fossils, keeps a placeholder, and remembers the choice', async ({ page }) => {
  await page.locator(node('Tapirus webbi')).waitFor({ timeout: 15_000 });
  await page.locator('#hide-extinct').check();

  await expect(page.locator(node('Tapirus webbi'))).toHaveCount(0);
  await expect(page.locator(node('Tapirus terrestris'))).toHaveCount(1);
  const placeholder = page.locator('#tree-container svg g[data-rank="hidden"]');
  await expect(placeholder).toContainText(/† \d+ extinct hidden/);

  await page.reload();
  await expect(page.locator('#hide-extinct')).toBeChecked();
});

test('a species only IUCN lists as extinct is hidden without opening its panel', async ({ page }) => {
  // Barbodes pachycheilus: IUCN status EX
  const BARBODES = 'Animalia|Chordata|Teleostei|Cypriniformes|Cyprinidae|Barbodes';
  const barb = (name: string) => page.locator(`#tree-container svg g[data-node-id="${BARBODES}|${name}"]`);
  await page.locator('#search-input').fill('');
  await page.locator('#search-input').pressSequentially('Barbodes bunau');
  await page.locator('#search-results li').first().click();
  await barb('Barbodes bunau').waitFor({ timeout: 15_000 });
  await page.locator('#sp-close').click();

  await expect(barb('Barbodes pachycheilus').locator('text')).toContainText('†');
  await page.locator('#hide-extinct').check();
  await expect(barb('Barbodes pachycheilus')).toHaveCount(0);
  await expect(barb('Barbodes bunau')).toHaveCount(1);
});

test('clicking the placeholder shows fossils again and unticks the toggle', async ({ page }) => {
  await page.locator(node('Tapirus webbi')).waitFor({ timeout: 15_000 });
  await page.locator('#hide-extinct').check();
  await page.locator('#tree-container svg g[data-rank="hidden"]').click();

  await expect(page.locator('#hide-extinct')).not.toBeChecked();
  await expect(page.locator(node('Tapirus webbi'))).toHaveCount(1);
});
