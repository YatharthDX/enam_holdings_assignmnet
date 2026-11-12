import {clearRecords, esc, nav, openSheet, route, getRecord, setWorkspaceAccess} from './ui.js?v=0.6.3';
import {briefView, peopleView, portfolioView, researchView, verdict} from './views.js?v=0.6.3';
import {liveBriefView} from './live-view.js?v=0.6.3';
import {workspaceNotice, workspaceView} from './workspace-view.js?v=0.6.3';
import {identityResult} from './network-view.js?v=0.6.3';

const workspace = document.querySelector('#workspace');
const sheet = document.querySelector('#sheet');
const scrollPositions = new Map();
let catalog;
let session;
let activeResearch;
let revision = 0;
let activeHash = '';
let pollTimer;
let liveSignature = '';
let lastNotice = '';

function signature(value) {
  return JSON.stringify([value.job?.started,value.job?.finished,value.job?.status,value.unread]);
}

function userIsReading() {
  return sheet.open || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
}

function scheduleResearchPoll() {
  clearTimeout(pollTimer);
  if (activeResearch?.discovery?.status !== 'running' && activeResearch?.analysis?.job?.status !== 'running') return;
  const symbol = activeResearch.company.symbol;
  const previous = JSON.stringify([activeResearch.discovery, activeResearch.analysis?.job]);
  const lens = activeResearch.analysis?.lens || 'business';
  pollTimer = setTimeout(async () => {
    const {view, params} = locationState();
    if (view !== 'research' || (params.get('ticker') || 'INFY') !== symbol || (params.get('lens') || 'business') !== lens) return;
    try {
      const [docs, analysis] = await Promise.all([
        api('research/' + encodeURIComponent(symbol) + '/discovery'),
        activeResearch.analysis?.enabled && activeResearch.analysis?.job?.status === 'running' ?
          api('research/' + encodeURIComponent(symbol) + '/analysis',{lens}).catch(() => ({job:activeResearch.analysis?.job || null})) :
          Promise.resolve({job:activeResearch.analysis?.job || null})
      ]);
      if (JSON.stringify([docs.job, analysis.job]) !== previous && !userIsReading() &&
          !document.querySelector('.analysis-method[open]')) {
        catalog = null;
        await render();
        return;
      }
    } catch {
      const status = document.querySelector('#discovery-status');
      if (status) status.textContent = 'Connection interrupted. Existing indexed sources remain available.';
    }
    scheduleResearchPoll();
  }, 4000);
}

function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    const {view,params}=locationState();
    if (view!=='brief' || params.get('mode')==='replay') return;
    try {
      const current=await api('live/status');
      if (signature(current)!==liveSignature &&
          !userIsReading() &&
          !document.querySelector('#alert-rules[open]') &&
          !document.querySelector('#date-form:not([hidden])')) {
        await render();
        return;
      }
    } catch {
      const status=document.querySelector('#live-status');
      if (status) status.textContent='Connection interrupted. Showing the records already loaded.';
    }
    schedulePoll();
  },4000);
}
function locationState() {
  const [view, raw=''] = location.hash.slice(1).split('?');
  return {view:view || 'brief', params:new URLSearchParams(raw)};
}
async function api(path, params = {}, options = {}) {
  const url = new URL('/api/' + path, location.origin);
  Object.entries(params).forEach(([key,value]) => { if (value) url.searchParams.set(key,value); });
  const response = await fetch(url,{...options,headers:{Accept:'application/json',
    ...(session?.csrf && options.method?{'X-FINN-CSRF':session.csrf}:{}),
    ...(options.body ? {'Content-Type':'application/json'} : {})}});
  if (!response.ok) {
    if (response.status===401) {session=null;catalog=null;activeResearch=null;clearRecords();}
    const error = await response.json().catch(()=>({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : 'The request could not be completed.');
  }
  return response.json();
}
async function render() {
  clearTimeout(pollTimer);
  const version=++revision;
  if (activeHash) scrollPositions.set(activeHash, window.scrollY);
  let destination=location.hash || '#brief';
  const aiWasOpen=activeHash===destination && Boolean(document.querySelector('#optional-ai')?.open);
  let {view,params}=locationState();
  sheet.close();
  nav(view);
  workspace.setAttribute('aria-busy','true');
  try {
    if (session?.authenticated && session.expires*1000<=Date.now()) {
      session=null; catalog=null; activeResearch=null; clearRecords();
    }
    session ||= await api('session');
    catalog ||= await api('catalog');
    if (version!==revision) return;
    const readOnly=Boolean(catalog.runtime?.read_only);
    setWorkspaceAccess(session.authenticated && !readOnly);
    if (readOnly && view==='brief' && !params.has('mode')) {
      params.set('mode','replay');
      if (!params.has('window')) params.set('window','7d');
      destination=route('brief',Object.fromEntries(params));
      history.replaceState(null,'',destination);
    }
    let draw;
    if (view==='brief') {
      const mode=params.get('mode') || 'live';
      const data=await api('brief',{mode,window:params.get('window') || '24h',
        start:params.get('start'),end:params.get('end')});
      draw=()=>mode==='live' ? liveBriefView(data,params,params.get('window')==='custom',{readOnly,autoRefresh:catalog.runtime.scheduled_refresh}) :
        briefView(data,params,params.get('window')==='custom');
      if (mode==='live') {
        liveSignature=signature({job:data.job,unread:data.alerts.filter(a=>!a.seen).length});
      }
    } else if (view==='research') {
      const symbol=params.get('ticker') || 'INFY';
      const data=await api('research/'+encodeURIComponent(symbol),{q:params.get('q'),lens:params.get('lens'),as_of:params.get('as_of')});
      draw=()=>{activeResearch=data;return researchView(data,catalog,{aiOpen:aiWasOpen || params.get('ai')==='1',readOnly,topic:params.get('topic')||'business'});};
    } else if (view==='people') {
      const q=params.get('q')||'',symbol=params.get('symbol')||'';
      const data=await api('people',{q,symbol});
      draw=()=>peopleView(data,q,symbol,catalog);
    } else if (view==='portfolio') {
      draw=()=>portfolioView(catalog);
    } else if (view==='account') {
      draw=()=>workspaceView(session);
    } else {
      throw new Error('This view is unavailable.');
    }
    if (version!==revision) return;
    clearRecords();
    workspace.innerHTML=workspaceNotice(session)+draw();
    const mode = view === 'research' ? 'Document index' : view === 'people' ? 'Professional network' :
      view === 'brief' && params.get('mode')!=='replay' ? 'Live sources' : 'Historical replay';
    document.querySelector('#mode-text').textContent = mode;
    document.title=(workspace.querySelector('h1')?.textContent || 'Portfolio brief')+' · FINN';
    activeHash=destination;
    window.scrollTo(0,scrollPositions.get(destination)||0);
    if (view==='brief' && params.get('mode')!=='replay' && !readOnly) {
      if (lastNotice) document.querySelector('#live-status').textContent=lastNotice;
      lastNotice='';
      schedulePoll();
    } else if (view === 'research') {
      scheduleResearchPoll();
    }
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
  if (target.id==='open-workspace') {
    target.disabled=true;
    api('session',{}, {method:'POST'}).then(data=>{session={...data,runtime:session?.runtime};catalog=null;render();}).catch(error=>{
      target.disabled=false;target.closest('aside')?.insertAdjacentHTML('beforeend',`<p role="alert">${esc(error.message)}</p>`);
    });return;
  }
  if (target.id==='export-workspace') {
    api('workspace/export').then(data=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='finn-workspace.json';a.click();URL.revokeObjectURL(url);
      document.querySelector('#workspace-status').textContent='Exported this workspace without access credentials.';
    }).catch(error=>{document.querySelector('#workspace-status').textContent=error.message;});return;
  }
  if (target.hasAttribute('data-review-candidate') || target.hasAttribute('data-review-source')) {
    const candidate=target.hasAttribute('data-review-candidate')?activeResearch.structured.candidates[Number(target.dataset.reviewCandidate)]:null;
    const source=candidate?.source || getRecord(target.dataset.reviewSource);
    const editor=document.querySelector('#fact-editor'), form=document.querySelector('#fact-form');
    if (source && editor && form) {
      sheet.close();editor.open=true;
      form.elements.source_id.value=source.id;form.elements.page.value=source.page;
      form.elements.quote.value=(candidate?.quote||source.excerpt||'').replace(/^…|…$/g,'');
      form.elements.published.value=/^\d{4}-\d{2}-\d{2}$/.test(source.date)?source.date:'';
      form.elements.kind.value=candidate?.kind||'guidance';form.elements.speaker.value=candidate?.speaker==='Unidentified'?'':candidate?.speaker||'';
      form.elements.speaker_kind.value=candidate?.speaker_kind||'unidentified';form.elements.reviewed.checked=false;
      if(candidate?.suggested)for(const [key,value] of Object.entries(candidate.suggested)){if(form.elements[key])form.elements[key].value=value;}
      editor.scrollIntoView({block:'start'});form.elements.quote.focus();
    }return;
  }
  if (target.hasAttribute('data-delete-fact')) {
    api('research/'+encodeURIComponent(activeResearch.company.symbol)+'/facts/'+encodeURIComponent(target.dataset.deleteFact),{}, {method:'DELETE'}).then(()=>render()).catch(error=>{target.textContent=error.message;});return;
  }
  if (target.hasAttribute('data-delete-person')) {
    api('people/'+encodeURIComponent(target.dataset.deletePerson),{}, {method:'DELETE'}).then(()=>{sheet.close();render();}).catch(error=>{target.textContent=error.message;});return;
  }
  if (target.hasAttribute('data-sheet')) { openSheet(target.dataset.sheet); return; }
  if (target.matches('.close') || (event.target===sheet && target===sheet)) { sheet.close(); return; }
  if (target.id==='retry') { render(); return; }
  if (target.id === 'show-alerts') {
    const history = document.querySelector('#alert-history');
    if (history) {
      history.open = true;
      history.scrollIntoView({block:'start'});
    }
    return;
  }
  if (target.id === 'discover-documents') {
    target.disabled = true;
    const symbol = activeResearch.company.symbol;
    api('research/' + encodeURIComponent(symbol) + '/discover', {}, {method:'POST'})
      .then(() => render())
      .catch(error => {
        target.disabled = false;
        const status = document.querySelector('#discovery-status');
        if (status) status.textContent = error.message;
      });
    return;
  }
  if (target.id === 'analyze-documents') {
    target.disabled = true;
    api('research/' + encodeURIComponent(activeResearch.company.symbol) + '/analyze', {}, {
      method:'POST',body:JSON.stringify({lens:activeResearch.analysis.lens})
    }).then(() => render()).catch(error => {
      target.disabled = false;
      const status = document.querySelector('#analysis-status');
      if (status) status.textContent = error.message;
    });
    return;
  }
  if (target.id==='live-refresh' || target.id==='alerts-read') {
    target.disabled=true;
    const path=target.id==='live-refresh'?'live/refresh':'alerts/read';
    api(path,{}, {method:'POST'}).then(()=>{
      lastNotice=path==='live/refresh'?'Refresh requested. Source results will appear here.':'Alerts marked as read.';
      render();
    }).catch(error=>{
      target.disabled=false;
      const status = document.querySelector('#live-status');
      if (status) status.textContent=error.message;
    });
    return;
  }
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
document.addEventListener('submit',async event=>{
  const form=event.target;
  const {params}=locationState();
  const fields=new FormData(form);
  const field=k=>String(fields.get(k)||'').trim();
  event.preventDefault();
  if (form.id==='fact-form') {
    const low=field('low'), value={kind:field('kind'),metric:field('metric'),period:field('period'),unit:field('unit'),scope:field('scope'),basis:field('basis'),speaker:field('speaker'),speaker_kind:field('speaker_kind'),source_id:field('source_id'),page:Number(field('page')),quote:field('quote'),published:field('published'),reviewed:fields.has('reviewed'),low,high:field('high')||low};
    try {await api('research/'+encodeURIComponent(activeResearch.company.symbol)+'/facts',{}, {method:'POST',body:JSON.stringify(value)});await render();}
    catch(error){document.querySelector('#fact-status').textContent=error.message;}
  } else if (form.id==='asof-form') {
    location.hash=route('research',{ticker:activeResearch.company.symbol,as_of:field('as_of'),q:params.get('q'),topic:params.get('topic')});
  } else if (form.id==='identity-form') {
    try {const result=await api('people/resolve',{name:field('name'),employer:field('employer'),role:field('role'),on:field('on')});document.querySelector('#identity-result').innerHTML=identityResult(result);}
    catch(error){document.querySelector('#identity-result').textContent=error.message;}
  } else if (form.id==='contact-note-form') {
    try {await api('people/'+encodeURIComponent(field('person'))+'/note',{}, {method:'PUT',body:JSON.stringify({note:field('note'),last_contact:field('last_contact')||null})});
      const record=getRecord(field('record'));if(record){record.note=field('note');record.last_contact=field('last_contact');}
      document.querySelector('#contact-note-status').textContent='Saved in this workspace.';
    } catch(error){document.querySelector('#contact-note-status').textContent=error.message;}
  } else if (form.id==='network-import-form') {
    const result=document.querySelector('#network-import-status');
    try {const file=fields.get('network');if(!file?.size||file.size>256*1024)throw new Error('Choose a JSON file smaller than 256 KiB.');
      const value=JSON.parse(await file.text());value.replace=fields.has('replace');
      const info=await api('network/import',{}, {method:'POST',body:JSON.stringify(value)});result.textContent='Imported '+info.imported+' profiles into this workspace.';
    } catch(error){result.textContent=error.message;}
  } else if (form.id==='portfolio-form') {
    try {await api('portfolio',{}, {method:'PUT',body:JSON.stringify({symbols:field('symbols').split(/[\s,]+/).filter(Boolean).map(s=>s.toUpperCase())})});catalog=null;await render();}
    catch(error){document.querySelector('#portfolio-status').textContent=error.message;}
  } else if (form.id==='delete-workspace-form') {
    if (!fields.has('confirm')) return;
    try {await api('workspace',{}, {method:'DELETE'});session=null;catalog=null;activeResearch=null;clearRecords();await render();}
    catch(error){document.querySelector('#workspace-status').textContent=error.message;}
  } else if (form.id==='date-form') {
    const start=field('start'),end=field('end');
    form.elements.end.setCustomValidity(start>end?'End date must be on or after the start date.':'');
    if (form.reportValidity()) location.hash=route('brief',{mode:params.get('mode')||'live',window:'custom',start,end});
  } else if (form.id==='ticker-form') {
    const input=field('ticker'), term=input.toLowerCase();
    const match=catalog.companies.find(c=>c.name.toLowerCase()===term || c.symbol.toLowerCase()===term);
    const possible=catalog.companies.filter(c=>c.name.toLowerCase().startsWith(term));
    const symbol=match?.symbol || (possible.length===1?possible[0].symbol:input.toUpperCase());
    form.elements.ticker.setCustomValidity(/^[A-Z0-9][A-Z0-9&.-]{0,24}$/.test(symbol)?'':'Choose a listed suggestion or enter an NSE ticker.');
    if (form.reportValidity()) location.hash=route('research',{ticker:symbol});
  } else if (form.id==='evidence-form') {
    location.hash=route('research',{ticker:activeResearch.company.symbol,lens:params.get('lens'),q:field('term'),as_of:params.get('as_of'),topic:params.get('topic')});
  } else if (form.id==='people-form') {
    location.hash=route('people',{q:field('q'),symbol:params.get('symbol')});
  } else if (form.id==='alert-rule-form') {
    const button=form.querySelector('[type=submit]');
    button.disabled=true;
    try {
      await api('alert-settings',{}, {method:'PUT',body:JSON.stringify({
        enabled:fields.has('enabled'),price_pct:Number(field('price_pct')),
        volume_multiple:Number(field('volume_multiple')),categories:fields.getAll('categories')
      })});
      lastNotice='Alert rules saved.';
      await render();
    } catch(error) {
      document.querySelector('#rules-result').textContent=error.message;
      button.disabled=false;
    }
  }
});
document.addEventListener('input',event=>{
  if (event.target.form?.id==='date-form') event.target.form.elements.end.setCustomValidity('');
  if (event.target.id==='ticker') event.target.setCustomValidity('');
});
if ('scrollRestoration' in history) history.scrollRestoration='manual';
window.addEventListener('hashchange',render);
render();
