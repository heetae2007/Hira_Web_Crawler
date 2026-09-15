# HIRA 심평원 고시 Telegram 알리미

건강보험심사평가원(HIRA)의 공식 RSS와 biz.hira 공개 게시판을 주기적으로 확인해 Telegram으로 알려줍니다. RSS는 키워드에 맞는 새 게시물, biz는 고시번호가 확인된 신규·수정 게시물을 알립니다.

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
Copy-Item .env.example .env
```

## 3. 설정

`.env`를 열어 최소 다음 두 값을 수정합니다.

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

첫 실행 여부와 관계없이 한국 시간 기준 게시일로 처리합니다.

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

## biz.hira 고시 수집

기본 게시판 ID는 `BBSMSTR_000000000675`입니다. 추가 게시판은 쉼표로 구분합니다.

```dotenv
BIZ_BBS_IDS=BBSMSTR_000000000675
BIZ_MAX_PAGES=200
```

- `BIZ_BBS_IDS=`로 비우면 기존 RSS만 수집합니다. 기존 `.env`에 설정이 없으면 위 게시판이 기본 활성화됩니다.
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
