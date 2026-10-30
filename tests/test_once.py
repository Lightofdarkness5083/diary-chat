"""같은 요청은 한 번만 검사.  실행: .venv/bin/python -m tests.test_once
연결이 끊겨 화면이 같은 요청(같은 요청 번호)을 다시 보내도 AI는 한 번만, 대화도 한 번만 남는다."""
import os
import threading
import time

os.environ.pop("FIREBASE_SERVICE_ACCOUNT", None)
os.environ.pop("APP_PASSCODE", None)
os.environ["DIARY_DEV_LOGIN"] = "1"

from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from once import Once  # noqa: E402
from diary import access  # noqa: E402
from meditation import ai_client  # noqa: E402
import chat.routes  # noqa: E402
import meditation.routes  # noqa: E402
import dev_main  # noqa: E402

# ---- Once 자체 ----
once, calls = Once(), []
assert [once.run("k", lambda: calls.append(1) or "답") for _ in range(3)] == ["답"] * 3 and len(calls) == 1
assert once.run("", lambda: calls.append(1) or "x") == "x" and len(calls) == 2          # 번호 없으면 그냥 한 번
fails = []
assert once.run("bad", lambda: fails.append(1) or JSONResponse({}, status_code=502)).status_code == 502
assert once.run("bad", lambda: fails.append(1) or "다시 됨") == "다시 됨" and len(fails) == 2   # 실패는 기억하지 않는다
# 처음 요청이 아직 답을 만드는 중이면, 다시 온 요청은 기다렸다가 같은 답을 받는다
slow, results = [], []
def work():
    slow.append(1); time.sleep(0.3); return "느린 답"
threads = [threading.Thread(target=lambda: results.append(once.run("slow", work))) for _ in range(3)]
[t.start() for t in threads]; [t.join() for t in threads]
assert results == ["느린 답"] * 3 and len(slow) == 1

# ---- 돌아보기 비서: 같은 물음을 다시 보내도 AI 한 번, 대화 한 줄 ----
access.reset()
chat.routes.read_prompt = lambda name: "시험용 지시문"
asked = []
ai_client.reply_with_tools = lambda system, messages, tools, run, **kw: (asked.append(1), "답")[1]
client = TestClient(dev_main.app)
ME = {"Authorization": "Bearer dev:me"}
body = {"messages": [{"role": "user", "content": "올해 어떤 책?"}], "today": "2026-10-30", "request_id": "q1"}
first = client.post("/api/chat", json=body, headers=ME).json()
again = client.post("/api/chat", json=body, headers=ME).json()
assert first == again and len(asked) == 1, (first, again, asked)
stored = client.get(f"/api/conversations/{first['conversation_id']}", headers=ME).json()
assert len(stored["messages"]) == 2, stored                       # 물음 하나, 답 하나
other = client.post("/api/chat", json={**body, "request_id": "q2"}, headers=ME).json()   # 새로 물으면 새로 답한다
assert len(asked) == 2 and other["reply"] == "답"
YOU = {"Authorization": "Bearer dev:you"}                         # 다른 사람의 같은 번호는 따로
client.post("/api/chat", json=body, headers=YOU)
assert len(asked) == 3

# ---- 묵상 정리: 같은 정리 요청을 다시 보내도 AI 한 번 ----
built = []
meditation.routes.build_record = lambda session: (built.append(1), {"title": "정리"})[1]
sid = "s" * 32
meditation.routes.SESSIONS[sid] = {"messages": [{"role": "user", "content": "기도"}], "passage": {}, "system": "", "completed": True}
r1 = client.post("/api/meditation/record", json={"session_id": sid, "request_id": "r1"}).json()
r2 = client.post("/api/meditation/record", json={"session_id": sid, "request_id": "r1"}).json()
assert r1 == r2 == {"title": "정리"} and len(built) == 1
client.post("/api/meditation/record", json={"session_id": sid, "request_id": "r2"})          # 묵상으로 돌아갔다가 다시 정리하면 새 번호, 새 정리
assert len(built) == 2

print("모든 검사 통과")
