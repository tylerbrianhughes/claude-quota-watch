const $ = id => document.getElementById(id);
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const duration = minutes => minutes === null ? 'No estimate' : minutes < 1 ? 'Now' : Math.round(minutes) < 60 ? `${Math.round(minutes)} min` : `${Math.floor(Math.round(minutes) / 60)}h ${Math.round(minutes) % 60}m`;
const clock = seconds => seconds == null ? 'Unknown' : new Date(seconds * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const age = seconds => seconds == null ? 'Never measured' : seconds < 0 ? 'Clock mismatch' : seconds < 60 ? `${Math.floor(seconds)}s old` : `${Math.floor(seconds / 60)}m old`;
let latestData;
function healthDecision(h, monitorOk, horizon) {
  const known=h.runway_minutes !== null && monitorOk;
  const covered=known && h.runway_minutes >= horizon;
  const reached=known && h.runway_minutes === 0;
  const reset=h.next_potential_reset;
  const bridge=known && !reached && reset && reset.minutes <= h.runway_minutes;
  const title=!monitorOk ? 'Capacity unknown: measurements need refreshing' : !h.active_accounts ? 'No active workload measured' : !known ? 'Capacity unknown: full-speed runway is unverified' : reached ? (h.ready_spares ? 'Switch needed now: verified spare available' : 'At risk now: switch threshold exceeded, no verified spare') : covered ? 'Current allocation covers this work block' : h.ready_spares ? 'Next switch ahead: verified spare available' : bridge ? 'Current capacity should bridge to the next reset' : h.runway_minutes < 15 ? 'At risk soon: less than 15 minutes to switch' : 'Coverage beyond the next switch is unverified';
  const action=!known ? 'Verify usage and observe the workload before making a purchase decision.' : covered ? 'No additional capacity is indicated for this horizon at the measured pace.' : h.ready_spares ? `Prepare the ${h.ready_spares} verified spare account(s); transfer coverage still needs confirmation.` : bridge ? 'Replacement verification pending. Verify the account after its scheduled reset, then switch before the active account reaches its guard. This does not establish coverage for the entire selected work block or a need to buy another account.' : 'No verified spare is ready. Verify replacement capacity before the next switch.';
  return {known,covered,reached,bridge,title,action};
}
function renderHealth(data) {
  const h=data.health, horizon=Number($('health-horizon').value), panel=$('fleet-health');
  if (!h) return;
  const decision=healthDecision(h,data.monitor_ok,horizon);
  const {known,covered,bridge}=decision;
  const urgent=known && h.runway_minutes < 15;
  const reached=known && h.runway_minutes === 0;
  panel.className=`fleet-health ${!known ? 'unknown' : covered ? 'covered' : urgent ? 'critical' : 'watch'}`;
  $('health-title').textContent=decision.title;
  $('health-verdict').textContent=reached ? 'An active account is already beyond its switch threshold. Its remaining quota is a buffer, not verified coverage for continued full-speed work.' : known ? `About ${duration(h.runway_minutes)} until the first account reaches its switch guard, at the recent pace. ${h.sample_minutes === null ? "A fresh reading has reached the switch guard." : `Based on a ${Math.round(h.sample_minutes)}-minute sample; this is a short-term projection.`}` : 'A missing, stale or flat rate cannot establish sustained capacity.';
  const bar=$('health-bar'); bar.value=known ? Math.min(100,h.runway_minutes/horizon*100) : 0;
  bar.setAttribute('aria-valuetext',known ? `${Math.round(bar.value)}% of selected horizon before next switch` : 'Unknown coverage');
  $('health-scale').replaceChildren(make('span',known ? `${duration(h.runway_minutes)} measured-rate runway` : 'Coverage unknown'),make('span',`${duration(horizon)} target`));
  const metrics=$('health-metrics'); metrics.replaceChildren();
  const extra=known && h.fresh_account_minutes > 0 ? Math.ceil(Math.max(0,horizon-h.runway_minutes)/h.fresh_account_minutes) : null;
  const reset=h.next_potential_reset;
  for(const [label,value,note] of [
    ['Next switch', known ? duration(h.runway_minutes) : 'Unknown',h.bottleneck ? `${h.bottleneck.email} · ${h.bottleneck.window}` : 'Two fresh observations needed'],
    ['Ready spares',String(h.ready_spares),`${h.unknown_accounts} accounts need verification`],
    ['Next 5-hour reset with weekly quota remaining',reset ? duration(reset.minutes) : 'Unknown',reset ? `${reset.email} · ${reset.weekly_used}% weekly used at last check · verify after reset` : 'No qualifying five-hour reset established'],
    ['Hypothetical fresh accounts (resets excluded)',extra===null ? 'Not comparable' : extra===0 ? 'None for this block' : `≈ ${extra} more`,h.fresh_account_minutes ? `Each identical fresh account ≈ ${duration(h.fresh_account_minutes)} at this load` : 'Requires one measured account carrying the fleet']]) {
      const node=make('div',undefined,'health-metric');node.append(make('span',label),make('b',value),make('small',note));metrics.append(node);
  }
  let action=decision.action;
  if(known && !covered && !bridge && h.unknown_accounts) action+=' Verify the unknown accounts before buying another.';
  if(known && reset && reset.minutes>h.runway_minutes) action+=` The next potential reset is ${duration(reset.minutes-h.runway_minutes)} beyond current runway.`;
  $('health-action').textContent=action;
  $('health-assumptions').textContent=`${h.assumptions} The bar measures time before the first switch, not a sum of account percentages. Ready spares are listed separately. The scenario excludes future natural resets and existing spares; it is a capacity estimate, not a purchase instruction. Short rate samples can change quickly. ${h.reference_account ? 'Reference: '+h.reference_account+'.' : ''}`;
}
$('health-horizon').addEventListener('change',()=>{if(latestData)renderHealth(latestData);});
function render(data) {
  latestData=data;
  renderHealth(data);
  $('error').hidden = true;
  const heartbeat = $('heartbeat');
  heartbeat.textContent = data.monitor_ok ? `Monitor checked ${age(data.monitor_age_seconds)}` : `Monitor overdue · ${age(data.monitor_age_seconds)}`;
  heartbeat.className = `badge${data.monitor_ok ? '' : ' warn'}`;
  const rows = data.accounts;
  const totalProcesses = rows.every(a => a.process_count !== null) ? rows.reduce((n,a) => n+a.process_count, 0) : '?';
  const summary = $('summary'); summary.replaceChildren();
  for (const [label,value,note] of [
    ['Verified available', rows.filter(a=>a.state==='available').length, 'Current quota and eligibility'],
    ['Constrained', rows.filter(a=>a.state==='constrained').length, 'Session or weekly/model threshold'],
    ['Needs verification', rows.filter(a=>a.state.endsWith('unknown')).length, 'Unknown is not exhausted'],
    ['Running processes', totalProcesses, 'Approximate load; not subagents']]) {
    const card=make('div',undefined,'stat'); card.append(make('span',label),make('b',String(value)),make('small',note)); summary.append(card);
  }
  $('updated').textContent = `Snapshot ${clock(data.checked_at)} · page ${new Date().toLocaleTimeString()}`;
  const accounts = $('accounts'); accounts.replaceChildren();
  for (const account of rows) {
    const card=make('article',undefined,`account ${account.state}`);
    const top=make('div',undefined,'account-top'); top.append(make('h3',account.email),make('span',account.state.replaceAll('_',' '),'state')); card.append(top);
    const meta=make('div',undefined,'meta'); meta.append(make('span',`${account.profiles.join(' · ') || 'Standby'} · ${account.process_count ?? '?'} processes`),make('span',age(account.age_seconds))); card.append(meta);
    if (account.verification) {
      const v=account.verification;
      const info=make('p',undefined,'verification');
      info.append(make('strong',`Standby checks: ${v.state.replaceAll('_',' ')}. `),document.createTextNode(v.reason));
      if(v.last_attempt_at) info.append(make('small',` Last check ${clock(v.last_attempt_at)}${v.last_result ? ' · '+v.last_result.replaceAll('_',' ') : ''}`));
      card.append(info);
    }
    for (const window of account.windows) {
      const section=make('div',undefined,`window${!window.fresh ? ' stale' : window.used >= window.threshold ? ' warn' : ''}`);
      const title=make('div',undefined,'window-title'); title.append(make('span',window.name==='session' ? 'Five-hour window' : window.name==='weekly' ? 'Weekly' : window.name), make('b',window.used === null ? 'Unknown' : `${window.used}%${window.fresh ? '' : ' · stale'}`));
      const bar=make('progress',undefined,'meter'); bar.max=100; bar.value=window.used ?? 0; bar.setAttribute('aria-label', `${window.name} used`);
      const details=make('div',undefined,'window-details');
      const rate = window.rate_per_minute === null ? 'No rate estimate' : `${window.rate_per_minute.toFixed(2)} pp/min · ${Math.round(window.sample_minutes)}m sample`;
      details.append(make('span',rate),make('span',window.reset ? `Resets ${clock(window.reset)}` : 'Reset not started / unknown'));
      const forecast=make('div',undefined,'window-details'); forecast.append(make('span',`${window.threshold}% threshold`),make('span',window.fresh ? window.reset_before_threshold ? 'Reset precedes projected threshold' : duration(window.minutes_to_threshold) : 'Refresh needed'));
      section.append(title,bar,details,forecast); card.append(section);
    }
    const projection=make('div',undefined,'projection'); projection.append(make('span','Earliest projected threshold'),make('b',account.state.endsWith('unknown') ? 'Verify capacity' : duration(account.minutes_to_first_threshold))); card.append(projection); accounts.append(card);
  }
  const obligations=$('obligations'); obligations.replaceChildren();
  if (!data.obligations.length) obligations.append(make('p','No open recovery obligations in the current snapshot.','subtitle'));
  for (const item of data.obligations) {
    const node=make('article',undefined,'obligation'); node.append(make('h3',`${item.id} · ${item.state?.replaceAll('_',' ')}`),make('p',item.reason || 'No reason recorded'),make('small',`${item.overdue ? 'Overdue · ' : ''}Check by ${clock(item.deadline)}`)); obligations.append(node);
  }
}
async function refresh() {
  try { const result=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(4000)}); if(!result.ok) throw new Error('Snapshot unavailable'); render(await result.json()); }
  catch(error) { $('error').hidden=false; $('error').textContent='Dashboard data unavailable. Values below may be stale. Retrying automatically.'; $('heartbeat').textContent='Connection lost'; $('heartbeat').className='badge warn'; $('fleet-health').className='fleet-health unknown'; $('health-title').textContent='Live health unavailable'; $('health-verdict').textContent='Connection lost. Previous forecasts are stale.'; $('health-bar').value=0; $('health-scale').replaceChildren(); $('health-metrics').replaceChildren(); $('health-action').textContent='Wait for fresh measurements before relying on a capacity estimate.'; latestData=null; }
  finally { setTimeout(refresh,5000); }
}
refresh();
