# HIRA 심평원 고시 Telegram 알리미

건강보험심사평가원(HIRA)의 공식 RSS, 요양기관 업무포털 메인 공지사항, e-Form 공지사항을 주기적으로 확인해 Telegram으로 알려줍니다. 두 포털은 비로그인 Playwright Chromium으로 조회합니다. 기존 직접 POST 게시판 수집은 선택 기능입니다.

## e-Form 공지사항 (기본 활성화)

```dotenv
EFORM_ENABLED=1
EFORM_MIN_INTERVAL=300
EFORM_PAGES=1
```

- 새 비로그인 브라우저로 `https://ef.hira.or.kr/efweb/index.do`에 접속한 뒤, 동일 브라우저 컨텍스트의 쿠키를 공유하는 API 클라이언트로 `POST /efweb/ia/iac/selectBoardList.ndo`를 호출합니다. 로그인·인증서·쿠키 하드코딩은 사용하지 않습니다.
- 제공된 `dsCond` 컬럼 순서, `boardTpCd=W`, `fetchRow=20`, NULL(`0x03`)과 빈 문자열 구분을 보존하여 SSV 바이트를 만듭니다. `Content-Type: text/xml`, `X-Requested-With: XMLHttpRequest`, `Accept: application/xml, text/xml, */*`를 사용합니다.
- 응답 `dsList`의 `brdId`, 전체 제목 `brdTtl`, 작성일 `creDt`를 사용합니다. 작성일은 날짜로 표시하며 `chgDt` 수정일과 구분합니다. 응답의 `brdTpCd=01`(일반)은 요청의 `boardTpCd=W`와 다른 코드입니다.
- 기본 범위는 **목록 첫 페이지 20건**입니다. `EFORM_PAGES=2`이면 첫 40건까지 조회하며 1~10페이지 설정이 가능합니다. 전체 게시판 수집을 보장하지 않으며 감시 범위 밖의 항목은 놓칠 수 있습니다. 게시판의 정렬 순서를 그대로 따릅니다.
- **첫 실행에는 조회 범위의 기존 공지를 모두 알립니다.** 이후 처음 확인한 `brdId`만 알립니다. 제목·첨부·내용 수정은 재알림하지 않으며 키워드·고시번호·날짜 제한은 적용하지 않습니다. 다른 출처에 같은 공지가 있으면 각각 알릴 수 있습니다.
- 제목·작성일·게시글 ID·e-Form 진입 주소를 Telegram으로 보냅니다. 상세 본문과 첨부파일은 다운로드하지 않습니다.
- 기존 DB에 `eform_notices`, `eform_poll` 테이블을 추가합니다. biz의 기존 DB 테이블과 발송 상태는 유지합니다. 알림 완료는 전송 성공 후 기록하며, 실패 항목은 목록에서 사라져도 재시도합니다. 전송 직후 저장 전에 종료되면 중복 전송될 수 있습니다.
- 기본 조회 간격은 300초(최소 60초)이며 API 요청 간에는 2초 대기합니다. 수집 오류 시 같은 실행에서 반복 요청하지 않습니다. 빈 목록, 형식 변경, 반복 페이지, 조회 도중 건수 변경은 실패로 기록하고 직전 목록을 보존합니다.
- 2026-09-22 개발 환경에서 공지사항 화면의 실제 SSV 응답을 확보했고, 새 수집기로 1페이지 20건 및 2페이지 40건 조회에 성공했습니다. 본문에 쿠키 문자열을 재삽입하지 않아도 정상 조회되었습니다. Ubuntu 운영 환경과 실제 Telegram 발송은 별도 확인이 필요합니다.
- 기존 `run.sh`와 5분 cron을 그대로 사용합니다. `BIZ_MODE`와 독립적으로 실행하며 `EFORM_ENABLED=0`으로 끌 수 있습니다.

Ubuntu에 **`eform_hira.py`, `biz_hira.py`, `hira_alert.py`를 함께 업데이트**하세요. 로컬 변경을 Git으로 배포한다면 commit/push 이후 서버에서 반영해야 합니다. 기존 Playwright/Chromium 설치를 그대로 사용합니다.

```bash
cd /home/ubuntu/Hira_Web_Crawler
# DB 저장과 Telegram 발송 없이 e-form만 점검
.venv/bin/python eform_hira.py
# 필요하면 2페이지까지 점검
.venv/bin/python eform_hira.py --pages 2
# RSS, 업무포털, e-form 수집 및 알림
sh run.sh
```

테스트의 `tests/fixtures/eform_list.ssv`는 비로그인 공지 목록에서 확보한 실제 공개 응답입니다. 요청 쿠키나 인증정보는 포함하지 않습니다.

## 업무포털 메인 공지사항 (기본 활성화)

```dotenv
BIZ_MODE=main
BIZ_MAIN_MIN_INTERVAL=300
```

- 매 실행 시 새 비로그인 브라우저로 `https://biz.hira.or.kr/index.do`에 접속합니다. 로그인·인증서·저장된 브라우저 프로필을 사용하지 않습니다.
- 페이지 로딩 전에 응답 대기를 등록하고, 브라우저가 보내는 `/qya/main/selectTotalZoneList.ndo` POST의 200 응답에서 `dsBoard`를 읽습니다. Playwright [네트워크 응답 대기 API](https://playwright.dev/python/docs/network)를 사용합니다.
- 실제 비로그인 브라우저 응답에서 `bbsId`, `itemId`, `title`, `regDate`를 확인했습니다. 등록일은 `20260921100846000` 형태를 `2026-09-21`로 변환합니다. 2026-09-22 개발 환경에서 새 점검 명령으로 공지 8건을 조회했고, ID `75929`의 설명회 안내(등록일 `2026-09-21`)를 확인했습니다. Ubuntu 운영 환경의 조회·Telegram 전송은 별도 확인이 필요합니다.
- 신규 여부는 게시판 ID+게시글 ID로 판단합니다. 게시글 ID가 비어 있으면 게시판 ID+제목+등록일을 사용합니다. ID가 있는 글의 제목 수정은 신규 알림이 아닙니다.
- 기존 SQLite에 `biz_main_notices`, `biz_main_poll` 테이블을 추가합니다. 최신 목록 표시와 전체 확인 이력을 함께 유지하여 목록에서 사라졌다 다시 나타난 글은 재발송하지 않습니다.
- **첫 실행에는 현재 메인 목록의 모든 공지를 알립니다.** 메인 공지사항에는 고시번호·키워드·기존 9월 9일 날짜 필터를 적용하지 않습니다. RSS의 기존 필터는 유지됩니다.
- 알림 성공 후에만 발송 완료를 저장합니다. 실패한 알림은 목록에서 사라져도 다음 주기에 재시도합니다. 전송 직후 저장 전에 프로세스가 종료되면 중복 전송될 수 있습니다.
- 응답 실패, 필수 컬럼/날짜 오류, 빈 목록은 오류로 기록하고 직전 목록을 보존합니다. 해당 실행에서 브라우저를 다시 열지 않고 다음 주기에 재시도합니다.
- 기본 조회 간격은 300초이며 최소 60초로 제한합니다. 실패한 조회도 간격에 포함됩니다. 간격은 DB에 저장되므로 cron 재실행에도 유지됩니다. 페이지 자체가 로딩하는 리소스 요청은 브라우저가 처리합니다.
- `run.sh`는 Linux의 `flock`으로 중복 실행을 막습니다. 기본 운용은 기존 5분 cron에서 1회씩 실행하는 방식입니다.
- 메인 화면에 표시된 항목만 감시하므로 주기 사이에 목록 밖으로 밀려난 공지는 확인할 수 없습니다.
- `BIZ_MODE=legacy`는 기존 직접 POST 고시 수집, `both`는 두 방식 모두, `off`는 biz 수집을 끕니다. e-form은 `EFORM_ENABLED`로 따로 제어합니다. `both`에서는 같은 게시물에 출처별 알림이 갈 수 있습니다. 기존 `.env`에 `BIZ_BBS_IDS`만 있어도 기본 모드는 `main`입니다.

### 기존 Ubuntu 설치 업데이트

수정된 소스와 `requirements.txt`를 서버에 반영한 뒤 실행합니다. 기존 DB는 유지하세요.

```bash
cd /home/ubuntu/Hira_Web_Crawler
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium
# DB 저장 및 Telegram 발송 없는 실제 메인 목록 점검
.venv/bin/python biz_hira.py
# 기존 RSS + 메인 공지사항 확인 및 Telegram 발송
./run.sh
```

`--with-deps`는 Ubuntu 브라우저 실행에 필요한 시스템 패키지도 설치하며 sudo 권한이 필요할 수 있습니다. cron과 같은 OS 사용자로 브라우저를 설치하세요. Windows 설치는 `.venv\Scripts\python -m playwright install chromium`을 사용합니다.

테스트: `python -m unittest discover -s tests` (Playwright와 Chromium 설치 필요). 브라우저 테스트는 네트워크 응답을 로컬에서 대체하여 사이트 요청·Telegram 발송 없이 검증합니다.

## 기본 감시 RSS

- 공지사항
- 보험인정기준 - 행위
- 보험인정기준 - 치료재료
- 보험인정기준 - 약제
- 보험인정기준 - 의료급여
- 청구관련기준자료

기본적으로 키워드 제한 없이 모집 결과를 포함한 모든 RSS 게시물을 대상으로 합니다.

## 1. Telegram 봇 만들기

1. Telegram에서 `@BotFather` 검색
2. `/newbot`
3. 봇 이름과 username 설정
4. 발급받은 Bot Token 복사
5. 만든 봇에게 아무 메시지나 한 번 전송

chat_id 확인:

브라우저에서 아래 주소를 열어 확인합니다.

`https://api.telegram.org/bot<여기에_봇토큰>/getUpdates`

결과의 `"chat":{"id": ... }` 값을 사용합니다.

그룹에서 사용한다면 봇을 그룹에 추가하고 그룹에서 메시지를 한 번 보낸 뒤 `getUpdates`를 다시 확인하세요.

## 2. 설치

Linux / macOS:

```bash
unzip hira_notice_alert.zip
cd hira_notice_alert
./setup.sh
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
Copy-Item .env.example .env
```

## 3. 설정

`.env`를 열어 최소 다음 두 값을 수정합니다.

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

RSS 및 선택 기능인 기존 고시 수집은 첫 실행 여부와 관계없이 한국 시간 기준 게시일로 처리합니다. 메인 공지사항은 위 정책을 따릅니다.

- 2026년 9월 8일까지: DB에 기준점으로 저장만 합니다.
- 2026년 9월 9일부터: 미발송 게시물을 알립니다.
- 기존 DB에 저장됐지만 발송되지 않은 항목도 다시 확인합니다. 이미 발송된 항목은 같은 RSS에서 재발송하지 않습니다.
- 게시일이 없거나 해석할 수 없으면 오류를 기록하고 발송을 보류합니다.

Linux 서버에도 수정한 `hira_alert.py`와 `biz_hira.py`를 함께 반영하고, 서버 `.env`를 다음처럼 설정하세요. 기존 DB는 유지하세요.

```dotenv
INCLUDE_KEYWORDS=
EXCLUDE_KEYWORDS=
```

`SEND_EXISTING_ON_FIRST_RUN`은 더 이상 사용하지 않습니다. 다음 cron 실행에서 9월 9일 이후 미발송 글이 여러 건 전송될 수 있습니다.
RSS 수집 범위는 현재 RSS 항목과 기존 DB입니다. RSS에도 DB에도 없는 게시물은 알릴 수 없습니다. biz 수집 범위는 아래와 같습니다.

## biz.hira 기존 고시 수집 (BIZ_MODE=legacy 또는 both)

기본 게시판 ID는 `BBSMSTR_000000000675`입니다. 추가 게시판은 쉼표로 구분합니다.

```dotenv
BIZ_BBS_IDS=BBSMSTR_000000000675
BIZ_MAX_PAGES=200
BIZ_MODE=legacy
```

- `BIZ_BBS_IDS=`로 비우면 기존 직접 POST 게시판 수집을 생략합니다. 메인 수집 활성화 여부는 `BIZ_MODE`로 결정합니다.
- `selectComBbsList.ndo`에 UTF-8 SSV `dsParam`을 POST하고 `dsMain`을 파싱합니다. 브라우저 쿠키·분석 식별자·로그인 정보를 넣지 않습니다.
- 연결 10초 / 응답 30초 timeout입니다. 연결·응답 시간 초과와 HTTP 429/500/502/503/504는 최대 3회 요청하며 1초, 2초 간격으로 재시도합니다. 파싱 오류와 리다이렉트는 실패로 기록합니다.
- 일반 게시글이 없는 페이지까지 순회합니다. 이미 저장된 ID가 있는 페이지도 계속 읽으므로 뒤쪽 신규·수정 게시글을 확인합니다. 고정 공지는 ID로 중복 제거하고 종료 판단에서 제외합니다.
- 일반 게시글만 반복되거나 `BIZ_MAX_PAGES`에 도달하면 수집 미완료 오류를 기록합니다. 수집한 항목은 보존됩니다. 기본 상한보다 게시글이 많으면 값을 늘리세요.
- 첫 실행도 기존 정책에 따라 **등록일 2026-09-09 이후의 고시를 알립니다**. 그 이전 글은 저장만 하며, 이후 수정되어도 등록일 기준 제한은 유지합니다. 알림 없는 첫 실행 baseline으로 변경하지 않았습니다.
- `(source, bbs_id, ntt_id)`로 신규 여부를 판단합니다. 수정일·제목·첨부파일 ID·본문·등록일 변경은 `UPDATED`, 같으면 `UNCHANGED`를 반환합니다. 정렬 순서나 마지막 조회시간은 사용하지 않습니다.
- 제목을 먼저 검사하고 본문도 검사하여 `고시 제2026 - 184호` 등의 번호를 `2026-184`로 저장합니다. 여러 번호는 모두 저장하고 첫 번호는 `gosi_no`에 둡니다. HTML과 공백 차이를 처리하며 `일부개정`이라는 단어만으로는 고시로 분류하지 않습니다.
- 고시번호를 인용한 일반 안내도 포함될 수 있는 정규식 기반 분류입니다. 첨부파일 안에만 번호가 있는 글은 현재 분류할 수 없습니다.
- 기존 SQLite 파일에 `biz_posts` 테이블을 자동 생성합니다. 기존 `seen_items`와 RSS의 중복 키는 유지됩니다. `change_state`는 마지막 변경 상태를 보관하고 실행 로그에는 NEW/UPDATED/UNCHANGED 개수를 각각 기록합니다.
- 일반 공지도 저장합니다. 고시번호·게시일·기존 키워드 필터를 통과한 글만 발송합니다. 발송 완료 버전은 성공 후에만 갱신하며, 실패한 신규/수정 알림은 목록에서 빠져도 DB에서 재시도합니다. 여러 번 수정되면 최신 수집 버전을 알립니다.
- RSS와 biz 사이의 동일 고시번호 중복은 제거하지 않습니다. 두 출처에 모두 올라온 고시는 각각 알릴 수 있습니다.

### 실제 서버 검증 상태와 조회 점검

개발 환경에서 쿠키 없는 POST를 시도했으나 30초 응답 timeout이 발생했습니다. 따라서 **쿠키 없는 정상 조회, 실제 응답 컬럼과 게시판 범위는 아직 검증되지 않았습니다**. 현재 구현은 제공된 필드명과 [Nexacro 공식 SSV 규격](https://docs.tobesoft.com/advanced_development_guide_nexacro_17_ko/a5e1e2fb1080ae59)을 기준으로 합니다. 테스트 데이터는 실제 서버에서 채집한 응답이 아닌 합성 데이터입니다.

운영 환경에서 먼저 다음 명령으로 첫 페이지를 확인할 수 있습니다. DB에 저장하거나 Telegram을 발송하지 않습니다.

```powershell
.\.venv\Scripts\python biz_hira.py --bbs-id BBSMSTR_000000000675
```

Linux에서는 `./.venv/bin/python biz_hira.py --bbs-id BBSMSTR_000000000675`를 사용합니다. 성공하면 게시글 수·응답 컬럼·고시 후보 수를 출력합니다. 실제 응답이 다르면 필수 컬럼 오류를 내도록 하여 누락을 빈 목록으로 취급하지 않습니다.

상세 조회·첨부파일 다운로드 주소는 제공되거나 검증되지 않아 추측해서 추가하지 않았습니다. `nttCn` 본문과 `atchFileId`를 저장하고 첨부 유무를 알립니다. 메시지는 포털 주소와 게시글 ID·제목을 제공하며, 직접 상세 링크는 아직 지원하지 않습니다. 목록에서 `nttCn` 자체가 누락되면 상세 수집 연동이 필요하다는 뜻이므로 오류를 확인해야 합니다.

## 4. 수동 실행

Linux / macOS:

```bash
./run.sh
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python hira_alert.py
```

정상 동작하면 `hira_alert.db`와 `hira_alert.log`가 생성됩니다.

## 5. 5분마다 자동 실행 (Linux cron)

`crontab -e`를 열고 아래 한 줄을 추가합니다.

```cron
*/5 * * * * /절대경로/hira_notice_alert/run.sh >> /절대경로/hira_notice_alert/cron.log 2>&1
```

예:

```cron
*/5 * * * * /home/ubuntu/hira_notice_alert/run.sh >> /home/ubuntu/hira_notice_alert/cron.log 2>&1
```

## 키워드 변경

`.env`:

```dotenv
INCLUDE_KEYWORDS=고시,급여기준,수가
```

쉼표로 구분합니다. 하나라도 제목/요약에 포함되면 알림을 보냅니다.

모든 신규 게시물을 받고 싶으면:

```dotenv
INCLUDE_KEYWORDS=
```

제외할 단어도 지정할 수 있습니다.

```dotenv
EXCLUDE_KEYWORDS=채용,개인정보
```

## 테스트

```bash
python -m unittest discover -s tests -v
```

테스트는 임시 DB, 합성 SSV 응답, 가짜 HTTP/RSS/발송 함수를 사용합니다. 운영 DB와 Telegram에는 접근하지 않습니다.

## 운영 권장

개인 PC를 계속 켜두는 것보다 Ubuntu 서버, NAS, Raspberry Pi 또는 항상 켜져 있는 Linux 환경에서 cron으로 실행하는 것이 안정적입니다.
