"""다른 주소의 화면(Vercel)이 서버를 부를 수 있는지 검사.  실행: .venv/bin/python -m tests.test_cors"""
import importlib
import os

os.environ["APP_PASSCODE"] = "열쇠"
os.environ["ALLOWED_ORIGINS"] = "https://diary-chat.vercel.app/, https://another.example"

from fastapi.testclient import TestClient  # noqa: E402

import dev_main  # noqa: E402

app = importlib.reload(dev_main).app
client = TestClient(app)
ALLOWED, STRANGER = "https://diary-chat.vercel.app", "https://stranger.example"

# 1. 브라우저의 사전 문의(OPTIONS)에 답한다. 암호 없이 와도 막지 않는다
r = client.options("/api/meditation/start", headers={
    "Origin": ALLOWED, "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "x-passcode, authorization, content-type"})
assert r.status_code == 200, r.status_code
assert r.headers["access-control-allow-origin"] == ALLOWED
assert "x-passcode" in r.headers["access-control-allow-headers"].lower()

# 2. 암호가 틀렸다는 답(401)도 허락된 화면이 읽을 수 있다. 그래야 암호 입력 창이 뜬다
r = client.get("/api/meditation/books", headers={"Origin": ALLOWED})
assert r.status_code == 401 and r.headers["access-control-allow-origin"] == ALLOWED

# 3. 명단에 없는 주소에는 허락 표시를 붙이지 않는다
r = client.get("/api/meditation/books", headers={"Origin": STRANGER})
assert "access-control-allow-origin" not in r.headers

# 4. 명단은 자물쇠가 아니다: 허락된 주소여도 암호는 그대로 확인한다
r = client.get("/api/config", headers={"Origin": ALLOWED})
assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ALLOWED

# 5. 끝의 빗금(/)과 띄어쓰기는 알아서 정리한다
r = client.get("/api/config", headers={"Origin": "https://another.example"})
assert r.headers["access-control-allow-origin"] == "https://another.example"

# 6. 명단을 비워 두면 예전처럼 같은 주소에서만 부를 수 있다
os.environ["ALLOWED_ORIGINS"] = ""
plain = TestClient(importlib.reload(dev_main).app)
r = plain.get("/api/config", headers={"Origin": ALLOWED})
assert "access-control-allow-origin" not in r.headers

print("모든 검사 통과")
