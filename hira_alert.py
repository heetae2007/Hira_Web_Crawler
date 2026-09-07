#!/usr/bin/env python3
import hashlib
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "hira_alert.db")
LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "hira_alert.log")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_EXISTING_ON_FIRST_RUN = os.getenv(
    "SEND_EXISTING_ON_FIRST_RUN", "false"
).lower() in {"1", "true", "yes", "y"}

# 쉼표로 구분. 비워두면 모든 새 글 알림.
INCLUDE_KEYWORDS = [
    x.strip().lower()
    for x in os.getenv("INCLUDE_KEYWORDS", "고시").split(",")
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


def is_first_run(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()
    return row[0] == 0


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
        INSERT OR IGNORE INTO seen_items
        (item_key, feed_name, title, link, published, first_seen_at, notified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
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
    first_run = is_first_run(conn)

    total_new = 0
    sent = 0
    errors = 0

    for feed_name, url in RSS_FEEDS.items():
        try:
            feed = fetch_feed(url)
        except Exception as e:
            errors += 1
            log.exception("[%s] RSS 조회 실패: %s", feed_name, e)
            continue

        # 오래된 글부터 처리해서 여러 건 발생 시 시간 순서로 알림
        entries: Iterable = reversed(feed.entries)

        for entry in entries:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "") or ""
            published = (
                getattr(entry, "published", "")
                or getattr(entry, "updated", "")
                or ""
            ).strip()
            key = make_item_key(feed_name, entry)

            exists = conn.execute(
                "SELECT 1 FROM seen_items WHERE item_key = ?", (key,)
            ).fetchone()
            if exists:
                continue

            total_new += 1
            should_notify = matches_keywords(title, summary)

            # 첫 실행 기본값: 현재 RSS에 있는 기존 글은 기준점으로 저장만 함.
            # 이후 새로 올라온 글부터 알림.
            if first_run and not SEND_EXISTING_ON_FIRST_RUN:
                mark_seen(
                    conn, key, feed_name, title, link, published, notified=False
                )
                log.info("[%s] 초기 기준점 저장: %s", feed_name, title)
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
