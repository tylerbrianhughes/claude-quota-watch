import sys
from pathlib import Path
import unittest
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/claude-quota-watch/scripts'))
from throughput import Throughput,price
from fleet_forecast import simulate

class MetricsTests(unittest.TestCase):
    def test_deduplicates_blocks_and_profiles_and_keeps_final_output(self):
        t=Throughput([]);now=10000
        r={'type':'assistant','timestamp':datetime.fromtimestamp(now-30,timezone.utc).isoformat(),
           'requestId':'r','message':{'id':'m','model':'claude-opus-5-5','usage':{
               'input_tokens':10,'output_tokens':20,'cache_read_input_tokens':1000}}}
        t.ingest(r,now);t.ingest(r,now)
        r['message']['usage']['output_tokens']=30;t.ingest(r,now)
        w=t.summarize(now)['windows'][0]
        self.assertEqual(w['requests'],1);self.assertEqual(w['tokens']['output_tokens'],30)
        self.assertEqual(w['processed_per_hour'],4160)
        self.assertEqual(t.summarize(now+3601)['windows'][1]['requests'],0)
    def test_model_prices_cache_ttl_and_missing_ttl_range(self):
        u={'input_tokens':1000000,'output_tokens':1000000,'cache_creation_input_tokens':1000000,'cache_read_input_tokens':1000000,
           'cache_creation':{'ephemeral_1h_input_tokens':1000000}}
        self.assertEqual(price('claude-fable-5-1',u),[80.25,80.25])
        self.assertEqual(price('claude-haiku-4-5-20251001',u),[8.1,8.1])
        del u['cache_creation'];self.assertEqual(price('claude-opus-5-5',u),[29.2,32.2])
        self.assertIsNone(price('claude-future-unknown',u))
        self.assertIsNone(price('claude-opus-5-6',u))
    def account(self,s=0,w=0,sreset=None,wreset=None):
        return {'windows':[{'name':'session','used':s,'threshold':80,'reset':sreset},
                           {'name':'weekly','used':w,'threshold':85,'reset':wreset}]}
    def test_spare_and_reset_bridge_extend_coverage(self):
        rates={'session':1,'weekly':.1}
        a=self.account(70)
        self.assertAlmostEqual(simulate([a],rates,0),10)
        b=self.account(80,sreset=5*60)
        self.assertGreater(simulate([a,b],rates,0),80)
        b['windows'][1]['used']=100
        self.assertAlmostEqual(simulate([a,b],rates,0),10)
    def test_weekly_limits_survive_session_reset_and_weekly_reset_recovers(self):
        rates={'session':1,'weekly':1}
        a=self.account(0,84,sreset=60)
        self.assertAlmostEqual(simulate([a],rates,0),1)
        a['windows'][1]['reset']=60
        self.assertGreater(simulate([a],rates,0),10)
    def test_expiration_removes_capacity_from_forecast(self):
        a=self.account();a['expires_at']=60
        self.assertEqual(simulate([a],{'session':1,'weekly':.1},0),1)

    def test_faster_burn_shortens_runway_and_no_gap_is_censored(self):
        a=self.account();rates={'session':1,'weekly':.1}
        self.assertLess(simulate([a],rates,0,speed=1.25),simulate([a],rates,0))
        self.assertIsNone(simulate([a],rates,0,horizon=5))

if __name__=='__main__':unittest.main()
