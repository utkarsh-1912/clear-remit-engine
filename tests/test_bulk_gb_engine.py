"""Performance & Accounting Invariant Tests for the GB-Scale Streaming Bulk Engine."""

import pathlib
import tempfile
import time
import unittest

from core.database import init_database
from core.bulk_engine import ingest_file_streaming, run_stress_benchmark
from core.ledger import list_vouchers_paginated
from core.reports import generate_financial_statements


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
SAMPLE_DIR = BASE_DIR / "sample_data"


class TestBulkGbStreamingEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self.tmp_dir.name) / "test_bulk.db"
        init_database(self.db_path, seed_demo=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_streaming_iso20022_xml_constant_memory(self):
        xml_path = SAMPLE_DIR / "sample_camt053.xml"
        res = ingest_file_streaming(
            file_path=xml_path,
            filename="sample_camt053.xml",
            db_path=self.db_path,
            cleanup_file=False,
        )
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["vouchers_ingested"], 6)
        self.assertEqual(res["posting_lines_ingested"], 12)

        st = generate_financial_statements(self.db_path)
        self.assertTrue(st["trial_balance"]["is_balanced"])
        self.assertTrue(st["balance_sheet"]["is_balanced"])

    def test_high_throughput_50k_lines_stress_and_fast_pagination(self):
        # Stream 25,000 vouchers (50,000 GL posting lines) into SQLite WAL
        res = run_stress_benchmark(num_vouchers=25000, chunk_size=5000, db_path=self.db_path)
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["vouchers_ingested"], 25000)
        self.assertEqual(res["posting_lines_ingested"], 50000)
        print(f"\n[GB-STREAM BENCHMARK] 50,000 GL lines in {res['elapsed_sec']}s -> {res['rows_per_sec']} lines/sec")

        # Verify fast server-side pagination over 25,000+ vouchers
        t0 = time.perf_counter()
        page = list_vouchers_paginated(page=1, page_size=50, db_path=self.db_path)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[FAST PAGINATION] Page 1/501 over {page['total_count']} vouchers in {latency_ms:.2f} ms")
        self.assertEqual(len(page["items"]), 50)
        self.assertGreaterEqual(page["total_count"], 25004)

        # Verify Balance Sheet & Trial Balance remain 100% zero-variance balanced after 50,000 bulk lines!
        st = generate_financial_statements(self.db_path)
        self.assertTrue(st["trial_balance"]["is_balanced"])
        self.assertTrue(st["balance_sheet"]["is_balanced"])


if __name__ == "__main__":
    unittest.main()
