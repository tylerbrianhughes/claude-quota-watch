"""Conditional equal-capacity fleet simulation; never used to authorize a switch."""
import copy
from datetime import datetime

def simulate(accounts, rates, now, horizon=10080, session=True, speed=1):
    """Minute-step, divisible workload, earliest weekly reset first.

    Full load can be spread across eligible accounts. Unknown future window start
    times begin at first consumption. Only scheduled resets are credited; no banked
    resets. This ideal allocation scenario deliberately excludes switch latency.
    """
    pool=copy.deepcopy(accounts)
    for minute in range(horizon):
        at=now+minute*60
        for a in pool:
            for w in a['windows']:
                if w['reset'] is not None and w['reset']<=at:
                    w['used']=0;w['reset']=None
        demand=1.0
        pool.sort(key=lambda a:next(w['reset'] or float('inf') for w in a['windows'] if w['name']=='weekly'))
        for a in pool:
            if a.get('expires_at') is not None and at>=a['expires_at']:continue
            limits=[w for w in a['windows'] if session or w['name']!='session']
            if any(w['used']>=w['threshold']-1e-9 for w in limits):continue
            shares=[(w['threshold']-w['used'])/(rates.get(w['name'],0)*speed)
                    for w in limits if rates.get(w['name'],0)>0]
            share=min([demand]+shares)
            if share<=0:continue
            for w in limits:
                burn=rates.get(w['name'],0)*speed*share
                if burn and w['reset'] is None:
                    w['reset']=at+(300 if w['name']=='session' else 10080)*60
                w['used']+=burn
            demand-=share
            if demand<1e-9:break
        if demand>1e-9:return minute+(1-demand)
    return None

def forecast(rows,now,monitor_ok):
    active=[r for r in rows if r['profiles'] or (r.get('process_count') or 0)>0]
    base={'state':'unknown','horizon_minutes':10080,
          'assumption':'Equal quota capacity per account and the same model mix after transfer. Ideal instant workload redistribution; scheduled resets must still be verified live. Banked resets excluded. Cancelled accounts are excluded from the start of their recorded expiration day.',
          'unknown_accounts':sum(r['state'].endswith('unknown') for r in rows)}
    if not monitor_ok or not active:return base
    if any(r['state'].endswith('unknown') or any(not w['fresh'] or w['rate_per_minute'] is None for w in r['windows']) for r in active):return base
    rates={}
    for r in active:
        for w in r['windows']:rates[w['name']]=rates.get(w['name'],0)+w['rate_per_minute']
    if rates.get('session',0)<=0 or rates.get('weekly',0)<=0:return base
    eligible=[r for r in rows if not r['state'].endswith('unknown') and all(w['fresh'] for w in r['windows'])]
    # Account for quota consumed since each measurement before simulating.
    pool=copy.deepcopy(eligible)
    for r in pool:
        if r.get('cancelled') and r.get('expiration_date'):
            try:r['expires_at']=datetime.strptime(r['expiration_date'],'%Y-%m-%d').timestamp()
            except ValueError:pass
        for w in r['windows']:
            w['used']=min(100,w['used']+(w['rate_per_minute'] or 0)*max(0,r['age_seconds'])/60)
    return {**base,'state':'scenario','accounts_included':len(pool),'rates_per_hour':{k:v*60 for k,v in rates.items()},
            'sample_minutes':min(w['sample_minutes'] for r in active for w in r['windows'] if w['sample_minutes'] is not None),
            'combined_gap_minutes':simulate(pool,rates,now),
            'faster_gap_minutes':simulate(pool,rates,now,speed=1.25),
            'weekly_gap_minutes':simulate(pool,rates,now,session=False),
            'weekly_faster_gap_minutes':simulate(pool,rates,now,session=False,speed=1.25)}
