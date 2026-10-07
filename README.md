# Public Data Workers

Generic public-data batch workers for reusable collection and normalization tasks.

Implemented sources:
- `overture_places`
- `gdelt_events`
- `overpass_places`
- `greenhouse_jobs`
- `lever_jobs`

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
