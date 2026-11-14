"""업무포털 메인 공지사항 (비로그인 Playwright)."""

import html
import re
from datetime import datetime
from urllib.parse import urlsplit

from ..ssv import SSVError, parse_ssv_dataset
from .notice_board import MainNotice, NoticeSource, run_notice_source

PORTAL_URL = "https://biz.hira.or.kr/"
MAIN_URL = PORTAL_URL + "index.do"
MAIN_LIST_PATH = "/qya/main/selectTotalZoneList.ndo"
SOURCE = NoticeSource("biz:main", "biz_main", "심평원 업무포털", MAIN_URL)


def parse_main_notices(text: str) -> list[MainNotice]:
    """Use the dsBoard schema observed in the public homepage response."""
    notices = {}
    for row in parse_ssv_dataset(text, "dsBoard"):
        if not {"title", "regDate", "bbsId"} <= row.keys():
            raise SSVError("메인 공지사항 필수 컬럼 누락: title/regDate/bbsId")
        title = html.unescape(row["title"]).strip()
        bbs_id = row["bbsId"].strip()
        raw_date = row["regDate"].strip()
        if not title or not bbs_id:
            raise SSVError("메인 공지사항 제목 또는 게시판 ID 누락")
        try:
            if re.fullmatch(r"\d{17}", raw_date):
                registered_at = datetime.strptime(raw_date, "%Y%m%d%H%M%S%f").date()
            else:
                registered_at = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SSVError(f"메인 공지사항 등록일 오류: {raw_date!r}") from exc
        notice = MainNotice(bbs_id, row.get("itemId", "").strip(), title, registered_at.isoformat())
        if notice.key in notices and notices[notice.key] != notice:
            raise SSVError("같은 공지사항 ID에 서로 다른 데이터가 있습니다")
        notices[notice.key] = notice
    # An empty/changed response must not silently replace a working baseline.
    if not notices:
        raise SSVError("메인 공지사항 dsBoard가 비어 있습니다. 상태를 보존합니다")
    return list(notices.values())


def read_main_response(page, *, timeout_ms=60000):
    """Listen before navigation, including requests from Nexacro frames."""
    def matches(response):
        url = urlsplit(response.url)
        return (url.scheme == "https" and url.hostname == "biz.hira.or.kr"
                and url.path == MAIN_LIST_PATH and response.request.method == "POST")

    page.set_default_timeout(timeout_ms)
    with page.expect_response(matches, timeout=timeout_ms) as pending:
        page.goto(MAIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    response = pending.value
    if response.status != 200:
        raise SSVError(f"메인 공지사항 HTTP {response.status}")
    return parse_main_notices(response.text())


def fetch_main_notices(*, timeout_ms=60000):
    """Fresh anonymous browser; no login, certificate or persistent profile."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="ko-KR")
            return read_main_response(context.new_page(), timeout_ms=timeout_ms)
        finally:
            browser.close()


def run_main_notices(conn, *, send_notification, min_interval=300,
                     fetch=None, now=None):
    return run_notice_source(conn, source=SOURCE, send_notification=send_notification,
                             min_interval=min_interval, fetch=fetch or fetch_main_notices, now=now)
