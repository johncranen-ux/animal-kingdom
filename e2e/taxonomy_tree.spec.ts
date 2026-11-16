import { test, expect } from '@playwright/test';

test.describe('Taxonomy tree', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for SVG to appear and at least one node to render
    await page.locator('#tree-container svg circle').first().waitFor({ timeout: 15_000 });
  });

  test('tree renders with kingdom nodes on load', async ({ page }) => {
    const count = await page.locator('#tree-container svg circle').count();
    expect(count).toBeGreaterThanOrEqual(3);
  });

  test('tree node labels are visible', async ({ page }) => {
    const label = page.locator('#tree-container svg text').first();
    await expect(label).toBeVisible();
    const text = await label.textContent();
    expect(text!.length).toBeGreaterThan(0);
  });

  test('clicking a kingdom node expands children', async ({ page }) => {
    const circles = page.locator('#tree-container svg circle');
    const beforeCount = await circles.count();

    const kingdom = page.locator('#tree-container svg g[data-rank="kingdom"]').first();
    await kingdom.waitFor({ timeout: 5_000 });
    await kingdom.click();

    // Poll until more circles appear (API latency varies)
    await expect(async () => {
      const after = await circles.count();
      expect(after).toBeGreaterThan(beforeCount);
    }).toPass({ timeout: 10_000 });
  });

  test('clicking an expanded kingdom collapses it', async ({ page }) => {
    const circles = page.locator('#tree-container svg circle');
    const initialCount = await circles.count();
    const kingdom = page.locator('#tree-container svg g[data-rank="kingdom"]').first();
    await kingdom.waitFor({ timeout: 5_000 });

    // Expand and wait for new nodes
    await kingdom.click();
    await expect(async () => {
      expect(await circles.count()).toBeGreaterThan(initialCount);
    }).toPass({ timeout: 10_000 });
    const expandedCount = await circles.count();

    // Collapse and wait for nodes to be removed
    await kingdom.click();
    await expect(async () => {
      expect(await circles.count()).toBeLessThan(expandedCount);
    }).toPass({ timeout: 5_000 });
  });

  test('a kingdom closed after opening keeps its colour as a ring', async ({ page }) => {
    const circles = page.locator('#tree-container svg circle');
    const initialCount = await circles.count();
    const kingdom = page.locator('#tree-container svg g[data-rank="kingdom"]').first();
    await kingdom.waitFor({ timeout: 5_000 });
    await kingdom.click();
    await expect(async () => {
      expect(await circles.count()).toBeGreaterThan(initialCount);
    }).toPass({ timeout: 10_000 });
    await kingdom.click();
    const dot = kingdom.locator('circle');
    await expect(dot).toHaveAttribute('stroke', '#e74c3c', { timeout: 5_000 });
    await expect(dot).toHaveAttribute('fill', '#111827');
  });

  test('the colour legend stays in place while the tree is panned', async ({ page }) => {
    const legend = page.locator('#tree-legend');
    await expect(legend).toContainText('Kingdom');
    await expect(legend).toContainText('Closed, opened before');
    const before = await legend.boundingBox();
    const svg = page.locator('#tree-container svg');
    const box = (await svg.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + 40);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 200, box.y + 140, { steps: 5 });
    await page.mouse.up();
    expect(await legend.boundingBox()).toEqual(before);
  });

  test('search bar is present and accepts input', async ({ page }) => {
    const input = page.locator('#search-input');
    await expect(input).toBeVisible();
    await input.fill('Panthera');
    await expect(input).toHaveValue('Panthera');
  });

  test('search shows a dropdown with results', async ({ page }) => {
    await page.locator('#search-input').fill('Panthera');
    // Wait for debounce (300ms) + API response
    const firstResult = page.locator('#search-results li').first();
    await expect(firstResult).toBeVisible({ timeout: 5_000 });
    const count = await page.locator('#search-results li').count();
    expect(count).toBeGreaterThan(0);
  });

  test('clearing search hides the dropdown', async ({ page }) => {
    const input = page.locator('#search-input');
    await input.fill('Panthera');
    await page.locator('#search-results li').first().waitFor({ timeout: 5_000 });

    await input.fill('');
    await input.dispatchEvent('input');
    await expect(page.locator('#search-results')).toHaveClass(/hidden/, { timeout: 2_000 });
  });

});
