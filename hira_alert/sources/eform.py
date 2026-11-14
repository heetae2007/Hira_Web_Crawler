"""e-Form 공지사항 (비로그인 Playwright 세션 + Nexacro SSV API)."""

import time
from datetime import datetime

from ..ssv import ETX, RS, US, SSVError, parse_ssv_dataset
from .notice_board import MainNotice, NoticeSource, run_notice_source

PORTAL_URL = "https://ef.hira.or.kr/efweb/index.do"
SOURCE = NoticeSource("eform", "eform", "심평원 e-Form", PORTAL_URL)
ENDPOINT = "https://ef.hira.or.kr/efweb/ia/iac/selectBoardList.ndo"
HEADERS = {
    "Content-Type": "text/xml",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/xml, text/xml, */*",
    "Referer": PORTAL_URL,
}
COLUMNS = ("brdLrgTxt", "brdTtl", "brdDivCd", "brdSrchTpCd", "totCnt",
           "fetchRow", "pageNum", "rn", "openType", "boardTpCd", "brdId", "brdNo")


def build_request(page=1):
    if not isinstance(page, int) or page < 1:
        raise ValueError("pageNum은 1 이상의 정수여야 합니다")
    # Preserve NULL (ETX) separately from empty string. W selects notices;
    # the response's brdTpCd is a different field (e.g. 01 = 일반).
    values = [ETX, ETX, "", "0", ETX, "20", str(page), ETX, "", "W", ETX, ""]
    return RS.join(["SSV:utf-8", "Dataset:dsCond",
                    US.join(["_RowType_"] + [c + ":STRING(256)" for c in COLUMNS]),
                    US.join(["N", *values]), "", ""]).encode("utf-8")


def parse_page(text, page=1):
    rows = parse_ssv_dataset(text, "dsList")
    if not rows:
        raise SSVError("e-form dsList가 비어 있습니다. 기존 상태를 보존합니다")
    notices, totals, ids = [], set(), set()
    for index, row in enumerate(rows):
        if not {"rn", "totCnt", "brdId", "brdTtl", "creDt"} <= row.keys():
            raise SSVError("e-form 필수 컬럼 누락: rn/totCnt/brdId/brdTtl/creDt")
        ident, title = row["brdId"].strip(), row["brdTtl"].strip()
        if not ident or not title or ident in ids:
            raise SSVError("e-form 게시글 ID/제목 누락 또는 중복 ID")
        try:
            registered = datetime.strptime(row["creDt"], "%Y-%m-%d %H:%M").date().isoformat()
            total, ordinal = int(row["totCnt"]), int(row["rn"])
        except ValueError as exc:
            raise SSVError("e-form 등록일/전체 건수/행 번호 형식 오류") from exc
        if ordinal != (page - 1) * 20 + index + 1 or total < ordinal:
            raise SSVError("e-form 페이지 번호 또는 전체 건수 불일치")
        ids.add(ident)
        totals.add(total)
        notices.append(MainNotice("W", ident, title, registered))
    if len(totals) != 1 or len(rows) != min(20, next(iter(totals)) - (page - 1) * 20):
        raise SSVError("e-form 전체 건수 또는 페이지 행 수 불일치")
    return notices, totals.pop()


def fetch_with_context(context, *, pages=1, timeout_ms=60000, sleep=time.sleep):
    """APIRequestContext shares cookies with the anonymous browser context."""
    if not 1 <= pages <= 10:
        raise ValueError("EFORM_PAGES는 1~10이어야 합니다")
    page = context.new_page()
    navigation = page.goto(PORTAL_URL, wait_until="load", timeout=timeout_ms)
    if navigation is None or navigation.status >= 400:
        raise SSVError("e-form 비로그인 진입 화면 로딩 실패")
    notices, seen = [], set()
    initial_total = None
    for number in range(1, pages + 1):
        sleep(2)  # Separate list calls (including the first) from page loading.
        response = context.request.post(ENDPOINT, data=build_request(number),
                                        headers=HEADERS, timeout=timeout_ms, max_redirects=0)
        try:
            if response.status != 200:
                raise SSVError(f"e-form 목록 HTTP {response.status}")
            batch, total = parse_page(response.text(), number)
        finally:
            response.dispose()
        if initial_total is not None and total != initial_total:
            raise SSVError("e-form 조회 중 전체 건수가 변경되었습니다. 다음 주기에 재시도합니다")
        initial_total = total
        if any(n.key in seen for n in batch):
            raise SSVError("e-form 페이지 간 중복 ID: 다음 주기에 재시도합니다")
        notices.extend(batch)
        seen.update(n.key for n in batch)
        if number * 20 >= total:
            break
    return notices


def fetch_notices(*, pages=1, timeout_ms=60000):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="ko-KR")
            return fetch_with_context(context, pages=pages, timeout_ms=timeout_ms)
        finally:
            browser.close()


def run_eform(conn, *, send_notification, min_interval=300, pages=1, fetch=None, now=None):
    return run_notice_source(conn, source=SOURCE, send_notification=send_notification,
                             min_interval=min_interval, now=now,
                             fetch=fetch or (lambda: fetch_notices(pages=pages)))
