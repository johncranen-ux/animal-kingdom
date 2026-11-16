import { describe, it, expect, vi } from 'vitest';
import {
  noPictureHtml, searchedAgainDate, retryPicture,
  otherPicturesButtonHtml, candidatesHtml, galleryMessageHtml, galleryNoteText, fetchCandidates, choosePicture,
} from '../js/images.js';

function dom(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

function resp(status, body = {}) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
}

describe('noPictureHtml', () => {
  it('none: says no picture found and offers Search again', () => {
    const el = dom(noPictureHtml('none'));
    expect(el.textContent).toContain('No picture found.');
    const btn = el.querySelector('button[data-picture-retry]');
    expect(btn.textContent).toBe('Search again');
    expect(btn.disabled).toBe(false);
  });

  it('none with a date: says when it was searched again', () => {
    expect(dom(noPictureHtml('none', '2026-11-12')).textContent)
      .toContain('No picture found (searched again on 2026-11-12).');
  });

  it('searching: disables the button and says Searching more sources…', () => {
    const el = dom(noPictureHtml('searching'));
    expect(el.textContent).toContain('Searching more sources…');
    expect(el.querySelector('button[data-picture-retry]').disabled).toBe(true);
  });

  it('still-none: says Still no picture after a wider search.', () => {
    const el = dom(noPictureHtml('still-none'));
    expect(el.textContent).toContain('Still no picture after a wider search.');
    expect(el.querySelector('button[data-picture-retry]').disabled).toBe(false);
  });

  it('unavailable: says a picture source did not answer', () => {
    expect(dom(noPictureHtml('unavailable')).textContent)
      .toContain("A picture source didn't answer. Try again later.");
  });

  it('escapes the date', () => {
    const html = noPictureHtml('none', '<img src=x>');
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img');
  });
});

describe('searchedAgainDate', () => {
  it('reads the date the backend stores with a failed retry', () => {
    expect(searchedAgainDate('searched again 2026-11-12')).toBe('2026-11-12');
  });
  it('is null for anything else', () => {
    expect(searchedAgainDate('')).toBeNull();
    expect(searchedAgainDate(null)).toBeNull();
    expect(searchedAgainDate('© Wikipedia contributors')).toBeNull();
  });
});

describe('retryPicture', () => {
  it('calls /image?retry=true with the encoded name and returns the picture', async () => {
    const fetchFn = vi.fn(() => resp(200, { url: 'https://x/a.jpg', attribution: '© A' }));
    const res = await retryPicture('Bacteria laesa [Phasmatidae]', { api: 'http://h', fetchFn });
    expect(fetchFn).toHaveBeenCalledWith(
      'http://h/api/species/Bacteria%20laesa%20%5BPhasmatidae%5D/image?retry=true');
    expect(res).toEqual({ url: 'https://x/a.jpg', attribution: '© A' });
  });

  it('maps 404 to still-none with the date', async () => {
    const fetchFn = () => resp(404, { detail: { message: 'No image found', searched_again: '2026-11-12' } });
    expect(await retryPicture('Neomonas', { api: '', fetchFn }))
      .toEqual({ state: 'still-none', searchedOn: '2026-11-12' });
  });

  it('maps 503 and network errors to unavailable', async () => {
    expect(await retryPicture('Neomonas', { api: '', fetchFn: () => resp(503) }))
      .toEqual({ state: 'unavailable' });
    expect(await retryPicture('Neomonas', { api: '', fetchFn: () => Promise.reject(new Error('down')) }))
      .toEqual({ state: 'unavailable' });
  });
});

// ── Increment 32: Other pictures ─────────────────────────────────────────────

const CANDS = [
  { url: 'https://i/goat.jpg', attribution: '(c) a', source: 'iNaturalist' },
  { url: 'https://g/2.jpg', attribution: '© NHM (CC BY 4.0) via GBIF (museum specimen)', source: 'GBIF' },
];

describe('otherPicturesButtonHtml', () => {
  it('is a button marked data-picture-choose', () => {
    const btn = dom(otherPicturesButtonHtml()).querySelector('button[data-picture-choose]');
    expect(btn.textContent).toBe('Other pictures');
  });
});

describe('candidatesHtml', () => {
  it('shows each candidate as a thumbnail with its source and a Cancel button', () => {
    const el = dom(candidatesHtml(CANDS));
    const items = el.querySelectorAll('button[data-candidate]');
    expect(items.length).toBe(2);
    expect(items[1].dataset.candidate).toBe('1');
    expect(items[0].querySelector('img').getAttribute('src')).toBe('https://i/goat.jpg');
    expect(items[1].textContent).toContain('GBIF');
    expect(items[1].title).toBe('© NHM (CC BY 4.0) via GBIF (museum specimen)');
    expect(el.querySelector('button[data-picture-cancel]').textContent).toBe('Cancel');
  });

  it('escapes outside text and URLs', () => {
    const html = candidatesHtml([{ url: 'https://x/"><script>1</script>', attribution: '<b>x</b>', source: '<i>' }]);
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<b>');
    expect(html).toContain('&lt;b&gt;');
  });

  it('has an empty note line above the grid by default', () => {
    const note = dom(candidatesHtml(CANDS)).querySelector('[data-gallery-note]');
    expect(note.textContent).toBe('');
    expect(note.classList.contains('hidden')).toBe(true);
  });

  it('shows a note when some sources were too slow', () => {
    const note = dom(candidatesHtml(CANDS, 'partial')).querySelector('[data-gallery-note]');
    expect(note.textContent).toBe(galleryNoteText('partial'));
    expect(note.classList.contains('hidden')).toBe(false);
  });
});

describe('galleryNoteText', () => {
  it.each([
    ['partial', 'Some picture sources were too slow. Other pictures again may find more.'],
    ['failed', "Couldn't keep that picture. Try again."],
  ])('%s', (state, text) => expect(galleryNoteText(state)).toBe(text));
});

describe('galleryMessageHtml', () => {
  it.each([
    ['loading', 'Looking for pictures…'],
    ['empty', 'No other pictures found.'],
    ['unavailable', "A picture source didn't answer. Try again later."],
  ])('%s', (state, text) => {
    const el = dom(galleryMessageHtml(state));
    expect(el.textContent).toContain(text);
    expect(el.querySelector('button[data-picture-cancel]')).not.toBeNull();
  });
});

describe('fetchCandidates', () => {
  it('asks /image/candidates with the encoded name', async () => {
    const fetchFn = vi.fn(() => resp(200, { candidates: CANDS, unavailable: false }));
    const res = await fetchCandidates('Bacteria laesa [Phasmatidae]', { api: 'http://h', fetchFn });
    expect(fetchFn).toHaveBeenCalledWith('http://h/api/species/Bacteria%20laesa%20%5BPhasmatidae%5D/image/candidates');
    expect(res).toEqual({ candidates: CANDS, unavailable: false });
  });

  it('treats an error or a failed request as unavailable', async () => {
    expect(await fetchCandidates('X', { api: '', fetchFn: () => resp(500) }))
      .toEqual({ candidates: [], unavailable: true });
    expect(await fetchCandidates('X', { api: '', fetchFn: () => Promise.reject(new Error('down')) }))
      .toEqual({ candidates: [], unavailable: true });
  });
});

describe('choosePicture', () => {
  it('PUTs the chosen url and attribution', async () => {
    const fetchFn = vi.fn(() => resp(200, { url: 'https://i/goat.jpg', attribution: '(c) a' }));
    const res = await choosePicture('Oreamnos americanus', CANDS[0], { api: 'http://h', fetchFn });
    expect(fetchFn).toHaveBeenCalledWith('http://h/api/species/Oreamnos%20americanus/image', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: 'https://i/goat.jpg', attribution: '(c) a' }),
    });
    expect(res).toEqual({ url: 'https://i/goat.jpg', attribution: '(c) a' });
  });

  it('returns null when the server refuses', async () => {
    expect(await choosePicture('X', CANDS[0], { api: '', fetchFn: () => resp(400) })).toBeNull();
    expect(await choosePicture('X', CANDS[0], { api: '', fetchFn: () => Promise.reject(new Error()) })).toBeNull();
  });
});
