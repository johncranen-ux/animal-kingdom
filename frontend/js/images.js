// Species panel without a picture: a grey line and a "Search again" button that
// asks the backend for its wide search (/image?retry=true: an old name's current
// name, GBIF photos). app.js shows the line wherever it used to hide the image area.
import { escapeHtml } from './traits.js';

const MESSAGES = {
  none: 'No picture found.',
  searching: 'Searching more sources…',
  'still-none': 'Still no picture after a wider search.',
  unavailable: "A picture source didn't answer. Try again later.",
};

export function noPictureHtml(state, searchedOn) {
  const text = state === 'none' && searchedOn
    ? `No picture found (searched again on ${escapeHtml(searchedOn)}).`
    : escapeHtml(MESSAGES[state] || MESSAGES.none);
  const disabled = state === 'searching' ? ' disabled' : '';
  return `<span>${text}</span>
    <button type="button" data-picture-retry${disabled}
            class="ml-2 px-2 py-0.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700 disabled:opacity-50">Search again</button>`;
}

// The backend stores "searched again YYYY-MM-DD" with a failed retry's no-picture mark
export function searchedAgainDate(attribution) {
  const m = /^searched again (\d{4}-\d{2}-\d{2})$/.exec(attribution || '');
  return m ? m[1] : null;
}

export async function retryPicture(name, { api, fetchFn = fetch }) {
  try {
    const resp = await fetchFn(`${api}/api/species/${encodeURIComponent(name)}/image?retry=true`);
    if (resp.ok) {
      const data = await resp.json();
      return { url: data.url, attribution: data.attribution || '' };
    }
    if (resp.status === 404) {
      let searchedOn = null;
      try { searchedOn = (await resp.json())?.detail?.searched_again || null; } catch { /* no body */ }
      return { state: 'still-none', searchedOn };
    }
  } catch { /* network error: same as a source being down */ }
  return { state: 'unavailable' };
}

// ── "Other pictures": candidates from every source; the clicked one is kept ──

const TOOL_BUTTON = 'px-2 py-0.5 rounded border border-gray-600 text-gray-200 hover:bg-gray-700 disabled:opacity-50';

export function otherPicturesButtonHtml() {
  return `<button type="button" data-picture-choose class="${TOOL_BUTTON}">Other pictures</button>`;
}

const CANCEL = `<button type="button" data-picture-cancel class="${TOOL_BUTTON} mt-1">Cancel</button>`;

const GALLERY_MESSAGES = {
  loading: 'Looking for pictures…',
  empty: 'No other pictures found.',
  unavailable: "A picture source didn't answer. Try again later.",
};

export function galleryMessageHtml(state) {
  return `<p>${escapeHtml(GALLERY_MESSAGES[state] || GALLERY_MESSAGES.empty)}</p>${CANCEL}`;
}

// A line above the thumbnails, which stay so the user can pick again
const GALLERY_NOTES = {
  partial: 'Some picture sources were too slow. Other pictures again may find more.',
  failed: "Couldn't keep that picture. Try again.",
};

export function galleryNoteText(state) {
  return GALLERY_NOTES[state] || '';
}

export function candidatesHtml(list, note = null) {
  const text = galleryNoteText(note);
  const noteHtml = `<p data-gallery-note class="mb-1${text ? '' : ' hidden'}">${escapeHtml(text)}</p>`;
  const items = list.map((c, i) => `
    <button type="button" data-candidate="${i}" title="${escapeHtml(c.attribution)}"
            class="block text-left rounded overflow-hidden border border-gray-700 hover:border-indigo-400">
      <img src="${escapeHtml(c.url)}" alt="" loading="lazy" class="w-full h-20 object-cover bg-gray-800" />
      <span class="block px-1 text-[10px] text-gray-400 truncate">${escapeHtml(c.source)}</span>
    </button>`).join('');
  return `${noteHtml}<div class="grid grid-cols-3 gap-1">${items}</div>${CANCEL}`;
}

export async function fetchCandidates(name, { api, fetchFn = fetch }) {
  try {
    const resp = await fetchFn(`${api}/api/species/${encodeURIComponent(name)}/image/candidates`);
    if (resp.ok) {
      const data = await resp.json();
      return { candidates: data.candidates || [], unavailable: !!data.unavailable };
    }
  } catch { /* network error */ }
  return { candidates: [], unavailable: true };
}

export async function choosePicture(name, candidate, { api, fetchFn = fetch }) {
  try {
    const resp = await fetchFn(`${api}/api/species/${encodeURIComponent(name)}/image`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: candidate.url, attribution: candidate.attribution }),
    });
    if (resp.ok) return await resp.json();
  } catch { /* network error */ }
  return null;
}
