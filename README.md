# Claude Quota Watch

An agent skill and a small monitor for keeping existing Claude Code sessions working through account quota changes.

The monitor reads account-bound native usage, checks session and weekly runway, and sends incidents to one configured agent. The skill guides that agent through login, draft preservation, live-session adoption, optional remote-control recovery, and ledger updates. A login succeeding is not enough to declare the work recovered.

**Status: experimental 0.1.0.** The personal workflow that motivated this package was used on a six-profile macOS/tmux setup. This portable extraction has automated contract tests; it has not yet been proven through a complete unattended recovery on a second installation. Browser login challenges and ambiguous terminal state still need an agent or user. The script itself never switches accounts or alters terminals.

## Install the skill

Clone this repository, then copy the self-contained skill directory into your agent's skill directory. For Codex:

```bash
git clone https://github.com/tylerbrianhughes/claude-quota-watch.git
mkdir -p ~/.codex/skills
cp -R claude-quota-watch/skills/claude-quota-watch ~/.codex/skills/
```

If that destination already exists, review or back it up before replacing it. Restart the agent session if necessary to discover the skill. No watcher is installed by this command.

Invoke:

> $claude-quota-watch — Inspect my configured profiles and current owner. Perform one quota check; preserve ongoing sessions and drafts. Do not create another watcher or Goal.

Use the [setup reference](skills/claude-quota-watch/references/setup.md) to configure profiles, verified subscription eligibility, required quota windows, and an optional host-specific notification adapter. Another agent can observe immediately; switching ownership requires an explicit handoff. The package has no hardcoded accounts, sheet identifiers or agent-session destinations.

## Behavior

- Default rotation trigger: 80% five-hour usage; weekly/model-specific threshold: 85%. These are configurable operating defaults, not provider guarantees.
- Missing, stale, reset-expired or account-mismatched quota stays unknown.
- Account-level aggregation exposes multiple launchers sharing capacity. The agent distributes work across verified destinations with sufficient runway.
- One locked state directory and one registered notification owner prevent concurrent monitor transactions. The recovery owner must also avoid overlapping switch interventions.
- Distinct observation history supports consumption forecasts. Failed delivery does not consume transition events; unresolved high-session incidents retry.
- Recovery obligations retain incomplete adoption, real drafts, remote access and ledger work across invocations.
- Resets and refills require explicit user authorization by default, including promotional/free resets.

## Fleet dashboard: no model calls

The bundled local dashboard refreshes every five seconds, reading the monitor's JSON snapshot. It shows account capacity, assigned profiles, process load, sample age, measured percentage-point consumption rates, estimated time to each threshold, resets, monitor heartbeat and pending recovery obligations.

```bash
python3 skills/claude-quota-watch/scripts/dashboard.py \
  --status /absolute/path/state/state.json \
  --obligations /absolute/path/state/obligations.json
```

The account grid sorts by usage, five-hour and weekly resets, banked resets, process count and measurement time. Expand an account for forecast and verification details. To show recorded banked reset counts, add `--banked-resets /path/to/banked-resets.json`:

```json
{"accounts":{"person@example.com":{"count":1,"observed_at":1790298000,"source":"Quota sheet"}}}
```

Counts are read from this local inventory on each refresh. Blank, missing or invalid counts display as unknown, never zero. Keep the inventory updated when the source ledger changes; its observation time is visible in account details. Banked resets are excluded from runway and require explicit authorization to use.

Open http://127.0.0.1:8767. It binds only to loopback and requires no Python dependencies, model calls, CDN or cloud service. The page's five-second refresh does not imply a fresh quota measurement: each reading retains its actual timestamp. Run the deterministic monitor from your scheduler for new measurements; only material incidents need an agent wakeup. The dashboard is read-only and cannot switch accounts or spend resets.

Forecasts use two distinct observations from the same account and window; they expire with the underlying data. They estimate quota use, not API dollars or tokens. Plan percentages are not interchangeable across accounts. Supply `--session-threshold` and `--other-threshold` if your monitor uses nondefault thresholds. See the [architecture](docs/architecture.md).

The top health bar compares the current allocation's measured runway with a selected 1–24 hour work horizon. It explicitly reports when an active account has already crossed its switch guard and no verified spare is ready. It shows the first switch guard, verified standby count, and next five-hour reset on an account whose last observed weekly/model usage is below the allocation guards. Weekly resets are not substituted for that five-hour countdown. It does not add percentages across plans or credit a future reset before verification. Missing or flat rate samples produce unknown coverage; a stale monitor removes the health forecast.

When a single account carries the fleet, a separate scenario estimates how many additional fresh accounts **with that same quota size** would cover the selected horizon at the recent pace. Existing spares, future resets and banked credits are excluded from that scenario; verify them before buying. With multiple active accounts, quota sizes are not inferred and the fresh-account scenario is unavailable. This is a short-window extrapolation, not a promise of monthly capacity.

## Limits

The collector uses an internal Claude cache schema, which can change. It invokes native `claude auth status` and reads selected cache fields; it does not refresh usage automatically, manage tokens, provide an authentication proxy, or implement a notification transport. Stale usage prompts the recovery agent to perform a native refresh. Subscription eligibility is supplied and expires explicitly.

The OS lock covers one monitor transaction, not an entire multi-turn agent intervention. Single-owner discipline and the handoff procedure remain necessary. Separate state directories do not coordinate. A delivery command's success proves queue acceptance only; verify actual receipt on setup and transfer. Process counts are an approximation, not token throughput.

Sheets and other ledgers are optional and operated by the agent with the user's available tools. This repository has no bundled Sheets credentials or integration.

## Development

Python 3.11+, macOS/Linux, standard library only:

```bash
python3 -m unittest discover -s tests -v
```

Tests use synthetic accounts, fake collectors and local notification processes. They do not touch real terminals or subscriptions. Keep local configuration and state outside the checkout; do not attach real account inventories or tokens to issues.

Several independent projects already offer automatic switching. See [related projects](docs/alternatives.md) for overlap with clauth, ccswap, ccswitch and subswapper. This package focuses on the recovery procedure; it does not claim automatic rotation is novel.

MIT licensed. Independent project; not affiliated with Anthropic or OpenAI.

### Independent standby verification

Keep a separate, normally authenticated Claude configuration directory for each subscription, including the account currently carrying work. Rotating launchers must never be the only measurement route. Finish the CLI onboarding once and prove a disposable native `/usage` refresh before registering the route; `auth status` alone is insufficient. Do not copy credentials.

The local fleet adapter now publishes a separate `capacity[email].verification` record (`state`, `reason`, last attempt/result), which the dashboard displays without confusing missing authentication with exhausted quota. Detect a lost standby route even while the active launcher still supplies fresh quota. Size the inference-free refresh batch for the whole inventory: Tyler's eleven-account deployment checks up to four independent standbys per three-minute cycle, refreshing from five minutes old and retaining the fifteen-minute validity cap. Retry failures separately and recheck after natural resets. This adapter scheduling policy is distinct from the public cache-only collector.
