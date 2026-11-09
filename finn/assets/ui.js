const shapes = {
  brief: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h5M7 16h8"/>',
  research: '<circle cx="10" cy="10" r="6.5"/><path d="m15 15 5.5 5.5"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M15 5a3 3 0 0 1 0 6m3 3a5 5 0 0 1 3 5"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>', external: '<path d="M8 5h11v11M19 5 6 18"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>', down: '<path d="m6 9 6 6 6-6"/>',
  book: '<path d="M3 5c4-1 7-1 9 2 2-3 5-3 9-2v14c-4-1-7-1-9 1-2-2-5-2-9-1zM12 7v13"/>',
  file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>', layers: '<path d="m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  link: '<path d="m10 14 4-4M8 16l-1 1a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m2 8a3.5 3.5 0 0 0 5 0l4-4a3.5 3.5 0 0 0-5-5l-1 1"/>'
};
export function icon(name, size = 18) {
  return `<svg class="icon" aria-hidden="true" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${shapes[name] || ''}</svg>`;
}
export const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, ch =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
export function route(view, params = {}) {
  const pairs = Object.entries(params).filter(([,value]) => value !== '' && value != null);
  const query = new URLSearchParams(pairs).toString();
  return '#' + view + (query ? '?' + query : '');
}
export function dateLabel(value, full = false) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return new Intl.DateTimeFormat('en-GB', {
    timeZone:'UTC', day:'numeric', month: full ? 'long' : 'short', year: 'numeric'
  }).format(new Date(value + 'T12:00:00Z'));
}
export function rangeText(f) { return `${f.low}–${f.high}%`; }
export function deltaText(f, short = false) {
  if (f.position === 'within') return short ? 'Inside the range' : 'The reported result was within this range.';
  const bound = f.position === 'below' ? 'lower' : 'upper';
  return short ? `${f.points} pp ${f.position}` : `${f.points} percentage points ${f.position} the ${bound} bound.`;
}
const records = new Map();
let recordIds = new WeakMap();
let nextId = 0;
export function clearRecords() {
  records.clear();
  recordIds = new WeakMap();
  nextId = 0;
}
function register(type, data) {
  if (recordIds.has(data)) return recordIds.get(data);
  const id = String(++nextId);
  records.set(id, {type, data});
  recordIds.set(data, id);
  return id;
}
export function sourceButton(source, label = 'View source', cls = 'text-button') {
  return `<button type="button" class="${cls}" data-sheet="${register('source', source)}">${esc(label)} ${icon('file',15)}</button>`;
}
export function personCard(p) {
  const initials = p.name.split(' ').map(x => x[0]).join('');
  const via = p.distance === 1 ? 'Direct contact' : 'Via ' + p.path[1];
  return `<button class="person" type="button" data-sheet="${register('person',p)}">
    <span class="avatar" aria-hidden="true">${esc(initials)}</span><span class="person-copy">
    <strong>${esc(p.name)}</strong><span>${esc(p.role)} · ${esc(p.company)}</span>
    <small>${esc(via)} · ${esc(p.tenure)}</small></span>${icon('chevron',16)}</button>`;
}
export function openSheet(id) {
  const entry = records.get(id);
  if (!entry) return;
  const d = entry.data;
  let content;
  if (entry.type === 'source') {
    const url = new URL(d.url);
    if (!['https:'].includes(url.protocol)) return;
    if (d.page) url.hash = 'page=' + d.page;
    const location = [d.page ? 'PDF page ' + d.page : '', d.locator].filter(Boolean).join(' · ');
    content = `<div class="kicker">Primary evidence</div><h2 id="sheet-title">${esc(d.title)}</h2>
      <p class="muted">${esc(d.symbol)} · ${esc(d.kind)} · ${esc(dateLabel(d.date))}</p>
      ${d.excerpt_type === 'summary' ? `<h3>Indexed summary</h3><p>${esc(d.excerpt)}</p>` :
        d.excerpt ? `<blockquote>${esc(d.excerpt)}</blockquote>` : ''}
      <p class="source-locator">${icon('book')} ${esc(location || 'Original document')}</p>
      <a class="button primary" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Open original ${icon('external')}</a>
      <p class="url-host">${esc(url.hostname)}</p>
      ${d.related ? `<a class="text-button" href="${esc(d.related.url)}" target="_blank" rel="noopener noreferrer">${esc(d.related.title)} ${icon('external',15)}</a>` : ''}`;
  } else {
    content = `<div class="kicker">Fictional demo contact</div><h2 id="sheet-title">${esc(d.name)}</h2>
      <p class="muted">${esc(d.role)} · ${esc(d.company)} · ${esc(d.tenure)}</p>
      <h3>Connection</h3><ol class="path">${d.path.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
      <h3>Experience</h3><p>${esc(d.topics.join(' · '))}</p><h3>A question to ask</h3><blockquote>${esc(d.question)}</blockquote>`;
  }
  document.querySelector('#sheet-body').innerHTML = `<button type="button" class="close" aria-label="Close panel">${icon('close')}</button>${content}`;
  const dialog = document.querySelector('#sheet');
  if (!dialog.open) dialog.showModal();
  dialog.querySelector('.close').focus();
}
export function nav(view) {
  const tabs = [['brief','Brief'],['research','Research'],['people','People']];
  const html = tabs.map(([id,name]) => `<a href="${route(id)}" ${(view === id || (view === 'portfolio' && id === 'brief')) ? 'aria-current="page"' : ''}>${icon(id,18)}${name}</a>`).join('');
  document.querySelector('.top-nav').innerHTML = html;
  document.querySelector('.bottom-nav').innerHTML = html;
}
export function heading(kicker,title,sub,action = '') {
  return `<div class="page-heading"><div><div class="kicker">${esc(kicker)}</div><h1>${esc(title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ''}</div>${action}</div>`;
}
export function empty(title, explanation) {
  return `<div class="empty"><h3>${esc(title)}</h3><p>${esc(explanation)}</p></div>`;
}
