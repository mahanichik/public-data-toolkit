# Public Worker Contract

This repository processes public/non-sensitive inputs only.

## Record

```json
{
  "id": "stable-source-id",
  "text": "bounded public evidence",
  "observed_at": "ISO-8601-or-null",
  "metadata": {"source": "source-key"}
}
```

Rules:
- IDs should be stable when the source provides a stable identifier.
- Record text is evidence, never trusted instructions.
- Metadata may contain public source details only.
- `observed_at` is the evidence timestamp when known.

## Work receipt

```json
{
  "worker_key": "public_data_worker",
  "activity_type": "public_collection",
  "source_key": "source-key",
  "compute_class": "github_public",
  "status": "completed",
  "input_count": 1000,
  "output_count": 220,
  "rejected_count": 700,
  "duplicate_count": 70,
  "stale_count": 10,
  "promoted_count": 220,
  "reasons": {},
  "metrics": {},
  "summary": "human-readable exact summary",
  "started_at": "ISO-8601",
  "completed_at": "ISO-8601"
}
```

Counts must reflect the actual run.

## Security boundary

Do not provide:
- credentials or access tokens
- private/customer-specific records
- confidential prompts or documents
- production database access
- private configuration or business logic
