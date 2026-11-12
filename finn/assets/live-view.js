import {dateLabel, empty, esc, heading, icon, personCard, route, sourceButton} from './ui.js?v=0.6.2';
import {reconnectCards} from './network-view.js?v=0.6.2';

export function modeSwitch(mode) {
  return `<div class="mode-switch" aria-label="Data mode">
    <a href="${route('brief',{mode:'live'})}" ${mode==='live'?'aria-current="true"':''}>Live sources</a>
    <a href="${route('brief',{mode:'replay'})}" ${mode==='replay'?'aria-current="true"':''}>Historical replay</a>
  </div>`;
}

export function windowControls(data, params, customOpen) {
  const selected = params.get('window') || '24h';
  const mode = data.mode || 'replay';
  const material = data.rows.filter(row => row.priority === 'Material').length;
  const routine = data.rows.filter(row => row.priority === 'Routine').length;
  const other = data.rows.length-material-routine;
  return `<div class="control-row"><div class="segments" aria-label="Time window">
    ${[['24h','24 hours'],['7d','7 days']].map(([key,label]) => `<a href="${route('brief',{mode,window:key})}" ${selected===key?'aria-current="true"':''}>${label}</a>`).join('')}
    <button type="button" id="dates-toggle" aria-expanded="${customOpen}" ${selected==='custom'?'class="active"':''}>Dates ${icon('down',13)}</button>
    </div><div class="counts"><b>${material}</b> material <span>·</span> ${routine} routine${other?' · '+other+' other':''}</div></div>
    <form id="date-form" class="date-form" ${customOpen?'':'hidden'}>
      <label>From<input type="date" name="start" required max="${data.as_of}" value="${data.start}"></label>
      <label>Through<input type="date" name="end" required max="${data.as_of}" value="${data.end}"></label>
      <button class="button primary" type="submit">Apply dates</button>
    </form>`;
}

function when(value) {
  if (!value) return 'Awaiting refresh';
  if (value.length === 10) return dateLabel(value);
  return new Intl.DateTimeFormat('en-IN', {
    day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Kolkata'
  }).format(new Date(value)) + ' IST';
}

function feedStatus(data) {
  const filing = data.sources.find(s=>s.key==='nse');
  const prices = data.sources.filter(s=>s.key.startsWith('yahoo:'));
  const successful = prices.filter(s=>s.status==='ok').length;
  const coverage = filing?.status === 'error' ? 'Refresh failed' : filing?.coverage === 'partial' ? 'Partial coverage' :
    filing?.status === 'ok' ? 'Range fetched' : 'Awaiting refresh';
  return `<section class="feed-health" aria-label="Source status">
    <div><strong>NSE filings</strong><span>${coverage}</span><small>${filing?.success?'Last success '+when(filing.success):'No successful fetch yet'}</small></div>
    <div><strong>Price and volume</strong><span>${successful}/${data.holdings} ready</span><small>Completed daily sessions · Yahoo Finance</small></div>
    </section>
    <details class="source-health"><summary>Source details ${icon('down',14)}</summary>
      <p>Daily prices refresh after the closing-session buffer. Filing windows include fetched records. Check the source coverage before treating an empty window as complete.</p>
      ${data.sources.length?data.sources.map(s=>`<div class="feed-detail"><strong>${esc(s.key==='nse'?'NSE announcements':s.key.slice(6))}</strong>
      <span>${esc(s.status==='ok'?'Fetched':'Refresh failed')} · ${esc(when(s.attempt))}</span><p>${esc(s.detail)}</p></div>`).join(''):'<p>Refresh sources to fetch the portfolio’s latest records.</p>'}
    </details>`;
}

function settingsForm(data, readOnly = false) {
  const s=data.settings;
  if (readOnly) return `<details class="panel alert-rules" id="alert-rules"><summary>Alert rules ${icon('down',16)}</summary>
    <p class="panel-intro">Read only in this public demo. Configure monitoring in your own local workspace.</p>
    <div class="rules-grid"><p>Daily price move <strong>±${esc(s.price_pct)}%</strong></p><p>Volume above average <strong>${esc(s.volume_multiple)}×</strong></p></div>
    <p class="coverage">Monitoring ${s.enabled?'enabled':'disabled'} · ${s.categories.map(c=>esc(data.categories[c])).join(', ')}</p></details>`;
  return `<details class="panel alert-rules" id="alert-rules"><summary>Alert rules ${icon('down',16)}</summary>
    <form id="alert-rule-form">
      <label class="check"><input type="checkbox" name="enabled" ${s.enabled?'checked':''}> Monitor this demo portfolio</label>
      <div class="rules-grid">
        <label>Daily price move, ±%<input type="number" name="price_pct" min="0.1" max="100" step="0.1" required value="${s.price_pct}"></label>
        <label>Volume above average, ×<input type="number" name="volume_multiple" min="1" max="100" step="0.1" required value="${s.volume_multiple}"></label>
      </div>
      <fieldset><legend>Filing categories</legend><div class="category-options">${Object.entries(data.categories).map(([id,label])=>`<label class="check"><input type="checkbox" name="categories" value="${esc(id)}" ${s.categories.includes(id)?'checked':''}>${esc(label)}</label>`).join('')}</div></fieldset>
      <p class="coverage">Price uses absolute close-to-close change. Volume excludes the current session from its 20-session baseline. Saved rules also evaluate the latest cached session.</p>
      <div class="actions"><button class="button primary" type="submit">Save rules</button><span id="rules-result" role="status"></span></div>
    </form></details>`;
}

function notifications(data, readOnly = false) {
  const unread=data.alerts.filter(a=>!a.seen).length;
  if (!data.alerts.length) return '';
  return `<details class="panel notifications" id="alert-history"><summary>Alert history <b>${unread} unread</b> ${icon('down',16)}</summary>
    <p class="panel-intro">Generated under your saved rules. Event times appear with each alert.</p>
    ${readOnly ? '' : '<button type="button" class="text-button" id="alerts-read">Mark all read</button>'}
    ${data.alerts.map(a=>`<article class="notification ${a.seen?'':'unread'}"><div class="meta">${esc(a.symbol)} · ${esc(when(a.event_at))}</div><h3>${esc(a.title)}</h3><p>${esc(a.reason)}</p>
    ${sourceButton(a.source,'View source')} <a class="text-button" href="${route('people',{symbol:a.symbol})}">People ${icon('people',15)}</a></article>`).join('')}
    </details>`;
}

function market(data) {
  const number=value=>value==null?'—':new Intl.NumberFormat('en-IN',{maximumFractionDigits:2}).format(value);
  return `<section class="panel market-panel"><div class="section-meta">End of day · Yahoo Finance</div><h2>Latest completed sessions</h2>
    <div class="market-scroll"><table class="market-table"><thead><tr><th>Company / session</th><th>Close, ₹</th><th>Day, %</th><th>Volume, ×</th><th></th></tr></thead>
    <tbody>${data.quotes.map(q=>{
      const source={id:'quote-'+q.symbol,symbol:q.symbol,title:q.company+' daily price history',date:q.day,
        url:q.url,kind:'EOD market data',locator:'Provider daily close and share volume',page:null,excerpt:''};
      const change=q.price_change;
      return `<tr><th>${esc(q.symbol)}<small>${q.day?esc(dateLabel(q.day)):'Awaiting source'}</small>${q.note?`<details class="metric-note"><summary>Data note</summary><p>${esc(q.note)}</p></details>`:''}</th>
        <td>${number(q.close)}</td><td class="${change==null?'':change<0?'fall':'rise'}">${change==null?'—':(change>0?'+':'')+number(change)}</td>
        <td>${number(q.volume_ratio)}${q.volume_ratio==null?'':'×'}</td><td>${q.day?sourceButton(source,'Source'):''}</td></tr>`;
    }).join('')}</tbody></table></div></section>`;
}

function liveRow(row) {
  return `<article class="filing-row"><div class="meta">${esc(row.symbol)} · ${esc(when(row.published))}</div>
    <h3>${esc(row.title)}</h3><p>${esc(row.reason)}</p>${managementContext(row)}${sourceButton(row.source,'Open filing')}
    ${row.other_sources?.length?`<details><summary>Other originals · ${row.other_sources.length}</summary>${row.other_sources.map(s=>sourceButton(s,'Open original')).join('')}</details>`:''}
    <a class="text-button" href="${route('people',{symbol:row.symbol})}">Connections ${icon('people',15)}</a></article>`;
}

function managementContext(row) {
  const context=row.management_context;
  return context?`<div class="management-context"><strong>Incoming-person context · ${esc(context.status)}</strong><p>${esc(context.reason)}</p>${context.person?.distance?personCard(context.person):context.person?'<p>Employment matched; no introduction path is recorded.</p>':''}</div>`:'';
}

export function liveBriefView(data, params, customOpen, {readOnly = false, autoRefresh = false} = {}) {
  const active=data.rows.filter(row=>row.priority!=='Routine');
  const routine=data.rows.filter(row=>row.priority==='Routine');
  const lead=active[0];
  const running=data.job?.status==='running';
  const unread = data.alerts.filter(alert => !alert.seen).length;
  const feature=lead?`<article class="lead"><div class="lead-copy"><div class="lead-meta"><span class="flag">${esc(lead.label)}</span><span>${esc(lead.symbol)} · ${esc(when(lead.published))}</span></div>
    <h2>${esc(lead.title)}</h2><p>${esc(lead.details.slice(0,240)||lead.reason)}</p>${managementContext(lead)}
    <div class="actions">${sourceButton(lead.source,'Open filing','button primary')}
      <a class="button secondary" href="${route('research',{ticker:lead.symbol})}">Research index ${icon('arrow',16)}</a></div></div></article>`:'';
  const network=data.people.length?`<aside class="panel network-panel"><div class="section-meta">Network · ${esc(data.focus)}</div><h2>Who can help?</h2>
    <p class="panel-intro">Roles and tenure recorded in this workspace.</p>${data.people.map(personCard).join('')}</aside>`:'';
  return heading('Portfolio monitoring · '+dateLabel(data.as_of),'Portfolio brief','',
    `<a class="holdings-link" href="#portfolio">${icon('layers')} ${data.holdings} holdings</a>`)+
    `<div class="mode-actions">${modeSwitch('live')}${readOnly ? '<span class="meta">Read only</span>' : `<button id="live-refresh" aria-label="Refresh sources" class="button secondary" type="button" ${running?'disabled':''}>${running?'Refreshing…':'Refresh'}</button>`}</div>
    <p class="live-status" id="live-status" role="status">${readOnly ? 'Open Historical replay for the prepared investor journey. A private workspace is needed to refresh sources.' : running?'Fetching public filings and completed daily bars…':data.job?.finished?'Last refresh finished '+when(data.job.finished):autoRefresh?'Scheduled source refresh is enabled.':'Select Refresh to fetch public filings and completed daily bars.'}</p>
    ${data.alerts.length ? `<button type="button" class="text-button alert-jump" id="show-alerts">${unread} unread alerts ${icon('arrow',15)}</button>` : ''}
    ${feedStatus(data)}${windowControls(data,params,customOpen)}
    ${feature}${!data.rows.length?empty('No cached filings in this window','Check source status above, refresh, or choose a wider window. Historical replay is available from the selector.') : ''}
    <div class="lower-grid"><section class="panel"><div class="section-meta">Fetched portfolio disclosures</div><h2>Filing register</h2>
      ${lead?`<div class="register-entry"><span class="status-dot"></span><div><strong>${esc(lead.company)}</strong><small>Featured disclosure</small></div>${sourceButton(lead.source,'Source')}</div>`:''}
      ${active.slice(1).map(liveRow).join('')}
      ${routine.length?`<details class="routine"><summary>Routine disclosures <b>${routine.length}</b> ${icon('down',15)}</summary>${routine.map(liveRow).join('')}</details>`:''}
      <p class="coverage">Publication times in IST. Last 24 hours is a rolling window.${data.filing_count>data.rows.length?' '+data.filing_count+' filings grouped into '+data.rows.length+' distinct metadata events.':''}</p></section>${network}</div>
    ${reconnectCards(data.reconnect)}${notifications(data,readOnly)}${settingsForm(data,readOnly)}${market(data)}`;
}
