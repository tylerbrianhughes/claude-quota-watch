import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "skills/claude-quota-watch/scripts/quota_watch.py"
spec = importlib.util.spec_from_file_location("watch", SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
NOW = 1800000000
A, B = "one@example.com", "two@example.com"


def config():
    return {"owner": "test-owner", "profiles": {"primary": {"config_dir": None}},
            "accounts": {A: {"eligible": True, "verified_until": NOW + 86400},
                         B: {"eligible": True, "verified_until": NOW + 86400}},
            "notify_command": ["fake-delivery", "{owner}", "{message}"]}


def sample(email=A, session=20, weekly=30, observed=NOW, reset=NOW + 3600):
    return {"email": email, "account_uuid": email, "observed_at": observed,
            "limits": {"session": {"used": session, "reset": reset},
                       "weekly": {"used": weekly, "reset": NOW + 86400}}}


def aliases(email=A, count=1):
    return {"primary": {"email": email, "process_count": count, "active": count is None or count > 0}}


class DecisionTests(unittest.TestCase):
    def evaluate(self, item=None, **kwargs):
        return w.evaluate(kwargs.pop("config", config()), kwargs.pop("aliases", aliases()),
                          {A: item or sample()}, kwargs.pop("previous", {}),
                          kwargs.pop("obligations", {}), kwargs.pop("now", NOW))

    def test_80_percent_triggers_even_near_reset(self):
        for reset in (NOW + 1, NOW + 3600):
            for used in (79, 80, 81):
                with self.subTest(reset=reset, used=used):
                    result = self.evaluate(sample(session=used, reset=reset))
                    switches = [e for e in result["events"] if e["kind"] == "switch_required"]
                    self.assertEqual(bool(switches), used >= 80)
                    self.assertEqual(result["capacity"][A]["state"], "constrained" if used >= 80 else "available")

    def test_weekly_independent_of_fresh_session(self):
        result = self.evaluate(sample(session=0, weekly=99))
        self.assertEqual(result["capacity"][A]["state"], "constrained")
        self.assertTrue(any(e.get("limit") == "weekly" for e in result["events"]))

    def test_stale_future_or_reset_expired_is_unknown(self):
        for item in (sample(observed=NOW - 901), sample(observed=NOW + 1), sample(reset=NOW)):
            with self.subTest(item=item):
                result = self.evaluate(item)
                self.assertEqual(result["capacity"][A]["state"], "quota_unknown")
                self.assertFalse(any(e["kind"] == "switch_required" for e in result["events"]))

    def test_missing_model_limit_is_unknown(self):
        cfg = config()
        cfg["required_limits"] = ["session", "weekly", "model-x"]
        self.assertEqual(self.evaluate(config=cfg)["capacity"][A]["state"], "quota_unknown")
        item = sample()
        item["limits"]["model-x"] = {"used": 85, "reset": NOW + 60}
        self.assertEqual(self.evaluate(item, config=cfg)["capacity"][A]["state"], "constrained")

    def test_null_session_reset_allowed_only_with_fresh_measurement(self):
        self.assertEqual(self.evaluate(sample(reset=None))["capacity"][A]["state"], "available")
        self.assertEqual(self.evaluate(sample(reset=None, observed=NOW-901))["capacity"][A]["state"], "quota_unknown")

    def test_eligibility_expires_and_unknown_standby_remains(self):
        cfg = config()
        cfg["accounts"][A]["verified_until"] = NOW
        result = self.evaluate(config=cfg)
        self.assertEqual(result["capacity"][A]["state"], "eligibility_unknown")
        self.assertEqual(result["capacity"][B]["state"], "quota_unknown")

    def test_load_aggregated_and_unknown_not_zero(self):
        members = aliases()
        members["secondary"] = {"email": A, "process_count": 4, "active": True}
        self.assertEqual(self.evaluate(aliases=members)["capacity"][A]["process_count"], 5)
        members["secondary"]["process_count"] = None
        self.assertIsNone(self.evaluate(aliases=members)["capacity"][A]["process_count"])

    def test_off_launcher_sample_retained_but_ages(self):
        previous = self.evaluate()
        next_result = w.evaluate(config(), {}, {}, previous, {}, NOW + 901)
        self.assertEqual(next_result["accounts"][A], previous["accounts"][A])
        self.assertEqual(next_result["capacity"][A]["state"], "quota_unknown")

    def test_older_sample_cannot_replace_newer(self):
        self.assertEqual(w.merge_samples({A: sample(observed=NOW-10)}, {A: sample()})[A]["observed_at"], NOW)

    def test_distinct_samples_keep_forecast_on_repeated_cache(self):
        previous = self.evaluate(sample(session=20, observed=NOW-600), now=NOW-600)
        latest = self.evaluate(sample(session=70), previous=previous)
        self.assertEqual(next(e for e in latest["events"] if e.get("limit") == "session")["minutes_to_95"], 5)
        again = self.evaluate(sample(session=70), previous=latest, now=NOW+120)
        self.assertEqual(next(e for e in again["events"] if e.get("limit") == "session")["minutes_to_95"], 3)

    def test_reset_change_does_not_forecast(self):
        previous = self.evaluate(sample(session=20, observed=NOW-600, reset=NOW+60), now=NOW-600)
        result = self.evaluate(sample(session=70), previous=previous)
        self.assertFalse(any(e["kind"] == "switch_required" for e in result["events"]))

    def test_failed_auth_not_exhaustion(self):
        result = self.evaluate(aliases=aliases(email=None))
        self.assertTrue(any(e["kind"] == "login_verification_needed" for e in result["events"]))
        self.assertFalse(any(e["kind"] == "switch_required" for e in result["events"]))

    def test_overdue_recovery_is_not_auth_success(self):
        obligations = {"pane": {"state": "adoption_pending", "deadline": NOW, "reason": "Waiting on live pane"}}
        self.assertTrue(any(e["kind"] == "recovery_overdue" for e in self.evaluate(obligations=obligations)["events"]))
        obligations["pane"]["state"] = "recovered"
        self.assertFalse(any(e["kind"] == "recovery_overdue" for e in self.evaluate(obligations=obligations)["events"]))


class NativeTests(unittest.TestCase):
    def data(self):
        return {"oauthAccount": {"emailAddress": A, "accountUuid": "uuid-a"},
                "cachedUsageUtilization": {"accountUuid": "uuid-a", "fetchedAtMs": NOW*1000,
                "utilization": {"limits": [
                    {"kind": "session", "percent": 0, "resets_at": None},
                    {"kind": "weekly_all", "percent": 31, "resets_at": NOW+86400},
                    {"kind": "weekly_scoped", "scope": {"model": {"display_name": "Model-X"}}, "percent": 3}
                ]}}}

    def test_native_identity_binding_and_scoped_limit(self):
        data = self.data()
        result = w.native_snapshot(data, A)
        self.assertEqual(result["limits"]["model-x"]["used"], 3)
        self.assertIsNone(w.native_snapshot(data, B))
        data["cachedUsageUtilization"]["accountUuid"] = "other"
        self.assertIsNone(w.native_snapshot(data, A))

    def test_invalid_percent_or_timestamp_not_capacity(self):
        data = self.data()
        for percent in (True, float("nan"), 101, "30"):
            data["cachedUsageUtilization"]["utilization"]["limits"][0]["percent"] = percent
            self.assertNotIn("session", w.native_snapshot(data, A)["limits"])
        self.assertRaises(ValueError, w.timestamp, "2027-01-01T00:00:00")

    def test_process_probe_marker_is_exact(self):
        with patch.object(w.sys, "platform", "darwin"), patch.object(w.subprocess, "check_output", side_effect=[
            "10 claude\n11 claude\n12 claude\n13 unrelated\n",
            "claude CLAUDE_QUOTA_PROBE=1 CLAUDE_CONFIG_DIR=/tmp/a SECRET=redacted",
            "claude CLAUDE_QUOTA_PROBE=10 CLAUDE_CONFIG_DIR=/tmp/a SECRET=redacted",
            "claude CLAUDE_CONFIG_DIR=/tmp/b SECRET=redacted"
        ]):
            result = w.process_inventory()
        self.assertEqual(result, {str(Path('/tmp/a').resolve()): 1, str(Path('/tmp/b').resolve()): 1})

    def test_process_read_failure_is_unknown(self):
        with patch.object(w.subprocess, "check_output", side_effect=OSError()):
            self.assertIsNone(w.process_inventory())

    def test_collector_uses_native_auth_and_cache_without_live_accounts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            w.atomic_json(root / ".claude.json", self.data())
            cfg = config()
            cfg["profiles"] = {"test": {"config_dir": str(root)}}
            with patch.object(w, "process_inventory", return_value={str(root): 2}), patch.object(w.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps({"loggedIn": True, "email": A}))):
                actual_aliases, samples = w.collect(cfg)
            self.assertEqual(actual_aliases["test"]["process_count"], 2)
            self.assertEqual(samples[A]["limits"]["weekly"]["used"], 31)
            with patch.object(w, "process_inventory", return_value={}), patch.object(w.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '[1]')):
                actual_aliases, samples = w.collect(cfg)
            self.assertIsNone(actual_aliases["test"]["email"])
            self.assertEqual(samples, {})


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = config()

    def run_pass(self, notify=False, code=0, now=NOW, email=A):
        return w.run_once(self.cfg, self.root, notify,
                          collector=lambda _: (aliases(email), {email: sample(email=email)}),
                          runner=lambda *a, **k: subprocess.CompletedProcess(a, code), now=now)

    def test_failed_delivery_and_diagnostic_keep_capacity_transition(self):
        first = self.run_pass()
        self.assertEqual(first["delivered"], {})
        failed = self.run_pass(notify=True, code=1, now=NOW+1)
        self.assertFalse(failed["notification_succeeded"])
        delivered = self.run_pass(notify=True, now=NOW+2)
        self.assertTrue(any(e["kind"] == "capacity_available" for e in delivered["events"]))
        self.assertEqual(delivered["pending_transitions"], [])
        self.assertFalse(self.run_pass(notify=True, now=NOW+3)["notification_succeeded"])

    def test_identity_transition_survives_failure_and_obsolete_one_drops(self):
        self.run_pass(notify=True)
        self.run_pass(notify=True, code=1, now=NOW+1, email=B)
        delivered = self.run_pass(notify=True, now=NOW+2, email=B)
        self.assertTrue(any(e["kind"] == "identity_changed" for e in delivered["events"]))
        self.run_pass(notify=True, code=1, now=NOW+3, email=A)
        back = self.run_pass(notify=True, now=NOW+4, email=B)
        self.assertFalse(any(e["kind"] == "identity_changed" and e["new"] == A for e in back["events"]))

    def test_notification_timeout_is_retryable(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired('fake', 20)
        result = w.run_once(self.cfg, self.root, True, collector=lambda _: (aliases(), {A: sample()}), runner=timeout, now=NOW)
        self.assertEqual(result["notification_error"], "TimeoutExpired")
        self.assertEqual(result["delivered"], {})
        self.assertTrue(self.run_pass(notify=True, now=NOW+1)["notification_succeeded"])

    def test_other_owner_blocks_delivery(self):
        w.atomic_json(self.root / "owner.json", {"owner": "another-owner"})
        self.assertRaises(ValueError, self.run_pass, notify=True)
        self.assertFalse((self.root / "state.json").exists())

    def test_three_minute_retry_and_new_severity(self):
        event = {"kind": "switch_required", "email": A, "limit": "session", "used": 80, "reset": NOW+3600}
        delivered = {w.event_key(event): NOW}
        self.assertEqual(w.due([event], delivered, NOW+179), [])
        self.assertEqual(w.due([event], delivered, NOW+180), [event])
        event["used"] = 85
        self.assertEqual(w.due([event], delivered, NOW+1), [event])

    def test_real_local_delivery_argv_no_shell_and_private_state(self):
        output = self.root / "received.json"
        self.cfg["owner"] = 'owner;$(not-a-command)'
        self.cfg["notify_command"] = [sys.executable, "-c", "import json,sys;open(sys.argv[1],'w').write(json.dumps(sys.argv[2:]))", str(output), "{owner}", "{message}"]
        result = w.run_once(self.cfg, self.root, True, collector=lambda _: (aliases(), {A: sample()}), now=NOW)
        self.assertTrue(result["notification_succeeded"])
        self.assertEqual(json.loads(output.read_text())[0], self.cfg["owner"])
        self.assertEqual((self.root / "state.json").stat().st_mode & 0o777, 0o600)

    def test_cli_transaction_lock_blocks_second_process(self):
        config_path = self.root / "config.json"
        w.atomic_json(config_path, self.cfg)
        with (self.root / "monitor.lock").open("a") as lock:
            w.fcntl.flock(lock, w.fcntl.LOCK_EX | w.fcntl.LOCK_NB)
            proc = subprocess.run([sys.executable, str(SCRIPT), "--config", str(config_path), "--state-dir", str(self.root)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((self.root / "state.json").exists())

    def test_invalid_configuration_rejected(self):
        for cfg in ([], {}, {**config(), "profiles": {"bad": []}}, {**config(), "notify_command": "shell command"}, {**config(), "session_threshold": float('nan')}, {**config(), "required_limits": ["session"]}):
            with self.subTest(cfg=cfg):
                self.assertRaises(ValueError, w.validate, cfg)
        self.assertEqual(w.validate(config()), config())


if __name__ == "__main__":
    unittest.main()
