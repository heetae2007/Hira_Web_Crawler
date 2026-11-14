"""브라우저로 읽는 공지 목록(업무포털 메인, e-Form)의 공통 저장·알림 로직."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime

from ..ssv import SSVError

log = logging.getLogger("hira-alert")


@dataclass(frozen=True)
class NoticeSource:
    """SQL 식별자는 이 고정 정의에서만 만들고 설정값은 쓰지 않는다."""

    name: str
    table_prefix: str
    label: str
    portal_url: str


@dataclass(frozen=True)
class MainNotice:
    bbs_id: str
    item_id: str
    title: str
    registered_at: str

    @property
    def key(self):
        identity = (["id", self.bbs_id, self.item_id] if self.item_id else
                    ["title-date", self.bbs_id, self.title, self.registered_at])
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def run_notice_source(conn, *, source: NoticeSource, send_notification, fetch, min_interval=300, now=None):
    """Check once; retain history and a durable notification outbox.

    First successful check notifies all visible items. No gosi/date/keyword filter.
    Delivery is at least once: a crash after sending but before commit may duplicate.
    """
    prefix, label, portal_url = source.table_prefix, source.label, source.portal_url
    now = time.time() if now is None else now
    min_interval = max(60, min_interval)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {prefix}_poll (
        id INTEGER PRIMARY KEY CHECK (id=1), last_attempt REAL NOT NULL)""")
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {prefix}_notices (
        item_key TEXT PRIMARY KEY, bbs_id TEXT NOT NULL, item_id TEXT NOT NULL,
        title TEXT NOT NULL, registered_at TEXT NOT NULL,
        in_latest INTEGER NOT NULL DEFAULT 1, notified_at TEXT)""")
    conn.commit()
    # Persist the cooldown even on collection failure. BEGIN IMMEDIATE serializes
    # competing cron processes while reserving the next request window.
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute(f"SELECT last_attempt FROM {prefix}_poll WHERE id=1").fetchone()
        if previous and now - previous[0] < min_interval:
            log.info("[%s] 최소 조회 간격 %s초: 이번 실행 생략", source.name, min_interval)
            return 0, 0, 0
        conn.execute(f"INSERT INTO {prefix}_poll VALUES (1, ?) ON CONFLICT(id) "
                     "DO UPDATE SET last_attempt=excluded.last_attempt", (now,))
    new = sent = errors = 0
    try:
        notices = fetch()
        if not notices:
            raise SSVError(f"{source.name} 공지사항이 비어 있습니다")
        with conn:
            conn.execute(f"UPDATE {prefix}_notices SET in_latest=0")
            for notice in notices:
                exists = conn.execute(f"SELECT 1 FROM {prefix}_notices WHERE item_key=?",
                                      (notice.key,)).fetchone()
                new += int(exists is None)
                conn.execute(f"""INSERT INTO {prefix}_notices
                    (item_key, bbs_id, item_id, title, registered_at, in_latest)
                    VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT(item_key) DO UPDATE SET
                    title=excluded.title, registered_at=excluded.registered_at,
                    in_latest=1""", (notice.key, notice.bbs_id, notice.item_id,
                                     notice.title, notice.registered_at))
    except Exception:
        errors += 1
        log.exception("[%s] 목록 수집 실패, 다음 주기에 재시도", source.name)
    # Retry unsent items even if collection fails or items leave the main grid.
    pending = conn.execute(f"""SELECT item_key, title, registered_at, item_id
        FROM {prefix}_notices WHERE notified_at IS NULL ORDER BY registered_at, item_key""").fetchall()
    for key, title, registered_at, item_id in pending:
        try:
            send_notification("\n".join([
                f"📢 {label} 신규 공지사항", title[:1500],
                f"등록일: {registered_at}", f"게시글 ID: {item_id or '없음 (제목+등록일 기준)'}",
                portal_url,
            ]))
            with conn:
                conn.execute(f"UPDATE {prefix}_notices SET notified_at=? WHERE item_key=?",
                             (datetime.now().astimezone().isoformat(timespec="seconds"), key))
            sent += 1
        except Exception:
            errors += 1
            log.exception("[%s] 알림 실패, 다음 주기에 재시도: %s", source.name, key)
    log.info("[%s] 신규=%d, 발송=%d, 오류=%d", source.name, new, sent, errors)
    return new, sent, errors
