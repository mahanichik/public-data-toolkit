#!/usr/bin/env python3
from __future__ import annotations
import argparse,gzip,hashlib,json,os,pathlib,urllib.error,urllib.parse,urllib.request

AUDIENCE="public-worker-coordinator"

def oidc_token():
    url=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL","").strip()
    bearer=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","").strip()
    if not url or not bearer: raise RuntimeError("GitHub OIDC environment is unavailable")
    sep="&" if "?" in url else "?"
    req=urllib.request.Request(url+sep+urllib.parse.urlencode({"audience":AUDIENCE}),headers={"Authorization":"Bearer "+bearer,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=20) as r:data=json.loads(r.read(1_000_000).decode())
    token=str(data.get("value") or "")
    if token.count(".")!=2: raise RuntimeError("OIDC provider returned an invalid token")
    return token

def call(url,body,timeout=45):
    raw=json.dumps(body,separators=(",",":")).encode()
    req=urllib.request.Request(url,data=raw,method="POST",headers={"Authorization":"Bearer "+oidc_token(),"Content-Type":"application/json","Accept":"application/json","User-Agent":"PublicWorkerCoordinator/1"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            content=r.read(2_000_000)
            return r.status,json.loads(content.decode()) if content else {}
    except urllib.error.HTTPError as e:
        content=e.read(2000).decode("utf-8","replace")
        if e.code==204:return 204,{}
        raise RuntimeError(f"Coordinator HTTP {e.code}: {content}") from e

def claim(out:pathlib.Path):
    url=os.environ.get("COORDINATOR_URL","").strip()
    if not url:
        print("claimed=false")
        print("configured=false")
        return
    print("configured=true")
    status,data=call(url,{})
    if status==204 or not data.get("job"):
        print("claimed=false");return
    out.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    payload=data["job"].get("payload") or {}
    task=str(payload.get("source") or payload.get("task_type") or "")
    if not task: raise RuntimeError("Claimed job has no public task selector")
    print("claimed=true");print("task="+task)

def complete(claim_path:pathlib.Path,result_dir:pathlib.Path):
    claim=json.loads(claim_path.read_text(encoding="utf-8"))
    receipt=json.loads((result_dir/"receipt.json").read_text(encoding="utf-8"))
    result_name="records.json" if (result_dir/"records.json").exists() else "result.json"
    result=json.loads((result_dir/result_name).read_text(encoding="utf-8"))
    items=None;field=None
    for candidate in ("records","results","clusters"):
        if isinstance(result.get(candidate),list):
            items=result[candidate];field=candidate;break
    ingested=0;truncated=0;chunks=0
    chunks_url=claim.get("chunks_url")
    if items is not None and chunks_url:
        if len(items)>100000:
            raise RuntimeError("Archive supports at most 100000 normalized items per job; split the job")
        for index,i in enumerate(range(0,len(items),100)):
            batch=items[i:i+100]
            body=json.dumps({"field":field,"offset":i,"items":batch},ensure_ascii=False,separators=(",",":")).encode("utf-8")
            if len(body)>2_000_000: raise RuntimeError("Normalized item chunk too large; split records before dispatch")
            packed=gzip.compress(body,compresslevel=6,mtime=0)
            if len(packed)>500000: raise RuntimeError("Compressed item chunk too large; split records before dispatch")
            digest=hashlib.sha256(packed).hexdigest()
            url=str(chunks_url).rstrip("/")+"/"+str(index)
            req=urllib.request.Request(url,data=packed,method="PUT",headers={
                "Authorization":"Bearer "+oidc_token(),
                "Content-Type":"application/gzip",
                "X-Record-Kind":str(field),"X-Record-Count":str(len(batch)),
                "X-Content-Sha256":digest,"User-Agent":"PublicWorkerCoordinator/1"
            })
            with urllib.request.urlopen(req,timeout=90) as response:
                if response.status!=200:raise RuntimeError("Archive upload did not succeed")
            ingested+=len(batch);chunks+=1
        result={k:v for k,v in result.items() if k!=field}
        result.update({"item_field":field,"items_archived":ingested,"archive_chunks":chunks})
    elif items is not None and claim.get("items_url"):
        if len(items)>5000:raise RuntimeError("Indexed item limit is 5000 without archive storage; refusing silent truncation")
        for i in range(0,len(items),100):
            batch=items[i:i+100]
            status,_=call(str(claim["items_url"]),{"field":field,"offset":i,"items":batch})
            if status not in (200,201):raise RuntimeError("Item ingest failed")
            ingested+=len(batch)
        result={k:v for k,v in result.items() if k!=field}
        result.update({"item_field":field,"items_ingested":ingested})
    elif items:
        raise RuntimeError("Coordinator has no normalized-item ingest endpoint")
    status,data=call(str(claim["callback_url"]),{"receipt":receipt,"result":result})
    if status!=200:raise RuntimeError("Completion callback failed")
    print(json.dumps({"completed":True,"job_id":data.get("job_id"),"receipt_id":data.get("receipt_id"),"items_ingested":ingested,"items_not_ingested":truncated}))

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    c=sub.add_parser("claim");c.add_argument("--out",default="claim.json")
    d=sub.add_parser("complete");d.add_argument("--claim",default="claim.json");d.add_argument("--result-dir",default="out")
    a=ap.parse_args()
    if a.cmd=="claim":claim(pathlib.Path(a.out))
    else:complete(pathlib.Path(a.claim),pathlib.Path(a.result_dir))
if __name__=="__main__":main()
