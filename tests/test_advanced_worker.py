import json,pathlib,subprocess,tempfile,unittest,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
WORKER=ROOT/"advanced_worker.py"

class AdvancedWorkerTests(unittest.TestCase):
  def run_fixture(self,source,records,cfg=None):
    with tempfile.TemporaryDirectory() as td:
      d=pathlib.Path(td);fp=d/"fixture.json";cp=d/"config.json";out=d/"out"
      fp.write_text(json.dumps({"records":records}),encoding="utf-8")
      conf={**(cfg or {}),"fixture_path":str(fp)}
      cp.write_text(json.dumps(conf),encoding="utf-8")
      subprocess.run([sys.executable,str(WORKER),"--source",source,"--config",str(cp),"--out",str(out)],check=True)
      return json.loads((out/"records.json").read_text()),json.loads((out/"receipt.json").read_text())

  def test_all_advanced_sources_share_contract(self):
    for source in ["crawlee_site","scrapling_page","jobspy_jobs","searxng_search","tech_detect"]:
      data,receipt=self.run_fixture(source,[{"url":"https://example.com/a","title":"Example","text":"Public example evidence"}])
      self.assertEqual(data["records"][0]["text"],"Public example evidence")
      self.assertEqual(receipt["status"],"completed")
      self.assertEqual(receipt["output_count"],1)
      self.assertEqual(receipt["source_key"],source)

  def test_dedupes_fixture_ids(self):
    data,receipt=self.run_fixture("crawlee_site",[{"id":"same","text":"one"},{"id":"same","text":"two"}])
    self.assertEqual(len(data["records"]),1)
    self.assertEqual(receipt["duplicate_count"],1)

if __name__=="__main__":unittest.main()
