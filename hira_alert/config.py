"""환경 변수(.env)를 읽어 불변 Settings로 만든다. import 시점에는 아무것도 읽지 않는다."""

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
NOTIFY_FROM_DATE = date(2026, 9, 9)
BIZ_MODES = frozenset({"main", "legacy", "both", "off"})

# 건강보험심사평가원 공식 RSS (HIRA가 http 주소를 공식 제공)
RSS_FEEDS = {
    "공지사항": "http://www.hira.or.kr/cms/inform/01/notice.xml",
    "보험인정기준-행위": "http://www.hira.or.kr/cms/policy/03/01/01/01/act_notice.xml",
    "보험인정기준-치료재료": "http://www.hira.or.kr/cms/policy/03/01/01/02/care_notice.xml",
    "보험인정기준-약제": "http://www.hira.or.kr/cms/policy/03/01/01/03/druginfo_notice.xml",
    "보험인정기준-의료급여": "http://www.hira.or.kr/cms/policy/03/01/01/04/pay_notice.xml",
    "청구관련기준자료": "http://www.hira.or.kr/cms/policy/03/01/04/02/request.xml",
}


def _csv(value: str, *, lower: bool = False) -> tuple[str, ...]:
    items = (x.strip() for x in value.split(","))
    return tuple(dict.fromkeys(x.lower() if lower else x for x in items if x))


@dataclass(frozen=True)
class Settings:
    db_path: Path = BASE_DIR / "hira_alert.db"
    log_path: Path = BASE_DIR / "hira_alert.log"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_from_date: date = NOTIFY_FROM_DATE
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    rss_feeds: dict = field(default_factory=lambda: dict(RSS_FEEDS))
    biz_mode: str = "main"
    biz_bbs_ids: tuple[str, ...] = ("BBSMSTR_000000000675",)
    biz_max_pages: int = 200
    biz_main_min_interval: int = 300
    eform_enabled: bool = True
    eform_min_interval: int = 300
    eform_pages: int = 1

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        if env is None:
            load_dotenv(BASE_DIR / ".env")
            env = os.environ
        get = lambda key, default="": env.get(key, default).strip()
        return cls(
            db_path=BASE_DIR / get("DB_PATH", "hira_alert.db"),
            log_path=BASE_DIR / get("LOG_PATH", "hira_alert.log"),
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=get("TELEGRAM_CHAT_ID"),
            include_keywords=_csv(get("INCLUDE_KEYWORDS"), lower=True),
            exclude_keywords=_csv(get("EXCLUDE_KEYWORDS"), lower=True),
            biz_mode=get("BIZ_MODE", "main").lower(),
            biz_bbs_ids=_csv(get("BIZ_BBS_IDS", "BBSMSTR_000000000675")),
            biz_max_pages=int(get("BIZ_MAX_PAGES", "200")),
            biz_main_min_interval=max(60, int(get("BIZ_MAIN_MIN_INTERVAL", "300"))),
            eform_enabled=get("EFORM_ENABLED", "1").lower() in {"1", "true", "yes"},
            eform_min_interval=max(60, int(get("EFORM_MIN_INTERVAL", "300"))),
            eform_pages=int(get("EFORM_PAGES", "1")),
        )
