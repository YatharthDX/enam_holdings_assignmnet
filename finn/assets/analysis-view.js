import {dateLabel, esc, icon, route, sourceButton} from './ui.js?v=0.6.1';

function usageLine(usage, saved = true) {
  if (!usage) return '';
  const cost = usage.estimated_usd == null ? '' : ` · est. $${usage.estimated_usd.toFixed(4)} (rates ${usage.pricing_date})`;
  const reported = usage.provider_reported_usd == null ? '' : ` · provider-reported $${usage.provider_reported_usd.toFixed(6)}`;
  const thinking = usage.reasoning_tokens ? ` (including ${usage.reasoning_tokens.toLocaleString('en-IN')} thinking tokens)` : '';
  return `<p class="analysis-usage">Original run: ${usage.input_tokens.toLocaleString('en-IN')} input / ${usage.output_tokens.toLocaleString('en-IN')} output tokens${cost}${reported} · ${usage.seconds}s.
    ${thinking} ${saved ? 'Reopening uses this saved result with no new model call.' : 'This attempt used tokens. Retry analysis makes a new request.'}
    ${['gemini','openrouter'].includes(usage.provider) ? esc(usage.billing_note) : ''}${usage.provider==='openrouter' && usage.actual_model?` Served by ${esc(usage.actual_model)}.`:''}</p>`;
}

function analysisBody(data) {
  const a = data.analysis;
  if (!a) return '';
  const job = a.job, result = job?.result, running = job?.status === 'running';
  const historical = a.coverage.corpus === 'historical_excerpts';
  const ready = a.coverage.selected_passages > 0;
  const finished = job?.status === 'complete';
  const title = a.lenses.find(l => l.id === a.lens)?.title;
  const why = !a.configured ? `Add ${a.key_env} to .env, then restart FINN. Provider setup steps are in README.md.` :
    !ready ? 'Choose Find documents above to index primary sources for this ticker.' :
    historical ? 'This lens will analyze the curated historical excerpts. Find documents for a fresh document review.' :
    'Generate a concise reading of the indexed annual report and call transcripts.';
  return `<section class="analysis-panel" aria-labelledby="analysis-heading">
    <div class="analysis-top"><div class="section-meta">Optional model output</div>
      ${finished ? '<span class="saved-badge">Saved</span>' : ''}</div>
    <h2 id="analysis-heading">AI-generated reading</h2>
    <p class="analysis-provider">${esc(a.provider_label)} · ${esc(a.model)} · ${a.configured ? 'Key configured' : 'Key needed'}</p>
    ${a.provider==='openrouter'?`<p class="coverage">Free-only routing.${a.dynamic_model?' The free router selects an available compatible model; its reported model appears with the saved result.':''} Availability and quotas depend on OpenRouter.</p>`:''}
    <nav class="analysis-lenses" aria-label="Research lens">${a.lenses.map(l =>
      `<a class="chip" href="${route('research',{ticker:data.company.symbol,lens:l.id,ai:'1'})}" ${l.id===a.lens?'aria-current="true"':''}>${esc(l.title)}</a>`).join('')}</nav>
    <div class="analysis-coverage"><strong>${!ready ? 'No primary evidence yet' : historical ? 'Historical excerpt set' : 'Indexed originals'}</strong>
      <span>${a.coverage.documents_used} source${a.coverage.documents_used===1?'':'s'} · ${a.coverage.selected_passages} selected passage${a.coverage.selected_passages===1?'':'s'}</span></div>
    ${!finished ? `<p class="panel-intro">${esc(why)}</p>
      <button type="button" class="button primary" id="analyze-documents" ${running || !ready || !a.configured?'disabled':''}>
        ${running ? 'Analyzing…' : job ? 'Retry analysis' : 'Analyze documents'} ${icon('arrow',16)}</button>` : ''}
    <p id="analysis-status" class="analysis-status" role="status">${esc(running ? 'Reading sources and checking citations. You can keep browsing.' : job?.detail || '')}</p>
    ${result ? `<div class="analysis-result"><div class="section-meta">${esc(title)} · ${esc(dateLabel(job.finished))}</div>
      ${result.findings.map(f => `<article class="analysis-finding"><div class="analysis-label">${esc(f.label)}${f.kind==='inference' ? '<span>Interpretation</span>' : '<span>Reported</span>'}</div>
        <p>${esc(f.text)}</p><div class="analysis-citations">${f.sources.map((s,i) => sourceButton(s,`${s.title} · p. ${s.page}`)).join('')}</div></article>`).join('')}
      ${result.gaps.length ? `<details class="analysis-gaps" open><summary>Evidence gaps & limits</summary><ul>${result.gaps.map(g => `<li>${esc(g)}</li>`).join('')}</ul></details>` : ''}
      <p class="coverage">${esc(result.verification)}</p>${usageLine(job.usage)}</div>` : job?.usage ? usageLine(job.usage, false) : ''}
    <details class="analysis-method"><summary>Sources, privacy & usage</summary>
      <p>${esc(a.coverage.note)}</p><p>On your request, selected public document passages go to ${esc(a.provider_label)}. Your portfolio and fictional contacts stay in FINN. Results are generated only when you press Analyze documents or Retry analysis.</p>
      <p>One request per new lens, provider, model and document revision. FINN never switches providers after an error. Quotes and numerical literals are checked; the model’s interpretation still needs your judgment.</p>
      <p>${a.provider === 'openrouter' ? 'FINN accepts openrouter/free or a model ID ending in :free, requests zero-priced endpoints and requires JSON-schema support. OpenRouter and its selected model provider process the public passages under their respective policies. Paid model IDs and automatic fallback are disabled. A free endpoint may still be unavailable or quota-limited.' : a.provider === 'gemini' ? 'Gemini’s free tier has quotas and depends on your Google project plan. FINN cannot verify that billing is disabled. Free-tier content may be used to improve Google’s products; only public document passages are sent.' : 'OpenAI token costs are estimates using the listed pricing date, excluding taxes. Requests disable response storage with store: false; provider retention policies still apply.'}</p></details>
  </section>`;
}

export function analysisView(data, open = false) {
  const a = data.analysis;
  if (!a) return '';
  const state = !a.enabled ? 'Off' : a.configuration_error ? 'Setup' : a.job?.status === 'running' ? 'Running' : 'Available';
  const content = !a.enabled ? `<div class="optional-ai-copy"><p>The evidence search, guidance comparison and network above work without a model.</p>
    <p>${a.date_filtered ? 'This dated research view excludes later and undated evidence. Optional AI synthesis is available only in the unfiltered local view.' : a.public_demo ? 'AI synthesis is unavailable in this public demo. OpenRouter, Gemini or OpenAI can be configured in your own local workspace.' : a.needs_workspace ? 'Open your own workspace before using the optional local AI feature.' : 'AI synthesis is an optional extra. To enable it, set <code>FINN_ENABLE_LLM=1</code> and configure the default OpenRouter key, or select Gemini/OpenAI, as described in README.md.'}</p></div>` :
    a.configuration_error ? `<div class="optional-ai-copy"><p>Optional AI settings need attention: ${esc(a.configuration_error)}</p><p>Core research remains available above.</p></div>` : analysisBody(data);
  return `<details class="optional-ai" id="optional-ai" ${open ? 'open' : ''}>
    <summary><span>Optional AI synthesis</span><small>${state}</small>${icon('down',16)}</summary>${content}</details>`;
}
