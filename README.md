# 심평원 고시 알리미

건강보험심사평가원(HIRA)에 올라오는 고시·공지를 5분마다 확인해 **새 글만 Telegram으로 보내는** 자동화 서버입니다. 병원 HIS 운영팀이 심평원 화면을 매일 직접 열어 보던 일을 대신합니다.

## 무엇을 감시하나

| 출처 | 방식 | 신규 판단 | 기본 |
| --- | --- | --- | --- |
| 심평원 공식 RSS 6종 (공지, 보험인정기준 4종, 청구관련기준자료) | feedparser | RSS 항목 키 | 켜짐 |
| 요양기관 업무포털 메인 공지 | 비로그인 Playwright가 브라우저 응답(SSV)을 가로채 파싱 | 게시판 ID + 게시글 ID | `BIZ_MODE=main` |
| e-Form 공지사항 | 비로그인 세션 쿠키 + SSV API | `brdId` | 켜짐 |
| 업무포털 게시판 (고시번호 추출·수정 이력) | 직접 POST | `(source, bbs_id, ntt_id)` | `BIZ_MODE=legacy` |

로그인·인증서·저장된 브라우저 프로필은 쓰지 않습니다. 출처별 수집 규칙은 [docs/SOURCES.md](docs/SOURCES.md)에 있습니다.

## 설계 원칙

- **알림은 전송 성공 후에만 기록합니다.** 실패한 항목은 목록에서 사라져도 다음 주기에 재시도합니다(at-least-once).
- **수집 실패가 기존 상태를 지우지 않습니다.** 빈 목록·형식 변경·건수 불일치는 오류로 기록하고 직전 목록을 보존합니다.
- **출처는 서로 격리됩니다.** 한 출처가 예외를 내도 나머지는 계속 실행되고, 종료 코드만 1이 됩니다.
- **서버 부담을 줄입니다.** 출처별 최소 조회 간격을 SQLite에 저장해 cron이 겹쳐도 지켜지고, `flock`으로 중복 실행을 막습니다.

## 구조

```
hira_alert/
├── __main__.py        python -m hira_alert  (cron 진입점, 로깅 설정)
├── check.py           python -m hira_alert.check ...  (DB·Telegram 없이 조회만 점검)
├── config.py          .env → 불변 Settings
├── runner.py          출처별 수집기 실행·건수 합산·실패 격리
├── telegram.py        Telegram 발송
├── db.py              SQLite 연결, RSS 기준점 테이블
├── dates.py           게시일 해석 (시간대 없으면 KST)
├── keywords.py        포함/제외 키워드 필터
├── ssv.py             Nexacro SSV 파서
└── sources/
    ├── rss.py             공식 RSS
    ├── notice_board.py    브라우저형 공지의 공통 저장·알림 (cooldown, outbox)
    ├── biz_main.py        업무포털 메인 공지
    ├── eform.py           e-Form 공지
    └── biz_legacy.py      업무포털 게시판 직접 수집
tests/                 단위 테스트 (합성 SSV, 가짜 HTTP·RSS·발송 함수)
docs/SOURCES.md        출처별 상세 동작
run.sh / setup.sh      cron 실행 / 설치
```

새 브라우저형 출처를 추가하려면 `sources/`에 `fetch()`가 `MainNotice` 목록을 돌려주는 모듈을 만들고 `NoticeSource`를 정의한 뒤, `runner.py`에 한 줄 등록합니다. 저장·재시도·cooldown은 `notice_board.run_notice_source`가 처리합니다.

## 빠른 시작

```bash
git clone https://github.com/heetae2007/Hira_Web_Crawler.git
cd Hira_Web_Crawler
./setup.sh                 # venv, 의존성, Chromium 설치, .env 생성
# .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력
./.venv/bin/python -m hira_alert.check main     # 발송 없이 조회만 확인
./run.sh                                         # 1회 실행
```

Telegram 봇 만들기와 `chat_id` 확인 방법은 [docs/SOURCES.md](docs/SOURCES.md)를 참고하세요. 5분마다 실행하려면 cron에 등록합니다.

```cron
*/5 * * * * /절대경로/Hira_Web_Crawler/run.sh >> /절대경로/Hira_Web_Crawler/cron.log 2>&1
```

Windows는 `.\.venv\Scripts\python -m hira_alert`로 실행합니다.

## 설정 (.env)

전체 항목은 [.env.example](.env.example)에 있습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | (필수) | 발송 대상 |
| `INCLUDE_KEYWORDS`, `EXCLUDE_KEYWORDS` | 비움 | RSS·legacy 제목/요약 필터. 쉼표 구분 |
| `BIZ_MODE` | `main` | `main` / `legacy` / `both` / `off` |
| `BIZ_MAIN_MIN_INTERVAL` | `300` | 업무포털 메인 최소 조회 간격(초, 최소 60) |
| `EFORM_ENABLED` | `1` | e-Form 사용 여부 |
| `EFORM_MIN_INTERVAL`, `EFORM_PAGES` | `300`, `1` | 조회 간격(최소 60초), 페이지 수(1~10) |
| `DB_PATH`, `LOG_PATH` | `hira_alert.db`, `hira_alert.log` | 프로젝트 루트 기준 |

RSS와 legacy는 한국 시간 기준 **2026-09-09 이후** 게시글만 알립니다. 그 이전 글은 기준점으로만 저장합니다. 업무포털 메인과 e-Form은 첫 실행에 보이는 공지를 모두 알립니다.

## 점검 명령

DB와 Telegram을 건드리지 않고 조회만 확인합니다.

```bash
python -m hira_alert.check main
python -m hira_alert.check eform --pages 2
python -m hira_alert.check legacy --bbs-id BBSMSTR_000000000675
```

## 테스트

```bash
python -m unittest discover -s tests -t .
```

임시 DB와 합성 응답, 가짜 발송 함수를 쓰므로 운영 DB와 Telegram에는 접근하지 않습니다. 브라우저 테스트는 Playwright와 Chromium이 필요합니다.

## 알려진 한계

- 메인 화면·e-Form 첫 페이지에 보이는 항목만 감시합니다. 한 주기 사이에 목록 밖으로 밀려난 공지는 놓칠 수 있습니다.
- 전송 직후 저장 전에 프로세스가 죽으면 같은 알림이 한 번 더 갈 수 있습니다.
- 상세 본문과 첨부파일은 내려받지 않습니다.
