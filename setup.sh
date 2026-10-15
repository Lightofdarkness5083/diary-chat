#!/bin/sh
# 처음 한 번 실행한다: 가상환경을 만들고, 패키지를 설치하고, .env를 준비한다.
# 실행: sh setup.sh
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "설치를 마쳤습니다."
if [ -f bible/bible_clean.db ]; then
  .venv/bin/python -m bible.check_db || echo "성경 DB 검사에 실패한 항목이 있습니다. 위의 내용을 확인해 주세요."
else
  echo "성경 DB가 없습니다. bible 폴더에 bible_clean.db를 넣어 주세요."
fi
if ! grep -q '^ANTHROPIC_API_KEY=.' .env; then
  echo "다음 할 일: .env 파일을 열어 ANTHROPIC_API_KEY= 뒤에 API 키를 넣어 주세요."
fi
