"""접속 암호 검사.  실행: .venv/bin/python -m tests.test_passcode"""
import os
from urllib.parse import quote

from tests.test_bible import make_db

os.environ["BIBLE_DB"] = make_db(all_books=True)

from fastapi.testclient import TestClient  # noqa: E402

import dev_main  # noqa: E402

client = TestClient(dev_main.app)
path = "/api/meditation/passage?ref=골로새서 4:2-6"

# 암호를 정하지 않았으면 누구나 들어온다 (내 컴퓨터에서 쓸 때)
os.environ.pop("APP_PASSCODE", None)
assert client.get(path).status_code == 200

# 암호를 정하면, 암호 없이는 API를 쓸 수 없다. 첫 화면은 열린다
os.environ["APP_PASSCODE"] = "은혜2026"
assert client.get("/").status_code == 200
assert client.get("/api/config").status_code == 200        # 화면이 로그인 방법을 알아야 하므로 설정은 열려 있다
assert client.get(path).status_code == 401
assert client.get("/api/diary/records").status_code == 401   # 일기장은 암호 없이는 닿지 않는다
assert client.get(path, headers={"X-Passcode": "wrong"}).status_code == 401
assert client.post("/api/meditation/start", json={"ref": "골 4:2-6"}).status_code == 401
assert client.get(path, headers={"X-Passcode": quote("은혜2026")}).status_code == 200
os.environ.pop("APP_PASSCODE")

print("모든 검사 통과")
