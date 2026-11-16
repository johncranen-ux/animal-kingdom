// Chat conversation memory: the browser keeps the turns and sends the latest
// with each question, so "what does it eat" can follow "the largest animal".
// The backend caps them again; a page reload starts a new conversation.

export const CHAT_HISTORY_MAX = 6;   // messages: three questions and their answers

export function chatRequestBody(message, history) {
  return JSON.stringify({ message, history: history.slice(-CHAT_HISTORY_MAX) });
}

// A failed or empty answer is not remembered: the next question starts from the last good one
export function rememberTurn(history, question, answer) {
  if (answer && answer.trim()) {
    history.push({ role: 'user', content: question }, { role: 'assistant', content: answer });
  }
  return history;
}

// Chat name links: the server's `links` event names the animals the answer is
// about ({text, scientific_name, taxon_path, taxon_rank}); each mention becomes
// an <a class="taxon-link"> that app.js opens like a search result.
const SKIP_TAGS = new Set(['A', 'CODE', 'PRE']);
const WORD_CHAR = /[\p{L}\p{N}]/u;

function _skipped(node, root) {
  for (let el = node.parentElement; el && el !== root.parentElement; el = el.parentElement) {
    if (SKIP_TAGS.has(el.tagName)) return true;
  }
  return false;
}

function _textNodes(root) {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (!_skipped(walker.currentNode, root)) nodes.push(walker.currentNode);
  }
  return nodes;
}

function _isWordChar(ch) {
  return ch !== undefined && ch !== '' && WORD_CHAR.test(ch);
}

function _anchor(doc, link) {
  const a = doc.createElement('a');
  a.className = 'taxon-link';
  a.href = '#';
  a.textContent = link.text;
  a.dataset.scientificName = link.scientific_name;
  a.dataset.taxonPath = link.taxon_path || '';
  a.dataset.taxonRank = link.taxon_rank || '';
  a.title = link.taxon_rank ? `${link.scientific_name} (${link.taxon_rank})` : link.scientific_name;
  return a;
}

// Wraps every whole-word mention of each link's text; returns the number of links made
export function linkNames(root, links) {
  if (!root || !Array.isArray(links) || !links.length) return 0;
  const doc = root.ownerDocument;
  let made = 0;
  const ordered = links.filter(l => l && l.text).sort((a, b) => b.text.length - a.text.length);
  for (const link of ordered) {
    for (const node of _textNodes(root)) {
      let current = node;
      let from = 0;
      while (true) {
        const value = current.nodeValue;
        const at = value.indexOf(link.text, from);
        if (at < 0) break;
        const end = at + link.text.length;
        if (_isWordChar(value[at - 1]) || _isWordChar(value[end])) { from = at + 1; continue; }
        const match = at ? current.splitText(at) : current;
        const rest = match.splitText(link.text.length);
        match.replaceWith(_anchor(doc, link));
        made += 1;
        current = rest;
        from = 0;
      }
    }
  }
  return made;
}

// The item a taxon link opens: the shape search results have
export function taxonItem(anchor) {
  return {
    scientific_name: anchor.dataset.scientificName,
    taxon_path: anchor.dataset.taxonPath || null,
    taxon_rank: anchor.dataset.taxonRank || null,
  };
}
