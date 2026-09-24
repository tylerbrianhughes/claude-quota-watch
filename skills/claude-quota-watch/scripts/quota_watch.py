#!/usr/bin/env python3
"""Read native account-bound usage and deliver bounded recovery incidents.

No credential writes, login switching, terminal input, or paid resets.
Python 3.11+, macOS/Linux. Run once from a scheduler; one locked state directory.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

VERSION = "0.1.0"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {} if default is None else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def timestamp(value):
    if value is None:
        return None
    if number(value):
        return value
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp needs a timezone")
    return parsed.timestamp()


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    if not isinstance(config.get("owner"), str) or not config["owner"].strip():
        raise ValueError("Set an explicit owner session identifier")
    if not isinstance(config.get("profiles"), dict) or not config["profiles"]:
        raise ValueError("Configure at least one named launcher profile")
    seen = set()
    for name, profile in config["profiles"].items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("Profile labels must use letters, numbers, underscores or hyphens")
        if not isinstance(profile, dict):
            raise ValueError("Each profile must be an object")
        directory = profile.get("config_dir")
        if directory is not None and (not isinstance(directory, str) or not directory):
            raise ValueError("config_dir must be a path or null for the default profile")
        path = str(Path(directory).expanduser().resolve()) if directory else str(Path.home() / ".claude")
        if path in seen:
            raise ValueError("Register a config directory once, even if multiple launchers use it")
        seen.add(path)
    required = config.get("required_limits", ["session", "weekly"])
    if not isinstance(required, list) or not all(isinstance(x, str) for x in required) or not {"session", "weekly"} <= set(required):
        raise ValueError("required_limits must include session and weekly")
    for key, fallback in (("session_threshold", 80), ("other_threshold", 85), ("max_age_seconds", 900)):
        value = config.get(key, fallback)
        if not number(value) or value <= 0 or ("threshold" in key and value > 100):
            raise ValueError(f"Invalid {key}")
    if not isinstance(config.get("accounts", {}), dict):
        raise ValueError("accounts must map exact emails to eligibility records")
    for entry in config.get("accounts", {}).values():
        if not isinstance(entry, dict):
            raise ValueError("Invalid eligibility entry")
        if entry.get("eligible") is True and not number(entry.get("verified_until")):
            raise ValueError("Eligible accounts need a verified_until Unix timestamp")
    command = config.get("notify_command", [])
    if command and (not isinstance(command, list) or not all(isinstance(x, str) for x in command)):
        raise ValueError("notify_command must be an argv array, never a shell string")
    if not isinstance(config.get("claude_command", "claude"), str):
        raise ValueError("claude_command must be an executable path or name")
    return config


def native_snapshot(data, auth_email):
    account = data.get("oauthAccount", {})
    cache = data.get("cachedUsageUtilization", {})
    if not auth_email or account.get("emailAddress") != auth_email:
        return None
    identity = account.get("accountUuid")
    fetched = cache.get("fetchedAtMs")
    if not identity or cache.get("accountUuid") != identity or not number(fetched):
        return None
    limits = {}
    for item in cache.get("utilization", {}).get("limits", []):
        name = {"session": "session", "weekly_all": "weekly"}.get(item.get("kind"))
        if item.get("kind") == "weekly_scoped":
            model = ((item.get("scope") or {}).get("model") or {}).get("display_name", "")
            name = model.lower().strip() or None
        used = item.get("percent")
        if name and number(used) and 0 <= used <= 100:
            try:
                reset = timestamp(item.get("resets_at"))
            except (ValueError, TypeError, AttributeError):
                continue
            limits[name] = {"used": used, "reset": reset}
    return {"email": auth_email, "account_uuid": identity, "observed_at": fetched / 1000, "limits": limits}


def fresh(item, required, now, max_age):
    observed = item.get("observed_at")
    if not number(observed) or not 0 <= now - observed <= max_age:
        return False
    for name in required:
        limit = item.get("limits", {}).get(name, {})
        used, reset = limit.get("used"), limit.get("reset")
        if not number(used) or not 0 <= used <= 100:
            return False
        if reset is not None and (not number(reset) or reset <= now):
            return False
    return True


def merge_samples(current, previous):
    """Retain account observations after launchers leave, without reviving stale data."""
    merged = copy.deepcopy(previous)
    for email, sample in current.items():
        old = merged.get(email, {})
        if old.get("account_uuid") != sample.get("account_uuid") or sample["observed_at"] > old.get("observed_at", 0):
            merged[email] = copy.deepcopy(sample)
    return merged


def evaluate(config, aliases, samples, previous, obligations, now):
    required = config.get("required_limits", ["session", "weekly"])
    max_age = config.get("max_age_seconds", 900)
    threshold = config.get("session_threshold", 80)
    other = config.get("other_threshold", 85)
    accounts = merge_samples(samples, previous.get("accounts", {}))
    baselines = copy.deepcopy(previous.get("baselines", {}))
    for email, item in accounts.items():
        old = previous.get("accounts", {}).get(email)
        if old and old.get("account_uuid") == item.get("account_uuid") and old.get("observed_at", 0) < item["observed_at"]:
            baselines[email] = old
    capacity, events = {}, []
    registry = config.get("accounts", {})
    emails = set(accounts) | set(registry) | {a["email"] for a in aliases.values() if a.get("email")}
    for email in sorted(emails):
        item = accounts.get(email, {})
        members = {k: a for k, a in aliases.items() if a.get("email") == email}
        active = any(a.get("active", True) for a in members.values())
        eligibility = registry.get(email, {})
        eligible = eligibility.get("eligible") is True and eligibility.get("verified_until", 0) > now
        measured = fresh(item, required, now, max_age)
        usage = {name: item.get("limits", {}).get(name, {}).get("used") for name in required}
        high = measured and any(usage[n] >= (threshold if n == "session" else other) for n in required)
        state = "eligibility_unknown" if not eligible else "quota_unknown" if not measured else "constrained" if high else "available"
        counts = [a.get("process_count") for a in members.values()]
        capacity[email] = {"state": state, "observed_at": item.get("observed_at"), "used": usage,
                           "profiles": list(members), "process_count": sum(counts) if all(number(x) for x in counts) else None,
                           "minimum_headroom": min(100 - usage[n] for n in required) if measured else None}
        if not measured:
            events.append({"kind": "refresh_needed" if active else "standby_verification_needed", "email": email,
                           "reason": "Missing, expired, future-dated or account-mismatched observation; quota unknown"})
        elif active:
            for name in required:
                limit = item["limits"][name]
                used, reset = limit["used"], limit.get("reset")
                old = baselines.get(email, {})
                old_limit = old.get("limits", {}).get(name, {})
                elapsed = (item["observed_at"] - old.get("observed_at", item["observed_at"])) / 60
                runway = None
                if elapsed >= 2 and old.get("account_uuid") == item.get("account_uuid") and old_limit.get("reset") == reset and number(old_limit.get("used")) and used > old_limit["used"]:
                    rate = (used - old_limit["used"]) / elapsed
                    runway = max(0, (95 - used) / rate - (now - item["observed_at"]) / 60)
                if used >= (threshold if name == "session" else other) or (runway is not None and runway <= 15):
                    events.append({"kind": "switch_required", "email": email, "limit": name,
                                   "used": used, "reset": reset, "minutes_to_95": runway})
        if not eligible:
            events.append({"kind": "eligibility_verification_needed", "email": email})
        if state == "available" and previous.get("capacity", {}).get(email, {}).get("state") != "available":
            events.append({"kind": "capacity_available", "email": email})
    for name, alias in aliases.items():
        old_email = previous.get("aliases", {}).get(name, {}).get("email")
        if alias.get("active", True) and not alias.get("email"):
            events.append({"kind": "login_verification_needed", "profile": name})
        elif old_email and old_email != alias.get("email"):
            events.append({"kind": "identity_changed", "profile": name, "old": old_email, "new": alias.get("email")})
    for key, obligation in obligations.items():
        if obligation.get("state") not in ("recovered", "cancelled") and now >= obligation.get("deadline", 0):
            events.append({"kind": "recovery_overdue", "obligation": key, "state": obligation.get("state"), "reason": obligation.get("reason")})
    # A diagnostic or failed notification cannot consume a one-shot transition.
    for event in previous.get("pending_transitions", []):
        relevant = (
            event["kind"] == "capacity_available" and capacity.get(event.get("email"), {}).get("state") == "available"
        ) or (
            event["kind"] == "identity_changed" and aliases.get(event.get("profile"), {}).get("email") == event.get("new")
        )
        if relevant and event not in events:
            events.append(event)
    return {"checked_at": now, "aliases": aliases, "accounts": accounts, "baselines": baselines,
            "capacity": capacity, "events": events}


def event_key(event):
    band = next((x for x in (100, 95, 90, 85, 80) if event.get("used", 0) >= x), 0)
    return json.dumps([event.get(x) for x in ("kind", "email", "profile", "obligation", "state", "new", "limit", "reset")] + [band])


def due(events, delivered, now, session_threshold=80):
    result = []
    for event in events:
        delay = 180 if event["kind"] == "switch_required" and event.get("limit") == "session" and event.get("used", 0) >= session_threshold else 1800 if "verification" in event["kind"] or event["kind"] == "refresh_needed" else 600
        last = delivered.get(event_key(event))
        if last is None or now - last >= delay:
            result.append(event)
    return result


def process_inventory():
    """Return config directories only. Never print a process environment."""
    result = {}
    try:
        rows = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True, timeout=10).splitlines()
        for row in rows:
            parts = row.split(None, 1)
            if len(parts) != 2 or Path(parts[1]).name != "claude":
                continue
            try:
                if sys.platform.startswith("linux"):
                    env = dict(x.split("=", 1) for x in Path(f"/proc/{parts[0]}/environ").read_text().split("\0") if "=" in x)
                elif sys.platform == "darwin":
                    raw = subprocess.check_output(["ps", "eww", "-p", parts[0], "-o", "command="], text=True, timeout=5)
                    env = dict(re.findall(r"(?:^|\s)(CLAUDE_CONFIG_DIR|CLAUDE_QUOTA_PROBE)=(.*?)(?=\s+[A-Za-z_][A-Za-z_0-9]*=|$)", raw))
                else:
                    return None
            except (OSError, subprocess.SubprocessError):
                return None  # Unknown inventory must not be reported as zero load.
            if env.get("CLAUDE_QUOTA_PROBE") == "1":
                continue
            directory = str(Path(env.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser().resolve())
            result[directory] = result.get(directory, 0) + 1
        return result
    except (OSError, subprocess.SubprocessError):
        return None


def collect(config):
    inventory = process_inventory()
    aliases, samples = {}, {}
    for name, profile in config["profiles"].items():
        directory = profile.get("config_dir")
        env = os.environ.copy()
        if directory:
            directory = str(Path(directory).expanduser().resolve())
            env["CLAUDE_CONFIG_DIR"] = directory
            cache_path = Path(directory) / ".claude.json"
        else:
            env.pop("CLAUDE_CONFIG_DIR", None)
            directory = str(Path.home() / ".claude")
            cache_path = Path.home() / ".claude.json"
        email = None
        error = None
        try:
            auth = subprocess.run([config.get("claude_command", "claude"), "auth", "status"], env=env, capture_output=True, text=True, timeout=15)
            data = json.loads(auth.stdout)
            email = data.get("email") if auth.returncode == 0 and data.get("loggedIn") is True else None
            if not isinstance(email, str) or not email.strip():
                email = None
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            error = "auth_status_unavailable"
        count = inventory.get(directory, 0) if inventory is not None else None
        aliases[name] = {"email": email, "process_count": count, "active": count is None or count > 0, "auth_error": error}
        try:
            sample = native_snapshot(read_json(cache_path), email)
        except (OSError, ValueError, TypeError, AttributeError):
            sample = None
        if sample and sample["observed_at"] > samples.get(email, {}).get("observed_at", 0):
            samples[email] = sample
    return aliases, samples


def run_once(config, root, notify=False, collector=collect, runner=subprocess.run, now=None):
    """Caller holds the cross-process lock for this state directory."""
    now = time.time() if now is None else now
    previous = read_json(root / "state.json")
    owner = read_json(root / "owner.json").get("owner")
    if notify and owner not in (None, config["owner"]):
        raise ValueError("Another owner is registered; complete an explicit handoff first")
    if notify and not config.get("notify_command"):
        raise ValueError("--notify requires an explicit notify_command")
    aliases, samples = collector(config)
    result = evaluate(config, aliases, samples, previous, read_json(root / "obligations.json"), now)
    delivered = previous.get("delivered", {})
    pending = due(result["events"], delivered, now, config.get("session_threshold", 80))
    result["delivered"] = dict(delivered)
    result["notification_succeeded"] = False
    result["pending_transitions"] = [e for e in result["events"] if e["kind"] in ("capacity_available", "identity_changed")]
    # Persist evidence before any potentially failing external notification.
    atomic_json(root / "state.json", result)
    if notify:
        atomic_json(root / "owner.json", {"owner": config["owner"]})
    if notify and pending:
        message = ("Use $claude-quota-watch for ONE bounded intervention. Read " + str(root / "state.json") +
                   ". Recheck live state, discard obsolete events, preserve sessions/drafts/goals, verify live adoption, "
                   "and keep any continuous Goal paused. No paid resets without explicit authorization. Incidents: " + json.dumps(pending))
        argv = [part.replace("{owner}", config["owner"]).replace("{message}", message) for part in config["notify_command"]]
        try:
            outcome = runner(argv, capture_output=True, text=True, timeout=20)
            result["notification_succeeded"] = outcome.returncode == 0
        except (OSError, subprocess.SubprocessError) as exc:
            result["notification_error"] = type(exc).__name__
        if result["notification_succeeded"]:
            for event in pending:
                result["delivered"][event_key(event)] = now
            result["pending_transitions"] = [e for e in result["pending_transitions"] if e not in pending]
    atomic_json(root / "state.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--notify", action="store_true", help="Deliver to the explicitly configured owner; otherwise diagnostic only")
    args = parser.parse_args()
    config = validate(read_json(args.config))
    root = args.state_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "monitor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_once(config, root, args.notify)
    print(json.dumps({k: result[k] for k in ("checked_at", "capacity", "events", "notification_succeeded")}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"quota-watch: {error}", file=sys.stderr)
        sys.exit(1)
