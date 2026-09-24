const $ = id => document.getElementById(id);
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const duration = minutes => minutes === null ? 'No estimate' : minutes < 1 ? 'Now' : minutes < 60 ? `${Math.round(minutes)} min` : `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`;
const clock = seconds => seconds == null ? 'Unknown' : new Date(seconds * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const age = seconds => seconds == null ? 'Never measured' : seconds < 0 ? 'Clock mismatch' : seconds < 60 ? `${Math.floor(seconds)}s old` : `${Math.floor(seconds / 60)}m old`;
function render(data) {
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
  catch(error) { $('error').hidden=false; $('error').textContent='Dashboard data unavailable. Values below may be stale. Retrying automatically.'; $('heartbeat').textContent='Connection lost'; $('heartbeat').className='badge warn'; }
  finally { setTimeout(refresh,5000); }
}
refresh();
