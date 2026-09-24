# Setup and operation

Requires Python 3.11+, macOS or Linux, and an installed Claude Code CLI. The collector depends on Claude's native `cachedUsageUtilization` schema; this is an internal format and may change. An unsupported/mismatched cache produces unknown capacity. Authentication and terminal/browser recovery are performed by the agent using available native tools, not by the monitor script.

## Local configuration

Store configuration and state outside the public checkout. Use one shared state directory for all invocations, with restrictive local permissions. Different state directories cannot coordinate ownership. Do not put account names, session identifiers, credentials or telemetry in commits.

```json
{
  "owner": "YOUR_EXISTING_AGENT_SESSION",
  "claude_command": "claude",
  "profiles": {
    "default": {"config_dir": null},
    "secondary": {"config_dir": "~/.claude-secondary"}
  },
  "required_limits": ["session", "weekly"],
  "session_threshold": 80,
  "other_threshold": 85,
  "max_age_seconds": 900,
  "accounts": {
    "primary@example.com": {"eligible": false},
    "secondary@example.com": {"eligible": false}
  },
  "notify_command": []
}
```

Configure each directory only once. `null` is the native default profile (`~/.claude`, cache `~/.claude.json`); explicit directories use `DIRECTORY/.claude.json`. Native `auth status` must identify the account. Configure independently authenticated standby directories if off-launcher accounts need ongoing measurements.

After verifying a subscription remains usable, set its `eligible` field to `true` with a `verified_until` Unix timestamp bounded by that verification or known cancellation date. This is subscription eligibility, not a quota reading. Example addresses deliberately remain ineligible. Add the exact lowercased native scoped model display name to `required_limits` when that model's separate quota matters. A missing required limit blocks selection.

Diagnostic command, from the installed skill directory:

```bash
python3 scripts/quota_watch.py --config /absolute/path/config.local.json --state-dir /absolute/path/state
```

This checks current auth and reads caches, persists diagnostic state, and prints selected quota fields. It does not notify, switch, open a browser, send terminal input, or refresh stale usage. Failed collection does not erase previous account observations; they age into unknown. It does not infer unlimited quota from a missing cache.

## Notifications and scheduling

First configure a supported delivery adapter for the host agent. `notify_command` is an argv list with `{owner}` and `{message}` replacements; no shell is used. For example, a local adapter could accept `['/absolute/path/deliver-to-agent', '--session', '{owner}', '--message', '{message}']`. That path is illustrative: this package does not include a host-specific delivery executable. Use the actual host's documented interface and verify a harmless receipt. The adapter must return zero only when the destination accepted delivery; an agent receipt is stronger evidence than the queue's exit code.

Run with `--notify` only when delivery to this owner is authorized. The script writes `owner.json` on first notifying run, rejects a different owner, and takes a nonblocking OS lock for the entire collection/delivery transaction. Each invocation exits after one pass. Exit 1 includes malformed configuration, a conflicting owner, or an already-running transaction. Notification errors are recorded in state and leave events eligible for retry on the next pass.

Only when the user requests ongoing monitoring, schedule the exact absolute command with launchd, systemd, or their existing scheduler, typically every 180 seconds. Use the same state directory. Test the actual scheduled environment (PATH may differ), exit status, destination receipt and next wake; a manually successful command is not scheduler proof. Do not create another schedule when one exists. The daemon does not require an active continuous agent Goal.

Session-threshold incidents retry after 180 seconds; new severity bands bypass cooldown. Other incidents retry after 600 seconds, stale/verification notices after 1800 seconds. Failed delivery and diagnostic-only runs do not consume one-shot capacity or identity transitions. Before recovery the agent must recheck live state, so old queued notices cannot force an obsolete switch.

## Recovery obligations

`STATE/obligations.json` is an object keyed by a stable recovery identifier:

```json
{
  "profile-secondary-adoption": {
    "state": "adoption_pending",
    "reason": "Native login and quota verified; original running pane has not shown destination identity yet",
    "deadline": 1800000000,
    "evidence": {"pane": "%12", "pid": 12345}
  }
}
```

The example deadline and pane are illustrative, not current. Set a real near-term deadline; refresh the reason after inspection. The monitor emits overdue entries except those marked `recovered` or `cancelled`. Useful states include `draft_preserved`, `waiting_for_safe_prompt`, `adoption_pending`, `adoption_verified_rc_pending`, and `ledger_pending`. The deadline is not permission to destroy input or interrupt work.

The script only reads obligations. The recovery owner updates them atomically, preserving unrelated entries. Do not claim `recovered` from an auth/cache reading alone.

## Transfer or stand down

1. Get a user-authorized transfer; stop new interventions by the predecessor and stop its schedule if it must be retargeted. Preserve its state and work.
2. Confirm no switch transaction is active. Have the successor read the live state and recovery handoff in observer mode.
3. Under `monitor.lock`, atomically change the local configured owner and `owner.json` to the same new identifier. Do not erase cooldowns, observations or obligations. Restart the one schedule if needed.
4. Send a harmless receipt check to the successor, confirm it arrives, then retire the predecessor's ownership. If delivery fails, leave an explicit handoff failure and repair routing before allowing concurrent mutation.

Invoke an observer with: `$claude-quota-watch: Read the current owner and live status; perform one diagnostic check without creating another watch or switching concurrently.`

Invoke a successor with: `$claude-quota-watch: Take over from the existing owner, preserve sessions and drafts, verify delivery, then continue the existing event-driven recovery policy. Keep the continuous Goal paused.`
