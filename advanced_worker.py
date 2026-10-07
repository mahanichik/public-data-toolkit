#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, hashlib, ipaddress, json, pathlib, socket, subprocess, urllib.parse, urllib.request
from datetime import datetime, timezone
from typing import Any

UA="PublicDataToolkit/1"
SOURCES={"crawlee_site","scrapling_page","jobspy_jobs","searxng_search","tech_detect"}

def clean(v:Any,limit:int=6000)->str:
    return " ".join(str(v or "").split())[:limit]

def rid(prefix:str,*parts:Any)->str:
    raw="|".join(clean(x,2000) for x in parts)
    return prefix+"_"+hashlib.sha256(raw.encode()).hexdigest()[:24]

def now()->str:
    return datetime.now(timezone.utc).isoformat()

def fixture(cfg):
    p=cfg.get("fixture_path")
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8")) if p else None

def ensure_public_url(value:str)->str:
    u=urllib.parse.urlparse(clean(value,1500))
    if u.scheme not in {"http","https"} or not u.hostname or u.username or u.password:
        raise ValueError("Only credential-free public http/https URLs are allowed")
    host=u.hostname
    if host.lower() in {"localhost","localhost.localdomain"}:
        raise ValueError("Local addresses are not allowed")
    try:
        ips={info[4][0] for info in socket.getaddrinfo(host,u.port or (443 if u.scheme=="https" else 80),type=socket.SOCK_STREAM)}
    except socket.gaierror as e:
        raise ValueError("Hostname could not be resolved") from e
    for raw in ips:
        ip=ipaddress.ip_address(raw.split("%",1)[0])
        if not ip.is_global:
            raise ValueError("Only public network targets are allowed")
    return u.geturl()

def dedupe(records):
    seen=set();out=[];dupes=0
    for r in records:
        key=str(r.get("id") or "")
        if not key or key in seen:dupes+=1;continue
        seen.add(key);out.append(r)
    return out,dupes

def from_fixture(source,cfg,doc):
    rows=doc.get("records",doc if isinstance(doc,list) else [])
    if not isinstance(rows,list):raise ValueError("Fixture must contain a records list")
    out=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict):continue
        url=clean(row.get("url"),1500);title=clean(row.get("title"),500);text=clean(row.get("text") or row.get("content"),6000)
        out.append({"id":clean(row.get("id"),200) or rid(source,url,title,i),"text":text or title or url,"observed_at":row.get("observed_at"),"metadata":{"source":source,**{k:v for k,v in row.items() if k not in {"id","text","observed_at"}}}})
    return out,0,{"fixture":True}

async def crawl_real(cfg):
    from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
    starts=[ensure_public_url(x) for x in (cfg.get("urls") or [])]
    if not starts:raise ValueError("urls is required")
    max_pages=max(1,min(200,int(cfg.get("max_pages") or 20)))
    max_chars=max(500,min(20000,int(cfg.get("max_chars_per_page") or 6000)))
    records=[]
    crawler=BeautifulSoupCrawler(
        max_requests_per_crawl=max_pages,
        respect_robots_txt_file=True,
        retry_on_blocked=False,
        max_request_retries=2,
    )
    @crawler.router.default_handler
    async def handler(context:BeautifulSoupCrawlingContext):
        url=str(context.request.url)
        title=clean(context.soup.title.string if context.soup.title and context.soup.title.string else "",500)
        text=clean(context.soup.get_text(" ",strip=True),max_chars)
        records.append({"id":rid("crawl",url),"text":text or title or url,"observed_at":now(),"metadata":{"source":"crawlee","url":url,"title":title}})
        await context.enqueue_links()
    await crawler.run(starts)
    return records,0,{"start_urls":len(starts),"robots_txt":True,"retry_on_blocked":False,"max_pages":max_pages}

def crawlee_site(cfg):
    doc=fixture(cfg)
    return from_fixture("crawlee",cfg,doc) if doc is not None else asyncio.run(crawl_real(cfg))

def scrapling_page(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("scrapling",cfg,doc)
    from scrapling.fetchers import Fetcher
    urls=[ensure_public_url(x) for x in (cfg.get("urls") or [])]
    if not urls:raise ValueError("urls is required")
    max_urls=max(1,min(50,int(cfg.get("max_urls") or 10)))
    records=[];failed=0
    for url in urls[:max_urls]:
        try:
            page=Fetcher.get(url)
            text=clean(page.get_all_text(ignore_tags=("script","style")),int(cfg.get("max_chars_per_page") or 6000))
            records.append({"id":rid("scrapling",url),"text":text or url,"observed_at":now(),"metadata":{"source":"scrapling","url":url,"status":getattr(page,"status",None),"mode":"plain_fetcher"}})
        except Exception:
            failed+=1
    return records,failed,{"requested":min(len(urls),max_urls),"mode":"plain_fetcher","access_control_bypass":False}

def jobspy_jobs(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("jobspy",cfg,doc)
    from jobspy import scrape_jobs
    sites=[clean(x,40).lower() for x in (cfg.get("sites") or ["indeed","linkedin","glassdoor","zip_recruiter"])]
    allowed={"indeed","linkedin","glassdoor","zip_recruiter","google","bayt","bdjobs","naukri"}
    if not sites or any(x not in allowed for x in sites):raise ValueError("Unsupported JobSpy site")
    wanted=max(1,min(200,int(cfg.get("results_wanted") or 25)))
    df=scrape_jobs(
        site_name=sites,
        search_term=clean(cfg.get("search_term"),300) or None,
        location=clean(cfg.get("location"),200) or None,
        results_wanted=wanted,
        hours_old=max(1,min(24*30,int(cfg.get("hours_old") or 168))),
        country_indeed=clean(cfg.get("country_indeed"),80) or "USA",
        fetch_description=False,
        verbose=0,
    )
    records=[]
    for row in df.fillna("").to_dict(orient="records")[:wanted]:
        url=clean(row.get("job_url") or row.get("job_url_direct"),1500)
        title=clean(row.get("title"),400);company=clean(row.get("company"),300);loc=clean(row.get("location"),300)
        records.append({"id":rid("jobspy",row.get("site"),url,title,company),"text":f"{title}. Company: {company}. Location: {loc}.","observed_at":clean(row.get("date_posted"),80) or None,"metadata":{"source":"jobspy","site":clean(row.get("site"),80),"url":url,"title":title,"company":company,"location":loc}})
    return records,0,{"sites":sites,"requested":wanted}

def searxng_search(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("searxng",cfg,doc)
    endpoint=ensure_public_url(cfg.get("endpoint") or "")
    query=clean(cfg.get("query"),500)
    if not query:raise ValueError("query is required")
    limit=max(1,min(100,int(cfg.get("max_records") or 25)))
    base=endpoint.rstrip("/")+"/search"
    url=base+"?"+urllib.parse.urlencode({"q":query,"format":"json","language":clean(cfg.get("language"),30) or "all","safesearch":"1"})
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=45) as r:
        raw=r.read(5_000_001)
    if len(raw)>5_000_000:raise ValueError("SearXNG response too large")
    data=json.loads(raw.decode("utf-8","replace"))
    records=[]
    for row in (data.get("results") or [])[:limit]:
        target=clean(row.get("url"),1500);title=clean(row.get("title"),500);content=clean(row.get("content"),2500)
        if not target:continue
        records.append({"id":rid("searxng",target),"text":f"{title}. {content}","observed_at":None,"metadata":{"source":"searxng","url":target,"title":title,"engine":clean(row.get("engine"),100),"score":row.get("score")}})
    return records,0,{"query":query,"returned":len(records)}

def tech_detect(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("tech_detect",cfg,doc)
    urls=[ensure_public_url(x) for x in (cfg.get("urls") or [])]
    if not urls:raise ValueError("urls is required")
    records=[]
    for url in urls[:50]:
        techdir=pathlib.Path(__file__).resolve().parent/"techdetect"
        proc=subprocess.run(["go","run",".","--url",url],cwd=techdir,capture_output=True,text=True,timeout=90,check=True)
        data=json.loads(proc.stdout)
        tech=data.get("technologies") or []
        records.append({"id":rid("tech",url),"text":f"Technology fingerprint for {url}: {', '.join(tech[:100])}.","observed_at":now(),"metadata":{"source":"wappalyzergo","url":url,"technologies":tech[:200]}})
    return records,0,{"requested":min(len(urls),50),"engine":"wappalyzergo"}

HANDLERS={"crawlee_site":crawlee_site,"scrapling_page":scrapling_page,"jobspy_jobs":jobspy_jobs,"searxng_search":searxng_search,"tech_detect":tech_detect}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--source",required=True,choices=sorted(SOURCES));ap.add_argument("--config",required=True);ap.add_argument("--out",default="out")
    a=ap.parse_args();cfg=json.loads(pathlib.Path(a.config).read_text(encoding="utf-8"));started=now();err=None
    try:records,rejected,metrics=HANDLERS[a.source](cfg)
    except Exception as e:records=[];rejected=0;metrics={};err=f"{type(e).__name__}: {e}"
    records,dupes=dedupe(records);out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    receipt={"worker_key":"public_data_worker","activity_type":"public_collection","source_key":a.source,"compute_class":"github_public","status":"failed" if err else "completed","input_count":len(records)+rejected+dupes,"output_count":len(records),"rejected_count":rejected,"duplicate_count":dupes,"stale_count":0,"promoted_count":len(records),"reasons":{k:v for k,v in {"failed_or_filtered":rejected,"duplicate":dupes}.items() if v},"metrics":metrics,"summary":err or f"{a.source}: {len(records)} normalized records; {rejected} filtered/failed; {dupes} duplicates.","started_at":started,"completed_at":now()}
    (out/"records.json").write_text(json.dumps({"source":a.source,"records":records,"meta":metrics},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False))
    if err:raise SystemExit(1)
if __name__=="__main__":main()
