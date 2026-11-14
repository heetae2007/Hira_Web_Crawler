"""한 번의 실행: 출처별 수집기를 돌리고 신규/발송/오류 건수를 합산한다."""

import logging
from functools import partial

from .config import BIZ_MODES, Settings
from .dates import publication_date
from .db import connect_db
from .keywords import matches_keywords
from .sources import biz_legacy, biz_main, eform, rss
from .telegram import send_telegram

log = logging.getLogger("hira-alert")


def _guarded(name, step):
    """출처 하나가 실패해도 다른 출처는 계속 실행한다."""
    try:
        return step()
    except Exception:
        log.exception("%s 실행 실패", name)
        return 0, 0, 1


def run(settings: Settings | None = None, *, send=None) -> int:
    settings = settings or Settings.from_env()
    if settings.biz_mode not in BIZ_MODES:
        log.error("BIZ_MODE는 main, legacy, both, off 중 하나여야 합니다")
        return 1
    send = send or partial(send_telegram, settings.telegram_bot_token, settings.telegram_chat_id)
    conn = connect_db(settings.db_path)
    log.info("실행 시작: 알림 시작일=%s (한국 시간), DB=%s", settings.notify_from_date, settings.db_path)

    steps = [("RSS", lambda: rss.run_rss(conn, settings, send))]
    if settings.biz_mode in {"main", "both"}:
        steps.append(("메인 공지사항", lambda: biz_main.run_main_notices(
            conn, send_notification=send, min_interval=settings.biz_main_min_interval)))
    if settings.biz_mode in {"legacy", "both"} and settings.biz_bbs_ids:
        steps.append(("biz 수집", lambda: biz_legacy.run_biz(
            conn, list(settings.biz_bbs_ids), notify_from_date=settings.notify_from_date,
            publication_date=publication_date,
            matches_keywords=lambda title, summary="": matches_keywords(
                title, summary, include=settings.include_keywords, exclude=settings.exclude_keywords),
            send_telegram=send, max_pages=settings.biz_max_pages)))
    if settings.eform_enabled:
        steps.append(("e-form 공지사항", lambda: eform.run_eform(
            conn, send_notification=send,
            min_interval=settings.eform_min_interval, pages=settings.eform_pages)))

    new = sent = errors = 0
    for name, step in steps:
        n, s, e = _guarded(name, step)
        new, sent, errors = new + n, sent + s, errors + e
    conn.close()
    log.info("완료: 신규=%d, 발송=%d, 오류=%d", new, sent, errors)
    return 1 if errors else 0
