"""Public biz.hira SSV source adapter and persistent change tracking."""

import hashlib
import html
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser

import requests

RS, US, ETX = "\x1e", "\x1f", "\x03"
ENDPOINT = "https://biz.hira.or.kr/qya/bbs/selectComBbsList.ndo"
PORTAL_URL = "https://biz.hira.or.kr/"
SOURCE = "biz.hira"
log = logging.getLogger("hira-alert")


class SSVError(ValueError):
    pass


def parse_ssv_dataset(response_text: str, dataset_name: str) -> list[dict]:
    """Parse typed SSV records; preserve HTML/newlines and reject ambiguous rows."""
    records = response_text.lstrip("\ufeff").split(RS)
    if not records or records[0].lower() != "ssv:utf-8":
        raise SSVError("UTF-8 SSV 응답이 아닙니다 (로그인/오류 HTML 확인 필요)")
    active = found = False
    columns = None
    constants = {}
    rows = []
    for record in records[1:]:
        if record.startswith("Dataset:"):
            if active:
                break
            active = record == f"Dataset:{dataset_name}"
            found = found or active
            continue
        if not active:
            for variable in record.split(US):
                key, sep, value = variable.partition("=")
                if sep and key.split(":", 1)[0] == "ErrorCode":
                    try:
                        error_code = int(value)
                    except ValueError as exc:
                        raise SSVError("잘못된 SSV ErrorCode") from exc
                    if error_code < 0:
                        raise SSVError(f"서버 SSV 오류: ErrorCode={error_code}")
            continue
        if not record:
            continue
        fields = record.split(US)
        if fields[0] == "_Const_":
            for field in fields[1:]:
                name, sep, value = field.partition("=")
                if not sep:
                    raise SSVError("잘못된 SSV 상수 컬럼")
                constants[name.split(":", 1)[0]] = "" if value == ETX else value
        elif fields[0] == "_RowType_":
            if columns is not None:
                raise SSVError("중복 SSV 컬럼 정의")
            columns = [field.split(":", 1)[0] for field in fields[1:]]
            if not all(columns) or len(set(columns)) != len(columns):
                raise SSVError("잘못된 SSV 컬럼 이름")
        else:
            if columns is None or fields[0] not in {"N", "I", "U", "D", "O"}:
                raise SSVError("SSV 컬럼 정의 또는 행 타입 확인 필요")
            values = fields[1:]
            if len(values) != len(columns):
                # Never shift fields or guess where an omitted value belongs.
                raise SSVError(f"SSV 열 개수 불일치: expected={len(columns)}, actual={len(values)}")
            if fields[0] in {"D", "O"}:
                continue
            rows.append({**constants, **dict(zip(columns, ("" if v == ETX else v for v in values)))})
    if not found:
        raise SSVError(f"Dataset:{dataset_name} 누락")
    return rows


def build_list_request(bbs_id: str, page: int, page_size: int = 20) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_]+", bbs_id) or page < 1 or not 1 <= page_size <= 100:
        raise ValueError("게시판 ID 또는 페이지 설정 오류")
    columns = ["currentPage:INT", "recordCountPerPage:INT", "firstIndex:INT",
               "lastIndex:INT", "bbsId:STRING(64)", "cbSearchCnd:STRING(32)",
               "edSearchWrd:STRING(256)"]
    values = [str(page), str(page_size), str((page - 1) * page_size),
              str(page * page_size), bbs_id, "all", ""]
    return RS.join(["SSV:utf-8", "Dataset:dsParam", US.join(["_RowType_"] + columns),
                    US.join(["N"] + values), "", ""]).encode("utf-8")


def fetch_biz_page(bbs_id: str, page: int, page_size: int = 20) -> list[dict]:
    body = build_list_request(bbs_id, page, page_size)
    for attempt in range(3):
        try:
            # A fresh request each time: no browser cookies or persisted session cookies.
            with requests.post(ENDPOINT, data=body,
                               headers={"Content-Type": "text/plain; charset=UTF-8"},
                               timeout=(10, 30), allow_redirects=False) as response:
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise SSVError("게시판 조회가 리다이렉트되었습니다 (로그인 필요 여부 확인)")
                return parse_ssv_dataset(response.content.decode("utf-8-sig"), "dsMain")
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")


def plain_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(html.unescape(value))
    return "".join(parser.parts)


def extract_gosi_numbers(title: str, content: str) -> list[str]:
    pattern = r"고시\s*제?\s*(\d{4})\s*-\s*(\d+)\s*호"
    numbers = []
    for text in (title, content):
        for year, number in re.findall(pattern, plain_text(text)):
            normalized = f"{year}-{int(number)}"
            if normalized not in numbers:
                numbers.append(normalized)
    return numbers


@dataclass(frozen=True)
class BizPost:
    bbs_id: str
    ntt_id: str
    ntt_no: str
    title: str
    content: str
    registered_at: str
    modified_at: str
    attachment_id: str
    is_notice: bool

    @classmethod
    def from_row(cls, row: dict, bbs_id: str):
        required = {"nttId", "nttSj", "nttCn", "frstregisterPntt", "lastUpdusrPnttm", "atchFileId", "isNotice"}
        if required - row.keys():
            raise SSVError(f"게시글 필수 컬럼 누락: {sorted(required - row.keys())}")
        if not row["nttId"].strip() or not row["nttSj"].strip():
            raise SSVError("게시글 ID/제목 누락")
        if row.get("bbsId") and row["bbsId"] != bbs_id:
            raise SSVError("응답 게시판 ID 불일치")
        return cls(bbs_id, row["nttId"].strip(), row.get("nttNo", ""), row["nttSj"],
                   row.get("nttCn", ""), row["frstregisterPntt"], row["lastUpdusrPnttm"],
                   row["atchFileId"], row["isNotice"].upper() == "Y")

    @property
    def version(self):
        # Content and registration date changes also need re-evaluation.
        values = [self.modified_at, self.title, self.attachment_id, self.content, self.registered_at]
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()

    @property
    def gosi_numbers(self):
        return extract_gosi_numbers(self.title, self.content)

    @property
    def notice_type(self):
        match = re.match(r"\s*\[([^\]]+)\]", plain_text(self.title))
        return match[1].strip() if match else None


def crawl_biz_hira(bbs_id: str, *, page_size=20, max_pages=200, fetch_page=None):
    """Scan through the end, including old pages where edits may occur."""
    fetch_page = fetch_page or fetch_biz_page
    seen = set()
    for page in range(1, max_pages + 1):
        rows = fetch_page(bbs_id, page, page_size)
        posts = [BizPost.from_row(row, bbs_id) for row in rows]
        regular_ids = {post.ntt_id for post in posts if not post.is_notice}
        new_regular = regular_ids - seen
        for post in posts:
            if post.ntt_id not in seen:
                yield post
                seen.add(post.ntt_id)
        log.info("[biz:%s] 페이지=%d, 항목=%d", bbs_id, page, len(posts))
        if not regular_ids:
            return
        if not new_regular:
            raise SSVError(f"페이지 {page}에서 일반 게시글 반복: 페이지 처리 확인 필요")
        # Do not terminate on a short page: pinned rows can affect page sizes.
    raise SSVError(f"최대 {max_pages}페이지 도달: 수집 미완료, BIZ_MAX_PAGES 조정 필요")


def init_biz_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS biz_posts (
            source TEXT NOT NULL,
            bbs_id TEXT NOT NULL,
            ntt_id TEXT NOT NULL,
            ntt_no TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            notice_type TEXT,
            gosi_no TEXT,
            gosi_numbers TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            attachment_id TEXT NOT NULL,
            is_notice INTEGER NOT NULL,
            version TEXT NOT NULL,
            notified_version TEXT NOT NULL DEFAULT '',
            change_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            notified_at TEXT,
            PRIMARY KEY (source, bbs_id, ntt_id)
        )
    """)
    conn.commit()


def store_biz_post(conn, post: BizPost) -> str:
    key = (SOURCE, post.bbs_id, post.ntt_id)
    previous = conn.execute("SELECT version FROM biz_posts WHERE source=? AND bbs_id=? AND ntt_id=?", key).fetchone()
    state = "NEW" if previous is None else ("UNCHANGED" if previous[0] == post.version else "UPDATED")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    data = {**asdict(post), "source": SOURCE, "notice_type": post.notice_type,
            "gosi_no": next(iter(post.gosi_numbers), None),
            "gosi_numbers": json.dumps(post.gosi_numbers), "version": post.version,
            "change_state": state, "created_at": now, "updated_at": now}
    columns = list(data)
    updates = [f"{name}=excluded.{name}" for name in columns
               if name not in {"source", "bbs_id", "ntt_id", "created_at", "change_state"}]
    updates.append("change_state=CASE WHEN biz_posts.version=excluded.version THEN biz_posts.change_state ELSE excluded.change_state END")
    conn.execute(f"INSERT INTO biz_posts ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                 f"ON CONFLICT(source,bbs_id,ntt_id) DO UPDATE SET {','.join(updates)}",
                 [data[name] for name in columns])
    conn.commit()
    return state


def format_biz_message(post: BizPost, state: str) -> str:
    return "\n".join([
        f"📢 심평원 biz 고시 {'신규' if state == 'NEW' else '수정'} 알림",
        f"[biz:{post.bbs_id}]", plain_text(post.title)[:1500],
        f"고시번호: {', '.join(post.gosi_numbers)[:500]}",
        f"분류: {post.notice_type or '기타'}",
        f"게시글 ID: {post.ntt_id}", f"등록: {post.registered_at}",
        f"수정: {post.modified_at or '정보 없음'}",
        f"첨부파일: {'있음' if post.attachment_id else '없음'}",
        "게시판에서 위 게시글 ID 또는 제목으로 확인:", PORTAL_URL,
    ])


def run_biz(conn, boards, *, notify_from_date, publication_date, matches_keywords,
            send_telegram, max_pages=200):
    init_biz_db(conn)
    counts = {"NEW": 0, "UPDATED": 0, "UNCHANGED": 0}
    sent = errors = 0
    for bbs_id in boards:
        try:
            for post in crawl_biz_hira(bbs_id, max_pages=max_pages):
                counts[store_biz_post(conn, post)] += 1
        except Exception:
            errors += 1
            log.exception("[biz:%s] 목록 수집 실패", bbs_id)

        # Durable retry even when an item disappears from subsequent responses.
        cursor = conn.execute("SELECT * FROM biz_posts WHERE source=? AND bbs_id=? AND version != notified_version",
                              (SOURCE, bbs_id))
        names = [column[0] for column in cursor.description]
        for values in cursor.fetchall():
            row = dict(zip(names, values))
            post = BizPost(**{name: row[name] for name in BizPost.__dataclass_fields__})
            try:
                if not post.gosi_numbers:
                    continue
                if publication_date(post.registered_at) < notify_from_date:
                    continue
                if not matches_keywords(plain_text(post.title), plain_text(post.content)):
                    continue
                # If a new post changes before its first successful send, it is still new to the recipient.
                state = "UPDATED" if row["notified_version"] else "NEW"
                send_telegram(format_biz_message(post, state))
                conn.execute("UPDATE biz_posts SET notified_version=?, notified_at=? WHERE source=? AND bbs_id=? AND ntt_id=? AND version=?",
                             (post.version, datetime.now().astimezone().isoformat(timespec="seconds"),
                              SOURCE, bbs_id, post.ntt_id, post.version))
                conn.commit()
                sent += 1
            except Exception:
                errors += 1
                log.exception("[biz:%s/%s] 알림 처리 실패, 다음 실행 재시도", bbs_id, post.ntt_id)
    log.info("biz 완료: 신규=%d, 수정=%d, 동일=%d, 발송=%d, 오류=%d",
             counts["NEW"], counts["UPDATED"], counts["UNCHANGED"], sent, errors)
    return counts["NEW"], sent, errors


def main():
    """Check one public page without opening the DB or sending notifications."""
    import argparse

    parser = argparse.ArgumentParser(description="biz.hira 공개 목록 조회 점검 (DB/Telegram 사용 안 함)")
    parser.add_argument("--bbs-id", default="BBSMSTR_000000000675")
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()
    try:
        rows = fetch_biz_page(args.bbs_id, args.page)
        posts = [BizPost.from_row(row, args.bbs_id) for row in rows]
    except (requests.RequestException, ValueError) as exc:
        print(f"biz check failed: {exc}")
        return 1
    print(json.dumps({"bbs_id": args.bbs_id, "page": args.page, "count": len(posts),
                      "columns": list(rows[0]) if rows else [],
                      "gosi_count": sum(bool(post.gosi_numbers) for post in posts)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
