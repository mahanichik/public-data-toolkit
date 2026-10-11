#!/usr/bin/env python3
"""Read-only generic source probe. No coordinator, customer inputs or raw output.

Uses the toolkit's existing bounded HTTP reader. The fixed government dataset
profile is independent of any customer's brief or selected procurement.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from worker import http_json

API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
PROFILE = "uk_recent_public_procurement_source_health_v1"


def summarize(doc):
    if not isinstance(doc, dict):
        raise ValueError("Unrecognized source schema")
    releases = doc.get("releases")
    packages = doc.get("releasePackages")
    if isinstance(releases, list):
        if len(releases) > 100 or any(not isinstance(r, dict) for r in releases):
            raise ValueError("Invalid bounded release package")
        kind, package_count = "release_package", 1
    elif isinstance(packages, list):
        if len(packages) > 100 or any(not isinstance(p, dict) or not isinstance(p.get("releases"), list) for p in packages):
            raise ValueError("Invalid bounded package list")
        releases = [r for p in packages for r in p["releases"]]
        if len(releases) > 100 or any(not isinstance(r, dict) for r in releases):
            raise ValueError("Invalid bounded release package")
        kind, package_count = "package_list", len(packages)
    else:
        raise ValueError("Unrecognized source schema")
    return {
        "schema_kind": kind,
        "package_count": package_count,
        "release_count": len(releases),
        "unique_procurement_count": len({r["ocid"] for r in releases if isinstance(r.get("ocid"), str)}),
        "existing_flat_reader_compatible": kind == "release_package",
        "parsed_json_sha256": hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
    }


def probe(fetch_json=http_json, clock=lambda: datetime.now(timezone.utc)):
    observed = clock()
    if observed.tzinfo is None:
        raise ValueError("Probe clock must include timezone")
    observed = observed.astimezone(timezone.utc)
    query = urlencode({"updatedFrom": (observed-timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S"), "limit": "1"})
    receipt = {"profile": PROFILE, "observed_at": observed.isoformat(), "mode": "READ_ONLY_GENERIC_SOURCE", "scope": "SOURCE_AVAILABILITY_ONLY", "customer_inputs": 0, "records_persisted": 0}
    try:
        doc = fetch_json(API+"?"+query, timeout=15, max_bytes=2_000_000)
        receipt.update(status="completed", **summarize(doc))
    except urllib.error.HTTPError as error:
        receipt.update(status="failed", reason="source_http_error", http_status=int(error.code))
    except Exception as error:
        # Exception URL, body, upstream contact data and traceback never leave.
        receipt.update(status="failed", reason="source_read_or_schema_error", error_class=type(error).__name__)
    return receipt


def main():
    receipt = probe()
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
