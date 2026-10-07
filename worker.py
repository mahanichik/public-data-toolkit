#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from typing import Any

UA="PublicDataWorker/1"

def clean(v:Any,limit:int=5000)->str:
    return " ".join(str(v or "").split())[:limit]

def rid(prefix:str,*parts:Any)->str:
    raw="|".join(clean(p,2000) for p in parts)
    return prefix+"_"+hashlib.sha256(raw.encode()).hexdigest()[:24]

def now()->str:
    return datetime.now(timezone.utc).isoformat()

def http_json(url:str,timeout:int=60,max_bytes:int=8_000_000):
    last=None
    for attempt in range(4):
        req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:
                raw=r.read(max_bytes+1)
            if len(raw)>max_bytes:
                raise RuntimeError("Response exceeded size limit")
            return json.loads(raw.decode("utf-8","replace"))
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504) or attempt==3:
                raise
            retry=e.headers.get("Retry-After")
            try:
                delay=min(30,max(1,int(retry))) if retry else min(30,2**attempt)
            except ValueError:
                delay=min(30,2**attempt)
            time.sleep(delay)
    raise last if last else RuntimeError("HTTP request failed")

def load_fixture(cfg:dict[str,Any]):
    p=cfg.get("fixture_path")
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8")) if p else None

def dedupe(records:list[dict[str,Any]]):
    seen=set();out=[];duplicates=0
    for r in records:
        key=str(r.get("id") or "")
        if not key or key in seen:
            duplicates+=1;continue
        seen.add(key);out.append(r)
    return out,duplicates

def overture(cfg):
    bbox=cfg.get("bbox")
    if not isinstance(bbox,list) or len(bbox)!=4:raise ValueError("bbox must be [minLon,minLat,maxLon,maxLat]")
    max_records=max(1,min(50000,int(cfg.get("max_records") or 10000)))
    terms={clean(x,120).lower() for x in (cfg.get("category_terms") or []) if clean(x,120)}
    doc=load_fixture(cfg)
    if doc is None:
        with tempfile.TemporaryDirectory() as td:
            out=pathlib.Path(td)/"places.geojson"
            cmd=["overturemaps","download","--bbox",",".join(map(str,bbox)),"-f","geojson","--type","place","-o",str(out)]
            subprocess.run(cmd,check=True,timeout=max(60,min(1800,int(cfg.get("timeout_seconds") or 900))))
            doc=json.loads(out.read_text(encoding="utf-8"))
    records=[];filtered=0
    for f in doc.get("features") or []:
        if not isinstance(f,dict):continue
        p=f.get("properties") or {};names=p.get("names") or {};tax=p.get("taxonomy") or {}
        labels=[clean(p.get("basic_category"),120).lower(),clean(tax.get("primary"),120).lower()]
        labels += [clean(x,120).lower() for x in (tax.get("hierarchy") or [])]
        if terms and not any(any(t in label for label in labels if label) for t in terms):
            filtered+=1;continue
        name=clean(names.get("primary"),240)
        if not name:filtered+=1;continue
        addresses=p.get("addresses") or []
        address=clean((addresses[0] or {}).get("freeform") if addresses and isinstance(addresses[0],dict) else "",500)
        websites=[clean(x,600) for x in (p.get("websites") or []) if clean(x,600)]
        emails=[clean(x,254).lower() for x in (p.get("emails") or []) if clean(x,254)]
        phones=[clean(x,100) for x in (p.get("phones") or []) if clean(x,100)]
        oid=clean(f.get("id") or p.get("id"),200)
        records.append({"id":rid("overture",oid or name,address),"text":f"{name}. Category: {labels[0] or labels[1]}. Address: {address}. Website: {websites[0] if websites else ''}.","observed_at":now(),"metadata":{"source":"overture","overture_id":oid,"name":name,"categories":[x for x in labels if x],"websites":websites[:5],"emails":emails[:5],"phones":phones[:5],"address":address}})
        if len(records)>=max_records:break
    return records,filtered,{"bbox":bbox,"category_terms":sorted(terms)}

def gdelt(cfg):
    query=clean(cfg.get("query"),1500)
    if len(query)<2:raise ValueError("query is required")
    max_records=max(1,min(250,int(cfg.get("max_records") or 250)))
    timespan=clean(cfg.get("timespan") or "7d",30)
    doc=load_fixture(cfg)
    if doc is None:
        params={"query":query,"mode":"artlist","format":"json","maxrecords":str(max_records),"sort":"datedesc","timespan":timespan}
        doc=http_json("https://api.gdeltproject.org/api/v2/doc/doc?"+urllib.parse.urlencode(params),45,5_000_000)
    records=[];filtered=0
    for a in doc.get("articles") or []:
        if not isinstance(a,dict):continue
        url=clean(a.get("url"),1200);title=clean(a.get("title"),800)
        if not url or not title:filtered+=1;continue
        seen=clean(a.get("seendate") or a.get("seenDate"),60);observed=None
        for fmt in ("%Y%m%dT%H%M%SZ","%Y%m%d%H%M%S"):
            try:
                if seen:observed=datetime.strptime(seen,fmt).replace(tzinfo=timezone.utc).isoformat();break
            except ValueError:pass
        records.append({"id":rid("gdelt",url),"text":f"{title}. Source: {clean(a.get('domain'),300)}. Country: {clean(a.get('sourcecountry'),120)}.","observed_at":observed,"metadata":{"source":"gdelt","url":url,"title":title,"domain":clean(a.get("domain"),300),"language":clean(a.get("language"),80),"source_country":clean(a.get("sourcecountry"),120)}})
        if len(records)>=max_records:break
    return records,filtered,{"query":query,"timespan":timespan}

def overpass(cfg):
    bbox=cfg.get("bbox")
    if not isinstance(bbox,list) or len(bbox)!=4:raise ValueError("bbox must be [south,west,north,east]")
    tags=[clean(x,120) for x in (cfg.get("tags") or []) if clean(x,120)]
    if not tags:raise ValueError("tags are required")
    max_records=max(1,min(20000,int(cfg.get("max_records") or 5000)))
    doc=load_fixture(cfg)
    if doc is None:
        south,west,north,east=map(float,bbox)
        parts=[]
        for t in tags:
            if "=" not in t:raise ValueError("Overpass tags must be key=value")
            k,v=t.split("=",1)
            parts += [f'nwr["{k}"="{v}"]({south},{west},{north},{east});']
        query="[out:json][timeout:60];("+ "".join(parts) +");out center tags;"
        data=urllib.parse.urlencode({"data":query}).encode()
        endpoints=[
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"
        ]
        last=None
        for endpoint in endpoints:
            try:
                req=urllib.request.Request(endpoint,data=data,headers={"User-Agent":UA,"Accept":"application/json"})
                with urllib.request.urlopen(req,timeout=90) as r:
                    doc=json.loads(r.read(10_000_000).decode("utf-8","replace"))
                break
            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:
                last=e
        else:
            raise last if last else RuntimeError("Overpass request failed")
    records=[];filtered=0
    for e in doc.get("elements") or []:
        tagsd=e.get("tags") or {};name=clean(tagsd.get("name"),240)
        if not name:filtered+=1;continue
        website=clean(tagsd.get("website") or tagsd.get("contact:website"),600)
        email=clean(tagsd.get("email") or tagsd.get("contact:email"),254).lower()
        phone=clean(tagsd.get("phone") or tagsd.get("contact:phone"),100)
        lat=e.get("lat") or (e.get("center") or {}).get("lat");lon=e.get("lon") or (e.get("center") or {}).get("lon")
        records.append({"id":rid("osm",e.get("type"),e.get("id")),"text":f"{name}. Public OSM tags: {', '.join(f'{k}={v}' for k,v in list(tagsd.items())[:12])}.","observed_at":now(),"metadata":{"source":"osm_overpass","osm_type":e.get("type"),"osm_id":e.get("id"),"name":name,"website":website or None,"email":email or None,"phone":phone or None,"lat":lat,"lon":lon,"tags":tagsd}})
        if len(records)>=max_records:break
    return records,filtered,{"bbox":bbox,"tags":tags}

def greenhouse(cfg):
    boards=[clean(x,150) for x in (cfg.get("board_tokens") or []) if clean(x,150)]
    max_records=max(1,min(20000,int(cfg.get("max_records") or 5000)))
    records=[];filtered=0
    fixtures=load_fixture(cfg)
    for board in boards:
        doc=(fixtures or {}).get(board) if isinstance(fixtures,dict) else None
        if doc is None:doc=http_json(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(board)}/jobs?content=true")
        for j in doc.get("jobs") or []:
            title=clean(j.get("title"),300);url=clean(j.get("absolute_url"),1000)
            if not title or not url:filtered+=1;continue
            loc=clean((j.get("location") or {}).get("name"),240)
            records.append({"id":rid("greenhouse",board,j.get("id")),"text":f"{title}. Location: {loc}. Public job posting for {board}.","observed_at":clean(j.get("updated_at"),80) or None,"metadata":{"source":"greenhouse","board_token":board,"job_id":j.get("id"),"title":title,"location":loc,"url":url}})
            if len(records)>=max_records:return records,filtered,{"boards":boards}
    return records,filtered,{"boards":boards}

def lever(cfg):
    sites=[clean(x,150) for x in (cfg.get("sites") or []) if clean(x,150)]
    max_records=max(1,min(20000,int(cfg.get("max_records") or 5000)))
    records=[];filtered=0
    fixtures=load_fixture(cfg)
    for site in sites:
        rows=(fixtures or {}).get(site) if isinstance(fixtures,dict) else None
        if rows is None:rows=http_json(f"https://api.lever.co/v0/postings/{urllib.parse.quote(site)}?mode=json")
        for j in rows or []:
            title=clean(j.get("text"),300);url=clean(j.get("hostedUrl"),1000)
            if not title or not url:filtered+=1;continue
            cats=j.get("categories") or {};loc=clean(cats.get("location"),240)
            records.append({"id":rid("lever",site,j.get("id") or url),"text":f"{title}. Location: {loc}. Public job posting for {site}.","observed_at":None,"metadata":{"source":"lever","site":site,"job_id":j.get("id"),"title":title,"location":loc,"url":url,"team":clean(cats.get("team"),200)}})
            if len(records)>=max_records:return records,filtered,{"sites":sites}
    return records,filtered,{"sites":sites}

SOURCES={"overture_places":overture,"gdelt_events":gdelt,"overpass_places":overpass,"greenhouse_jobs":greenhouse,"lever_jobs":lever}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--source",required=True,choices=sorted(SOURCES));ap.add_argument("--config",required=True);ap.add_argument("--out",default="out")
    args=ap.parse_args();cfg=json.loads(pathlib.Path(args.config).read_text(encoding="utf-8"))
    started=now();error=None
    try:records,filtered,meta=SOURCES[args.source](cfg)
    except Exception as e:
        records=[];filtered=0;meta={};error=f"{type(e).__name__}: {e}"
    records,dupes=dedupe(records)
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=True)
    status="failed" if error else "completed"
    receipt={"worker_key":"public_data_worker","activity_type":"public_collection","source_key":args.source,"compute_class":"github_public","status":status,"input_count":len(records)+filtered+dupes,"output_count":len(records),"rejected_count":filtered,"duplicate_count":dupes,"stale_count":0,"promoted_count":len(records),"reasons":{k:v for k,v in {"filtered":filtered,"duplicate":dupes}.items() if v},"metrics":meta,"summary":error or f"{args.source}: {len(records)} normalized records; {filtered} filtered; {dupes} duplicates.","started_at":started,"completed_at":now()}
    (out/"records.json").write_text(json.dumps({"source":args.source,"records":records,"meta":meta},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False))
    if error:raise SystemExit(1)

if __name__=="__main__":main()
