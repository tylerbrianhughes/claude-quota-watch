const $ = id => document.getElementById(id);
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const duration = minutes => minutes === null ? 'No estimate' : minutes < 1 ? 'Now' : Math.round(minutes) < 60 ? `${Math.round(minutes)} min` : minutes >= 1440 ? `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h` : `${Math.floor(Math.round(minutes) / 60)}h ${Math.round(minutes) % 60}m`;
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
  renderOutlook(data);
  renderThroughput(data.throughput);
  $('error').hidden = true;
  const heartbeat = $('heartbeat');
  heartbeat.textContent = data.monitor_ok ? `Monitor checked ${age(data.monitor_age_seconds)}` : `Monitor overdue · ${age(data.monitor_age_seconds)}`;
  heartbeat.className = `badge${data.monitor_ok ? '' : ' warn'}`;
  const rows = data.accounts;
  const totalProcesses = rows.every(a => a.process_count !== null) ? rows.reduce((n,a) => n+a.process_count, 0) : '?';
  const summary = $('summary'); summary.replaceChildren();
  for (const [label,value,note] of [
    ['Verified available', rows.filter(a=>a.state==='available').length, 'Current quota and eligibility'],
    ['Weekly exhausted', rows.filter(a=>a.display_status==='weekly_exhausted').length, '95% or more weekly used'],
    ['5-hour limited', rows.filter(a=>a.display_status==='session_limited').length, 'Session guard reached; weekly quota remains'],
    ['Other limited', rows.filter(a=>['weekly_limited','model_limited','constrained'].includes(a.display_status || a.state)).length, 'Weekly or model switch guard'],
    ['Needs verification', rows.filter(a=>a.state.endsWith('unknown')).length, 'Unknown is not exhausted'],
    ['Running processes', totalProcesses, 'Approximate load; not subagents']]) {
    const card=make('div',undefined,'stat'); card.append(make('span',label),make('b',String(value)),make('small',note)); summary.append(card);
  }
  $('updated').textContent = `Snapshot ${clock(data.checked_at)} · page ${new Date().toLocaleTimeString()}`;
  renderAccounts(rows);
  const obligations=$('obligations'); obligations.replaceChildren();
  if (!data.obligations.length) obligations.append(make('p','No open recovery obligations in the current snapshot.','subtitle'));
  for (const item of data.obligations) {
    const node=make('article',undefined,'obligation'); node.append(make('h3',`${item.id} · ${item.state?.replaceAll('_',' ')}`),make('p',item.reason || 'No reason recorded'),make('small',`${item.overdue ? 'Overdue · ' : ''}Check by ${clock(item.deadline)}`)); obligations.append(node);
  }
}

const columns = [
  ['email','Account'], ['state','Status'], ['session','Five-hour'],
  ['weekly','Weekly'], ['fable','Fable'], ['session_rate','5h burn / h'], ['weekly_rate','Weekly burn / h'], ['reset','5h reset'],
  ['weekly_reset','Weekly reset'], ['banked_resets','Banked resets'], ['expiration_date','Expiration date'],
  ['switch','Switch guard'], ['processes','Processes'], ['observed','Verified']
];
let accountSort = {key:'priority',direction:'asc'};
try { const saved=JSON.parse(localStorage.getItem('quota-account-sort')); if(saved && ['priority',...columns.map(c=>c[0])].includes(saved.key) && ['asc','desc'].includes(saved.direction)) accountSort=saved; } catch {}
const expandedAccounts = new Set();
const windowFor = (account,name) => account.windows.find(w=>w.name===name);
const activeAccount = account => account.profiles.length>0 || account.process_count>0;
const statusLabel = account => ({session_limited:'5-hour limited'}[account.display_status] || (account.display_status || account.state).replaceAll('_',' '));
function sortValue(account,key) {
  if (['session','weekly','fable'].includes(key)) return windowFor(account,key)?.used ?? null;
  if(key.endsWith('_rate')) {const w=windowFor(account,key.replace('_rate',''));return w?.fresh && w.rate_per_minute!=null ? w.rate_per_minute*60 : null;}
  if(key==='reset') return windowFor(account,'session')?.reset ?? null;
  if(key==='weekly_reset') return windowFor(account,'weekly')?.reset ?? null;
  if(key==='switch') return account.state.endsWith('unknown') ? null : account.minutes_to_first_threshold;
  if(key==='state') return statusLabel(account);
  if(key==='processes') return account.process_count;
  if(key==='observed') return account.observed_at;
  return account[key];
}
function compareValue(a,b,direction='asc') {
  // Missing measurements stay last in either direction; unknown never means zero.
  if(a==null || b==null) return a==null ? (b==null ? 0 : 1) : -1;
  const result=typeof a==='string' ? a.localeCompare(b) : a-b;
  return direction==='asc' ? result : -result;
}
function sortedAccounts(rows,sort=accountSort) {
  const group=a=>activeAccount(a) ? 0 : a.state==='available' ? 1 : a.state.endsWith('unknown') ? 2 : 3;
  return [...rows].sort((a,b)=>{
    const result=sort.key==='priority'
      ? group(a)-group(b) || (activeAccount(a) ? compareValue(sortValue(a,'switch'),sortValue(b,'switch')) : 0)
      : compareValue(sortValue(a,sort.key),sortValue(b,sort.key),sort.direction);
    return result || a.email.localeCompare(b.email);
  });
}
function setAccountSort(key) {
  accountSort={key,direction:accountSort.key===key && accountSort.direction==='asc' ? 'desc' : 'asc'};
  try {localStorage.setItem('quota-account-sort',JSON.stringify(accountSort));} catch {}
  if(latestData) renderAccounts(latestData.accounts);
}
function initAccountTable() {
  const row=$('account-head');
  for(const [key,label] of columns) {
    const th=make('th');th.scope='col';th.dataset.key=key;
    const button=make('button',label,'sort-button');button.type='button';button.addEventListener('click',()=>setAccountSort(key));
    th.append(button);row.append(th);
  }
  $('priority-sort').addEventListener('click',()=>{
    accountSort={key:'priority',direction:'asc'};
    try {localStorage.setItem('quota-account-sort',JSON.stringify(accountSort));} catch {}
    if(latestData) renderAccounts(latestData.accounts);
  });
}
function renderAccounts(rows) {
  const focus=document.activeElement;
  const focusedEmail=focus?.dataset?.account;
  for(const th of $('account-head').children) {
    const selected=th.dataset.key===accountSort.key;
    th.setAttribute('aria-sort',selected ? (accountSort.direction==='asc' ? 'ascending' : 'descending') : 'none');
    const label=columns.find(c=>c[0]===th.dataset.key)[1];
    th.firstChild.textContent=label+(selected ? (accountSort.direction==='asc' ? ' ↑' : ' ↓') : ' ↕');
  }
  $('priority-sort').setAttribute('aria-pressed',String(accountSort.key==='priority'));
  $('account-sort-note').textContent=accountSort.key==='priority' ? 'Active accounts nearest their guard first, then ready spares.' : `Sorted by ${columns.find(c=>c[0]===accountSort.key)[1].toLowerCase()} · ${accountSort.direction==='asc' ? 'ascending' : 'descending'}. Unknown values last.`;
  const body=$('account-body');body.replaceChildren();
  for(const [index,account] of sortedAccounts(rows).entries()) {
    const tr=make('tr',undefined,`account-row ${account.state} ${account.display_status || account.state}${activeAccount(account) ? ' active-account' : ''}`);
    const name=make('th');name.scope='row';
    const toggle=make('button',`${expandedAccounts.has(account.email) ? '▾' : '▸'} ${account.email}`,'account-toggle');
    toggle.type='button';toggle.dataset.account=account.email;
    toggle.setAttribute('aria-expanded',String(expandedAccounts.has(account.email)));toggle.setAttribute('aria-controls',`account-detail-${index}`);
    toggle.addEventListener('click',()=>{expandedAccounts.has(account.email) ? expandedAccounts.delete(account.email) : expandedAccounts.add(account.email);renderAccounts(latestData.accounts);body.querySelectorAll('.account-toggle').forEach(b=>{if(b.dataset.account===account.email)b.focus({preventScroll:true});});});
    name.append(toggle,make('small',account.profiles.join(' · ') || 'Standby','profile-label'));tr.append(name);
    const status=make('td');status.title=account.status_reason || '';status.append(make('span',statusLabel(account),'state'));tr.append(status);
    for(const key of ['session','weekly','fable']) {
      const w=windowFor(account,key), cell=make('td',undefined,`usage-cell window${!w?.fresh ? ' stale' : w.used>=w.threshold ? ' warn' : ''}`);
      cell.append(make('b',w?.used==null ? 'Unknown' : `${w.used}%`));
      if(w?.used!=null) {const bar=make('progress',undefined,'meter');bar.max=100;bar.value=w.used;bar.setAttribute('aria-label',`${account.email} ${key} ${w.used}% used${w.fresh ? '' : ', stale'}`);cell.append(bar);}
      if(w && !w.fresh && w.used!=null) cell.append(make('small','Stale'));
      tr.append(cell);
    }
    for(const kind of ['session','weekly']) {
      const w=windowFor(account,kind), rate=w?.fresh && w.rate_per_minute!=null ? w.rate_per_minute*60 : null;
      const cell=make('td',rate==null ? 'No estimate' : `${rate.toFixed(1)} pp/h`,'rate-cell');
      if(rate!=null) cell.append(make('small',`${Math.round(w.sample_minutes)}m sample`));
      tr.append(cell);
    }
    for(const kind of ['session','weekly']) {
      const reset=windowFor(account,kind)?.reset;
      const resetCell=make('td',undefined,'reset-cell');resetCell.append(make('span',reset ? clock(reset) : 'Not started / unknown'));
      if(reset) resetCell.append(make('small',reset*1000<=Date.now() ? 'Refresh needed' : `in ${duration((reset*1000-Date.now())/60000)}`));
      tr.append(resetCell);
    }
    const banked=make('td',String(account.banked_resets ?? 'Unknown'),'banked-cell');
    banked.title=account.banked_resets_observed_at ? `Recorded ${clock(account.banked_resets_observed_at)} · ${account.banked_resets_source || 'inventory'} · explicit authorization required to use` : 'Count not recorded; unknown is not zero';
    tr.append(banked);
    const expires=make('td',account.cancelled===false ? 'N/A' : account.expiration_date || 'Not recorded','reset-cell');
    expires.title=account.cancelled===false ? 'No cancellation marked in the ledger' : 'Recorded cancellation end date from the ledger; paid-through date should be verified before expiry';
    tr.append(expires);
    tr.append(make('td',account.state.endsWith('unknown') ? 'Verify capacity' : account.minutes_to_first_threshold===0 && !activeAccount(account) ? 'At guard' : duration(account.minutes_to_first_threshold),'switch-cell'));
    tr.append(make('td',String(account.process_count ?? '?'),'numeric'));
    const verified=make('td',age(account.age_seconds),'verified-cell');verified.title=clock(account.observed_at);tr.append(verified);body.append(tr);
    const detail=make('tr',undefined,'account-detail');detail.id=`account-detail-${index}`;detail.hidden=!expandedAccounts.has(account.email);
    const cell=make('td');cell.colSpan=columns.length;
    const card=make('div',undefined,'account-detail-content');
    if(account.status_reason) card.append(make('p',account.status_reason,'verification'));
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

    card.append(make('p',`Banked resets: ${account.banked_resets ?? 'Unknown'}. ${account.banked_resets_observed_at ? 'Recorded '+clock(account.banked_resets_observed_at)+' from '+(account.banked_resets_source || 'inventory')+'. ' : ''}Blank records are unknown. Use requires explicit authorization; banked resets are excluded from runway.`, 'verification'));
    const tasks=(latestData?.obligations || []).filter(o=>account.profiles.some(p=>o.id===p || o.id.startsWith(p+'_')));
    for(const task of tasks) card.append(make('p',`${task.id}: ${task.reason}`,'verification'));
    cell.append(card);detail.append(cell);body.append(detail);
  }
  if(focusedEmail) body.querySelectorAll('.account-toggle').forEach(b=>{if(b.dataset.account===focusedEmail)b.focus({preventScroll:true});});
}
initAccountTable();


function metricsInto(id,items) {
  const target=$(id);target.replaceChildren();
  for(const [label,value,note] of items){const n=make('div',undefined,'health-metric');n.append(make('span',label),make('b',value),make('small',note));target.append(n);}
}
function renderOutlook(data) {
  const f=data.fleet_forecast;
  if(!f || f.state!=='scenario') {metricsInto('outlook-metrics',[]);$('outlook-note').textContent='Fleet outlook needs fresh, positive session and weekly burn measurements across all active accounts.';return;}
  const gap=n=>n==null ? 'Beyond 7 days' : duration(n);
  metricsInto('outlook-metrics',[
    ['First modeled capacity gap',gap(f.combined_gap_minutes),'Includes scheduled five-hour and weekly resets'],
    ['If burn rises 25%',gap(f.faster_gap_minutes),'Sensitivity scenario, not a confidence interval'],
    ['Weekly / model quota horizon',gap(f.weekly_gap_minutes),'Ignores five-hour limits; includes weekly resets'],
    ['Weekly at 25% faster burn',gap(f.weekly_faster_gap_minutes),'Long-term constraint if this pace persists']]);
  const when=f.combined_gap_minutes==null ? 'No gap modeled within seven days.' : `First modeled gap around ${clock(data.served_at+f.combined_gap_minutes*60)}.`;
  $('outlook-note').textContent=`Conditional forecast: ${when} ${f.accounts_included} measured accounts, ${f.unknown_accounts} unknown excluded; ${Math.round(f.sample_minutes)}-minute rate sample. ${f.assumption} A short sample projected days ahead is a scenario, not guaranteed coverage. Recomputed with each measurement.`;
}
function renderThroughput(t) {
  if(!t || t.state!=='ready') {metricsInto('throughput-metrics',[]);$('throughput-note').textContent=t?.state==='loading' ? 'Indexing the last hour of local Claude logs…' : 'Local token measurements unavailable.';return;}
  const w=t.windows.find(w=>w.minutes===15), hour=t.windows.find(w=>w.minutes===60);
  const compact=n=>new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1}).format(n);
  const dollars=w=>w.unpriced_models.length ? 'Partially priced' : Math.abs(w.usd_per_hour_high-w.usd_per_hour_low)<.01 ? `$${w.usd_per_hour_low.toFixed(0)}/h` : `$${w.usd_per_hour_low.toFixed(0)}–${w.usd_per_hour_high.toFixed(0)}/h`;
  metricsInto('throughput-metrics',[
    ['Processed tokens / h',compact(w.processed_per_hour),'Last 15 minutes scaled to an hour; includes cache reads'],
    ['Output tokens / h',compact(w.output_per_hour),'Generated output, including reported thinking'],
    ['API-equivalent / h',dollars(w),'15-minute pace at dated API list prices'],
    ['Last-hour API equivalent',dollars(hour).replace('/h',''),'Actual trailing 60-minute token usage']]);
  $('throughput-note').replaceChildren(document.createTextNode(`${t.roots} launcher directories, including subagents; ${w.requests} unique responses in 15 minutes. Updated ${age(Date.now()/1000-t.checked_at)}. ${t.read_errors ? t.read_errors+' files/directories unreadable; totals may be incomplete. ' : ''}Cached reads are processed tokens, not newly generated text. API equivalent is an estimate, not your subscription bill; excludes server tool fees. Cache-write TTL missing in older logs produces a price range. `));
  const link=make('a',`Anthropic pricing (${t.price_date})`);link.href=t.price_source;link.target='_blank';link.rel='noreferrer';$('throughput-note').append(link);
}

async function refresh() {
  try { const result=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(4000)}); if(!result.ok) throw new Error('Snapshot unavailable'); render(await result.json()); }
  catch(error) { renderThroughput(null);metricsInto('outlook-metrics',[]);$('outlook-note').textContent='Forecast unavailable until fresh dashboard data returns.'; $('error').hidden=false; $('error').textContent='Dashboard data unavailable. Values below may be stale. Retrying automatically.'; $('heartbeat').textContent='Connection lost'; $('heartbeat').className='badge warn'; $('fleet-health').className='fleet-health unknown'; $('health-title').textContent='Live health unavailable'; $('health-verdict').textContent='Connection lost. Previous forecasts are stale.'; $('health-bar').value=0; $('health-scale').replaceChildren(); $('health-metrics').replaceChildren(); $('health-action').textContent='Wait for fresh measurements before relying on a capacity estimate.'; latestData=null; }
  finally { setTimeout(refresh,5000); }
}
refresh();
