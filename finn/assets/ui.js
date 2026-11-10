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
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return new Intl.DateTimeFormat('en-IN', {
      timeZone:'Asia/Kolkata', day:'numeric', month:'short', year:'numeric',
      hour:'2-digit', minute:'2-digit', hour12:false
    }).format(new Date(value)) + ' IST';
  }
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
let canReview = false;
export function setWorkspaceAccess(value) { canReview=Boolean(value); }
export function getRecord(id) { return records.get(id)?.data; }
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
    const sourceLocation = [d.page ? 'PDF page ' + d.page : '', d.locator].filter(Boolean).join(' · ');
    const evidenceKind = d.kind === 'EOD market data' ? 'Market data' : 'Primary evidence';
    const cached=d.cached_url && /^\/api\/documents\/[a-zA-Z0-9-]+\/original\?revision=[a-f0-9]{64}$/.test(d.cached_url)?new URL(d.cached_url,window.location.origin):null;
    if(cached && d.page)cached.hash='page='+d.page;
    content = `<div class="kicker">${evidenceKind}</div><h2 id="sheet-title">${esc(d.title)}</h2>
      <p class="muted">${esc(d.symbol)} · ${esc(d.kind)} · ${esc(dateLabel(d.date))}</p>
      ${d.date_note?`<p class="coverage">${esc(d.date_note)}</p>`:''}
      ${d.excerpt_type === 'summary' ? `<h3>Indexed summary</h3><p>${esc(d.excerpt)}</p>` :
        d.excerpt ? `<blockquote>${esc(d.excerpt)}</blockquote>` : ''}
      <p class="source-locator">${icon('book')} ${esc(sourceLocation || 'Original document')}</p>
      ${cached?`<a class="button primary" href="${esc(cached.href)}" target="_blank" rel="noopener noreferrer">Open cached original ${icon('file')}</a>`:''}
      <a class="button ${cached?'secondary':'primary'}" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Open original ${icon('external')}</a>
      <p class="url-host">${esc(url.hostname)}</p>
      ${d.versions?.length>1?`<details><summary>Recorded filing versions · ${d.versions.length}</summary>${d.versions.map(v=>`<p>${esc(dateLabel(v.date))} · ${esc(v.title)}</p><a class="text-button" href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">Open original</a>`).join('')}</details>`:''}
      ${canReview && d.page && d.excerpt && d.excerpt_type!=='summary' && ['Annual report','Earnings call'].includes(d.kind)?`<button type="button" class="text-button" data-review-source="${esc(id)}">Use passage in a reviewed fact</button>`:''}
      ${d.related ? `<a class="text-button" href="${esc(d.related.url)}" target="_blank" rel="noopener noreferrer">${esc(d.related.title)} ${icon('external',15)}</a>` : ''}`;
  } else {
    content = `<div class="kicker">${d.fictional?'Fictional demo contact':'Permissioned network profile'}</div><h2 id="sheet-title">${esc(d.name)}</h2>
      <p class="muted">${esc(d.role)} · ${esc(d.company)} · ${esc(d.tenure)}</p>
      <h3>Connection</h3><ol class="path">${d.path.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
      <h3>Experience</h3><p>${esc(d.topics.join(' · '))}</p>
      ${d.employment?.length>1?`<details><summary>Employment history</summary>${d.employment.map(e=>`<p>${esc(e.role)} · ${esc(e.employer)} · ${esc(e.start||'Date unverified')}–${esc(e.end||'present')}</p>`).join('')}</details>`:''}
      ${d.education?.length?`<h3>Education</h3><p>${esc(d.education.join(' · '))}</p>`:''}
      <h3>A question to ask</h3><blockquote>${esc(d.question)}</blockquote>
      ${d.can_edit?`<details class="contact-notes"><summary>Private contact note</summary><form id="contact-note-form" class="stack"><input type="hidden" name="person" value="${esc(d.id)}"><input type="hidden" name="record" value="${esc(id)}"><label>Last contact<input type="date" name="last_contact" max="${new Date().toISOString().slice(0,10)}" value="${esc(d.last_contact||'')}"></label><label>Note<textarea name="note" rows="3" maxlength="2000">${esc(d.note||'')}</textarea></label><button type="submit" class="button secondary">Save private note</button><p id="contact-note-status" role="status"></p></form><button type="button" class="text-button" data-delete-person="${esc(d.id)}">Withdraw this profile and its links</button></details>`:''}`;
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
