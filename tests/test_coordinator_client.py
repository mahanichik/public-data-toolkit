import contextlib,gzip,hashlib,io,json,pathlib,tempfile,unittest
from unittest.mock import patch
import coordinator_client as client

class HttpResult:
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):return False

class CoordinatorTests(unittest.TestCase):
    def test_http_failure_does_not_include_body_url_or_chained_exception(self):
        error=client.urllib.error.HTTPError("https://private-label.invalid/path",422,"PRIVATE_REASON",{},io.BytesIO(b"PRIVATE_RESPONSE"))
        with patch.object(client,"oidc_token",return_value="fake.jwt.token"),patch.object(client.urllib.request,"urlopen",side_effect=error):
            with self.assertRaisesRegex(RuntimeError,"^Coordinator HTTP 422$") as caught:
                client.call("https://private-label.invalid/path",{})
        self.assertTrue(caught.exception.__suppress_context__)

    def test_cli_never_prints_network_errors_or_tracebacks(self):
        output=io.StringIO();errors=io.StringIO()
        with patch.object(client,"claim",side_effect=RuntimeError("PRIVATE_URL PRIVATE_TOKEN PRIVATE_RESPONSE")):
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):code=client.main(["claim"])
        self.assertEqual(code,1)
        self.assertNotIn("PRIVATE_",output.getvalue()+errors.getvalue())
        self.assertNotIn("Traceback",errors.getvalue())

    def test_unknown_selector_is_never_written_or_printed(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"claim.json";output=io.StringIO()
            data={"job":{"id":"opaque","payload":{"source":"unsupported\nPRIVATE_FIELD=value"}}}
            with patch.dict(client.os.environ,{"COORDINATOR_URL":"https://coordinator.invalid"}),patch.object(client,"call",return_value=(200,data)):
                with contextlib.redirect_stdout(output),self.assertRaises(RuntimeError):client.claim(path)
            self.assertFalse(path.exists());self.assertNotIn("PRIVATE_FIELD",output.getvalue())

    def test_claim_keeps_only_transport_fields_and_protects_file_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"claim.json"
            manifest=json.loads((pathlib.Path(client.__file__).parent/"worker-manifest.json").read_text())
            task=manifest["capabilities"][0]["key"]
            data={"job":{"id":"opaque","payload":{"source":task,"config":{}},"workspace_id":"PRIVATE_WS","agent_key":"PRIVATE_AGENT"},"callback_url":"https://coordinator.invalid/callback","internal":"PRIVATE_PLAN"}
            with patch.dict(client.os.environ,{"COORDINATOR_URL":"https://coordinator.invalid"}),patch.object(client,"call",return_value=(200,data)),contextlib.redirect_stdout(io.StringIO()):client.claim(path)
            self.assertNotIn("PRIVATE_",path.read_text());self.assertEqual(path.stat().st_mode&0o777,0o600)

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

