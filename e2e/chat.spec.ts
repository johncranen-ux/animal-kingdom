import { test, expect } from '@playwright/test';

const OLLAMA_TIMEOUT = 90_000;

async function waitForApp(page: import('@playwright/test').Page) {
  // The chat listener is attached AFTER initTree() resolves, so we wait for the
  // tree SVG to confirm DOMContentLoaded + initTree have both completed.
  await page.locator('#tree-container svg circle').first().waitFor({ timeout: 15_000 });
}

async function sendMessage(page: import('@playwright/test').Page, text: string) {
  const input = page.locator('#chat-input');
  await input.fill(text);
  await input.press('Enter');
}

test.describe('Chat panel', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForApp(page);
  });

  test('chat input and send button are present', async ({ page }) => {
    await expect(page.locator('#chat-input')).toBeVisible();
    await expect(page.locator('#chat-form button[type="submit"]')).toBeVisible();
  });

  test('empty message does not submit', async ({ page }) => {
    await page.locator('#chat-input').press('Enter');
    await expect(page.locator('#chat-messages .bubble-text')).toHaveCount(0);
  });

  test('message appears as user bubble on submit', async ({ page }) => {
    await sendMessage(page, 'Hello');

    const userBubble = page.locator('#chat-messages .flex.justify-end').first();
    await expect(userBubble).toBeVisible({ timeout: 3_000 });
    await expect(userBubble.locator('.bubble-text')).toHaveText('Hello');
  });

  test('input is disabled while response streams', async ({ page }) => {
    await sendMessage(page, 'What is Panthera leo?');

    // Input disabled immediately after submit, before response arrives
    await expect(page.locator('#chat-input')).toBeDisabled({ timeout: 3_000 });
  });

  test('assistant response appears and contains text', async ({ page }) => {
    test.setTimeout(OLLAMA_TIMEOUT + 10_000);

    await sendMessage(page, 'Tell me one fact about lions');

    const assistantBubble = page.locator('#chat-messages .flex.justify-start').first();
    const textEl = assistantBubble.locator('.bubble-text');
    await expect(textEl).not.toBeEmpty({ timeout: OLLAMA_TIMEOUT });

    const text = await textEl.textContent();
    expect(text!.length).toBeGreaterThan(20);
  });

  test('input re-enables after response completes', async ({ page }) => {
    test.setTimeout(OLLAMA_TIMEOUT + 10_000);

    await sendMessage(page, 'What is Canis lupus?');

    await expect(
      page.locator('#chat-messages .flex.justify-start').first().locator('.bubble-text')
    ).not.toBeEmpty({ timeout: OLLAMA_TIMEOUT });

    await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 5_000 });
  });

  test('a follow-up question carries the earlier turns', async ({ page }) => {
    const bodies: any[] = [];
    await page.route('**/api/chat', async route => {
      bodies.push(route.request().postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({ type: 'token', content: `Answer ${bodies.length}.` })}\n\n`
            + `data: ${JSON.stringify({ type: 'done' })}\n\n`,
      });
    });
    const answers = page.locator('#chat-messages .flex.justify-start .bubble-text');

    await sendMessage(page, 'what is the largest animal');
    await expect(answers.nth(0)).toHaveText('Answer 1.');
    await expect(page.locator('#chat-input')).toBeEnabled();
    await sendMessage(page, 'what does it eat');
    await expect(answers.nth(1)).toHaveText('Answer 2.');

    expect(bodies[0]).toEqual({ message: 'what is the largest animal', history: [] });
    expect(bodies[1]).toEqual({
      message: 'what does it eat',
      history: [{ role: 'user', content: 'what is the largest animal' },
                { role: 'assistant', content: 'Answer 1.' }],
    });
  });

  test('a name link in an answer opens the animal in the tree and the panel', async ({ page }) => {
    const lion = { text: 'Lion', scientific_name: 'Panthera leo', taxon_rank: 'species',
                   taxon_path: 'Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo' };
    await page.route('**/api/chat', route => route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ type: 'token', content: 'Database: The Lion (*Panthera leo*) is big.' })}\n\n`
          + `data: ${JSON.stringify({ type: 'links', links: [lion] })}\n\n`
          + `data: ${JSON.stringify({ type: 'done' })}\n\n`,
    }));

    await sendMessage(page, 'how big is a lion');
    const link = page.locator('#chat-messages a.taxon-link');
    await expect(link).toHaveCount(1);
    await expect(link).toHaveText('Lion');
    await expect(link).toHaveAttribute('title', 'Panthera leo (species)');

    await link.click();
    await expect(page.locator('#species-panel')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#species-panel')).toContainText('Panthera leo');
    await expect(page.locator('#tree-container svg g[opacity="0.12"]').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('#tree-container svg text', { hasText: /Panthera leo|^Lion$/ }).first())
      .toBeVisible({ timeout: 15_000 });
    expect(page.url()).not.toContain('#');
  });

});
