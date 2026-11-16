import { describe, it, expect } from 'vitest';
import { chatRequestBody, rememberTurn, CHAT_HISTORY_MAX, linkNames, taxonItem } from '../js/chat.js';

describe('chat memory', () => {
  it('sends the question with the earlier turns', () => {
    const history = [{ role: 'user', content: 'what is the largest animal' },
                     { role: 'assistant', content: 'Database: The Blue whale.' }];
    expect(JSON.parse(chatRequestBody('what does it eat', history)))
      .toEqual({ message: 'what does it eat', history });
  });

  it('sends only the last turns', () => {
    const history = Array.from({ length: 20 }, (_, i) =>
      ({ role: i % 2 ? 'assistant' : 'user', content: `m${i}` }));
    const sent = JSON.parse(chatRequestBody('q', history)).history;
    expect(sent).toHaveLength(CHAT_HISTORY_MAX);
    expect(sent[0].content).toBe(`m${20 - CHAT_HISTORY_MAX}`);
  });

  it('remembers a question with its answer', () => {
    const history = [];
    rememberTurn(history, 'what is the largest animal', 'Database: The Blue whale.');
    expect(history).toEqual([{ role: 'user', content: 'what is the largest animal' },
                             { role: 'assistant', content: 'Database: The Blue whale.' }]);
  });

  it('forgets a turn that failed or had no answer', () => {
    const history = [];
    rememberTurn(history, 'q', '');
    rememberTurn(history, 'q', '   ');
    rememberTurn(history, 'q', null);
    expect(history).toEqual([]);
  });
});

describe('chat name links', () => {
  const LION = { text: 'Lion', scientific_name: 'Panthera leo', taxon_path: 'A|P', taxon_rank: 'species' };
  const box = html => { const el = document.createElement('div'); el.innerHTML = html; return el; };

  it('wraps each mention in a taxon link with its data and tooltip', () => {
    const el = box('<p>Database: Koalas eat leaves. The <strong>Koalas</strong> sleep.</p>');
    expect(linkNames(el, [{ text: 'Koalas', scientific_name: 'Phascolarctos cinereus',
                            taxon_path: 'A|P', taxon_rank: 'species' }])).toBe(2);
    const a = el.querySelector('a.taxon-link');
    expect(a.textContent).toBe('Koalas');
    expect(a.dataset.scientificName).toBe('Phascolarctos cinereus');
    expect(a.dataset.taxonPath).toBe('A|P');
    expect(a.dataset.taxonRank).toBe('species');
    expect(a.title).toBe('Phascolarctos cinereus (species)');
    expect(el.textContent).toBe('Database: Koalas eat leaves. The Koalas sleep.');
  });

  it('does not wrap inside a longer word, a link or code', () => {
    const el = box('<p>Lionfish. <a href="#">Lion</a> <code>Lion</code> <pre>Lion</pre> Lion.</p>');
    expect(linkNames(el, [LION])).toBe(1);
  });

  it('wraps a possessive and a name inside emphasis', () => {
    expect(linkNames(box("<p>The Lion's mane.</p>"), [LION])).toBe(1);
    const el = box('<p>(<em>Panthera leo</em>)</p>');
    expect(linkNames(el, [{ ...LION, text: 'Panthera leo' }])).toBe(1);
    expect(el.querySelector('em a.taxon-link').textContent).toBe('Panthera leo');
  });

  it('links the longest text first and several mentions in one text node', () => {
    const el = box('<p>Panthera leo is in Panthera. Panthera again.</p>');
    const n = linkNames(el, [{ text: 'Panthera', scientific_name: 'Panthera', taxon_path: 'A|P', taxon_rank: 'genus' },
                             { ...LION, text: 'Panthera leo' }]);
    expect(n).toBe(3);
    expect([...el.querySelectorAll('a')].map(a => a.dataset.scientificName))
      .toEqual(['Panthera leo', 'Panthera', 'Panthera']);
  });

  it('treats names literally', () => {
    const el = box('<p>a+b (c) and a+b (c)x</p>');
    expect(linkNames(el, [{ ...LION, text: 'a+b (c)' }])).toBe(1);
  });

  it('reads the item back from a link, without a path for rows outside the tree', () => {
    const el = box('<p>Gbif onlyus.</p>');
    linkNames(el, [{ text: 'Gbif onlyus', scientific_name: 'Gbif onlyus', taxon_path: null, taxon_rank: 'species' }]);
    expect(taxonItem(el.querySelector('a.taxon-link')))
      .toEqual({ scientific_name: 'Gbif onlyus', taxon_path: null, taxon_rank: 'species' });
  });

  it('makes no links for an empty list', () => {
    expect(linkNames(box('<p>Lion</p>'), [])).toBe(0);
    expect(linkNames(box('<p>Lion</p>'), undefined)).toBe(0);
  });
});
