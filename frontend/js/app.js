import { initTree, renderLegend, searchSpecies, highlightNodes, expandToNode, openDomain, clearSelection, getPathToNode, setHideExtinct, setNodeExtinct, refreshAncestorFlags } from './visualizer.js';
import { escapeHtml, traitRowsHtml, nextTraitStage, panelShows, loadTraits, searchResultLabel, rankLine, currentNameHtml } from './traits.js';
import { chatRequestBody, rememberTurn, linkNames, taxonItem } from './chat.js';
import {
  noPictureHtml, searchedAgainDate, retryPicture,
  otherPicturesButtonHtml, candidatesHtml, galleryMessageHtml, galleryNoteText, fetchCandidates, choosePicture,
} from './images.js';

// Same origin when FastAPI serves the page (any port); :8000 fallback for file:// pages.
const API = window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:8000';
const SEARCH_DEBOUNCE_MS = 300;

let _searchTimer = null;
let _resultsEl = null;

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  const legend = document.getElementById('tree-legend');
  if (legend) renderLegend(legend);
  await initTree('tree-container');
  _initSearch();
  _initChat();
  _initSpeciesPanel();
  _initTreeSpinner();
  _initHideExtinct();
});

// ── Hide-extinct toggle (remembered between visits) ───────────────────────────

const HIDE_EXTINCT_KEY = 'ak.hideExtinct';

function _initHideExtinct() {
  const box = document.getElementById('hide-extinct');
  if (!box) return;
  box.checked = localStorage.getItem(HIDE_EXTINCT_KEY) === '1';
  setHideExtinct(box.checked);
  const save = hide => localStorage.setItem(HIDE_EXTINCT_KEY, hide ? '1' : '0');
  box.addEventListener('change', () => {
    setHideExtinct(box.checked);
    save(box.checked);
  });
  // Clicking a tree's "† N extinct hidden" placeholder turns the filter off
  document.addEventListener('hide-extinct-changed', ({ detail }) => {
    box.checked = detail.hide;
    save(detail.hide);
  });
}

// ── Tree spinner ──────────────────────────────────────────────────────────────

function _initTreeSpinner() {
  const spinner = document.getElementById('tree-spinner');
  if (!spinner) return;
  document.addEventListener('tree-loading', ({ detail }) => {
    spinner.classList.toggle('hidden', !detail.loading);
  });
}

// ── Search ────────────────────────────────────────────────────────────────────

function _initSearch() {
  const input   = document.getElementById('search-input');
  const results = document.getElementById('search-results');
  _resultsEl = results;
  if (!input || !results) return;

  input.addEventListener('input', () => {
    clearTimeout(_searchTimer);
    const q = input.value.trim();
    if (!q) { _clearResults(); highlightNodes([]); return; }
    _searchTimer = setTimeout(() => _doSearch(q), SEARCH_DEBOUNCE_MS);
  });

  document.addEventListener('click', e => {
    if (input.contains(e.target) || results.contains(e.target)) return;
    // A chat name link has just highlighted its taxon: close the list, keep the highlight
    if (e.target.closest?.('a.taxon-link')) _hideResults();
    else _clearResults();
  });
}

async function _doSearch(q) {
  let data;
  try {
    data = await searchSpecies(q);
  } catch {
    _showToast('Search failed — is the backend running?');
    return;
  }
  _showResults(data);
  highlightNodes(data.map(r => r.taxon_path).filter(Boolean));
}

function _showResults(items) {
  _resultsEl.innerHTML = '';
  if (!items.length) { _resultsEl.classList.add('hidden'); return; }
  items.forEach(item => {
    const li = document.createElement('li');
    li.className = 'px-3 py-2 hover:bg-gray-700 cursor-pointer text-sm';
    li.innerHTML = searchResultLabel(item);
    li.addEventListener('click', async () => {
      document.getElementById('search-input').value = item.scientific_name;
      _resultsEl.innerHTML = '';
      _resultsEl.classList.add('hidden');
      await openTaxon(item);
    });
    _resultsEl.appendChild(li);
  });
  _resultsEl.classList.remove('hidden');
}

// Opens a taxon in the tree and the panel: search results and chat name links
async function openTaxon(item) {
  if (item.taxon_rank === 'domain') {
    highlightNodes([]);
    await openDomain(item.taxon_path);
  } else if (item.taxon_path) {
    highlightNodes([item.taxon_path]);
    await expandToNode(item.taxon_path);
    _fetchAndShowSpecies(item.scientific_name);
  } else {
    // Kept in the database but outside the classification: nothing to open in the tree
    highlightNodes([]);
    _fetchAndShowSpecies(item.scientific_name);
  }
}

function _hideResults() {
  if (_resultsEl) { _resultsEl.innerHTML = ''; _resultsEl.classList.add('hidden'); }
}

function _clearResults() {
  _hideResults();
  highlightNodes([]);
}

// ── Species detail panel ──────────────────────────────────────────────────────

// The record the panel shows, for its "Current name" link (re-rendered as traits arrive)
let _panelSp = null;

function _initSpeciesPanel() {
  document.getElementById('sp-fields')?.addEventListener('click', e => {
    const link = e.target.closest?.('a[data-current-name]');
    const cur = _panelSp?.current_name;
    if (!link || !cur) return;
    e.preventDefault();
    openTaxon(cur);
  });

  // "Search again" on a panel without a picture: the backend's wide search
  document.getElementById('sp-image-wrap')?.addEventListener('click', async e => {
    if (!e.target.closest('button[data-picture-retry]') || !_panelSp) return;
    const name = _panelSp.scientific_name;
    const gen = ++_imageGen;
    _showNoPicture('searching');
    const res = await retryPicture(name, { api: API });
    if (gen !== _imageGen) return;   // the panel moved on, or a picture was chosen meanwhile
    if (res.url) _showPicture(res.url, res.attribution, name, () => _showNoPicture('still-none'));
    else _showNoPicture(res.state, res.searchedOn);
  });

  // "Other pictures": candidates from every source; the clicked one is kept
  document.getElementById('sp-picture-tools').innerHTML = otherPicturesButtonHtml();
  document.getElementById('sp-image-wrap')?.addEventListener('click', async e => {
    if (!_panelSp) return;
    const name = _panelSp.scientific_name;
    if (e.target.closest('button[data-picture-cancel]')) {
      _closeGallery();
    } else if (e.target.closest('button[data-picture-choose]')) {
      _openGallery(galleryMessageHtml('loading'));
      const { candidates, unavailable } = await fetchCandidates(name, { api: API });
      if (!panelShows(name) || !_galleryOpen()) return;
      if (candidates.length) _showCandidates(candidates, unavailable ? 'partial' : null);
      else _openGallery(galleryMessageHtml(unavailable ? 'unavailable' : 'empty'));
    } else {
      const btn = e.target.closest('button[data-candidate]');
      if (!btn || _choosing) return;   // one choice at a time: a second click waits for the first
      _choosing = true;
      const box = document.getElementById('sp-picture-choice');
      box.classList.add('opacity-50');
      let chosen;
      try {
        chosen = await choosePicture(name, _candidates[Number(btn.dataset.candidate)], { api: API });
      } finally {
        _choosing = false;
        box.classList.remove('opacity-50');
      }
      if (!panelShows(name)) return;
      if (!chosen) {   // keep the thumbnails so another click can try again
        const note = box.querySelector('[data-gallery-note]');
        if (note) { note.textContent = galleryNoteText('failed'); note.classList.remove('hidden'); }
        return;
      }
      ++_imageGen;   // a lookup still running for this panel must not replace the choice
      _closeGallery();
      _panelSp.primary_image_url = chosen.url;
      _panelSp.image_attribution = chosen.attribution;
      _showPicture(chosen.url, chosen.attribution, name, () => _fetchRemoteImage(name, true, chosen.url));
    }
  });

  document.getElementById('sp-close')?.addEventListener('click', () => {
    document.getElementById('species-panel').classList.add('hidden');
    clearSelection();
  });

  document.addEventListener('species-selected', ({ detail }) => {
    if (!detail.selected) {
      document.getElementById('species-panel').classList.add('hidden');
      return;
    }
    _fetchAndShowSpecies(detail.scientific_name);
  });
}

async function _fetchAndShowSpecies(scientificName) {
  const panel = document.getElementById('species-panel');
  panel.classList.remove('hidden');
  document.getElementById('sp-fields').innerHTML =
    '<p class="text-gray-400">Loading…</p>';

  try {
    const resp = await fetch(`${API}/api/species/${encodeURIComponent(scientificName)}`);
    if (!resp.ok) throw new Error(`Not found (${resp.status})`);
    _showSpeciesPanel(await resp.json());
  } catch (err) {
    document.getElementById('sp-fields').innerHTML =
      `<p class="text-red-400">${err.message}</p>`;
  }
}

function _buildLineage(taxonPath) {
  if (!taxonPath) return null;
  const pathNodes = getPathToNode(taxonPath);
  if (!pathNodes) return taxonPath.replace(/\|/g, ' › ');
  return pathNodes.map(({ node_id, label }) => {
    const sciName = node_id.split('|').pop();
    return label !== sciName ? `${label} (${sciName})` : label;
  }).join(' › ');
}

function _showSpeciesPanel(sp) {
  document.getElementById('sp-name').textContent   = sp.scientific_name || '—';
  document.getElementById('sp-common').textContent = sp.common_names?.join(', ') || '';

  _panelSp = sp;   // before the image lookup, so "Search again" knows the animal
  ++_imageGen;     // lookups started for the previous animal are now stale
  _closeGallery();
  if (sp.primary_image_url === '__none__') {
    _showNoPicture('none', searchedAgainDate(sp.image_attribution));
  } else if (sp.primary_image_url) {
    _showPicture(sp.primary_image_url, sp.image_attribution, sp.scientific_name,
                 () => _fetchRemoteImage(sp.scientific_name, true, sp.primary_image_url));
  } else {
    _showPicture(null, 'Finding image…', sp.scientific_name, null);
    document.getElementById('sp-image').removeAttribute('src');
    _fetchRemoteImage(sp.scientific_name, false);
  }

  _renderSpeciesFields(sp, !!nextTraitStage(sp));
  if (nextTraitStage(sp)) _loadTraits(sp);
}

function _renderSpeciesFields(sp, loading) {
  _panelSp = sp;
  // re-rendered as traits arrive, so the extinct flag from GBIF shows up too
  document.getElementById('sp-rank').textContent = rankLine(sp);
  // keep the tree's † in step with what the panel learned
  // (/traits returns the raw column value 1/0, /species a boolean)
  const extinct = sp.iucn_status === 'EX' || (sp.extinct == null ? null : !!sp.extinct);
  if (setNodeExtinct(sp.taxon_path, extinct) && extinct) refreshAncestorFlags(sp.taxon_path);
  const lineage = _buildLineage(sp.taxon_path);
  const lineageRow = lineage
    ? `<div class="flex gap-1.5">
         <span class="text-gray-400 shrink-0 w-28">Lineage</span>
         <span class="text-gray-200 break-words">${escapeHtml(lineage)}</span>
       </div>`
    : '';

  document.getElementById('sp-fields').innerHTML = [
    currentNameHtml(sp),
    traitRowsHtml(sp, sp.provenance),
    lineageRow,
    loading ? '<p id="sp-traits-loading" class="text-gray-400 italic">Looking up traits…</p>' : '',
    sp.wikipedia_abstract
      ? `<p class="mt-2 pt-2 border-t border-gray-700 text-gray-300 leading-relaxed">
           ${escapeHtml(sp.wikipedia_abstract)}
         </p>`
      : '',
  ].join('');
}

// Fetch missing traits after the panel opens (like _fetchRemoteImage for images)
function _loadTraits(sp) {
  const name = sp.scientific_name;
  loadTraits(sp, {
    api: API,
    isCurrent: () => panelShows(name),
    onData: updated => _renderSpeciesFields(updated, !!nextTraitStage(updated)),
    onDone: () => document.getElementById('sp-traits-loading')?.remove(),
  });
}

// failedUrl: a stored picture that didn't load; this lookup skips it (not rejected for
// good: offline, every picture fails)
async function _fetchRemoteImage(scientificName, force, failedUrl = null) {
  const params = new URLSearchParams();
  if (force) params.set('force', 'true');
  if (failedUrl) params.set('failed', failedUrl);
  const qs  = params.toString() ? `?${params}` : '';
  const url = `${API}/api/species/${encodeURIComponent(scientificName)}/image${qs}`;
  const gen = _imageGen;
  let data = null;
  let state = 'none';
  try {
    const resp = await fetch(url);
    if (resp.ok) data = await resp.json();
    else if (resp.status === 503) state = 'unavailable';
  } catch {
    state = 'unavailable';
  }
  // another animal, a choice or a Search again since this lookup started: it's stale
  if (gen !== _imageGen || !panelShows(scientificName)) return;
  if (data) _showPicture(data.url, data.attribution, scientificName, () => _showNoPicture('none'));
  else _showNoPicture(state);
}

// The image area shows either a picture (with its attribution) or the no-picture line
function _showPicture(url, attribution, name, onError) {
  const imgEl = document.getElementById('sp-image');
  document.getElementById('sp-no-image').classList.add('hidden');
  imgEl.classList.remove('hidden');
  imgEl.onerror = onError;
  if (url) imgEl.src = url;
  imgEl.alt = name;
  const attrEl = document.getElementById('sp-attr');
  attrEl.textContent = attribution || '';
  attrEl.classList.remove('hidden');
  document.getElementById('sp-image-wrap').classList.remove('hidden');
  _setChooseEnabled(true);
}

// "Other pictures" waits while Search again runs, so a gallery never opens beside it
function _setChooseEnabled(enabled) {
  const btn = document.querySelector('button[data-picture-choose]');
  if (btn) btn.disabled = !enabled;
}

function _showNoPicture(state, searchedOn) {
  const imgEl = document.getElementById('sp-image');
  imgEl.onerror = null;
  imgEl.removeAttribute('src');
  imgEl.classList.add('hidden');
  document.getElementById('sp-attr').classList.add('hidden');
  const box = document.getElementById('sp-no-image');
  box.innerHTML = noPictureHtml(state, searchedOn);
  box.classList.remove('hidden');
  document.getElementById('sp-image-wrap').classList.remove('hidden');
  _setChooseEnabled(state !== 'searching');
}

// The "Other pictures" gallery takes the image area's place until a choice or Cancel
let _candidates = [];
let _choosing = false;   // a choice is being saved
let _imageGen = 0;       // bumped by a new panel, a choice and Search again; older lookups are stale

function _galleryOpen() {
  return !document.getElementById('sp-picture-choice').classList.contains('hidden');
}

function _openGallery(html) {
  const box = document.getElementById('sp-picture-choice');
  box.innerHTML = html;
  box.classList.remove('hidden');
  document.getElementById('sp-image-view').classList.add('hidden');
  document.getElementById('sp-image-wrap').classList.remove('hidden');
}

function _closeGallery() {
  _candidates = [];
  const box = document.getElementById('sp-picture-choice');
  box.innerHTML = '';
  box.classList.add('hidden');
  document.getElementById('sp-image-view').classList.remove('hidden');
}

function _showCandidates(candidates, note = null) {
  _candidates = candidates;
  _openGallery(candidatesHtml(candidates, note));
  const box = document.getElementById('sp-picture-choice');
  // a picture that doesn't load isn't offered
  box.querySelectorAll('button[data-candidate] img').forEach(img => img.addEventListener('error', () => {
    img.closest('button').remove();
    if (!box.querySelector('button[data-candidate]')) _openGallery(galleryMessageHtml('empty'));
  }));
}

// ── Toast notifications ───────────────────────────────────────────────────────

function _showToast(message, type = 'error') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const colors = type === 'error'
    ? 'bg-red-900/95 border-red-700 text-red-100'
    : 'bg-yellow-900/95 border-yellow-700 text-yellow-100';
  const toast = document.createElement('div');
  toast.className = `flex items-start gap-2 max-w-xs px-4 py-3 rounded-lg border shadow-lg
                     backdrop-blur text-sm ${colors} transition-opacity duration-300`;
  toast.innerHTML = `<span class="flex-1">${message}</span>
    <button class="shrink-0 opacity-60 hover:opacity-100 text-lg leading-none">&times;</button>`;
  toast.querySelector('button').addEventListener('click', () => toast.remove());
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function _initChat() {
  const form    = document.getElementById('chat-form');
  const input   = document.getElementById('chat-input');
  const messages = document.getElementById('chat-messages');
  if (!form || !input || !messages) return;
  const history = [];   // this page's conversation, sent with each question

  messages.addEventListener('click', e => {
    const a = e.target.closest('a.taxon-link');
    if (!a || !messages.contains(a)) return;
    e.preventDefault();
    openTaxon(taxonItem(a));
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.disabled = true;
    form.querySelector('button').disabled = true;

    _appendBubble(messages, 'user', text);
    const assistantBubble = _appendBubble(messages, 'assistant', '');

    try {
      rememberTurn(history, text, await _streamChat(text, assistantBubble, history));
    } catch (err) {
      _setError(assistantBubble, err.message);
      if (err.message.includes('backend') || err.message.includes('server')) {
        _showToast(err.message);
      }
    } finally {
      input.disabled = false;
      form.querySelector('button').disabled = false;
      input.focus();
    }
  });
}

// Returns the answer text, or '' after an error event
async function _streamChat(message, bubble, history = []) {
  let resp;
  try {
    resp = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: chatRequestBody(message, history),
    });
  } catch {
    throw new Error('Cannot reach the server. Is the backend running?');
  }

  if (!resp.ok) {
    throw new Error(`Server error ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const textEl = bubble.querySelector('.bubble-text');
  let buffer = '';
  let rawText = '';
  let failed = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let event;
      try { event = JSON.parse(line.slice(6)); } catch { continue; }

      if (event.type === 'token') {
        rawText += event.content;
        textEl.innerHTML = typeof marked !== 'undefined'
          ? marked.parse(rawText)
          : rawText;
        bubble.scrollIntoView({ block: 'end', behavior: 'smooth' });
      } else if (event.type === 'links') {
        linkNames(textEl, event.links);
      } else if (event.type === 'image') {
        _appendImage(bubble, event.url, event.attribution);
      } else if (event.type === 'error') {
        _setError(bubble, event.detail || 'Unknown error');
        failed = true;
      }
    }
  }
  return failed ? '' : rawText;
}

// ── Bubble helpers ─────────────────────────────────────────────────────────────

function _appendBubble(container, role, text) {
  const wrap = document.createElement('div');
  wrap.className = role === 'user'
    ? 'flex justify-end'
    : 'flex justify-start';

  const bubble = document.createElement('div');
  bubble.className = role === 'user'
    ? 'max-w-xs lg:max-w-md bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2 text-sm'
    : 'max-w-xs lg:max-w-md bg-gray-800 text-gray-100 rounded-2xl rounded-tl-sm px-4 py-2 text-sm';

  const textEl = document.createElement('div');
  textEl.className = role === 'user'
    ? 'bubble-text whitespace-pre-wrap leading-relaxed'
    : 'bubble-text prose prose-invert prose-sm max-w-none leading-relaxed';
  textEl.textContent = text;

  bubble.appendChild(textEl);
  wrap.appendChild(bubble);
  container.appendChild(wrap);
  wrap.scrollIntoView({ block: 'end', behavior: 'smooth' });
  return bubble;
}

function _appendImage(bubble, url, attribution) {
  const img = document.createElement('img');
  img.src = url;
  img.alt = 'Species image';
  img.className = 'mt-2 rounded max-w-[200px] block';
  img.onerror = () => img.remove();
  bubble.appendChild(img);

  if (attribution) {
    const cap = document.createElement('a');
    cap.href = attribution;
    cap.target = '_blank';
    cap.rel = 'noopener noreferrer';
    cap.className = 'text-xs text-gray-400 hover:text-gray-300 block mt-1';
    cap.textContent = 'Image source';
    bubble.appendChild(cap);
  }
}

function _setError(bubble, message) {
  const textEl = bubble.querySelector('.bubble-text');
  if (textEl && !textEl.textContent) {
    textEl.textContent = `⚠ ${message}`;
    textEl.className += ' text-red-400';
  } else {
    const err = document.createElement('p');
    err.className = 'text-red-400 text-xs mt-1';
    err.textContent = `⚠ ${message}`;
    bubble.appendChild(err);
  }
}
