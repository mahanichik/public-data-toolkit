# Public Data Workers

Generic public-data batch workers for reusable collection and normalization tasks.

Implemented sources:
- `overture_places`
- `gdelt_events`
- `overpass_places`
- `greenhouse_jobs`
- `lever_jobs`
- `ashby_jobs` — direct public Ashby job-board feed
- `crawlee_site` — robots-aware same-hostname HTTP crawling
- `scrapling_page` — plain public-page extraction; no stealth/access-control bypass
- `jobspy_jobs` — fallback multi-board job discovery
- `searxng_search` — client for a configured public SearXNG endpoint
- `tech_detect` — WappalyzerGo technology fingerprinting

Each run emits:
- `out/records.json`
- `out/receipt.json`

This repository is for public/non-sensitive inputs only. Do not provide credentials, private records, or confidential configuration.

## Normalized record

```json
{
  "id": "stable-source-id",
  "text": "bounded public evidence",
  "observed_at": "ISO-8601-or-null",
  "metadata": {"source": "source-key"}
}
```

## Manual run

Use **Actions → Run data worker** and provide a public source config.

Examples:

```json
{"bbox":[-0.14,51.50,-0.10,51.52],"category_terms":["hotel","restaurant"],"max_records":10000}
```

```json
{"query":"business opening OR hiring","timespan":"7d","max_records":250}
```


## Safety

Network tasks accept only public HTTP(S) targets. Crawlee respects robots.txt and automatic blocked-request bypass is disabled. The Scrapling adapter uses the plain fetcher only; no CAPTCHA, Turnstile, login, or access-control bypass is implemented.


## Contact evidence and browser fallback

- `contact_extract` extracts only public email/phone evidence visible on allowed pages and labels it `DISCOVERED`; it does not guess or verify mailbox ownership.
- `crawl4ai_page` is a static fallback using Crawl4AI 0.9.3 with robots checks enabled, JavaScript disabled, no persistent session, and public-network target validation.


## Deterministic bulk transform

- `duckdb_batch` provides bounded filter/sort/distinct/limit operations over up to 10,000 public records using DuckDB. It never accepts caller-supplied SQL.
