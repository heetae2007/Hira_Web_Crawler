import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import biz_hira as biz
import eform_hira as ef


def payload(page=1, total=21):
    columns = ['rn', 'totCnt', 'brdId', 'brdTtl', 'creDt']
    rows = [[str(i), str(total), str(3000 + i), '공지 ' + str(i), '2026-09-22 09:00']
            for i in range((page - 1) * 20 + 1, min(page * 20, total) + 1)]
    return biz.RS.join(['SSV:utf-8', 'ErrorCode:int=0', 'Dataset:dsList',
                         biz.US.join(['_RowType_'] + [c + ':STRING(256)' for c in columns]),
                         *[biz.US.join(['N', *row]) for row in rows], '', ''])


class EformParsingTests(unittest.TestCase):
    def test_request_matches_captured_field_order_and_nulls(self):
        body = ef.build_request(2)
        records = body.decode().split(biz.RS)
        self.assertEqual(records[0:2], ['SSV:utf-8', 'Dataset:dsCond'])
        self.assertEqual(records[2].split(biz.US)[1:], [c + ':STRING(256)' for c in ef.COLUMNS])
        self.assertEqual(records[3].split(biz.US),
                         ['N', biz.ETX, biz.ETX, '', '0', biz.ETX, '20', '2', biz.ETX,
                          '', 'W', biz.ETX, ''])
        self.assertNotIn(b'WMONID', body)
        with self.assertRaises(ValueError):
            ef.build_request(0)

    def test_actual_public_response(self):
        captured = (Path(__file__).parent / 'fixtures' / 'eform_list.ssv').read_text(encoding='utf-8')
        notices, total = ef.parse_page(captured)
        self.assertEqual((len(notices), total), (20, 208))
        self.assertEqual(notices[0].item_id, '2174')
        self.assertEqual(notices[0].registered_at, '2026-09-14')
        self.assertIn('사용자매뉴얼 배포', notices[0].title)
        # creDt (creation), not chgDt (last edit).
        self.assertEqual(notices[1].registered_at, '2026-09-04')

    def test_invalid_and_incomplete_pages_fail(self):
        for text, number in [('<html>login</html>', 1), (payload(), 2),
                             (payload().replace('ErrorCode:int=0', 'ErrorCode:int=-1'), 1),
                             (payload().replace('creDt:', 'wrong:'), 1),
                             (payload().replace('2026-09-22 09:00', 'invalid'), 1),
                             (payload().replace(biz.US + '21' + biz.US,
                                                biz.US + '99' + biz.US, 1), 1),
                             (payload(total=0), 1)]:
            with self.subTest(number=number), self.assertRaises(biz.SSVError):
                ef.parse_page(text, number)


class FetchTests(unittest.TestCase):
    def context(self, *responses):
        context = Mock()
        context.new_page.return_value.goto.return_value.status = 200
        context.request.post.side_effect = responses
        return context

    def response(self, text, status=200):
        response = Mock(status=status)
        response.text.return_value = text
        return response

    def test_paging_headers_and_shared_context(self):
        first, last = self.response(payload()), self.response(payload(2))
        context = self.context(first, last)
        sleep = Mock()
        self.assertEqual(len(ef.fetch_with_context(context, pages=5, sleep=sleep)), 21)
        self.assertEqual(context.request.post.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        context.new_page.return_value.goto.assert_called_once()
        kwargs = context.request.post.call_args.kwargs
        self.assertEqual(kwargs['data'], ef.build_request(2))
        self.assertEqual(kwargs['headers']['Content-Type'], 'text/xml')
        self.assertNotIn('Cookie', kwargs['headers'])
        self.assertEqual(kwargs['max_redirects'], 0)
        first.dispose.assert_called_once()
        last.dispose.assert_called_once()

    def test_http_error_and_repeated_page_fail_without_retry(self):
        for responses in [(self.response('', 302),), (self.response('', 503),),
                          (self.response(payload()), self.response(payload()))]:
            context = self.context(*responses)
            with self.assertRaises(biz.SSVError):
                ef.fetch_with_context(context, pages=2, sleep=Mock())
            self.assertEqual(context.request.post.call_count, len(responses))

    def test_page_limit(self):
        context = self.context(self.response(payload()))
        self.assertEqual(len(ef.fetch_with_context(context, pages=1, sleep=Mock())), 20)
        context.request.post.assert_called_once()
        with self.assertRaises(ValueError):
            ef.fetch_with_context(context, pages=11)


class StorageTests(unittest.TestCase):
    def test_source_isolation_retry_cooldown_and_preserve_snapshot(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        notice = biz.MainNotice('W', '1', 'e-form 공지', '2026-09-22')
        sender = Mock()
        # Identical keys across sources must never suppress e-form notification.
        biz.run_main_notices(conn, send_notification=sender, fetch=lambda: [notice], now=1000)
        sender.reset_mock()
        sender.side_effect = RuntimeError('send failed')
        self.assertEqual(ef.run_eform(conn, send_notification=sender, fetch=lambda: [notice], now=1000),
                         (1, 0, 1))
        sender.side_effect = None
        fetch = Mock(side_effect=RuntimeError('timeout'))
        self.assertEqual(ef.run_eform(conn, send_notification=sender, fetch=fetch, now=1001), (0, 0, 0))
        fetch.assert_not_called()
        self.assertEqual(ef.run_eform(conn, send_notification=sender, fetch=fetch, now=1300), (0, 1, 1))
        self.assertIn('e-Form', sender.call_args.args[0])
        self.assertEqual(conn.execute('SELECT in_latest FROM eform_notices').fetchone()[0], 1)
        self.assertEqual(ef.run_eform(conn, send_notification=sender,
                                     fetch=lambda: [replace(notice, title='수정')], now=1600), (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
