import sqlite3
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import biz_hira as biz


def response_text(*rows):
    # Schema captured from the anonymous homepage's actual dsBoard response.
    columns = ['bbsId', 'itemId', 'title', 'regNm', 'regDate']
    return biz.RS.join(['SSV:UTF-8', 'ErrorCode:string=0', 'Dataset:dsPopupZone',
                         'Dataset:dsBoard', biz.US.join(['_RowType_'] +
                         [c + ':string(32)' for c in columns]),
                         *[biz.US.join(['N', *row]) for row in rows], '',
                         'Dataset:gdsSysInfo', ''])


ROW = ['BBSMSTR_000000000675', '75929', '「2026년 이의신청 요양기관 설명회」개최 안내',
       '담당자', '20260921100846000']


class ParsingTests(unittest.TestCase):
    def test_observed_schema_and_date(self):
        notice, = biz.parse_main_notices(response_text(ROW))
        self.assertEqual(notice.item_id, '75929')
        self.assertEqual(notice.registered_at, '2026-09-21')
        self.assertEqual(notice.key, replace(notice, title='수정된 제목').key)
        self.assertNotEqual(notice.key, replace(notice, bbs_id='other').key)

    def test_fallback_and_same_day_multiple_items(self):
        notice, = biz.parse_main_notices(response_text([ROW[0], biz.ETX, *ROW[2:]]))
        self.assertEqual(notice.item_id, '')
        self.assertNotEqual(notice.key, replace(notice, title='다른 공지').key)

    def test_invalid_responses_are_not_empty_success(self):
        for text in ['<html>error</html>', response_text(),
                     response_text(ROW).replace('regDate:', 'unknown:'),
                     response_text(ROW).replace('20260921100846000', '20261399100846000'),
                     response_text(ROW).replace('ErrorCode:string=0', 'ErrorCode:string=-1'),
                     response_text(ROW).replace('Dataset:dsBoard', 'Dataset:other')]:
            with self.subTest(text=text), self.assertRaises(biz.SSVError):
                biz.parse_main_notices(text)

    def test_conflicting_duplicate_rejected(self):
        with self.assertRaises(biz.SSVError):
            biz.parse_main_notices(response_text(ROW, [*ROW[:2], 'different', *ROW[3:]]))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.notice = biz.parse_main_notices(response_text(ROW))[0]
        self.clock = 1000

    def run_check(self, notices, sender=None, fetch=None):
        self.clock += 300
        return biz.run_main_notices(self.conn, send_notification=sender or Mock(),
                                    fetch=fetch or Mock(return_value=notices), now=self.clock)

    def test_first_run_notify_then_no_duplicate_or_title_update(self):
        sender = Mock()
        self.assertEqual(self.run_check([self.notice], sender), (1, 1, 0))
        self.assertEqual(self.run_check([replace(self.notice, title='수정')], sender), (0, 0, 0))
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(self.conn.execute('SELECT title FROM biz_main_notices').fetchone()[0], '수정')

    def test_same_day_new_id_and_returning_old_notice(self):
        other = replace(self.notice, item_id='75930')
        self.run_check([self.notice])
        self.assertEqual(self.run_check([other]), (1, 1, 0))
        self.assertEqual(self.run_check([self.notice, other]), (0, 0, 0))

    def test_failed_notification_retried_after_item_leaves_list(self):
        self.assertEqual(self.run_check([self.notice], Mock(side_effect=RuntimeError('send failed'))),
                         (1, 0, 1))
        self.assertEqual(self.run_check([replace(self.notice, item_id='other')]), (1, 2, 0))

    def test_collection_failure_preserves_snapshot_and_retries_pending(self):
        self.run_check([self.notice], Mock(side_effect=RuntimeError('send failed')))
        self.assertEqual(self.run_check([], fetch=Mock(side_effect=RuntimeError('timeout'))), (0, 1, 1))
        self.assertEqual(self.conn.execute('SELECT in_latest FROM biz_main_notices').fetchone()[0], 1)
        self.assertEqual(self.run_check([]), (0, 0, 1))
        self.assertEqual(self.conn.execute('SELECT in_latest FROM biz_main_notices').fetchone()[0], 1)

    def test_cooldown_survives_failure_and_skips_fetch(self):
        self.run_check([], fetch=Mock(side_effect=RuntimeError('timeout')))
        fetch = Mock()
        self.assertEqual(biz.run_main_notices(self.conn, send_notification=Mock(), fetch=fetch,
                                            now=self.clock + 20), (0, 0, 0))
        fetch.assert_not_called()


class BrowserTests(unittest.TestCase):
    def test_real_browser_captures_post_after_navigation_without_login(self):
        # Exercise Playwright networking offline using the exact observed endpoint/schema.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                context.route('https://biz.hira.or.kr/index.do', lambda route: route.fulfill(
                    content_type='text/html', body="""<html><body><script>
                    fetch('/qya/main/selectTotalZoneList.ndo', {method:'POST'});
                    </script></body></html>"""))
                context.route('**/selectTotalZoneList.ndo', lambda route: route.fulfill(
                    content_type='text/plain; charset=utf-8', body=response_text(ROW)))
                notices = biz.read_main_response(context.new_page(), timeout_ms=5000)
                self.assertEqual(notices[0].item_id, '75929')
                self.assertEqual(context.cookies(), [])
            finally:
                browser.close()

    def test_non_200_response_is_failure(self):
        page = Mock()
        response = Mock(status=503)
        page.expect_response.return_value.__enter__ = Mock(return_value=Mock(value=response))
        page.expect_response.return_value.__exit__ = Mock(return_value=False)
        with self.assertRaises(biz.SSVError):
            biz.read_main_response(page)


if __name__ == '__main__':
    unittest.main()
