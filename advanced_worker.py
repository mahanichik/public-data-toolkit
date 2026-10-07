#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, hashlib, html.parser, ipaddress, json, pathlib, re, socket, subprocess, tempfile, urllib.error, urllib.parse, urllib.request, urllib.robotparser
from datetime import datetime, timezone
from typing import Any

UA="PublicDataToolkit/1"
SOURCES={"crawlee_site","scrapling_page","jobspy_jobs","searxng_search","tech_detect","contact_extract","crawl4ai_page","duckdb_batch"}

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


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        safe=ensure_public_url(urllib.parse.urljoin(req.full_url,newurl))
        return super().redirect_request(req,fp,code,msg,headers,safe)

def public_opener():
    return urllib.request.build_opener(SafeRedirect())

def fetch_public_bytes(url:str,max_bytes:int=2_000_000,timeout:int=30):
    target=ensure_public_url(url)
    parsed=urllib.parse.urlparse(target)
    robots=urllib.robotparser.RobotFileParser()
    robots.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try: robots.read()
    except Exception: pass
    if not robots.can_fetch(UA,target): raise PermissionError("robots.txt disallows this URL")
    req=urllib.request.Request(target,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"})
    with public_opener().open(req,timeout=timeout) as r:
        final=ensure_public_url(r.geturl())
        raw=r.read(max_bytes+1)
        ctype=str(r.headers.get("content-type") or "")
    if len(raw)>max_bytes: raise ValueError("Public page exceeds size limit")
    if "html" not in ctype.lower() and "text" not in ctype.lower(): raise ValueError("Expected a public text/html page")
    return final,raw,ctype

class ContactParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__();self.mailto=[];self.tel=[];self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()!="a": return
        href=dict(attrs).get("href","")
        if isinstance(href,str) and href.lower().startswith("mailto:"): self.mailto.append(href[7:].split("?",1)[0])
        if isinstance(href,str) and href.lower().startswith("tel:"): self.tel.append(href[4:].split("?",1)[0])
    def handle_data(self,data):
        if data and data.strip(): self.text.append(data)

def contact_extract(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("contact_extract",cfg,doc)
    urls=[ensure_public_url(x) for x in (cfg.get("urls") or [])]
    if not urls:raise ValueError("urls is required")
    max_urls=max(1,min(50,int(cfg.get("max_urls") or 10)))
    email_re=re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])",re.I)
    phone_re=re.compile(r"(?<!\w)(\+?[0-9][0-9().\-\s]{6,20}[0-9])(?!\w)")
    records=[];failed=0
    for url in urls[:max_urls]:
        try:
            final,raw,_=fetch_public_bytes(url)
            text=raw.decode("utf-8","replace")
            parser=ContactParser();parser.feed(text)
            visible=" ".join(parser.text)
            emails={clean(x,254).lower() for x in parser.mailto if clean(x,254)}
            emails.update(clean(x,254).lower() for x in email_re.findall(visible))
            phones={clean(x,80) for x in parser.tel if clean(x,80)}
            phones.update(clean(x,80) for x in phone_re.findall(visible))
            for email in sorted(emails):
                records.append({"id":rid("contact","email",email,final),"text":f"Public email evidence: {email}.","observed_at":now(),"metadata":{"source":"public_page","kind":"email","value":email,"state":"DISCOVERED","evidence_url":final}})
            for phone in sorted(phones):
                records.append({"id":rid("contact","phone",phone,final),"text":f"Public phone evidence: {phone}.","observed_at":now(),"metadata":{"source":"public_page","kind":"phone","value":phone,"state":"DISCOVERED","evidence_url":final}})
        except Exception:
            failed+=1
    return records,failed,{"requested":min(len(urls),max_urls),"state":"DISCOVERED","verification":"not_performed"}

def safe_final_url(url:str):
    target=ensure_public_url(url)
    req=urllib.request.Request(target,headers={"User-Agent":UA,"Accept":"text/html","Range":"bytes=0-0"})
    with public_opener().open(req,timeout=20) as r:
        return ensure_public_url(r.geturl())

async def crawl4ai_real(cfg):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    urls=[safe_final_url(x) for x in (cfg.get("urls") or [])]
    if not urls:raise ValueError("urls is required")
    max_urls=max(1,min(20,int(cfg.get("max_urls") or 5)))
    browser=BrowserConfig(headless=True,text_mode=True,java_script_enabled=False,user_agent=UA,use_persistent_context=False)
    run_cfg=CrawlerRunConfig(cache_mode=CacheMode.BYPASS,check_robots_txt=True,exclude_external_links=True,page_timeout=30000,word_count_threshold=5)
    records=[];failed=0
    async with AsyncWebCrawler(config=browser) as crawler:
        for url in urls[:max_urls]:
            try:
                result=await crawler.arun(url=url,config=run_cfg)
                if not result.success: failed+=1;continue
                final=ensure_public_url(str(result.url or url))
                markdown=clean(getattr(result,"markdown",""),8000)
                records.append({"id":rid("crawl4ai",final),"text":markdown or final,"observed_at":now(),"metadata":{"source":"crawl4ai","url":final,"status_code":getattr(result,"status_code",None),"robots_txt":True,"javascript":False}})
            except Exception:
                failed+=1
    return records,failed,{"requested":min(len(urls),max_urls),"robots_txt":True,"javascript":False,"mode":"static"}

def crawl4ai_page(cfg):
    doc=fixture(cfg)
    return from_fixture("crawl4ai",cfg,doc) if doc is not None else asyncio.run(crawl4ai_real(cfg))

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


def duckdb_batch(cfg):
    import duckdb
    doc=fixture(cfg)
    rows=(doc.get("records") if isinstance(doc,dict) else doc) if doc is not None else cfg.get("records")
    if not isinstance(rows,list) or len(rows)>10000 or any(not isinstance(x,dict) for x in rows):
        raise ValueError("records must be a list of at most 10000 objects")
    if not rows:return [],0,{"engine":"duckdb","input":0}
    def ident(v):
        s=clean(v,80)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",s):raise ValueError("Invalid DuckDB field")
        return '"'+s+'"'
    filter_field=cfg.get("filter_field");order_by=cfg.get("order_by");distinct_field=cfg.get("distinct_field")
    direction=str(cfg.get("order_direction") or "asc").lower()
    if direction not in {"asc","desc"}:raise ValueError("order_direction must be asc or desc")
    limit=max(1,min(10000,int(cfg.get("limit") or len(rows))))
    with tempfile.TemporaryDirectory() as td:
        path=pathlib.Path(td)/"input.ndjson"
        path.write_text("\n".join(json.dumps(x,ensure_ascii=False,default=str) for x in rows)+"\n",encoding="utf-8")
        con=duckdb.connect(database=":memory:")
        con.execute("CREATE TABLE input AS SELECT * FROM read_json_auto(?)",[str(path)])
        query="SELECT * FROM input";params=[]
        if filter_field:
            query+=" WHERE "+ident(filter_field)+" = ?";params.append(cfg.get("filter_equals"))
        if order_by:query+=" ORDER BY "+ident(order_by)+" "+direction.upper()
        query+=" LIMIT ?";params.append(limit)
        cur=con.execute(query,params);names=[d[0] for d in cur.description];selected=[dict(zip(names,row)) for row in cur.fetchall()]
        con.close()
    if distinct_field:
        key=clean(distinct_field,80)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",key):raise ValueError("Invalid distinct field")
        seen=set();unique=[]
        for row in selected:
            marker=json.dumps(row.get(key),sort_keys=True,default=str)
            if marker in seen:continue
            seen.add(marker);unique.append(row)
        selected=unique
    records=[]
    for i,row in enumerate(selected):
        item_id=clean(row.get("id"),200) or rid("duckdb",i,json.dumps(row,sort_keys=True,default=str))
        text=clean(row.get("text") or row.get("title") or row.get("name") or item_id,6000)
        records.append({"id":item_id,"text":text,"observed_at":row.get("observed_at"),"metadata":{"source":"duckdb_batch","row":row}})
    return records,max(0,len(rows)-len(records)),{"engine":"duckdb","input":len(rows),"output":len(records),"filter_field":filter_field,"order_by":order_by,"distinct_field":distinct_field}

def tech_detect(cfg):
    doc=fixture(cfg)
    if doc is not None:return from_fixture("tech_detect",cfg,doc)
    urls=[ensure_public_url(x) for x in (cfg.get("urls") or [])]
    if not urls:raise ValueError("urls is required")
    records=[]
    for url in urls[:50]:
        techdir=pathlib.Path(__file__).resolve().parent/"techdetect"
        proc=subprocess.run(["go","run",".","--url",url],cwd=techdir,capture_output=True,text=True,timeout=90)
        if proc.returncode!=0:
            raise RuntimeError("tech detector failed: "+clean(proc.stderr,1200))
        data=json.loads(proc.stdout)
        tech=data.get("technologies") or []
        records.append({"id":rid("tech",url),"text":f"Technology fingerprint for {url}: {', '.join(tech[:100])}.","observed_at":now(),"metadata":{"source":"wappalyzergo","url":url,"technologies":tech[:200]}})
    return records,0,{"requested":min(len(urls),50),"engine":"wappalyzergo"}

HANDLERS={"crawlee_site":crawlee_site,"scrapling_page":scrapling_page,"jobspy_jobs":jobspy_jobs,"searxng_search":searxng_search,"tech_detect":tech_detect,"contact_extract":contact_extract,"crawl4ai_page":crawl4ai_page,"duckdb_batch":duckdb_batch}

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
