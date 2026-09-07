# HIRA 심평원 고시 Telegram 알리미

건강보험심사평가원(HIRA)의 공식 RSS를 주기적으로 확인해 새 게시물 중 지정 키워드가 포함된 글을 Telegram으로 알려줍니다.

## 기본 감시 RSS

- 공지사항
- 보험인정기준 - 행위
- 보험인정기준 - 치료재료
- 보험인정기준 - 약제
- 보험인정기준 - 의료급여
- 청구관련기준자료

기본 키워드는 `고시`입니다.

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

기본적으로 첫 실행에서는 현재 RSS의 기존 항목을 DB에 등록만 하고 알림을 보내지 않습니다.
그 다음 실행부터 새 항목이 올라오면 알림을 보냅니다.

기존 항목까지 테스트 전송하고 싶으면:

```dotenv
SEND_EXISTING_ON_FIRST_RUN=true
```

주의: 이 경우 RSS에 남아 있는 과거 글 중 키워드에 맞는 글이 여러 개 한꺼번에 올 수 있습니다.

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

## 다시 처음부터 테스트

DB를 삭제하면 처음 실행 상태가 됩니다.

```bash
rm hira_alert.db
```

이후 `SEND_EXISTING_ON_FIRST_RUN=true`로 한 번 실행하면 현재 RSS의 기존 글 중 키워드 일치 항목도 발송됩니다.

## 운영 권장

개인 PC를 계속 켜두는 것보다 Ubuntu 서버, NAS, Raspberry Pi 또는 항상 켜져 있는 Linux 환경에서 cron으로 실행하는 것이 안정적입니다.
