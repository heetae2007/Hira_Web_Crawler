import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hira_alert import runner
from hira_alert.config import Settings
from hira_alert.dates import publication_date
from hira_alert.db import connect_db
from hira_alert.keywords import matches_keywords
from hira_alert.sources import rss


class ConfigTests(unittest.TestCase):
    def test_from_env_parses_and_clamps(self):
        s = Settings.from_env({
            "TELEGRAM_BOT_TOKEN": " t ", "INCLUDE_KEYWORDS": "고시, 수가,,", "EXCLUDE_KEYWORDS": "채용",
            "BIZ_MODE": "BOTH", "BIZ_BBS_IDS": "A,B,A", "EFORM_ENABLED": "no", "EFORM_MIN_INTERVAL": "5",
        })
        self.assertEqual(s.telegram_bot_token, "t")
        self.assertEqual(s.include_keywords, ("고시", "수가"))
        self.assertEqual(s.exclude_keywords, ("채용",))
        self.assertEqual((s.biz_mode, s.biz_bbs_ids), ("both", ("A", "B")))
        self.assertFalse(s.eform_enabled)
        self.assertEqual(s.eform_min_interval, 60)

    def test_keywords(self):
        self.assertTrue(matches_keywords("고시 안내"))
        self.assertFalse(matches_keywords("채용 고시", exclude=("채용",)))
        self.assertFalse(matches_keywords("공지", include=("고시",)))


class DateTests(unittest.TestCase):
    def test_dates_and_korean_midnight(self):
        for raw, expected in [
            ("20260908 23:59:59", "2026-09-08"),
            ("20260909 00:00:00", "2026-09-09"),
            ("2026-09-08T15:00:00Z", "2026-09-09"),
            ("Tue, 08 Sep 2026 14:59:59 GMT", "2026-09-08"),
            ("2026-09-09", "2026-09-09"),
            ("20260915102852000", "2026-09-15"),
        ]:
            self.assertEqual(publication_date(raw).isoformat(), expected)
        for raw in ("", "invalid", "20261399 00:00:00"):
            with self.assertRaises(ValueError):
                publication_date(raw)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = replace(
            Settings(), db_path=Path(self.tmp.name) / "test.db",
            rss_feeds={"test": "https://example.invalid/feed"},
            biz_mode="legacy", biz_bbs_ids=(), eform_enabled=False)

    def entry(self, ident, published):
        return SimpleNamespace(id=ident, title="방문진료 모집 결과", link=ident, published=published)

    def run_feed(self, entries, sender, settings=None):
        with patch.object(rss, "fetch_feed", return_value=SimpleNamespace(entries=entries)):
            return runner.run(settings or self.settings, send=sender)

    def test_first_run_cutoff_and_no_duplicate(self):
        entries = [self.entry("new", "20260909 00:00:00"), self.entry("old", "20260908 23:59:59")]
        sent = []
        self.assertEqual(self.run_feed(entries, sent.append), 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.run_feed(entries, sent.append), 0)
        self.assertEqual(len(sent), 1)
        conn = connect_db(self.settings.db_path)
        self.assertEqual(conn.execute("select count(*) from seen_items").fetchone()[0], 2)
        self.assertEqual(conn.execute("select count(*) from seen_items where notified_at is not null").fetchone()[0], 1)
        conn.close()

    def test_existing_unnotified_outside_rss_and_retry(self):
        conn = connect_db(self.settings.db_path)
        e = self.entry("missed", "20260910 16:00:00")
        rss.mark_seen(conn, rss.make_item_key("test", e), "test", e.title, e.link, e.published, False)
        before = conn.execute("select first_seen_at from seen_items").fetchone()[0]
        conn.close()

        def fail(message):
            raise RuntimeError("simulated failure")
        self.assertEqual(self.run_feed([], fail), 1)
        sent = []
        self.assertEqual(self.run_feed([], sent.append), 0)
        self.assertEqual(self.run_feed([], sent.append), 0)
        self.assertEqual(len(sent), 1)
        conn = connect_db(self.settings.db_path)
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

    def test_keyword_filter_stores_without_sending(self):
        sent = []
        settings = replace(self.settings, exclude_keywords=("방문진료",))
        self.assertEqual(self.run_feed([self.entry("x", "20260909")], sent.append, settings), 0)
        self.assertEqual(sent, [])

    def test_invalid_biz_mode_fails(self):
        self.assertEqual(runner.run(replace(self.settings, biz_mode="bogus"), send=lambda m: None), 1)

    def test_biz_failure_does_not_prevent_rss_notification(self):
        sent = []
        settings = replace(self.settings, biz_bbs_ids=("board",))
        with patch.object(runner.biz_legacy, "run_biz", side_effect=RuntimeError("simulated biz failure")):
            self.assertEqual(self.run_feed([self.entry("rss", "20260909")], sent.append, settings), 1)
        self.assertEqual(len(sent), 1)

    def test_main_mode_uses_existing_sender_without_legacy_crawl(self):
        sent = []
        settings = replace(self.settings, biz_mode="main")
        with patch.object(runner.biz_main, "run_main_notices", return_value=(2, 2, 0)) as main, \
             patch.object(runner.biz_legacy, "run_biz") as legacy:
            self.assertEqual(self.run_feed([], sent.append, settings), 0)
        self.assertEqual(main.call_args.kwargs["send_notification"], sent.append)
        legacy.assert_not_called()

    def test_eform_enabled_uses_existing_sender(self):
        sent = []
        settings = replace(self.settings, eform_enabled=True)
        with patch.object(runner.eform, "run_eform", return_value=(1, 1, 0)) as ef:
            self.assertEqual(self.run_feed([], sent.append, settings), 0)
        self.assertEqual(ef.call_args.kwargs["send_notification"], sent.append)

    def test_eform_failure_preserves_rss_delivery(self):
        sent = []
        settings = replace(self.settings, eform_enabled=True)
        with patch.object(runner.eform, "run_eform", side_effect=RuntimeError("eform failed")):
            self.assertEqual(self.run_feed([self.entry("rss", "20260909")], sent.append, settings), 1)
        self.assertEqual(len(sent), 1)

    def test_biz_table_added_to_existing_rss_database(self):
        sent = []
        entry = self.entry("rss", "20260909")
        self.assertEqual(self.run_feed([entry], sent.append), 0)
        settings = replace(self.settings, biz_bbs_ids=("board",))
        with patch.object(runner.biz_legacy, "crawl_biz_hira", return_value=iter([])):
            self.assertEqual(self.run_feed([entry], sent.append, settings), 0)
        self.assertEqual(len(sent), 1)
        conn = connect_db(self.settings.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM biz_posts").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
