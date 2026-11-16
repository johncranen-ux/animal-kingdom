import { test, expect } from '@playwright/test';

const OLLAMA_TIMEOUT = 90_000;

/**
 * Full user journey: search for a species in the tree then ask the chatbot about it.
 */
test('search for Panthera leo then ask chatbot', async ({ page }) => {
  test.setTimeout(OLLAMA_TIMEOUT + 30_000);

  await page.goto('/');

  // ── Step 1: Tree and search load ────────────────────────────────────────────
  await page.locator('#tree-container svg circle').first().waitFor({ timeout: 15_000 });

  // ── Step 2: Search for a known species ──────────────────────────────────────
  const searchInput = page.locator('#search-input');
  await searchInput.fill('Panthera leo');

  const firstResult = page.locator('#search-results li').first();
  await expect(firstResult).toBeVisible({ timeout: 5_000 });
  expect(await firstResult.textContent()).toMatch(/Panthera leo/i);

  // ── Step 3: Tree highlights matching nodes ──────────────────────────────────
  // At least some nodes should be dimmed (opacity < 1) after search
  const dimmedNodes = page.locator('#tree-container svg g[opacity="0.12"]');
  await expect(dimmedNodes.first()).toBeVisible({ timeout: 3_000 });

  // ── Step 4: Ask chatbot about the species ───────────────────────────────────
  await page.locator('#chat-input').fill('Tell me about Panthera leo');
  await page.locator('#chat-form').evaluate((f: HTMLFormElement) => f.requestSubmit());

  // User bubble appears
  const userBubble = page.locator('#chat-messages .flex.justify-end').first();
  await expect(userBubble.locator('.bubble-text')).toHaveText('Tell me about Panthera leo');

  // ── Step 5: Assistant response mentions the species ─────────────────────────
  const assistantText = page.locator('#chat-messages .flex.justify-start').first().locator('.bubble-text');
  await expect(assistantText).not.toBeEmpty({ timeout: OLLAMA_TIMEOUT });

  const response = (await assistantText.textContent())!.toLowerCase();
  const mentionsSpecies = response.includes('panthera') || response.includes('lion');
  expect(mentionsSpecies).toBe(true);
});

/**
 * Verify the layout: tree and chat panels coexist correctly.
 */
test('tree and chat panels are both visible', async ({ page }) => {
  await page.goto('/');
  await page.locator('#tree-container svg').waitFor({ timeout: 15_000 });

  await expect(page.locator('#tree-panel')).toBeVisible();
  await expect(page.locator('#chat-panel')).toBeVisible();
  await expect(page.locator('#tree-container svg')).toBeVisible();
  await expect(page.locator('#chat-input')).toBeVisible();
});
