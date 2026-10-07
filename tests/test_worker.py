import json,pathlib,subprocess,tempfile,unittest,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
WORKER=ROOT/"worker.py"

class WorkerTests(unittest.TestCase):
  def run_worker(self,source,cfg,fixture):
    with tempfile.TemporaryDirectory() as td:
      d=pathlib.Path(td);fp=d/"fixture.json";cp=d/"config.json";out=d/"out"
      fp.write_text(json.dumps(fixture),encoding="utf-8");cfg={**cfg,"fixture_path":str(fp)}
      cp.write_text(json.dumps(cfg),encoding="utf-8")
      subprocess.run([sys.executable,str(WORKER),"--source",source,"--config",str(cp),"--out",str(out)],check=True)
      return json.loads((out/"records.json").read_text()),json.loads((out/"receipt.json").read_text())

  def test_overture(self):
    doc={"features":[{"id":"1","properties":{"names":{"primary":"Hotel A"},"basic_category":"hotel","taxonomy":{"primary":"hotel","hierarchy":["hotel"]},"emails":["sales@a.example"],"addresses":[{"freeform":"Example City"}]}},{"id":"2","properties":{"names":{"primary":"Museum"},"basic_category":"museum","taxonomy":{"primary":"museum","hierarchy":["museum"]}}}]}
    records,receipt=self.run_worker("overture_places",{"bbox":[44,40,45,41],"category_terms":["hotel"]},doc)
    self.assertEqual(len(records["records"]),1);self.assertEqual(receipt["output_count"],1);self.assertEqual(receipt["rejected_count"],1)

  def test_gdelt(self):
    doc={"articles":[{"url":"https://e/x","title":"Company opens branch","domain":"e","sourcecountry":"Exampleland","seendate":"20261007T120000Z"}]}
    records,receipt=self.run_worker("gdelt_events",{"query":"opening","max_records":10},doc)
    self.assertEqual(records["records"][0]["metadata"]["source_country"],"Exampleland");self.assertEqual(receipt["output_count"],1)

  def test_overpass(self):
    doc={"elements":[{"type":"node","id":1,"lat":40.1,"lon":44.5,"tags":{"name":"Hotel B","tourism":"hotel","email":"info@b.example"}}]}
    records,receipt=self.run_worker("overpass_places",{"bbox":[40,44,41,45],"tags":["tourism=hotel"]},doc)
    self.assertEqual(records["records"][0]["metadata"]["email"],"info@b.example");self.assertEqual(receipt["output_count"],1)

  def test_greenhouse_and_lever(self):
    gh={"acme":{"jobs":[{"id":1,"title":"Marketing Manager","absolute_url":"https://jobs/a","location":{"name":"Remote"},"updated_at":"2026-10-07T00:00:00Z"}]}}
    lr={"acme":[{"id":"x","text":"Marketing Lead","hostedUrl":"https://jobs/l","categories":{"location":"Example City","team":"Marketing"}}]}
    r1,_=self.run_worker("greenhouse_jobs",{"board_tokens":["acme"]},gh);r2,_=self.run_worker("lever_jobs",{"sites":["acme"]},lr)
    self.assertEqual(r1["records"][0]["metadata"]["title"],"Marketing Manager");self.assertEqual(r2["records"][0]["metadata"]["team"],"Marketing")

  def test_ashby(self):
    fixture={"acme":{"jobs":[{"title":"Demand Gen Lead","location":"Remote","department":"Marketing","team":"Growth","isListed":True,"publishedAt":"2026-10-07T00:00:00Z","jobUrl":"https://jobs.example/demand","applyUrl":"https://jobs.example/apply","workplaceType":"Remote"},{"title":"Hidden","isListed":False,"jobUrl":"https://jobs.example/hidden"}]}}
    records,receipt=self.run_worker("ashby_jobs",{"board_names":["acme"]},fixture)
    self.assertEqual(receipt["output_count"],1);self.assertEqual(receipt["rejected_count"],1)
    self.assertEqual(records["records"][0]["metadata"]["source"],"ashby")

if __name__=="__main__":unittest.main()
