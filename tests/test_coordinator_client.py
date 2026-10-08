import contextlib,gzip,hashlib,io,json,pathlib,tempfile,unittest
from unittest.mock import patch
import coordinator_client as client

class HttpResult:
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):return False

class CoordinatorTests(unittest.TestCase):
    def test_unconfigured_claim_is_safe_noop(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"claim.json"
            with patch.dict(client.os.environ,{"COORDINATOR_URL":""},clear=False):
                with contextlib.redirect_stdout(io.StringIO()) as output: client.claim(path)
            self.assertFalse(path.exists())
            self.assertIn("claimed=false",output.getvalue())

    def test_chunk_upload_compressed_and_verified(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td);(base/"out").mkdir()
            records=[{"id":str(i),"text":"Public sample record "+str(i)} for i in range(125)]
            (base/"claim.json").write_text(json.dumps({"chunks_url":"https://coordinator.invalid/chunks/job","callback_url":"https://coordinator.invalid/callback","job":{"id":"example","payload":{"source":"demo"}}}))
            (base/"out"/"records.json").write_text(json.dumps({"records":records}))
            (base/"out"/"receipt.json").write_text(json.dumps({"status":"completed","output_count":125}))
            sent=[];callbacks=[]
            def upload(req,timeout=90):
                self.assertEqual(req.get_method(),"PUT")
                body=req.data
                self.assertEqual(hashlib.sha256(body).hexdigest(),req.headers["X-content-sha256"])
                sent.append(json.loads(gzip.decompress(body)))
                return HttpResult()
            def callback(url,payload,timeout=45):
                callbacks.append(payload);return 200,{"job_id":"example","receipt_id":"receipt"}
            with patch.object(client,"oidc_token",return_value="fake.jwt.token"),patch.object(client.urllib.request,"urlopen",side_effect=upload),patch.object(client,"call",side_effect=callback):
                with contextlib.redirect_stdout(io.StringIO()):client.complete(base/"claim.json",base/"out")
            self.assertEqual([len(x["items"]) for x in sent],[100,25])
            self.assertEqual(sum(len(x["items"]) for x in sent),125)
            self.assertNotIn("records",callbacks[0]["result"])
            self.assertEqual(callbacks[0]["result"]["items_archived"],125)

    def test_refuses_legacy_silent_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td);(base/"out").mkdir()
            (base/"claim.json").write_text(json.dumps({"items_url":"https://coordinator.invalid/items","callback_url":"https://coordinator.invalid/callback","job":{"id":"example"}}))
            (base/"out"/"records.json").write_text(json.dumps({"records":[{"id":str(i),"text":"example"} for i in range(5001)]}))
            (base/"out"/"receipt.json").write_text(json.dumps({"status":"completed","output_count":5001}))
            with self.assertRaisesRegex(RuntimeError,"refusing silent truncation"):
                client.complete(base/"claim.json",base/"out")

if __name__=="__main__":unittest.main()
