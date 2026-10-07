import json,pathlib,subprocess,tempfile,unittest,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
WORKER=ROOT/"advanced_worker.py"
class ContactFallbackTests(unittest.TestCase):
  def run_fixture(self,source,records):
    with tempfile.TemporaryDirectory() as td:
      d=pathlib.Path(td);fp=d/"fixture.json";cp=d/"config.json";out=d/"out"
      fp.write_text(json.dumps({"records":records}),encoding="utf-8")
      cp.write_text(json.dumps({"fixture_path":str(fp)}),encoding="utf-8")
      subprocess.run([sys.executable,str(WORKER),"--source",source,"--config",str(cp),"--out",str(out)],check=True)
      return json.loads((out/"records.json").read_text()),json.loads((out/"receipt.json").read_text())
  def test_contact_contract(self):
    data,receipt=self.run_fixture("contact_extract",[{"id":"e1","text":"Public email evidence: hello@example.test","state":"DISCOVERED","evidence_url":"https://example.com/"}])
    self.assertEqual(receipt["output_count"],1);self.assertEqual(data["records"][0]["metadata"]["source"],"contact_extract")
  def test_crawl4ai_contract(self):
    data,receipt=self.run_fixture("crawl4ai_page",[{"url":"https://example.com/","text":"Public page text"}])
    self.assertEqual(receipt["status"],"completed");self.assertEqual(data["records"][0]["metadata"]["source"],"crawl4ai_page")
if __name__=="__main__":unittest.main()
