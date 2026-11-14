"""심평원 공식 RSS 수집. 시작일 이전 글은 기준점으로만 저장한다."""

import hashlib
import logging
import sqlite3
from datetime import datetime
from types import SimpleNamespace

import feedparser

from ..dates import publication_date
from ..keywords import matches_keywords

log = logging.getLogger("hira-alert")


def fetch_feed(url: str):
    # HIRA가 http 주소를 공식 제공하므로 feedparser에 그대로 전달합니다.
    feed = feedparser.parse(url)
    if getattr(feed, "bozo", False):
        # 일부 정상 RSS도 경미한 XML 경고로 bozo가 켜질 수 있으므로 entries가 있으면 계속 진행합니다.
        if not getattr(feed, "entries", None):
            raise RuntimeError(f"RSS 파싱 실패: {getattr(feed, 'bozo_exception', 'unknown')}")
        log.warning("RSS 파싱 경고 (%s): %s", url, getattr(feed, "bozo_exception", ""))
    return feed


def make_item_key(feed_name: str, entry) -> str:
    raw_id = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
        or (getattr(entry, "title", "") + getattr(entry, "published", ""))
    )
    return hashlib.sha256(f"{feed_name}|{raw_id}".encode("utf-8", errors="replace")).hexdigest()


def format_message(feed_name: str, entry) -> str:
    title = getattr(entry, "title", "(제목 없음)").strip()
    link = getattr(entry, "link", "").strip()
    published = (getattr(entry, "published", "") or getattr(entry, "updated", "") or "").strip()
    lines = ["📢 심평원 신규 고시/기준 알림", "", f"[{feed_name}]", title]
    if published:
        lines += ["", f"게시: {published}"]
    if link:
        lines += ["", link]
    return "\n".join(lines)


def mark_seen(conn: sqlite3.Connection, item_key, feed_name, title, link, published, notified: bool) -> None:
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
        (item_key, feed_name, title, link, published, now, now if notified else None),
    )
    conn.commit()


def run_rss(conn, settings, send, *, fetch=None):
    """(신규, 발송, 오류) 건수를 돌려준다. 발송 실패 항목은 다음 실행에서 재시도한다."""
    fetch = fetch or fetch_feed
    total_new = sent = errors = 0

    # RSS에서 빠졌어도 기존 DB의 미발송 항목은 재평가한다.
    pending = conn.execute(
        "SELECT item_key, feed_name, title, link, published FROM seen_items WHERE notified_at IS NULL"
    ).fetchall()

    for feed_name, url in settings.rss_feeds.items():
        candidates = {
            row[0]: SimpleNamespace(title=row[2], link=row[3], published=row[4] or "")
            for row in pending if row[1] == feed_name
        }
        try:
            feed = fetch(url)
            for entry in reversed(feed.entries):
                candidates[make_item_key(feed_name, entry)] = entry
            log.info("[%s] RSS 항목=%d", feed_name, len(feed.entries))
        except Exception as e:
            errors += 1
            log.exception("[%s] RSS 조회 실패: %s", feed_name, e)

        for key, entry in candidates.items():
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "") or ""
            published = (getattr(entry, "published", "") or getattr(entry, "updated", "") or "").strip()

            exists = conn.execute("SELECT notified_at FROM seen_items WHERE item_key = ?", (key,)).fetchone()
            if exists and exists[0]:
                continue

            total_new += int(exists is None)
            should_notify = matches_keywords(
                title, summary, include=settings.include_keywords, exclude=settings.exclude_keywords)

            try:
                posted_on = publication_date(published)
            except ValueError as e:
                errors += 1
                log.error("[%s] 게시일 확인 필요, 발송 보류: %s (%s)", feed_name, title, e)
                continue

            if posted_on < settings.notify_from_date:
                mark_seen(conn, key, feed_name, title, link, published, notified=False)
                if not exists:
                    log.info("[%s] 시작일 이전, 기준점 저장: %s", feed_name, title)
                continue

            if not should_notify:
                mark_seen(conn, key, feed_name, title, link, published, notified=False)
                log.info("[%s] 키워드 불일치, 저장만 함: %s", feed_name, title)
                continue

            try:
                send(format_message(feed_name, entry))
                mark_seen(conn, key, feed_name, title, link, published, notified=True)
                sent += 1
                log.info("[%s] 알림 발송: %s", feed_name, title)
            except Exception as e:
                # 전송 실패 시 seen 처리하지 않음 -> 다음 실행에서 재시도
                errors += 1
                log.exception("[%s] Telegram 전송 실패: %s", feed_name, e)
    return total_new, sent, errors
