import {esc, heading, icon, route} from './ui.js?v=0.8.0';

export function workspaceNotice(session) {
  if (session?.authenticated) return `<aside class="workspace-notice"><span><strong>Your private demo workspace</strong> · expires within 24 hours</span><a href="#account" class="text-button">Workspace ${icon('chevron',14)}</a></aside>`;
  let hidden=false;
  try { hidden=sessionStorage.getItem('yfinn-notice')==='hidden'; } catch {}
  if (hidden) return '';
  return `<aside class="workspace-notice compact" aria-label="Demo notice"><p><strong>${session?.runtime?.public_demo?'Public demo':'Demo preview'}</strong> · real filings, results and prices; fictional network.</p>
    <div class="notice-actions">${session?.runtime?.can_start_workspace?'<button type="button" id="open-workspace" class="button primary small">Open my workspace</button>':'<span class="meta">Read only</span>'}
    <button type="button" class="icon-button" id="hide-notice" aria-label="Hide demo notice">${icon('close',16)}</button></div></aside>`;
}

export function workspaceView(session) {
  if (!session?.authenticated) return heading('Demo access','Your workspace','A private, expiring workspace for your alert rules, holdings, contacts and notes. No email or key needed.')+
    (session?.runtime?.can_start_workspace?`<section class="panel"><h2>Open a workspace</h2><p class="panel-intro">Everything you change stays in this browser's workspace and is erased after 24 hours, or sooner if you choose.</p><button type="button" id="open-workspace" class="button primary">Open my workspace</button></section>`:'<p class="coverage">This deployment is read only.</p>');
  const expires=new Intl.DateTimeFormat('en-IN',{dateStyle:'medium',timeStyle:'short'}).format(new Date(session.expires*1000));
  return heading('Workspace and privacy','Your workspace','This browser holds an expiring access cookie. No email or model key is needed.')+
    `<div class="stack account-stack"><section class="panel"><h2>Keep your work</h2><p class="panel-intro">Workspace expires ${esc(expires)}. Export your portfolio, profiles, notes and reviewed facts before expiry. Access credentials are excluded.</p>
      <button id="export-workspace" type="button" class="button primary">Export workspace ${icon('file',16)}</button><p id="workspace-status" role="status"></p></section>
    <section class="panel"><h2>Network profiles</h2><p class="panel-intro">Import dated roles, topics and recorded acquaintance links. A shared employer alone never creates an introduction.</p>
      <form id="network-import-form" class="stack"><label>Network JSON<input type="file" name="network" accept=".json,application/json" required></label>
      <label class="check"><input type="checkbox" name="replace"> Replace the current network (otherwise merge by profile ID)</label>
      <button class="button secondary" type="submit">Import profiles</button><span id="network-import-status" role="status"></span></form>
      <p class="coverage"><a href="/assets/network-example.json" download>Download a fictional example</a>. Public demos accept fictional profiles only. Real local imports require recorded consent, purpose, provenance and expiry.</p></section>
    <details class="panel"><summary>Erase this workspace ${icon('down',16)}</summary><p class="panel-intro">Deletes its sessions, profiles, connections, notes, preferences, alerts and reviewed facts. Shared public issuer documents remain available.</p>
      <form id="delete-workspace-form"><label class="check"><input type="checkbox" name="confirm" required> I want to erase this workspace</label><button class="button secondary" type="submit">Erase workspace</button></form></details></div>`;
}
