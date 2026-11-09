import {clearRecords, esc, nav, openSheet, route} from './ui.js';
import {briefView, peopleView, portfolioView, researchView, verdict} from './views.js';

const workspace = document.querySelector('#workspace');
const sheet = document.querySelector('#sheet');
const scrollPositions = new Map();
let catalog;
let activeResearch;
let revision = 0;
let activeHash = '';
function locationState() {
  const [view, raw=''] = location.hash.slice(1).split('?');
  return {view:view || 'brief', params:new URLSearchParams(raw)};
}
async function api(path, params = {}) {
  const url = new URL('/api/' + path, location.origin);
  Object.entries(params).forEach(([key,value]) => { if (value) url.searchParams.set(key,value); });
  const response = await fetch(url,{headers:{Accept:'application/json'}});
  if (!response.ok) {
    const error = await response.json().catch(()=>({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'The request could not be completed.');
  }
  return response.json();
}
async function render() {
  const version=++revision;
  if (activeHash) scrollPositions.set(activeHash, window.scrollY);
  const destination=location.hash || '#brief';
  const {view,params}=locationState();
  sheet.close();
  nav(view);
  workspace.setAttribute('aria-busy','true');
  try {
    catalog ||= await api('catalog');
    if (version!==revision) return;
    let draw;
    if (view==='brief') {
      const data=await api('brief',{window:params.get('window') || '24h', start:params.get('start'),end:params.get('end')});
      draw=()=>briefView(data,params,params.get('window')==='custom');
    } else if (view==='research') {
      const symbol=params.get('ticker') || 'INFY';
      const data=await api('research/'+encodeURIComponent(symbol),{q:params.get('q')});
      draw=()=>{activeResearch=data;return researchView(data,catalog);};
    } else if (view==='people') {
      const q=params.get('q')||'',symbol=params.get('symbol')||'';
      const data=await api('people',{q,symbol});
      draw=()=>peopleView(data,q,symbol,catalog);
    } else if (view==='portfolio') {
      draw=()=>portfolioView(catalog);
    } else {
      throw new Error('This view is unavailable.');
    }
    if (version!==revision) return;
    clearRecords();
    workspace.innerHTML=draw();
    const mode = view === 'research' ? 'Document index' : view === 'people' ? 'Fictional network' : 'Historical replay';
    document.querySelector('#mode-text').textContent = mode;
    document.title=(workspace.querySelector('h1')?.textContent || 'Portfolio brief')+' · FINN';
    activeHash=destination;
    window.scrollTo(0,scrollPositions.get(destination)||0);
  } catch(error) {
    if (version!==revision) return;
    workspace.innerHTML=`<section class="empty error" role="alert"><h2>Unable to open this view</h2><p>${esc(error.message)}</p><button class="button secondary" id="retry">Retry</button> <a href="#brief">Back to brief</a></section>`;
  } finally {
    if (version===revision) workspace.removeAttribute('aria-busy');
  }
}

document.addEventListener('click',event=>{
  const target=event.target.closest('button, a, dialog');
  if (!target) return;
  if (target.hasAttribute('data-sheet')) { openSheet(target.dataset.sheet); return; }
  if (target.matches('.close') || (event.target===sheet && target===sheet)) { sheet.close(); return; }
  if (target.id==='retry') { render(); return; }
  if (target.id==='dates-toggle') {
    const form=document.querySelector('#date-form');
    form.hidden=!form.hidden;
    target.setAttribute('aria-expanded',String(!form.hidden));
    if (!form.hidden) form.querySelector('input').focus();
    return;
  }
  if (target.matches('[data-forecast]') && activeResearch?.comparison) {
    const i=Number(target.dataset.forecast);
    document.querySelectorAll('[data-forecast]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn===target)));
    document.querySelector('#verdict').innerHTML=verdict(activeResearch.comparison,i);
  }
});
document.querySelector('.skip').addEventListener('click',event=>{event.preventDefault();workspace.focus();});
document.addEventListener('submit',event=>{
  const form=event.target;
  const {params}=locationState();
  const fields=new FormData(form);
  const field=k=>String(fields.get(k)||'').trim();
  event.preventDefault();
  if (form.id==='date-form') {
    const start=field('start'),end=field('end');
    form.elements.end.setCustomValidity(start>end?'End date must be on or after the start date.':'');
    if (form.reportValidity()) location.hash=route('brief',{window:'custom',start,end});
  } else if (form.id==='ticker-form') {
    const input=field('ticker'), term=input.toLowerCase();
    const match=catalog.companies.find(c=>c.name.toLowerCase()===term || c.symbol.toLowerCase()===term);
    const possible=catalog.companies.filter(c=>c.name.toLowerCase().startsWith(term));
    const symbol=match?.symbol || (possible.length===1?possible[0].symbol:input.toUpperCase());
    form.elements.ticker.setCustomValidity(/^[A-Z0-9][A-Z0-9&.-]{0,24}$/.test(symbol)?'':'Choose a listed suggestion or enter an NSE ticker.');
    if (form.reportValidity()) location.hash=route('research',{ticker:symbol});
  } else if (form.id==='evidence-form') {
    location.hash=route('research',{ticker:activeResearch.company.symbol,q:field('term')});
  } else if (form.id==='people-form') {
    location.hash=route('people',{q:field('q'),symbol:params.get('symbol')});
  }
});
document.addEventListener('input',event=>{
  if (event.target.form?.id==='date-form') event.target.form.elements.end.setCustomValidity('');
  if (event.target.id==='ticker') event.target.setCustomValidity('');
});
if ('scrollRestoration' in history) history.scrollRestoration='manual';
window.addEventListener('hashchange',render);
render();
