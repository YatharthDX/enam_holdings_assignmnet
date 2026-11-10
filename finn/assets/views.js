import {dateLabel, deltaText, empty, esc, heading, icon, personCard, rangeText, route, sourceButton} from './ui.js?v=0.5.0';
import {modeSwitch, windowControls} from './live-view.js?v=0.5.0';
import {analysisView} from './analysis-view.js?v=0.5.0';

function rangeChart(series) {
  const forecasts = series.forecasts;
  const rows = [forecasts[0], forecasts.at(-1)];
  const actual = series.actual.value;
  const min = Math.min(0, Math.floor(Math.min(actual, ...forecasts.map(r => r.low))));
  const max = Math.ceil(Math.max(actual, ...forecasts.map(r => r.high))) + 1;
  const pct = n => (n-min) * 100 / (max-min);
  return `<figure class="range-chart" aria-label="Original and final guidance ranges compared with reported growth">
    <figcaption>${esc(series.period)} · ${esc(series.basis)}</figcaption>
    <div class="actual-number">${actual}<span>%</span></div><div class="actual-label">Reported revenue growth</div>
    <div class="chart-rows">${rows.map(r => `<div class="range-row"><div><small>${esc(r.label)}</small><b>${rangeText(r)}</b></div>
      <div class="track"><i style="left:${pct(r.low)}%;width:${pct(r.high)-pct(r.low)}%"></i><span style="left:${pct(actual)}%"></span></div></div>`).join('')}</div>
    <div class="chart-legend"><i></i>Reported result</div></figure>`;
}
function itemRow(r) {
  return `<article class="filing-row"><div class="meta">${esc(r.symbol)} <span>·</span> ${esc(dateLabel(r.date))}</div>
    <h3>${esc(r.title)}</h3><p>${esc(r.reason)}</p>${sourceButton(r.source,'Open filing')}</article>`;
}
export function briefView(data, params, customOpen) {
  const material = data.rows.filter(r => r.priority === 'Material');
  const routine = data.rows.filter(r => r.priority === 'Routine');
  const lead = material[0];
  const comp = data.comparison;
  const final = comp?.forecasts.at(-1);
  const leadTitle = comp ? `${lead.company} closes ${comp.period} ${final.position} its final guidance` : lead?.title;
  const desc = comp ? `Revenue grew ${comp.actual.value}% in constant currency. Management’s final forecast was ${rangeText(final)}.` : lead?.reason;
  const feature = lead ? `<article class="lead ${comp?'with-chart':''}"><div class="lead-copy">
    <div class="lead-meta"><span class="flag">Material filing</span><span>${esc(lead.symbol)} · Results</span></div>
    <h2>${esc(leadTitle)}</h2><p>${esc(desc)}</p><div class="actions">
    ${comp?`<a class="button primary" href="${route('research',{ticker:lead.symbol})}">Check guidance ${icon('arrow')}</a>`:''}
    ${sourceButton(lead.source,'Open filing','button secondary')}</div></div>${comp?rangeChart(comp):''}</article>` : '';
  const more = material.slice(1).map(itemRow).join('');
  const network = data.people.length ? `<aside class="panel network-panel"><div class="section-meta">Network · ${esc(data.focus)}</div>
    <h2>Who can help?</h2><p class="panel-intro">Relevant experience in your demo network.</p>
    ${data.people.map(personCard).join('')}<a class="text-button" href="${route('people',{symbol:data.focus})}">See connections ${icon('arrow',16)}</a></aside>` : '';
  return heading('Thursday, 17 April 2025 · End of day','Portfolio brief',
    '',`<a class="holdings-link" href="#portfolio">${icon('layers')} ${data.holdings} holdings</a>`) +
    `<div class="mode-actions">${modeSwitch('replay')}</div>${windowControls(data,params,customOpen)}
    ${feature}${!data.rows.length ? empty('No filings in this sample window','Choose 7 days or a different date range in the historical replay.') : ''}
    <div class="lower-grid"><section class="panel"><div class="section-meta">${esc(data.start === data.end ? dateLabel(data.end) : dateLabel(data.start)+' – '+dateLabel(data.end))}</div>
    <h2>Filing register</h2>${more}${lead?`<div class="register-entry"><span class="status-dot"></span><div><strong>${esc(lead.company)}</strong><small>Featured result · ${esc(dateLabel(lead.date))}</small></div>${sourceButton(lead.source,'Source')}</div>`:''}
    ${routine.length?`<details class="routine"><summary>Routine disclosures <b>${routine.length}</b> ${icon('down',15)}</summary>${routine.map(itemRow).join('')}</details>`:''}
    <p class="coverage">${icon('clock',14)} Curated filing sample · historical dates in IST.</p></section>${network}</div>`;
}

export function verdict(comp, index) {
  const f = comp.forecasts[index];
  return `<div class="verdict"><div><span class="section-meta">Against ${esc(f.label.toLowerCase())}</span>
    <strong>${esc(deltaText(f))}</strong></div>${sourceButton(f.source,'Forecast source')}</div>`;
}
function guidanceCard(comp) {
  const final = comp.forecasts.length-1;
  return `<section class="panel guidance"><div class="section-meta">Historical ${esc(comp.period)} · ${esc(comp.basis)} · ${esc(comp.scope)}</div>
  <h2>Guidance check</h2><div class="actual-row"><div><small>Reported revenue growth</small><strong>${comp.actual.value}%</strong></div>${sourceButton(comp.actual.source,'Actual source')}</div>
  <p class="panel-intro">Choose a forecast to compare it with the final result.</p>
  <div class="forecasts">${comp.forecasts.map((r,i)=>`<button type="button" class="forecast" data-forecast="${i}" aria-pressed="${i===final}">
  <span><b>${esc(r.label)}</b><small>${esc(dateLabel(r.source.date))}</small></span><strong>${rangeText(r)}</strong></button>`).join('')}</div>
  <div id="verdict" aria-live="polite">${verdict(comp,final)}</div></section>`;
}
function tickerForm(symbol, catalog) {
  return `<form id="ticker-form" class="search-form"><label for="ticker">Company or NSE ticker</label>
    <div class="input-line">${icon('research')}<input id="ticker" name="ticker" value="${esc(symbol)}" placeholder="Search by company or ticker" required maxlength="80" list="tickers">
    <button class="button primary" type="submit">Research</button></div>
    <datalist id="tickers">${catalog.companies.map(c=>`<option value="${esc(c.symbol)}">${esc(c.name)}</option>`).join('')}</datalist></form>`;
}
export function researchView(data,catalog,options = {}) {
  const c=data.company;
  const title=c.name + (c.name !== c.symbol ? ' · '+c.symbol : '');
  const samples=catalog.sample_symbols.map(s=>`<a class="chip" href="${route('research',{ticker:s})}" ${c.symbol===s?'aria-current="true"':''}>${esc(s)}</a>`).join('');
  const matches = data.query ? (data.matches.length ? data.matches.map(m=>`<div class="match"><div class="meta">${esc(m.title)}${m.page?' · p. '+m.page:''}</div>
    <p>${esc(m.excerpt)}</p>${sourceButton(m,'Inspect passage')}</div>`).join('') : empty('No matching passage','Try a term used by the company, such as revenue, chemicals or delivery.')) : '';
  const citations = data.sources.map(s=>`<div class="source-row"><div><strong>${esc(s.title)}</strong><small>${esc(s.kind)} · ${esc(dateLabel(s.date))}</small></div>${sourceButton(s,'Inspect')}</div>`).join('');
  const search = `<section class="panel"><div class="section-meta">Primary documents</div><h2>Search the evidence</h2>
    ${data.imported ? `<p class="panel-intro">Includes ${data.imported} locally indexed ${data.imported === 1 ? 'document' : 'documents'}. Publication dates appear with each source.</p>` : ''}
    <form id="evidence-form" class="search-form"><label for="term">Word or phrase</label><div class="input-line">
    <input name="term" id="term" maxlength="160" value="${esc(data.query)}" placeholder="e.g. revenue guidance"><button class="button secondary" type="submit">Search</button></div></form>
    <div class="evidence-topics" aria-label="Evidence topics">${['revenue','guidance','cash flow'].map(q=>
      `<a class="chip" href="${route('research',{ticker:c.symbol,q})}" ${data.query===q?'aria-current="true"':''}>${esc(q)}</a>`).join('')}</div>
    ${matches}<details class="routine"><summary>Source documents <b>${data.sources.length}</b> ${icon('down',15)}</summary>${citations}</details></section>`;
  const noDocs = empty('No indexed sources for '+c.symbol,options.readOnly ? 'Index original documents for this ticker in your own local workspace. The public demo includes the prepared historical source set.' : 'Find primary documents for this ticker to build its evidence index.');
  const job = data.discovery;
  const discovery = options.readOnly ? '' : `<section class="discovery-panel" aria-label="Document discovery">
    <div><strong>Find primary documents</strong><p>Latest annual report and up to four call transcripts.</p></div>
    <button type="button" id="discover-documents" class="button secondary" ${job?.status==='running'?'disabled':''}>${job?.status==='running'?'Indexing…':'Find documents'} ${icon('book',16)}</button>
    <p id="discovery-status" class="discovery-status" role="status">${esc(job?.detail || 'Original documents are discovered via Screener’s public links.')}</p>
    ${job?.sources?.length ? `<details class="discovered-links"><summary>Discovered originals · ${job.sources.length}</summary>
      ${job.sources.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ${icon('external',14)}</a>`).join('')}</details>` : ''}
    </section>`;
  const network = `<section class="panel"><div class="section-meta">Fictional network · ${esc(c.symbol)}</div><h2>Who can help?</h2>${data.people.length?data.people.map(personCard).join(''):empty('No recorded connection','Try searching People by industry or area of experience.')}</section>`;
  return heading('Primary-source research','Company research','Inspect company evidence, compare guidance and find relevant contacts.')+
    tickerForm(c.symbol,catalog)+`<div class="chips">${samples}</div>${discovery}
    <div class="company-heading"><div class="kicker">${esc(c.sector || 'Research index')}</div><h2>${esc(title)}</h2>
    ${data.snapshot?`<div class="section-meta">Historical business snapshot · FY24</div><p>${esc(data.snapshot.text)} ${sourceButton(data.snapshot.source,'Source')}</p>`:''}
    </div><div class="research-grid"><div class="stack">
    ${data.comparison ? guidanceCard(data.comparison) : ''}${data.sources.length?search:noDocs}${analysisView(data,options.aiOpen)}</div><aside class="stack">${network}
    ${data.sources.length && !data.comparison ? `<div class="note"><strong>Guidance coverage</strong><p>No comparable forecast and outcome have been indexed for this ticker.</p></div>` : ''}</aside></div>`;
}
export function peopleView(data,query,symbol,catalog) {
  const c=catalog.companies.find(x=>x.symbol===symbol);
  return heading('Professional network','People','Search fictional profiles by company, role or experience.')+
    `<form id="people-form" class="search-form"><label for="who">Who can help?</label><div class="input-line">${icon('people')}
    <input id="who" name="q" value="${esc(query)}" placeholder="e.g. IT delivery, SRF or credit" maxlength="120"><button class="button primary" type="submit">Find people</button></div></form>
    <div class="chips">${['IT delivery','Specialty chemicals','Electricals'].map(q=>`<a class="chip" href="${route('people',{q})}">${esc(q)}</a>`).join('')}
    ${query||symbol?'<a class="text-button" href="#people">Clear filters</a>':''}</div>
    <div class="section-bar"><h2>${c?'Connections for '+esc(c.name):'Connections'}</h2><span>${data.people.length} ${data.people.length===1?'match':'matches'}</span></div>
    ${data.people.length ? `<div class="people-grid">${data.people.map(p=>`<article class="contact-tile">${personCard(p)}
     <p class="person-reason">${esc(p.reason)} · ${esc(p.topics[0])}</p></article>`).join('')}</div>` : empty('No matching connection','Try a different company or area of expertise, or clear the filters.')}`;
}
export function portfolioView(catalog) {
  const holdings=catalog.companies.filter(c=>c.holding);
  return heading('Demo holdings','Your portfolio',holdings.length+' listed companies monitored by this workspace.')+
    `<div class="holdings-grid">${holdings.map(c=>`<a class="holding" href="${route('research',{ticker:c.symbol})}"><span class="meta">${esc(c.symbol)}</span><strong>${esc(c.name)}</strong><small>${esc(c.sector)}</small>${icon('arrow',16)}</a>`).join('')}</div>`;
}
