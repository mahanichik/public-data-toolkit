import json
import contextlib
import io
import pathlib
import tempfile
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
import worker

class OrdinaryDemand(unittest.TestCase):
    def profile(self,**values):
        return {"profile":"ask_hn_service_requests_v1","max_records":40,**values}
    def hit(self,oid="101",**values):
        return {"objectID":oid,"title":"Ask HN: Need a website agency","story_text":"Our company needs an agency for our website.","created_at_i":int(datetime.now(timezone.utc).timestamp()),"_tags":["ask_hn"],**values}
    def test_fixed_profile_privacy_dedup_and_four_pages(self):
        with patch.object(worker,"http_json",return_value={"hits":[self.hit(story_text="Our company needs website help. Contact person@business.co.")]} ) as fetch:
            rows,rejected,metrics=worker.ask_hn_requests(self.profile())
        self.assertEqual(fetch.call_count,4);self.assertEqual(len(rows),1);self.assertEqual(rejected,0);self.assertEqual(metrics['duplicate_count'],3)
        self.assertEqual(rows[0]["metadata"]["url"],"https://news.ycombinator.com/item?id=101")
        self.assertNotIn("person@business.co",json.dumps(rows))
        self.assertFalse(metrics["buyer_geography_verified"]);self.assertFalse(metrics["contact_authorized"])
        for call in fetch.call_args_list:
            self.assertTrue(call.args[0].startswith("https://hn.algolia.com/api/v1/search_by_date?"))
            self.assertEqual(call.kwargs["max_bytes"],100000)
            self.assertIs(call.kwargs['allow_redirects'],False)
    def test_cli_receipt_separates_duplicate_from_rejected_work(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=pathlib.Path(folder)/'config.json';cfg.write_text(json.dumps(self.profile()))
            out=pathlib.Path(folder)/'out'
            with patch('sys.argv',['worker.py','--source','ask_hn_requests','--config',str(cfg),'--out',str(out)]),patch.object(worker,'http_json',return_value={'hits':[self.hit()]}),contextlib.redirect_stdout(io.StringIO()):
                worker.main()
            receipt=json.loads((out/'receipt.json').read_text())
            self.assertEqual([receipt['input_count'],receipt['output_count'],receipt['rejected_count'],receipt['duplicate_count']],[4,1,0,3])
    def test_unapproved_private_input_never_fetches(self):
        with patch.object(worker,"http_json") as fetch:
            for cfg in [self.profile(query="private target"),self.profile(profile="client_profile"),self.profile(max_records=41),self.profile(max_records=True)]:
                with self.assertRaises(ValueError):worker.ask_hn_requests(cfg)
            fetch.assert_not_called()
    def test_invalid_stale_and_wrong_family_are_filtered(self):
        hits=[self.hit("bad"),self.hit("102",created_at_i=1),self.hit("103",_tags=["story"]),self.hit("104",story_text="Need help with personal debt for my business")]
        with patch.object(worker,"http_json",return_value={"hits":hits}):
            rows,rejected,_=worker.ask_hn_requests(self.profile())
        self.assertEqual(rows,[]);self.assertEqual(rejected,16)
    def test_source_failure_and_oversized_page_do_not_claim_success(self):
        with patch.object(worker,"http_json",side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):worker.ask_hn_requests(self.profile())
        with patch.object(worker,"http_json",return_value={"hits":[self.hit()]*11}):
            with self.assertRaises(ValueError):worker.ask_hn_requests(self.profile())

if __name__=="__main__":unittest.main()
