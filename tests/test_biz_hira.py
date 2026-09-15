import sqlite3
import unittest
from dataclasses import replace
from datetime import date, datetime
from unittest.mock import Mock, patch

import requests

import biz_hira as biz

BBS = "BBSMSTR_000000000675"


def row(ident="75913", **changes):
    return {"nttId": ident, "bbsId": BBS, "nttNo": "10",
            "nttSj": "[행위] 고시 제2026-182호", "nttCn": "<p>본문</p>",
            "frstregisterPntt": "20260915102852000", "lastUpdusrPnttm": "20260915102852000",
            "atchFileId": "", "isNotice": "N", **changes}


def dataset(rows, name="dsMain", columns=None):
    columns = columns or list(row())
    return biz.RS.join([f"Dataset:{name}",
                        biz.US.join(["_RowType_"] + [f"{c}:string(4000)" for c in columns]),
                        *[biz.US.join(["N"] + [r.get(c, "") for c in columns]) for r in rows], ""])


def ssv(rows):
    return "SSV:utf-8" + biz.RS + "ErrorCode=0" + biz.RS + dataset(rows)


class ParserTests(unittest.TestCase):
    def test_twenty_rows_and_multiple_datasets(self):
        rows = [row(str(i)) for i in range(20)]
        text = "SSV:utf-8" + biz.RS + dataset([{"total": "20"}], "dsCount", ["total"]) + biz.RS
        text += dataset(rows) + biz.RS + dataset([{"x": "y"}], "dsOther", ["x"])
        self.assertEqual(biz.parse_ssv_dataset(text, "dsMain"), rows)

    def test_empty_dataset(self):
        self.assertEqual(biz.parse_ssv_dataset(ssv([]), "dsMain"), [])
        self.assertEqual(biz.parse_ssv_dataset("SSV:utf-8" + biz.RS + "Dataset:dsMain" + biz.RS, "dsMain"), [])

    def test_empty_values_pinned_and_korean_html(self):
        rows = [row("1", isNotice="Y", atchFileId=biz.ETX, nttCn=""),
                row("2", nttCn='<p>한글 &amp; 특수문자 "\'\n두 번째 줄</p>')]
        parsed = biz.parse_ssv_dataset(ssv(rows), "dsMain")
        self.assertEqual(parsed[0]["atchFileId"], "")
        self.assertEqual(parsed[0]["nttCn"], "")
        self.assertEqual(parsed[0]["isNotice"], "Y")
        self.assertEqual(parsed[1]["nttCn"], rows[1]["nttCn"])

    def test_malformed_and_error_responses_fail_closed(self):
        for text in ["<html>Login</html>", "SSV:utf-8" + biz.RS + "Dataset:other",
                     ssv([row()]).replace("ErrorCode=0", "ErrorCode=-1"),
                     ssv([row()]).replace("N" + biz.US + "75913", "N" + biz.US + "extra" + biz.US + "75913"),
                     ssv([row()]).replace(biz.US + "N" + biz.RS, biz.RS)]:
            with self.subTest(text=text[:50]), self.assertRaises(biz.SSVError):
                biz.parse_ssv_dataset(text, "dsMain")

    def test_constant_column_and_deleted_original_rows(self):
        text = biz.RS.join(["SSV:utf-8", "Dataset:dsMain", "_Const_" + biz.US + "bbsId:STRING=" + BBS,
                             "_RowType_" + biz.US + "nttId:INT", "N" + biz.US + "1",
                             "D" + biz.US + "2", "O" + biz.US + "3", ""])
        self.assertEqual(biz.parse_ssv_dataset(text, "dsMain"), [{"bbsId": BBS, "nttId": "1"}])

    def test_request_body_and_offsets(self):
        body = biz.build_list_request(BBS, 2)
        parsed = biz.parse_ssv_dataset(body.decode(), "dsParam")[0]
        self.assertEqual(parsed, {"bbsId": BBS, "currentPage": "2", "firstIndex": "20",
                                  "lastIndex": "40", "recordCountPerPage": "20",
                                  "cbSearchCnd": "all", "edSearchWrd": ""})

    def test_missing_identity_or_schema_is_error(self):
        for value in [row(""), {"nttId": "1"}, row(bbsId="another")]:
            with self.assertRaises(biz.SSVError):
                biz.BizPost.from_row(value, BBS)


class ClassificationTests(unittest.TestCase):
    def test_gosi_title_and_body(self):
        for title, content, expected in [
            ("[행위] 고시 제2026-182호", "", ["2026-182"]),
            ("보건복지부 고시 제2026-183호", "", ["2026-183"]),
            ("고시 제2026 - 184호", "", ["2026-184"]),
            ("안내", "<p>고시&nbsp;제2026 - <b>184</b> 호</p>", ["2026-184"]),
            ("일부개정 안내", "개정 내용", []),
            ("고시 제2026-182호", "고시 제2026-182호 / 고시 제2026-183호", ["2026-182", "2026-183"]),
        ]:
            with self.subTest(title=title):
                self.assertEqual(biz.extract_gosi_numbers(title, content), expected)

    def test_prefix(self):
        post = biz.BizPost.from_row(row(), BBS)
        self.assertEqual(post.notice_type, "행위")
        self.assertEqual(replace(post, title="[행위 및 치료재료] 안내").notice_type, "행위 및 치료재료")
        self.assertIsNone(replace(post, title="일반 안내").notice_type)


class PaginationTests(unittest.TestCase):
    def test_pinned_first_and_new_on_second_page(self):
        pinned = row("pin", isNotice="Y")
        fetch = Mock(side_effect=[[pinned, *[row(str(i)) for i in range(20)]],
                                  [pinned, row("second-page")], [pinned]])
        posts = list(biz.crawl_biz_hira(BBS, fetch_page=fetch))
        self.assertEqual(len(posts), 22)
        self.assertIn("second-page", [p.ntt_id for p in posts])
        self.assertEqual(fetch.call_count, 3)

    def test_repeated_page_and_limit_are_errors(self):
        with self.assertRaises(biz.SSVError):
            list(biz.crawl_biz_hira(BBS, fetch_page=Mock(return_value=[row()])))
        with self.assertRaises(biz.SSVError):
            list(biz.crawl_biz_hira(BBS, max_pages=1, fetch_page=Mock(return_value=[row()])))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        biz.init_biz_db(self.conn)
        self.post = biz.BizPost.from_row(row(), BBS)

    def run_source(self, posts, sender):
        with patch.object(biz, "crawl_biz_hira", return_value=iter(posts)):
            return biz.run_biz(self.conn, [BBS], notify_from_date=date(2026, 9, 9),
                               publication_date=lambda v: datetime.strptime(v, "%Y%m%d%H%M%S%f").date(),
                               matches_keywords=lambda title, summary: True, send_telegram=sender)

    def test_new_unchanged_updated(self):
        self.assertEqual(biz.store_biz_post(self.conn, self.post), "NEW")
        created = self.conn.execute("SELECT created_at FROM biz_posts").fetchone()[0]
        self.assertEqual(biz.store_biz_post(self.conn, self.post), "UNCHANGED")
        for changes in [{"modified_at": "20260916102852000"}, {"title": "바뀐 제목"},
                        {"attachment_id": "new-file"}, {"content": "바뀐 본문"}]:
            with self.subTest(changes=changes):
                self.assertEqual(biz.store_biz_post(self.conn, replace(self.post, **changes)), "UPDATED")
        self.assertEqual(self.conn.execute("SELECT created_at FROM biz_posts").fetchone()[0], created)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM biz_posts").fetchone()[0], 1)

    def test_board_identity_isolated(self):
        biz.store_biz_post(self.conn, self.post)
        self.assertEqual(biz.store_biz_post(self.conn, replace(self.post, bbs_id="other")), "NEW")

    def test_cutoff_classification_and_update_notifications(self):
        sender = Mock()
        old = replace(self.post, ntt_id="old", registered_at="20260908120000000")
        general = replace(self.post, ntt_id="general", title="일부개정 안내", content="")
        self.assertEqual(self.run_source([self.post, old, general], sender), (3, 1, 0))
        self.assertEqual(self.run_source([self.post, old, general], sender), (0, 0, 0))
        changed = replace(self.post, attachment_id="new")
        self.assertEqual(self.run_source([changed], sender), (0, 1, 0))
        self.assertIn("수정 알림", sender.call_args.args[0])
        self.assertEqual(self.run_source([changed], sender), (0, 0, 0))

    def test_failed_new_and_update_retry_after_disappearing(self):
        sender = Mock(side_effect=RuntimeError("simulated failure"))
        self.assertEqual(self.run_source([self.post], sender), (1, 0, 1))
        sender.side_effect = None
        self.assertEqual(self.run_source([], sender), (0, 1, 0))
        changed = replace(self.post, modified_at="20260916102852000")
        sender.side_effect = RuntimeError("simulated failure")
        self.assertEqual(self.run_source([changed], sender), (0, 0, 1))
        sender.side_effect = None
        self.assertEqual(self.run_source([], sender), (0, 1, 0))
        self.assertIn("수정 알림", sender.call_args.args[0])
        self.assertEqual(self.run_source([], sender), (0, 0, 0))

    def test_unknown_date_saved_and_retried(self):
        self.assertEqual(self.run_source([replace(self.post, registered_at="")], Mock()), (1, 0, 1))
        self.assertEqual(self.run_source([self.post], Mock()), (0, 1, 0))

    def test_second_page_update_even_when_first_page_known(self):
        biz.store_biz_post(self.conn, self.post)
        older = replace(self.post, ntt_id="older")
        biz.store_biz_post(self.conn, older)
        fetch = Mock(side_effect=[[row()], [row("older", atchFileId="changed")], []])
        with patch.object(biz, "fetch_biz_page", fetch):
            states = [biz.store_biz_post(self.conn, p) for p in biz.crawl_biz_hira(BBS)]
        self.assertEqual(states, ["UNCHANGED", "UPDATED"])

    def test_keyword_filter_uses_body_and_can_be_re_evaluated(self):
        sender = Mock()
        matcher = Mock(return_value=False)
        with patch.object(biz, "crawl_biz_hira", return_value=iter([self.post])):
            result = biz.run_biz(self.conn, [BBS], notify_from_date=date(2026, 9, 9),
                                 publication_date=lambda v: date(2026, 9, 15),
                                 matches_keywords=matcher, send_telegram=sender)
        self.assertEqual(result, (1, 0, 0))
        self.assertIn("본문", matcher.call_args.args[1])
        self.assertEqual(self.run_source([], sender), (0, 1, 0))


class HttpTests(unittest.TestCase):
    def response(self, status=200):
        response = Mock(status_code=status, content=ssv([row()]).encode())
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_cookie_free_ssv_request(self):
        with patch.object(biz.requests, "post", return_value=self.response()) as post:
            self.assertEqual(len(biz.fetch_biz_page(BBS, 1)), 1)
        args = post.call_args.kwargs
        self.assertIsInstance(args["data"], bytes)
        self.assertNotIn("cookies", args)
        self.assertNotIn("Cookie", args["headers"])
        self.assertEqual(args["timeout"], (10, 30))
        self.assertFalse(args["allow_redirects"])

    def test_retry_timeout_and_503(self):
        with patch.object(biz.requests, "post", side_effect=[requests.Timeout(), self.response(503), self.response()]) as post, \
             patch.object(biz.time, "sleep"):
            self.assertEqual(len(biz.fetch_biz_page(BBS, 1)), 1)
            self.assertEqual(post.call_count, 3)

    def test_redirect_rejected(self):
        with patch.object(biz.requests, "post", return_value=self.response(302)), self.assertRaises(biz.SSVError):
            biz.fetch_biz_page(BBS, 1)


if __name__ == "__main__":
    unittest.main()
