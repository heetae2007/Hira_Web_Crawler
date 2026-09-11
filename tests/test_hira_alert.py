import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class AlertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"LOG_PATH": str(Path(cls.logs.name) / "test.log")}):
            cls.app = importlib.import_module("hira_alert")

    @classmethod
    def tearDownClass(cls):
        import logging
        logging.shutdown()
        cls.logs.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in {
            "DB_PATH": Path(self.tmp.name) / "test.db",
            "RSS_FEEDS": {"test": "https://example.invalid/feed"},
            "INCLUDE_KEYWORDS": [], "EXCLUDE_KEYWORDS": [],
        }.items():
            p = patch.object(self.app, name, value)
            p.start()
            self.addCleanup(p.stop)

    def entry(self, ident, published):
        return SimpleNamespace(id=ident, title="방문진료 모집 결과", link=ident, published=published)

    def run_feed(self, entries, sender):
        with patch.object(self.app, "fetch_feed", return_value=SimpleNamespace(entries=entries)), \
             patch.object(self.app, "send_telegram", sender):
            return self.app.run()

    def test_dates_and_korean_midnight(self):
        for raw, expected in [
            ("20260908 23:59:59", "2026-09-08"),
            ("20260909 00:00:00", "2026-09-09"),
            ("2026-09-08T15:00:00Z", "2026-09-09"),
            ("Tue, 08 Sep 2026 14:59:59 GMT", "2026-09-08"),
            ("2026-09-09", "2026-09-09"),
        ]:
            self.assertEqual(self.app.publication_date(raw).isoformat(), expected)
        for raw in ("", "invalid", "20261399 00:00:00"):
            with self.assertRaises(ValueError):
                self.app.publication_date(raw)

    def test_first_run_cutoff_and_no_duplicate(self):
        entries = [self.entry("new", "20260909 00:00:00"), self.entry("old", "20260908 23:59:59")]
        sent = []
        self.assertEqual(self.run_feed(entries, sent.append), 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.run_feed(entries, sent.append), 0)
        self.assertEqual(len(sent), 1)
        conn = self.app.connect_db()
        self.assertEqual(conn.execute("select count(*) from seen_items").fetchone()[0], 2)
        self.assertEqual(conn.execute("select count(*) from seen_items where notified_at is not null").fetchone()[0], 1)
        conn.close()

    def test_existing_unnotified_outside_rss_and_retry(self):
        conn = self.app.connect_db()
        e = self.entry("missed", "20260910 16:00:00")
        self.app.mark_seen(conn, self.app.make_item_key("test", e), "test", e.title, e.link, e.published, False)
        before = conn.execute("select first_seen_at from seen_items").fetchone()[0]
        conn.close()
        def fail(message):
            raise RuntimeError("simulated failure")
        self.assertEqual(self.run_feed([], fail), 1)
        sent = []
        self.assertEqual(self.run_feed([], sent.append), 0)
        self.assertEqual(self.run_feed([], sent.append), 0)
        self.assertEqual(len(sent), 1)
        conn = self.app.connect_db()
        row = conn.execute("select first_seen_at, notified_at from seen_items").fetchone()
        conn.close()
        self.assertEqual(row[0], before)
        self.assertIsNotNone(row[1])

    def test_missing_date_is_held_then_retried(self):
        sent = []
        self.assertEqual(self.run_feed([self.entry("unknown", "")], sent.append), 1)
        self.assertEqual(sent, [])
        self.assertEqual(self.run_feed([self.entry("unknown", "20260909")], sent.append), 0)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
