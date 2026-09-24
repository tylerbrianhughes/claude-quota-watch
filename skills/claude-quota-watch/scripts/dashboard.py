#!/usr/bin/env python3
"""Serve an existing quota snapshot on loopback. No model/API calls or mutations."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from quota_watch import number, timestamp, read_json

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def epoch(value):
    try:
        return timestamp(value)
    except (ValueError, AttributeError, TypeError):
        return None


def fleet_health(rows, now, monitor_ok):
    """Current allocation runway; never add percentages across different accounts.

    Fresh-account scenarios are available only when one account carries the fleet,
    so its measured rates define an unambiguous same-size reference account.
    Natural resets are opportunities to verify, not credited future capacity.
    """
    active = [r for r in rows if r["profiles"] or (r.get("process_count") or 0) > 0]
    ready = [r for r in rows if r not in active and r["state"] == "available"]
    unknown = [r for r in rows if r["state"].endswith("unknown")]
    forecasts = []
    incomplete = []
    for row in active:
        windows = row["windows"]
        if (row["state"].endswith("unknown") or not windows
                or any(not w["fresh"] or w["rate_per_minute"] is None for w in windows)):
            incomplete.append(row["email"])
            continue
        # Do not count a scheduled reset until a fresh post-reset sample exists.
        candidates = [w for w in windows if w["minutes_to_threshold"] is not None]
        if not candidates:
            incomplete.append(row["email"])
            continue
        limiting = min(candidates, key=lambda w: w["minutes_to_threshold"])
        forecasts.append({"email": row["email"], "window": limiting["name"],
                          "minutes": limiting["minutes_to_threshold"]})
    bottleneck = min(forecasts, key=lambda f: f["minutes"]) if forecasts else None
    complete = monitor_ok and bool(active) and not incomplete
    runway = bottleneck["minutes"] if bottleneck and complete else None
    reached = [{"email": r["email"], "window": w["name"], "minutes": 0}
               for r in active for w in r["windows"]
               if w["fresh"] and w["used"] >= w["threshold"]]
    if reached and monitor_ok:
        runway, bottleneck = 0, reached[0]
    fresh_minutes = None
    reference = None
    if complete and len(active) == 1:
        reference = active[0]["email"]
        durations = [w["threshold"] / w["rate_per_minute"]
                     for w in active[0]["windows"] if w["rate_per_minute"] > 0]
        fresh_minutes = min(durations) if durations else None
    # This metric is specifically a five-hour reset with weekly/model headroom.
    # Old readings may identify a potential reset, but cannot verify its capacity.
    opportunities = []
    for row in rows:
        if row["state"] == "eligibility_unknown":
            continue
        for window in row["windows"]:
            if window["name"] != "session":
                continue
            if not window["reset"] or window["reset"] <= now:
                continue
            others = [w for w in row["windows"] if w is not window]
            if not any(w["name"] == "weekly" for w in others):
                continue
            if any(w["used"] is None or w["used"] >= w["threshold"]
                    or (w["reset"] is not None and w["reset"] <= now) for w in others):
                continue
            if window["used"] is None:
                continue
            opportunities.append({"email": row["email"], "at": window["reset"],
                                  "minutes": (window["reset"] - now) / 60,
                                  "weekly_used": next(w["used"] for w in others if w["name"] == "weekly"),
                                  "verification_required": True})
    next_reset = min(opportunities, key=lambda x: x["at"]) if opportunities else None
    return {"runway_minutes": runway, "bottleneck": bottleneck,
            "active_accounts": len(active), "ready_spares": len(ready),
            "unknown_accounts": len(unknown), "incomplete_accounts": incomplete,
            "fresh_account_minutes": fresh_minutes, "reference_account": reference,
            "sample_minutes": min((w["sample_minutes"] for r in active for w in r["windows"]
                                   if w["sample_minutes"] is not None), default=None),
            "next_potential_reset": next_reset, "forecast_complete": complete,
            "banked_resets_included": False,
            "assumptions": "Recent measured pace; current allocation; switch at guards. "
            "No future resets, unknown accounts or banked credits counted. "
            "Extra-account scenarios assume a fresh account with the same quota as the reference."}


def dashboard_view(state, now, max_age=900, obligations=None, session_threshold=80, other_threshold=85):
    """Support both this package's state and the original six-profile monitor."""
    checked = epoch(state.get("checked_at"))
    heartbeat_age = now - checked if checked is not None else None
    monitor_ok = heartbeat_age is not None and 0 <= heartbeat_age <= 600
    rows = []
    baselines = state.get("baselines", state.get("rate_baselines", {}))
    for email in sorted(set(state.get("capacity", {})) | set(state.get("accounts", {}))):
        account = state.get("accounts", {}).get(email, {})
        capacity = state.get("capacity", {}).get(email, {})
        old = baselines.get(email, {})
        observed = epoch(account.get("observed_at", capacity.get("observed_at")))
        age = now - observed if observed is not None else None
        timely = age is not None and 0 <= age <= max_age
        windows = []
        limits = account.get("limits", {})
        names = list(dict.fromkeys(["session", "weekly"] + list(capacity.get("used", {})) + list(limits)))
        for name in names:
            limit = limits.get(name, {})
            used, reset = limit.get("used"), epoch(limit.get("reset"))
            valid = timely and number(used) and 0 <= used <= 100 and limit.get("fresh", True) and (reset is None or reset > now)
            threshold = session_threshold if name == "session" else other_threshold
            rate = None
            baseline_at = epoch(old.get("observed_at"))
            prior = old.get("limits", {}).get(name, {})
            if (valid and baseline_at is not None and 120 <= observed - baseline_at <= 1800
                    and old.get("account_uuid") == account.get("account_uuid")
                    and account.get("account_uuid") and epoch(prior.get("reset")) == reset
                    and number(prior.get("used")) and used >= prior["used"]):
                rate = (used - prior["used"]) / ((observed - baseline_at) / 60)
            eta = max(0, (threshold - used) / rate - age / 60) if rate and valid else 0 if valid and used >= threshold else None
            reset_first = eta is not None and reset is not None and reset < now + eta * 60
            windows.append({"name": name, "used": used if number(used) else None,
                            "fresh": bool(valid), "reset": reset, "threshold": threshold,
                            "rate_per_minute": rate, "minutes_to_threshold": eta,
                            "reset_before_threshold": reset_first,
                            "sample_minutes": (observed-baseline_at)/60 if rate is not None else None,
                            "previous_used": prior.get("used") if rate is not None else None})
        status = capacity.get("state", "quota_unknown")
        if not all(x["fresh"] for x in windows):
            status = "quota_unknown" if status != "eligibility_unknown" else status
        elif status == "available" and any(x["used"] >= x["threshold"] for x in windows):
            status = "constrained"
        profiles = capacity.get("profiles", [name for name, a in state.get("aliases", {}).items() if a.get("email") == email])
        candidates = [x["minutes_to_threshold"] for x in windows if x["minutes_to_threshold"] is not None and not x["reset_before_threshold"]]
        rows.append({"email": email, "state": status, "profiles": profiles,
                     "verification": capacity.get("verification"),
                     "process_count": capacity.get("process_count"), "observed_at": observed,
                     "age_seconds": age, "windows": windows,
                     "minutes_to_first_threshold": min(candidates) if candidates else None})
    rows.sort(key=lambda r: (not bool(r["profiles"]), r["email"]))
    tasks = obligations if obligations is not None else state.get("recovery_obligations", {})
    pending = [{"id": key, "state": item.get("state"), "reason": item.get("reason"),
                "deadline": item.get("deadline"), "overdue": number(item.get("deadline")) and item["deadline"] <= now}
               for key, item in tasks.items() if item.get("state") not in ("recovered", "cancelled")]
    return {"served_at": now, "checked_at": checked, "monitor_ok": monitor_ok,
            "monitor_age_seconds": heartbeat_age, "accounts": rows, "obligations": pending,
            "health": fleet_health(rows, now, monitor_ok),
            "events": state.get("events", []), "notification_succeeded": state.get("notification_succeeded", state.get("queued")),
            "notification_error": state.get("notification_error"), "page_refresh_seconds": 5,
            "measurement_max_age_seconds": max_age, "session_threshold": session_threshold,
            "other_threshold": other_threshold}


def handler_for(status_path, obligations_path=None, max_age=900, session_threshold=80, other_threshold=85):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Loopback binding plus Host validation prevents DNS rebinding reads.
            if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == "/api/status":
                try:
                    state = read_json(status_path)
                    obligations = read_json(obligations_path) if obligations_path else None
                    payload = dashboard_view(state, time.time(), max_age, obligations, session_threshold, other_threshold)
                    body = json.dumps(payload, allow_nan=False).encode()
                except (OSError, ValueError, TypeError, AttributeError):
                    self.respond(503, b'{"error":"Snapshot unavailable or invalid; retrying"}', "application/json")
                    return
                self.respond(200, body, "application/json")
            elif path in ("/", "/dashboard.js", "/dashboard.css"):
                name = "dashboard.html" if path == "/" else path[1:]
                mime = {"dashboard.html": "text/html", "dashboard.js": "text/javascript", "dashboard.css": "text/css"}[name]
                self.respond(200, (ASSETS / name).read_bytes(), mime)
            else:
                self.send_error(404)

        def respond(self, code, body, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--obligations", type=Path)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--max-age", type=int, default=900)
    parser.add_argument("--session-threshold", type=float, default=80)
    parser.add_argument("--other-threshold", type=float, default=85)
    args = parser.parse_args()
    if args.max_age <= 0 or not 0 < args.session_threshold <= 100 or not 0 < args.other_threshold <= 100:
        parser.error("Use a positive age and thresholds between 0 and 100")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.status.expanduser(), args.obligations.expanduser() if args.obligations else None, args.max_age, args.session_threshold, args.other_threshold))
    print(f"Quota fleet dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
