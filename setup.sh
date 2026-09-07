#!/bin/sh
set -eu
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo ".env 파일을 생성했습니다."
    echo "TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 입력한 뒤 ./run.sh 를 실행하세요."
fi

chmod +x run.sh setup.sh
