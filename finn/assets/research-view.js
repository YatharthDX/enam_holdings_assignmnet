import {esc, dateLabel, route, sourceButton, empty} from './ui.js?v=0.6.0.2';

const option=(value,label,selected)=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`;
const label=value=>value.replaceAll('_',' ');

export function sourceBrief(data, topic='business') {
  const r=data.structured, b=r?.brief;
  if (!b?.documents) return data.as_of ? `<div class="note"><strong>No dated originals in the index by ${esc(data.as_of)}</strong><p>Undated originals are excluded from the extractive brief. Your reviewed facts retain dates you explicitly confirmed.</p></div>` : '';
  const chosen=b.groups.find(g=>g.id===topic)||b.groups[0];
  const passage=p=>`<article class="extractive-passage"><div class="meta">${esc(p.source.title)} · p. ${p.source.page}</div><p>${esc(p.text.length>420?p.text.slice(0,p.text.lastIndexOf(' ',420))+'…':p.text)}</p>${sourceButton(p.source,'Inspect full passage')}</article>`;
  return `<section class="panel source-brief"><div class="section-meta">${b.corpus==='historical_excerpts'?'Historical excerpts':'Indexed originals'} · ${b.documents} sources · ${b.pages} text pages</div>
    <h2>From the originals</h2><p class="panel-intro">Exact passages selected from company documents. No model needed.</p>
    <nav class="chips" aria-label="Research topic">${b.groups.map(g=>`<a class="chip" href="${route('research',{ticker:data.company.symbol,topic:g.id,as_of:data.as_of})}" ${g.id===chosen.id?'aria-current="true"':''}>${esc(g.title)}</a>`).join('')}</nav>
    ${chosen.passages.length?passage(chosen.passages[0]):empty('No selected passage','This topic was not found by the retrieval rules. Search the source directly before concluding it was not disclosed.')}
    ${chosen.passages.length>1?`<details><summary>More source perspectives · ${chosen.passages.length-1}</summary>${chosen.passages.slice(1).map(passage).join('')}</details>`:''}
    <p class="coverage">${esc(b.method)}${b.excluded_pages?' '+b.excluded_pages+' undated or later pages excluded.':''}</p></section>`;
}

export function dateFilter(data) {
  const today=new Date().toISOString().slice(0,10);
  return `<form id="asof-form" class="asof-form"><label>Evidence available by<input type="date" name="as_of" max="${today}" value="${esc(data.as_of||'')}"></label>
    <button class="button secondary" type="submit">Apply date</button>${data.as_of?`<a class="text-button" href="${route('research',{ticker:data.company.symbol})}">All indexed evidence</a>`:''}</form>`;
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
  const financials=r.financials.length?`<section class="panel"><div class="section-meta">Your reviewed figures</div><h2>Financial record</h2><div class="market-scroll"><table class="market-table"><thead><tr><th>Metric / period</th><th>Reported</th><th>QoQ</th><th>YoY</th><th>Evidence</th></tr></thead><tbody>${r.financials.map(row=>`<tr><th>${esc(r.metrics[row.fact.metric])}<small>${esc(row.fact.period)} · ${esc(row.fact.scope)} · ${esc(label(row.fact.basis))}</small></th><td>${esc(row.fact.low)} ${esc(row.fact.unit)}</td><td>${row.qoq?esc(row.qoq.percent.toFixed(2))+' '+esc(row.qoq.unit):'—'}</td><td>${row.yoy?esc(row.yoy.percent.toFixed(2))+' '+esc(row.yoy.unit):'—'}</td><td>${sourceButton(row.fact.source,'Source')}${row.qoq?sourceButton(row.qoq.source,'QoQ base'):''}${row.yoy?sourceButton(row.yoy.source,'YoY base'):''}</td></tr>`).join('')}</tbody></table></div><p class="coverage">Changes require matching units, scope and currency basis. Percentage metrics use percentage-point differences; amount ratios need a positive prior value. Missing baselines stay blank.</p></section>`:'';
  const review=r.can_review && data.sources.length?`<details class="panel fact-workbench" id="fact-editor"><summary>Review a fact for comparison</summary><p class="panel-intro">Record a sourced statement for any ticker. Quotes and values are checked against its indexed page; you confirm the period, authority, units and accounting basis.</p>
    <form id="fact-form" class="stack"><div class="rules-grid"><label>Source document<select name="source_id" required>${data.sources.map(s=>option(s.id,s.title,'')).join('')}</select></label><label>PDF page<input name="page" type="number" min="1" step="1" required></label></div>
      <label>Exact source quote<textarea name="quote" rows="4" maxlength="1200" minlength="16" required></textarea></label>
      <div class="rules-grid"><label>Statement<select name="kind">${option('guidance','Guidance','guidance')}${option('actual','Reported actual','guidance')}${option('qualitative','Qualitative statement','guidance')}</select></label><label>Metric<select name="metric">${Object.entries(r.metrics).map(([k,v])=>option(k,v,'revenue_growth')).join('')}</select></label>
      <label>Fiscal period<input name="period" placeholder="FY25 or Q4 FY25" maxlength="20" required></label><label>Units<select name="unit">${r.units.map(v=>option(v,v,'%')).join('')}</select></label>
      <label>Lower / actual value<input name="low" inputmode="decimal" maxlength="24"></label><label>Upper guidance value<input name="high" inputmode="decimal" maxlength="24" placeholder="Leave blank for one value"></label>
      <label>Accounting scope<select name="scope">${r.scopes.map(v=>option(v,label(v),'not_stated')).join('')}</select></label><label>Currency basis<select name="basis">${r.bases.map(v=>option(v,label(v),'not_stated')).join('')}</select></label>
      <label>Speaker / reporting authority<input name="speaker" maxlength="100" required></label><label>Statement authority<select name="speaker_kind">${option('unidentified','Unidentified','unidentified')}${option('management','Management','unidentified')}${option('question','Analyst question','unidentified')}${option('report','Company report','unidentified')}</select></label>
      <label>Verified publication date<input name="published" type="date" max="${new Date().toISOString().slice(0,10)}"></label></div>
      <label class="check"><input type="checkbox" name="reviewed" required> I inspected the original and reviewed the fields above</label><button class="button primary" type="submit">Save reviewed fact</button><p id="fact-status" role="status"></p></form></details>`:'';
  const drafts=r.candidates.length?`<details class="panel"><summary>Statements to review · ${r.candidates.length}</summary><p class="panel-intro">Rule-selected candidates, not accepted financial facts. Analyst questions and unidentified speakers remain labelled.</p>${r.candidates.map((c,i)=>`<article class="candidate"><div class="meta">${esc(c.speaker_kind)} · ${esc(c.source.title)} · p. ${c.source.page}</div><p>${esc(c.quote.slice(0,320))}${c.quote.length>320?'…':''}</p>${sourceButton(c.source,'Inspect')}${r.can_review?`<button class="text-button" type="button" data-review-candidate="${i}">Review fields</button>`:''}</article>`).join('')}</details>`:'';
  const saved=r.facts.length?`<details class="panel"><summary>Your reviewed facts · ${r.facts.length}</summary>${r.facts.map(f=>`<article class="candidate"><div class="meta">${esc(r.metrics[f.metric])} · ${esc(f.period)} · ${esc(f.kind)}${f.stale?' · Source changed':''}</div><p>${esc(f.quote)}</p>${sourceButton(f.source,'Evidence')}${r.can_review?`<button type="button" class="text-button" data-delete-fact="${esc(f.id)}">Remove fact</button>`:''}</article>`).join('')}</details>`:'';
  return `${comparisons?`<section class="panel"><div class="section-meta">Your reviewed comparisons · Deterministic arithmetic</div><h2>Promises and delivery</h2>${comparisons}</section>`:''}${financials}${drafts}${review}${saved}`;
}
