import {esc, dateLabel, route, sourceButton, empty} from './ui.js?v=0.8.0';

const option=(value,label,selected)=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`;
const label=value=>value.replaceAll('_',' ');

export function sourceBrief(data, topic='business') {
  const r=data.structured, b=r?.brief;
  // Only explain the date filter when it actually hid indexed documents.
  if (!b?.documents) return data.as_of && data.imported ? `<div class="note"><strong>Nothing was public by ${esc(dateLabel(data.as_of))}</strong><p>Every indexed document for ${esc(data.company.symbol)} became available after this date. Pick a later date or show all evidence.</p></div>` : '';
  const chosen=b.groups.find(g=>g.id===topic)||b.groups[0];
  const passage=p=>`<article class="extractive-passage"><div class="meta">${esc(p.source.title)} · p. ${p.source.page}</div><p>${esc(p.text.length>420?p.text.slice(0,p.text.lastIndexOf(' ',420))+'…':p.text)}</p>${sourceButton(p.source,'Inspect full passage')}</article>`;
  return `<section class="panel source-brief"><div class="section-meta">${b.corpus==='historical_excerpts'?'Historical excerpts':'Indexed originals'} · ${b.documents} sources · ${b.pages} text pages</div>
    <h2>From the originals</h2><p class="panel-intro">Exact passages selected from company documents. No model needed.</p>
    <nav class="chips" aria-label="Research topic">${b.groups.map(g=>`<a class="chip" href="${route('research',{ticker:data.company.symbol,topic:g.id,as_of:data.as_of,q:data.query,lens:data.analysis?.lens})}" ${g.id===chosen.id?'aria-current="true"':''}>${esc(g.title)}</a>`).join('')}</nav>
    ${chosen.passages.length?passage(chosen.passages[0]):empty('No selected passage','This topic was not found by the retrieval rules. Search the source directly before concluding it was not disclosed.')}
    ${chosen.passages.length>1?`<details><summary>More source perspectives · ${chosen.passages.length-1}</summary>${chosen.passages.slice(1).map(passage).join('')}</details>`:''}
    <p class="coverage">${esc(b.method)}${b.excluded_pages?' '+b.excluded_pages+' undated or later pages excluded.':''}</p></section>`;
}

export function dateFilter(data) {
  // Point-in-time view: hides evidence published after a date, so research shows only what was known then.
  const today=new Date().toISOString().slice(0,10);
  const active=data.as_of?`<span class="asof-active">${esc(dateLabel(data.as_of))}</span>`:'';
  return `<details class="asof" id="asof" ${data.as_of?'open':''}><summary>View as of a past date ${active}</summary>
    <p class="panel-intro">Hide documents published after this date to see only what was known then, without hindsight.</p>
    <form id="asof-form" class="asof-form"><label for="asof-date">Date</label>
      <div class="asof-row"><input id="asof-date" type="date" name="as_of" max="${today}" value="${esc(data.as_of||'')}" required>
      <button class="button secondary" type="submit">Apply</button></div>
      ${data.as_of?`<a class="text-button" href="${route('research',{ticker:data.company.symbol})}">Show all evidence</a>`:''}</form></details>`;
}

export function reviewedResearch(data) {
  const r=data.structured;
  if (!r) return '';
  const comparisons=r.comparisons.map(c=>{
    const f=c.forecast, difference=c.position==='within'?'The reviewed metric, period, units, scope and currency basis match.':c.points==null?'':`${c.points} ${f.unit==='%'?'percentage points':f.unit} ${c.position} the ${c.position==='below'?'lower':'upper'} bound.`;
    return `<article class="reviewed-comparison"><div class="meta">${esc(r.metrics[f.metric])} · ${esc(f.period)} · ${esc(f.scope)} · ${esc(label(f.basis))}</div>
      <h3>${esc(c.position==='within'?'Delivered within guidance':c.position==='above'?'Delivered above guidance':c.position==='below'?'Delivered below guidance':c.position==='pending'?'Outcome pending':label(c.position))}</h3>
      <p>Guidance ${esc(f.low)}–${esc(f.high)} ${esc(f.unit)}${c.actual?' · Delivered '+esc(c.actual.low)+' '+esc(f.unit):''}</p><p>${esc(difference||c.reason)}</p>
      ${sourceButton(f.source,'Guidance source')}${c.actual?sourceButton(c.actual.source,'Outcome source'):''}</article>`;
  }).join('');
  const financials=r.financials.length?`<div class="section-meta">Financial record</div><div class="market-scroll"><table class="market-table"><thead><tr><th>Metric / period</th><th>Reported</th><th>QoQ</th><th>YoY</th><th>Evidence</th></tr></thead><tbody>${r.financials.map(row=>`<tr><th>${esc(r.metrics[row.fact.metric])}<small>${esc(row.fact.period)} · ${esc(row.fact.scope)} · ${esc(label(row.fact.basis))}</small></th><td>${esc(row.fact.low)} ${esc(row.fact.unit)}</td><td>${row.qoq?esc(row.qoq.percent.toFixed(2))+' '+esc(row.qoq.unit):'—'}</td><td>${row.yoy?esc(row.yoy.percent.toFixed(2))+' '+esc(row.yoy.unit):'—'}</td><td>${sourceButton(row.fact.source,'Source')}${row.qoq?sourceButton(row.qoq.source,'QoQ base'):''}${row.yoy?sourceButton(row.yoy.source,'YoY base'):''}</td></tr>`).join('')}</tbody></table></div><p class="coverage">Changes require matching units, scope and currency basis. Percentage metrics use percentage-point differences; amount ratios need a positive prior value. Missing baselines stay blank.</p>`:'';
  const review=r.can_review && data.sources.length?`<details class="fact-workbench" id="fact-editor"><summary class="step">2 · Confirm what a figure means</summary><p class="panel-intro">Review fields fills this in from a statement. YFINN checks the quote is on that page and every number is in the quote; you confirm the period, speaker, units, scope and currency basis.</p>
    <form id="fact-form" class="stack"><div class="rules-grid"><label>Source document<select name="source_id" required>${data.sources.map(s=>option(s.id,s.title,'')).join('')}</select></label><label>PDF page<input name="page" type="number" min="1" step="1" required></label></div>
      <label>Exact source quote<textarea name="quote" rows="4" maxlength="1200" minlength="16" required></textarea></label>
      <div class="rules-grid"><label>Statement<select name="kind">${option('guidance','Guidance','guidance')}${option('actual','Reported actual','guidance')}${option('qualitative','Qualitative statement','guidance')}</select></label><label>Metric<select name="metric">${Object.entries(r.metrics).map(([k,v])=>option(k,v,'revenue_growth')).join('')}</select></label>
      <label>Fiscal period<input name="period" placeholder="FY25 or Q4 FY25" maxlength="20" required></label><label>Units<select name="unit">${r.units.map(v=>option(v,v,'%')).join('')}</select></label>
      <label>Lower / actual value<input name="low" inputmode="decimal" maxlength="24"></label><label>Upper guidance value<input name="high" inputmode="decimal" maxlength="24" placeholder="Leave blank for one value"></label>
      <label>Accounting scope<select name="scope">${r.scopes.map(v=>option(v,label(v),'not_stated')).join('')}</select></label><label>Currency basis<select name="basis">${r.bases.map(v=>option(v,label(v),'not_stated')).join('')}</select></label>
      <label>Speaker / reporting authority<input name="speaker" maxlength="100" required></label><label>Statement authority<select name="speaker_kind">${option('unidentified','Unidentified','unidentified')}${option('management','Management','unidentified')}${option('question','Analyst question','unidentified')}${option('report','Company report','unidentified')}</select></label>
      <label>Verified publication date<input name="published" type="date" max="${new Date().toISOString().slice(0,10)}"></label></div>
      <label class="check"><input type="checkbox" name="reviewed" required> I inspected the original and reviewed the fields above</label><button class="button primary" type="submit">Save reviewed fact</button><p id="fact-status" role="status"></p></form></details>`:'';
  const candidate=(c,i)=>`<article class="candidate"><div class="meta">${esc(c.speaker_kind)} · ${esc(c.source.title)} · p. ${c.source.page}</div><p>${esc(c.quote.slice(0,320))}${c.quote.length>320?'…':''}</p>${sourceButton(c.source,'Inspect')}${r.can_review?`<button class="text-button" type="button" data-review-candidate="${i}">Review fields</button>`:''}</article>`;
  const drafts=r.candidates.length?`<h3 class="step">1 · Statements found in the documents <small>${r.candidates.length}</small></h3>
    <p class="panel-intro">Sentences with a guidance word near a percentage. They are not accepted figures; analyst questions and unclear speakers stay labelled.</p>
    ${r.candidates.slice(0,4).map(candidate).join('')}
    ${r.candidates.length>4?`<details><summary>${r.candidates.length-4} more statements</summary>${r.candidates.slice(4).map((c,i)=>candidate(c,i+4)).join('')}</details>`:''}`:'';
  const saved=r.facts.length?`<h3 class="step">Saved figures <small>${r.facts.length}</small></h3>${r.facts.map(f=>`<article class="candidate"><div class="meta">${esc(r.metrics[f.metric])} · ${esc(f.period)} · ${esc(f.kind)}${f.stale?' · Source changed':''}</div><p>${esc(f.quote)}</p>${sourceButton(f.source,'Evidence')}${r.can_review?`<button type="button" class="text-button" data-delete-fact="${esc(f.id)}">Remove</button>`:''}</article>`).join('')}`:'';
  const results=comparisons||financials?`<h3 class="step">3 · Your comparisons</h3>${comparisons}${financials}`:'';
  if (!drafts && !review && !saved && !results) return '';
  const counts=[r.candidates.length?r.candidates.length+' found':'', r.facts.length?r.facts.length+' saved':''].filter(Boolean).join(' · ');
  return `<details class="panel manual-review" id="manual-review" ${r.facts.length?'open':''}>
    <summary>Check or add a figure yourself${counts?` <small>${counts}</small>`:''}</summary>
    <p class="panel-intro">For figures the automatic panel cannot score, such as constant-currency revenue guidance, or to double-check one: pick a statement, confirm what it means, and YFINN compares a promise with its outcome in code.${r.can_review?'':' Open your workspace to save figures.'}</p>
    ${drafts}${review}${saved}${results}</details>`;
}

const VERDICT = {below:'Missed', above:'Beat', within:'Delivered', tracking_below:'Tracking below', tracking_within:'On track',
  tracking_above:'Tracking above', due_later:'Not due yet', different_basis:'Different basis', pending:'Awaiting results', aspiration:'Aspiration'};
const monthLabel = m => m ? new Intl.DateTimeFormat('en-GB',{month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(m+'-01T00:00:00Z')) : 'Undated';
const range = i => i.high==null ? 'at least '+i.low+'%' : i.low===i.high ? i.low+'%' : i.low+'–'+i.high+'%';

function promiseRow(r) {
  const i=r.item, rep=r.repeated||{count:1};
  const delivered = r.actual!=null && !['due_later'].includes(r.status)
    ? `Delivered <b>${r.actual.toFixed(1)}%</b> · ${esc(r.span)}${r.points?` · ${r.points.toFixed(r.points<0.1?2:1)} pp ${r.status.includes('below')?'below':'above'} the ${r.status.includes('below')?'lower':'upper'} bound`:''}`
    : esc(r.span);
  return `<article class="promise ${esc(r.status)}"><div class="promise-head"><span class="verdict-chip ${esc(r.status)}">${esc(VERDICT[r.status]||r.status)}</span>
    <strong>${esc(i.label)}${i.period&&i.period!=='multi-year'?' · '+esc(i.period):''}</strong><span>promised ${esc(range(i))}${i.basis==='constant_currency'?' CC':''}</span></div>
    <p class="promise-actual">${delivered}</p>
    <p class="promise-quote">“${esc(i.quote.length>220?i.quote.slice(0,i.quote.lastIndexOf(' ',220))+'…':i.quote)}”</p>
    <p class="coverage">${esc(monthLabel(i.call_month))} call${rep.count>1?` · repeated on ${rep.count} calls since ${esc(monthLabel(rep.first))}`:''}${i.period_inferred?' · period inferred from the call date':''} · ${i.method.startsWith('model')?'model-extracted, quote and figures verified':'rule-extracted'} ${sourceButton(i.source,'Transcript')}</p></article>`;
}

export function promisesPanel(data) {
  const p=data.promises;
  if (!p || (!p.rows.length && !p.quarters.length)) return '';
  const scored=p.rows.filter(r=>!['aspiration','pending'].includes(r.status));
  const rest=p.rows.filter(r=>['aspiration','pending'].includes(r.status));
  return `<section class="panel promises"><div class="section-meta">Promised vs delivered · call transcripts × exchange XBRL</div>
    <h2>What management said, and what the filings show</h2>
    ${revisionsBlock(p)}
    ${p.rows.length?scored.slice(0,6).map(promiseRow).join('')+
      (scored.length>6||rest.length?`<details><summary>More statements · ${scored.slice(6).length+rest.length}</summary>${[...scored.slice(6),...rest].map(promiseRow).join('')}</details>`:'')
      :empty('No guidance statements yet','Find documents to read this company’s call transcripts. Only statements with a figure that can be traced to the transcript are kept.')}
    <p class="coverage">${esc(p.method)} Margins use filed lines (EBIT = PBT − exceptional items + finance costs − other income); a company's own "adjusted" figures can differ.</p>
    ${filedQuarters(p)}</section>`;
}

function revisionsBlock(p) {
  if (!p.revisions?.length) return '';
  return `<div class="revisions">${p.revisions.map(r=>`<div class="revision"><div class="promise-head">
    <span class="verdict-chip ${r.metric==='tax_rate'?'':r.direction==='lowered'?'below':r.direction==='raised'?'above':''}">Guidance ${esc(r.direction)}</span>
    <strong>${esc(r.label)} · ${esc(r.period)}${r.basis==='constant_currency'?' · CC':''}</strong></div>
    <ol class="revision-steps">${r.steps.map(s=>`<li><span>${esc(monthLabel(s.call_month))}</span><b>${esc(range(s))}</b>${sourceButton(s.source,'Quote')}</li>`).join('')}</ol></div>`).join('')}</div>`;
}

function filedQuarters(p) {
  const h=p.quarters||[];
  if (!h.length) return '';
  const byQ=Object.fromEntries(h.map(q=>[q.quarter,q]));
  const yoy=(q,key)=>{const prior=byQ['Q'+q.quarter[1]+' FY'+String(+q.quarter.slice(-2)-1).padStart(2,'0')];
    return prior&&prior[key]>0&&q[key]!=null?((q[key]/prior[key]-1)*100):null;};
  const n=v=>v==null?'—':new Intl.NumberFormat('en-IN',{maximumFractionDigits:0}).format(v);
  const pct=v=>v==null?'—':`<span class="${v<0?'fall':'rise'}">${v<0?'−':'+'}${Math.abs(v).toFixed(1)}%</span>`;
  const lender=p.card?.kind!=='industrial';
  const cell=(v,g)=>`<td>${n(v)}${g==null?'':`<small>${pct(g)}</small>`}</td>`;
  return `<details class="filed-quarters" open><summary>Filed quarters · ₹ crore · ${esc(p.card?.scope||'')}</summary><div class="market-scroll"><table class="market-table quarters-table">
    <thead><tr><th scope="col">Quarter</th><th scope="col">Revenue <small>YoY</small></th><th scope="col">${lender?'NII':'EBITDA %'}</th><th scope="col">PAT <small>YoY</small></th></tr></thead><tbody>
    ${h.slice(-6).reverse().map(q=>`<tr><th scope="row">${esc(q.quarter)}</th>${cell(q.revenue,yoy(q,'revenue'))}
      <td>${lender?n(q.core):q.core!=null&&q.revenue?(q.core/q.revenue*100).toFixed(1)+'%':'—'}</td>${cell(q.pat,yoy(q,'pat'))}</tr>`).join('')}
    </tbody></table></div>${p.card?`<p class="coverage">${sourceButton(p.card.source,'Latest XBRL filing')}</p>`:''}</details>`;
}
