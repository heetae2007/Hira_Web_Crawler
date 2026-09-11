#!/usr/bin/env python3
import hashlib
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import SimpleNamespace

import feedparser
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "hira_alert.db")
LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "hira_alert.log")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NOTIFY_FROM_DATE = date(2026, 9, 9)
KST = timezone(timedelta(hours=9))

# 쉼표로 구분. 비워두면 모든 새 글 알림.
INCLUDE_KEYWORDS = [
    x.strip().lower()
    for x in os.getenv("INCLUDE_KEYWORDS", "").split(",")
    if x.strip()
]
EXCLUDE_KEYWORDS = [
    x.strip().lower()
    for x in os.getenv("EXCLUDE_KEYWORDS", "").split(",")
    if x.strip()
]

# 건강보험심사평가원 공식 RSS
RSS_FEEDS = {
    "공지사항": "http://www.hira.or.kr/cms/inform/01/notice.xml",
    "보험인정기준-행위": "http://www.hira.or.kr/cms/policy/03/01/01/01/act_notice.xml",
    "보험인정기준-치료재료": "http://www.hira.or.kr/cms/policy/03/01/01/02/care_notice.xml",
    "보험인정기준-약제": "http://www.hira.or.kr/cms/policy/03/01/01/03/druginfo_notice.xml",
    "보험인정기준-의료급여": "http://www.hira.or.kr/cms/policy/03/01/01/04/pay_notice.xml",
    "청구관련기준자료": "http://www.hira.or.kr/cms/policy/03/01/04/02/request.xml",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("hira-alert")


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_items (
            item_key TEXT PRIMARY KEY,
            feed_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            published TEXT,
            first_seen_at TEXT NOT NULL,
            notified_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def publication_date(value: str) -> date:
    """HIRA의 시간대 없는 게시일은 한국 시간으로 해석한다."""
    value = value.strip()
    for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"게시일을 해석할 수 없습니다: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).date()


def make_item_key(feed_name: str, entry) -> str:
    raw_id = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
        or (getattr(entry, "title", "") + getattr(entry, "published", ""))
    )
    raw = f"{feed_name}|{raw_id}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def matches_keywords(title: str, summary: str = "") -> bool:
    haystack = f"{title}\n{summary}".lower()

    if EXCLUDE_KEYWORDS and any(k in haystack for k in EXCLUDE_KEYWORDS):
        return False

    if not INCLUDE_KEYWORDS:
        return True

    return any(k in haystack for k in INCLUDE_KEYWORDS)


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다."
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    response.raise_for_status()


def fetch_feed(url: str):
    # HIRA가 http 주소를 공식 제공하므로 feedparser에 그대로 전달합니다.
    feed = feedparser.parse(url)

    if getattr(feed, "bozo", False):
        # 일부 정상 RSS도 경미한 XML 경고로 bozo가 켜질 수 있으므로
        # entries가 있으면 계속 진행합니다.
        if not getattr(feed, "entries", None):
            raise RuntimeError(f"RSS 파싱 실패: {getattr(feed, 'bozo_exception', 'unknown')}")
        log.warning("RSS 파싱 경고 (%s): %s", url, getattr(feed, "bozo_exception", ""))

    return feed


def format_message(feed_name: str, entry) -> str:
    title = getattr(entry, "title", "(제목 없음)").strip()
    link = getattr(entry, "link", "").strip()
    published = (
        getattr(entry, "published", "")
        or getattr(entry, "updated", "")
        or ""
    ).strip()

    lines = [
        "📢 심평원 신규 고시/기준 알림",
        "",
        f"[{feed_name}]",
        title,
    ]
    if published:
        lines += ["", f"게시: {published}"]
    if link:
        lines += ["", link]

    return "\n".join(lines)


def mark_seen(
    conn: sqlite3.Connection,
    item_key: str,
    feed_name: str,
    title: str,
    link: str,
    published: str,
    notified: bool,
) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO seen_items
        (item_key, feed_name, title, link, published, first_seen_at, notified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_key) DO UPDATE SET
            title = excluded.title,
            link = excluded.link,
            published = excluded.published,
            notified_at = COALESCE(seen_items.notified_at, excluded.notified_at)
        """,
        (
            item_key,
            feed_name,
            title,
            link,
            published,
            now,
            now if notified else None,
        ),
    )
    conn.commit()


def run() -> int:
    conn = connect_db()
    log.info("실행 시작: 알림 시작일=%s (한국 시간), DB=%s", NOTIFY_FROM_DATE, DB_PATH)

    total_new = 0
    sent = 0
    errors = 0

    # RSS에서 빠졌어도 기존 DB의 미발송 항목은 재평가한다.
    pending = conn.execute(
        "SELECT item_key, feed_name, title, link, published FROM seen_items WHERE notified_at IS NULL"
    ).fetchall()

    for feed_name, url in RSS_FEEDS.items():
        candidates = {
            row[0]: SimpleNamespace(title=row[2], link=row[3], published=row[4] or "")
            for row in pending if row[1] == feed_name
        }
        try:
            feed = fetch_feed(url)
            for entry in reversed(feed.entries):
                candidates[make_item_key(feed_name, entry)] = entry
            log.info("[%s] RSS 항목=%d", feed_name, len(feed.entries))
        except Exception as e:
            errors += 1
            log.exception("[%s] RSS 조회 실패: %s", feed_name, e)

        # 기존 미발송 항목과 현재 RSS 항목을 함께 처리한다.
        for key, entry in candidates.items():
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "") or ""
            published = (
                getattr(entry, "published", "")
                or getattr(entry, "updated", "")
                or ""
            ).strip()

            exists = conn.execute(
                "SELECT notified_at FROM seen_items WHERE item_key = ?", (key,)
            ).fetchone()
            if exists and exists[0]:
                continue

            total_new += int(exists is None)
            should_notify = matches_keywords(title, summary)

            try:
                posted_on = publication_date(published)
            except ValueError as e:
                errors += 1
                log.error("[%s] 게시일 확인 필요, 발송 보류: %s (%s)", feed_name, title, e)
                continue

            if posted_on < NOTIFY_FROM_DATE:
                mark_seen(
                    conn, key, feed_name, title, link, published, notified=False
                )
                if not exists:
                    log.info("[%s] 시작일 이전, 기준점 저장: %s", feed_name, title)
                continue

            if not should_notify:
                mark_seen(
                    conn, key, feed_name, title, link, published, notified=False
                )
                log.info("[%s] 키워드 불일치, 저장만 함: %s", feed_name, title)
                continue

            try:
                send_telegram(format_message(feed_name, entry))
                mark_seen(
                    conn, key, feed_name, title, link, published, notified=True
                )
                sent += 1
                log.info("[%s] 알림 발송: %s", feed_name, title)
            except Exception as e:
                # 전송 실패 시 seen 처리하지 않음 -> 다음 실행에서 재시도
                errors += 1
                log.exception("[%s] Telegram 전송 실패: %s", feed_name, e)

    conn.close()
    log.info("완료: 신규=%d, 발송=%d, 오류=%d", total_new, sent, errors)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(run())
