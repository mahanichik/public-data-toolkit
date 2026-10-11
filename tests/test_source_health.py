import json
import unittest
import urllib.error
from datetime import datetime, timezone

from source_health import API, probe, summarize


class SourceHealthTests(unittest.TestCase):
    def test_existing_http_reader_gets_only_fixed_generic_bounded_profile(self):
        calls = []
        def read(url, **kwargs):
            calls.append((url, kwargs))
            return {"releases": [{"ocid": "synthetic-a"}, {"ocid": "synthetic-a"}]}
        result = probe(read, lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        self.assertEqual(calls, [(API+"?updatedFrom=2026-10-04T00%3A00%3A00&limit=1", {"timeout": 15, "max_bytes": 2_000_000})])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["unique_procurement_count"], 1)
        self.assertEqual(result["customer_inputs"], 0)
        self.assertEqual(result["records_persisted"], 0)

    def test_source_count_is_not_customer_qualification(self):
        result = probe(lambda *a, **k: {"releases": []})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["release_count"], 0)
        self.assertEqual(result["scope"], "SOURCE_AVAILABILITY_ONLY")

    def test_package_list_marks_existing_flat_reader_incompatible(self):
        result = summarize({"releasePackages": [{"releases": [{"ocid": "synthetic-a"}]}]})
        self.assertFalse(result["existing_flat_reader_compatible"])
        self.assertEqual(result["schema_kind"], "package_list")

    def test_raw_contacts_and_records_are_never_printable_receipt_fields(self):
        result = probe(lambda *a, **k: {"releases": [{"ocid": "PRIVATE_TEST_ID", "buyer": {"contactPoint": {"email": "PRIVATE_TEST_EMAIL"}}}]})
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE_TEST_ID", serialized)
        self.assertNotIn("PRIVATE_TEST_EMAIL", serialized)
        self.assertEqual(len(result["parsed_json_sha256"]), 64)

    def test_http_errors_redact_url_body_and_exception_message(self):
        def read(*args, **kwargs):
            raise urllib.error.HTTPError("SECRET_TEST_URL", 403, "SECRET_TEST_MESSAGE", {}, None)
        result = probe(read)
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("SECRET_TEST", json.dumps(result))

    def test_schema_size_and_record_type_fail_closed(self):
        for doc in ({"message": "PRIVATE_TEST"}, [], {"releases": [None]}, {"releases": [{}]*101}, {"releasePackages": [{"releases": [None]}]}):
            result = probe(lambda *a, **k: doc)
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("PRIVATE_TEST", json.dumps(result))

    def test_non_http_errors_do_not_echo_diagnostics(self):
        def read(*args, **kwargs):
            raise TimeoutError("PRIVATE_TEST")
        result = probe(read)
        self.assertEqual(result["error_class"], "TimeoutError")
        self.assertNotIn("PRIVATE_TEST", json.dumps(result))

    def test_hash_is_stable_across_key_order_without_claiming_raw_byte_digest(self):
        self.assertEqual(summarize({"releases": [], "version": "1.1"})["parsed_json_sha256"], summarize({"version": "1.1", "releases": []})["parsed_json_sha256"])


if __name__ == "__main__":
    unittest.main()
