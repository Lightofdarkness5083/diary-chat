#!/bin/sh
# 묵상 부분만 켠다 (dev_main.py). 이미 켜져 있는 서버가 있으면 먼저 끈다.
# 실행: sh run.sh   끄기: Ctrl + C
cd "$(dirname "$0")"
lsof -ti:8000 | xargs kill 2>/dev/null
sleep 1
echo "브라우저에서 http://127.0.0.1:8000 을 여세요."
exec .venv/bin/uvicorn dev_main:app
