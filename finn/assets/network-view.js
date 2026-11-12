import {esc,icon,personCard} from './ui.js?v=0.7.0';

export function identityForm() {
  return `<details class="panel identity-panel"><summary>Check a person's identity ${icon('down',16)}</summary><p class="panel-intro">A name alone cannot establish an introduction. Compare a recorded employer, role and tenure at the date of the event.</p>
    <form id="identity-form" class="stack"><div class="rules-grid"><label>Name<input name="name" maxlength="100" required></label><label>Employer / ticker<input name="employer" maxlength="100" required></label><label>Exact recorded role<input name="role" maxlength="100" required></label><label>Event date<input type="date" name="on" required></label></div><button class="button secondary" type="submit">Check recorded profiles</button></form><div id="identity-result" role="status"></div></details>`;
}

export function identityResult(result) {
  return `<div class="identity-result"><strong>${esc(result.status)}</strong><p>${esc(result.reason)}</p>${result.person?result.person.distance?personCard(result.person):`<p>${esc(result.person.name)} has relevant recorded employment, but no introduction path is recorded.</p>`:''}</div>`;
}

export function reconnectCards(items) {
  return items?.length?`<section class="panel"><div class="section-meta">A reason to reconnect</div><h2>Keep the network warm</h2>${items.map(x=>`<p class="panel-intro">${esc(x.reason)}</p>${personCard(x.person)}`).join('')}<p class="coverage">Suggested conversation only; FINN does not contact anyone.</p></section>`:'';
}
