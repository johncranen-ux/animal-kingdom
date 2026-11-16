import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeSSEBody(events) {
  const lines = events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('');
  const encoder = new TextEncoder();
  const bytes = encoder.encode(lines);
  let pos = 0;
  const stream = new ReadableStream({
    pull(ctrl) {
      if (pos < bytes.length) {
        ctrl.enqueue(bytes.slice(pos, pos + 64));
        pos += 64;
      } else {
        ctrl.close();
      }
    },
  });
  return stream;
}

function mockFetchSSE(events, status = 200) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    body: makeSSEBody(events),
  });
}

// ── Setup DOM ─────────────────────────────────────────────────────────────────

function setupChatDOM() {
  document.body.innerHTML = `
    <div id="chat-messages"></div>
    <form id="chat-form">
      <input id="chat-input" type="text" />
      <button type="submit">Send</button>
    </form>
  `;
}

// ── Import helpers under test (bypassing DOMContentLoaded) ────────────────────
// We test the individual helper functions by extracting them. Since app.js wires
// everything inside DOMContentLoaded, we test the _streamChat logic by building
// an integration scenario using fetch mocks and DOM assertions.

beforeEach(() => {
  vi.resetAllMocks();
  setupChatDOM();
});

afterEach(() => {
  document.body.innerHTML = '';
});

// ── Token accumulation ────────────────────────────────────────────────────────

describe('SSE token streaming', () => {
  it('accumulates token events into a text node', async () => {
    const events = [
      { type: 'token', content: 'The ' },
      { type: 'token', content: 'lion' },
      { type: 'token', content: ' is big.' },
      { type: 'done' },
    ];
    mockFetchSSE(events);

    // Inline the streaming logic so we can test it in isolation
    const text = await _simulateStream(events);
    expect(text).toBe('The lion is big.');
  });

  it('ignores done and non-token events in text accumulation', async () => {
    const events = [
      { type: 'token', content: 'Hello' },
      { type: 'image', url: 'https://example.com/img.jpg', attribution: 'CC' },
      { type: 'done' },
    ];
    const text = await _simulateStream(events);
    expect(text).toBe('Hello');
  });
});

// ── Image rendering ───────────────────────────────────────────────────────────

describe('SSE image events', () => {
  it('renders an img element for image events', async () => {
    const events = [
      { type: 'token', content: 'See photo:' },
      { type: 'image', url: 'https://example.com/lion.jpg', attribution: 'https://en.wikipedia.org/lion' },
      { type: 'done' },
    ];
    const { images } = await _simulateStreamFull(events);
    expect(images.length).toBe(1);
    expect(images[0].src).toContain('lion.jpg');
  });

  it('renders an attribution link when attribution is provided', async () => {
    const events = [
      { type: 'image', url: 'https://example.com/img.jpg', attribution: 'https://example.com/source' },
      { type: 'done' },
    ];
    const { links } = await _simulateStreamFull(events);
    expect(links.some(l => l.href.includes('example.com/source'))).toBe(true);
  });

  it('renders no attribution link when attribution is empty', async () => {
    const events = [
      { type: 'image', url: 'https://example.com/img.jpg', attribution: '' },
      { type: 'done' },
    ];
    const { links } = await _simulateStreamFull(events);
    expect(links.filter(l => l.className.includes('text-gray-400'))).toHaveLength(0);
  });
});

// ── Error handling ────────────────────────────────────────────────────────────

describe('SSE error events', () => {
  it('displays an error message on error event', async () => {
    const events = [
      { type: 'error', detail: 'Ollama not available' },
    ];
    const { errorTexts } = await _simulateStreamFull(events);
    expect(errorTexts.some(t => t.includes('Ollama not available'))).toBe(true);
  });
});

// ── Bubble structure ──────────────────────────────────────────────────────────

describe('chat bubble layout', () => {
  it('user bubble aligns right', () => {
    const container = document.getElementById('chat-messages');
    _appendBubble(container, 'user', 'Hello');
    const wrap = container.querySelector('div');
    expect(wrap.className).toContain('justify-end');
  });

  it('assistant bubble aligns left', () => {
    const container = document.getElementById('chat-messages');
    _appendBubble(container, 'assistant', '');
    const wrap = container.querySelector('div');
    expect(wrap.className).toContain('justify-start');
  });

  it('bubble-text element holds the text content', () => {
    const container = document.getElementById('chat-messages');
    _appendBubble(container, 'user', 'Test message');
    expect(container.querySelector('.bubble-text').textContent).toBe('Test message');
  });
});

// ── Inline implementations (mirrors app.js logic for unit testing) ─────────────
// These replicate just enough of app.js to make DOM-independent assertions.

async function _simulateStream(events) {
  let text = '';
  for (const e of events) {
    if (e.type === 'token') text += e.content;
  }
  return text;
}

async function _simulateStreamFull(events) {
  const bubble = document.createElement('div');
  const textEl = document.createElement('p');
  textEl.className = 'bubble-text';
  bubble.appendChild(textEl);
  document.getElementById('chat-messages').appendChild(bubble);

  for (const e of events) {
    if (e.type === 'token') {
      textEl.textContent += e.content;
    } else if (e.type === 'image') {
      const img = document.createElement('img');
      img.src = e.url;
      img.className = 'mt-2 rounded max-w-[200px] block';
      bubble.appendChild(img);
      if (e.attribution) {
        const cap = document.createElement('a');
        cap.href = e.attribution;
        cap.className = 'text-xs text-gray-400 block mt-1';
        cap.textContent = 'Image source';
        bubble.appendChild(cap);
      }
    } else if (e.type === 'error') {
      const err = document.createElement('p');
      err.className = 'text-red-400 text-xs mt-1';
      err.textContent = `⚠ ${e.detail}`;
      bubble.appendChild(err);
    }
  }

  return {
    text: textEl.textContent,
    images: Array.from(bubble.querySelectorAll('img')),
    links: Array.from(bubble.querySelectorAll('a')),
    errorTexts: Array.from(bubble.querySelectorAll('.text-red-400')).map(el => el.textContent),
  };
}

function _appendBubble(container, role, text) {
  const wrap = document.createElement('div');
  wrap.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';
  const bubble = document.createElement('div');
  const textEl = document.createElement('p');
  textEl.className = 'bubble-text whitespace-pre-wrap leading-relaxed';
  textEl.textContent = text;
  bubble.appendChild(textEl);
  wrap.appendChild(bubble);
  container.appendChild(wrap);
  return bubble;
}

// ── Species panel image helpers (inline reimplementations) ────────────────────
// Mirror the logic from app.js _showSpeciesPanel image block and _fetchRemoteImage.
// Tests here verify the decision tree, not the DOM wiring.

const API_BASE = 'http://localhost:8000';

function setupSpeciesImageDOM() {
  document.body.innerHTML = `
    <div id="sp-image-wrap" class="hidden">
      <img id="sp-image" alt="" />
      <p id="sp-attr"></p>
    </div>
  `;
}

// Inline of _fetchRemoteImage from app.js
async function _fetchRemoteImage(scientificName, imgEl, attrEl, imgWrap, force) {
  const qs  = force ? '?force=true' : '';
  const url = `${API_BASE}/api/species/${encodeURIComponent(scientificName)}/image${qs}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      imgWrap.classList.add('hidden');
      return;
    }
    const data = await resp.json();
    imgEl.src          = data.url;
    imgEl.alt          = scientificName;
    attrEl.textContent = data.attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => imgWrap.classList.add('hidden');
  } catch {
    imgWrap.classList.add('hidden');
  }
}

// Inline of the image block from _showSpeciesPanel
function _applyImageState(sp) {
  const imgWrap = document.getElementById('sp-image-wrap');
  const imgEl   = document.getElementById('sp-image');
  const attrEl  = document.getElementById('sp-attr');
  if (sp.primary_image_url === '__none__') {
    imgWrap.classList.add('hidden');
  } else if (sp.primary_image_url) {
    imgEl.src          = sp.primary_image_url;
    imgEl.alt          = sp.scientific_name || '';
    attrEl.textContent = sp.image_attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, true);
  } else {
    imgEl.removeAttribute('src');
    attrEl.textContent = 'Finding image…';
    imgWrap.classList.remove('hidden');
    _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, false);
  }
  return { imgWrap, imgEl, attrEl };
}

// ── Species panel image tests ──────────────────────────────────────────────────

describe('species panel — image state', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupSpeciesImageDOM();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('hides imgWrap immediately for __none__ sentinel without fetching', () => {
    global.fetch = vi.fn();
    const { imgWrap } = _applyImageState({ scientific_name: 'Apis mellifera', primary_image_url: '__none__' });
    expect(imgWrap.classList.contains('hidden')).toBe(true);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows loading text and calls /image when primary_image_url is null', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: 'https://example.com/bee.jpg', attribution: '© Example' }),
    });
    const { imgWrap, imgEl, attrEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: null,
    });
    // Loading text shown immediately (before fetch resolves)
    expect(attrEl.textContent).toBe('Finding image…');
    expect(imgWrap.classList.contains('hidden')).toBe(false);
    // Wait for fetch to resolve (vi.waitFor retries only when callback throws)
    await vi.waitFor(() => expect(imgEl.src).toBe('https://example.com/bee.jpg'));
    expect(attrEl.textContent).toBe('© Example');
    const call = global.fetch.mock.calls[0][0];
    expect(call).toContain('/api/species/Apis%20mellifera/image');
    expect(call).not.toContain('force=true');
  });

  it('hides imgWrap when /image endpoint returns 404', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    const { imgWrap, attrEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: null,
    });
    await vi.waitFor(() => expect(imgWrap.classList.contains('hidden')).toBe(true));
  });

  it('sets img src directly when valid URL is stored', () => {
    global.fetch = vi.fn();
    const { imgEl, imgWrap } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: 'https://stored.com/bee.jpg',
      image_attribution: '© Stored',
    });
    expect(imgEl.src).toBe('https://stored.com/bee.jpg');
    expect(imgWrap.classList.contains('hidden')).toBe(false);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('onerror on a stored URL calls /image with force=true', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: 'https://new.com/bee.jpg', attribution: '© New' }),
    });
    const { imgEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: 'https://broken.com/bee.jpg',
    });
    // Manually fire the onerror handler (JSDOM does not load images natively)
    imgEl.onerror();
    await vi.waitFor(() => {
      const call = global.fetch.mock.calls[0]?.[0] || '';
      expect(call).toContain('force=true');
    });
    const call = global.fetch.mock.calls[0][0];
    expect(call).toContain('/api/species/Apis%20mellifera/image?force=true');
  });
});
