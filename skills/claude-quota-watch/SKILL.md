---
name: claude-quota-watch
description: Monitor Claude Code account capacity and recover existing terminal sessions through quota-related account switches. Use for configured multi-account launcher profiles, stale quota incidents, and recovery handoffs; supports an explicit owner and event-driven monitoring.
---

# Claude Quota Watch

Keep existing work running on verified capacity. Account login, quota availability, live-session adoption, remote access, and goal continuity are separate claims. A successful login alone does not close an incident.

## Entry and ownership

Read the user's request and the local configuration, `owner.json`, `state.json`, and `obligations.json`. If their location is unknown, discover an existing installation before creating one. For setup or handoff, read [references/setup.md](references/setup.md).

Default to **one bounded intervention**. Do not create a Goal, timer, second watcher, or competing switching owner merely because this skill was invoked. An observer may inspect; account mutations belong to the configured owner. Transfer ownership only within the user's authorized handoff, including a receipt test before retiring the predecessor. Installation does not enable a schedule.

For a fleet dashboard, run `scripts/dashboard.py --status SNAPSHOT --obligations OBLIGATIONS` and open `http://127.0.0.1:8767`. This read-only local server refreshes the page from JSON every five seconds without model calls. It does not start another monitor or make an old measurement fresh. Keep its thresholds aligned with configuration. See [references/setup.md](references/setup.md) for measurement and scheduling behavior.

Honor existing authorization. Rotation authorization covers necessary in-scope login, measurement and recovery work; do not repeatedly ask for it. Keep banked/free resets and paid refills behind the user's explicit authorization unless their standing policy expressly permits them. Genuine draft deletion needs authorization that covers that draft.

## Decide from live evidence

1. Recheck account identity and quota before acting on an event. Run the bundled `scripts/quota_watch.py --config CONFIG --state-dir STATE` for diagnostics. It reads native caches and `claude auth status`; it does **not** refresh quota by itself. A stale cache remains unknown. Use the installed native `/usage` procedure in an isolated disposable probe to obtain a fresh reading when needed; mark probes with `CLAUDE_QUOTA_PROBE=1`, and clean up only the probe you created. If the local CLI lacks this cache format, report an unsupported source rather than inventing a reading.
2. Require matching live auth email, OAuth account UUID, cache UUID, and a recent timestamp. Check session, weekly, and each configured model-specific limit. A passed reset makes the old reading stale; it does not prove renewed capacity. Login failure and unknown quota are not exhaustion.
3. By default, initiate rotation at **80% five-hour usage**, including a window near reset. Independently constrain weekly/model-specific use at **85%**. Honor configured thresholds. Measured rapid consumption may justify earlier rotation; forecasts require distinct samples from the same account and window. Act promptly on fresh evidence, while preserving the running session.
4. Inventory live processes and tmux panes, including work sharing the same account through different launchers. Process counts are a rough load signal, not a count of model calls or subagents. Select a verified eligible account with runway in every required window; prefer a less-loaded account when it has sufficient runway. Keep independently authenticated standby routes where supported. A cancelled, unverified or 99%-used account is not a healthy destination just because its session counter is low.
5. If the live check shows no action is needed, acknowledge the incident and end without browser or spreadsheet work. Otherwise finish the bounded intervention or record the concrete unresolved obligation with a deadline and evidence; repeated reminders are not recovery.

## Standby measurements

Keep an independent, fixed-account login route for each subscription so switching the
last work profile away does not strand its measurements. Use ordinary profile-scoped
OAuth, complete native first-run onboarding, and prove `/usage` works in a disposable
probe before registering the route. Auth success alone does not prove unattended
refresh works. Never copy credentials or use a busy work pane for standby polling.

Size the installed refresh batch and cadence to cover the fleet within the source's
freshness window. Report missing login, unfinished onboarding, failed refresh and
scheduled refresh separately from capacity. Alert on a broken standby route even
while a work profile still supplies fresh readings. The bundled collector reads
caches; unattended native refresh requires the installed local adapter.

Time to the first switch is not total fleet coverage. When a qualifying natural
reset precedes that switch, show a potential bridge pending verification. Do not
claim a purchase is needed solely because the first switch falls inside the work
block; future resets and spare accounts still need measurement and allocation.

## Switch and recover

- Capture the target profile, exact account, pane/PID, session identifier, current work/goal, real draft and queued input before mutation. Use configured native account login or an already-approved backend. Confirm the rendered account identity before OAuth authorization. Do not copy bearer tokens between profiles or print credentials, callback codes, or whole process environments.
- Preserve long-running processes. Do not restart, kill or suspend them merely to make an identity change appear complete. If this CLI version cannot adopt a changed login in place, report that limit and use an explicitly authorized resumption procedure with a saved session identifier.
- After login, remeasure native quota and inspect the **same running process**. New work using the destination account, a changed live account display, or equivalent native evidence establishes adoption. Auth status by itself does not. If blocked work is idle at a safe prompt, send the smallest authorized quota-clear/retry instruction and verify useful work resumed.
- Inspect styled prompt state: a dim suggestion is not necessarily a draft. Preserve genuine draft, feedback, queued message and duplicate-command contents. For an authorized clear, verify it is the named input. Never send `/rc`, `/login` or a recovery instruction into a nonempty prompt. Before Enter, inspect the full command. Background agents alone do not make an otherwise idle, empty main prompt unsafe; active model work or queued input does.
- If remote access is part of this user's workflow, reconnect it at a safe prompt and verify the resulting URL. An adopted account with pending remote access is `adoption_verified_rc_pending`, not a failed switch. Do not send an old remote URL as fresh evidence.
- Preserve the original Goal text. Do not use `/goal pause` as a generic pause mechanism: some clients treat `pause` as the new objective. A duplicated original-goal command is not safe to submit blindly. Restore an accidentally replaced goal only after inspecting the saved objective and current prompt, without duplicating running work.
- Resolve stale obligations when evidence changes. Record actual identity, quota timestamp, adoption evidence, remote-access state and the remaining action. See [references/setup.md](references/setup.md) for the obligation schema. Close only when the requested recovery contract is satisfied.

## Ledger and handoff

If a ledger is configured, synchronize it after a switch using verified values and observation times. Read current headers; do not assume fixed columns or overwrite cancellation dates, banked resets or unrelated notes. Read back changed cells. A failed sheet write leaves `ledger_pending`; it does not undo a verified recovery.

For a successor, leave the owner, configuration/state locations, profile/account map, active pane/PID/session mapping, authorization boundaries, original goals, unresolved drafts and recovery obligations. Do not place tokens, private account inventories or live telemetry into a public repository. Explain precisely what was verified and what remains pending.
