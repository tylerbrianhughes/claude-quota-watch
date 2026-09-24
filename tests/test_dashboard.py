import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/claude-quota-watch/scripts'
sys.path.insert(0, str(SCRIPTS))
import dashboard as d
from test_quota_watch import NOW, A, sample


def state():
    return {'checked_at': NOW, 'accounts': {A: sample(session=60)},
            'capacity': {A: {'state': 'available', 'profiles': ['primary'], 'process_count': 2}},
            'rate_baselines': {A: sample(session=50, observed=NOW-600)}}


class DashboardTests(unittest.TestCase):
    def test_forecast_subtracts_age_and_uses_percentage_points(self):
        row = d.dashboard_view(state(), NOW+120)['accounts'][0]
        window = row['windows'][0]
        self.assertEqual(window['rate_per_minute'], 1)
        self.assertEqual(window['minutes_to_threshold'], 18)
        self.assertEqual(row['minutes_to_first_threshold'], 18)

    def test_repeated_page_requests_do_not_manufacture_new_samples(self):
        first = d.dashboard_view(state(), NOW)
        second = d.dashboard_view(state(), NOW+5)
        self.assertEqual(first['accounts'][0]['observed_at'], second['accounts'][0]['observed_at'])
        self.assertEqual(first['accounts'][0]['windows'][0]['sample_minutes'], 10)
        self.assertEqual(second['accounts'][0]['windows'][0]['sample_minutes'], 10)

    def test_expired_and_reset_samples_lose_forecast(self):
        for now in (NOW+901, NOW+3600):
            row = d.dashboard_view(state(), now)['accounts'][0]
            self.assertEqual(row['state'], 'quota_unknown')
            self.assertIsNone(row['windows'][0]['minutes_to_threshold'])
            self.assertIsNone(row['windows'][0]['rate_per_minute'])

    def test_reset_before_threshold_is_labeled(self):
        data=state()
        for key in ('accounts', 'rate_baselines'):
            data[key][A]['limits']['session']['reset'] = NOW+60
        row=d.dashboard_view(data, NOW)['accounts'][0]
        self.assertTrue(row['windows'][0]['reset_before_threshold'])
        self.assertIsNone(row['minutes_to_first_threshold'])

    def test_wrong_account_or_changed_window_has_no_rate(self):
        data=state()
        data['rate_baselines'][A]['account_uuid']='another'
        self.assertIsNone(d.dashboard_view(data,NOW)['accounts'][0]['windows'][0]['rate_per_minute'])

    def test_missing_snapshot_never_claims_healthy_monitor(self):
        self.assertFalse(d.dashboard_view({},NOW)['monitor_ok'])
        self.assertFalse(d.dashboard_view(state(),NOW+601)['monitor_ok'])

    def test_legacy_state_80_percent_not_shown_available(self):
        data=state()
        data['accounts'][A]['limits']['session']['used']=81
        self.assertEqual(d.dashboard_view(data,NOW)['accounts'][0]['state'],'constrained')

    def test_recovery_pending_and_complete_separate(self):
        data=state()
        data['recovery_obligations']={'done':{'state':'recovered'},'pending':{'state':'adoption_pending','deadline':NOW}}
        view=d.dashboard_view(data,NOW)
        self.assertEqual(len(view['obligations']),1)
        self.assertTrue(view['obligations'][0]['overdue'])
        self.assertNotIn('account_uuid',json.dumps(view))

    def test_http_local_snapshot_assets_and_host_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'status.json'
            path.write_text(json.dumps(state()))
            server=d.ThreadingHTTPServer(('127.0.0.1',0),d.handler_for(path))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                with urlopen(base+'/api/status') as response:
                    self.assertEqual(json.load(response)['accounts'][0]['email'],A)
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                with urlopen(base+'/') as response:
                    self.assertIn(b'Your fleet, in view.',response.read())
                for route in ('/dashboard.js','/dashboard.css'):
                    with urlopen(base+route) as response:
                        self.assertEqual(response.status,200)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/status',headers={'Host':'attacker.example'}))
                self.assertEqual(error.exception.code,403)
                path.write_text('{partial')
                with self.assertRaises(HTTPError) as error:
                    urlopen(base+'/api/status')
                self.assertEqual(error.exception.code,503)
                with self.assertRaises(HTTPError):
                    urlopen(base+'/../status.json')
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()


if __name__ == '__main__':
    unittest.main()
