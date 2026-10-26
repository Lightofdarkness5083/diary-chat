"""문지기 검사: 선착순 참여, 명단에 있는 계정만, 하루 천장 안에서.  실행: .venv/bin/python -m tests.test_gate
실제 Firestore와 AI에 연결하지 않는다."""
import copy
import os

os.environ.pop("FIREBASE_SERVICE_ACCOUNT", None)
os.environ.pop("APP_PASSCODE", None)
os.environ["DIARY_DEV_LOGIN"] = "1"
os.environ["AI_DAILY_LIMIT"] = "3"
os.environ["MAX_MEMBERS"] = "2"
os.environ.pop("SIGNUP_SHEET_ID", None)

from fastapi.testclient import TestClient  # noqa: E402

import gate  # noqa: E402
import signup_sheet  # noqa: E402
from diary import access  # noqa: E402
from diary.store import FirestoreStore  # noqa: E402
from meditation import ai_client  # noqa: E402
import chat.routes  # noqa: E402
import dev_main  # noqa: E402

chat.routes.read_prompt = lambda name: "시험용 지시문"
ai_client.reply_with_tools = lambda system, messages, tools, run, **kw: "답"

access.reset()
store = access.store()
store.members = {"me@dev": {"name": "me"}}          # 명단: me 한 사람
gate.reset()
sheet_rows = []
signup_sheet.add = lambda row: sheet_rows.append(row)     # 시트에 적는 일은 흉내만 낸다
client = TestClient(dev_main.app)
ME, STRANGER = {"Authorization": "Bearer dev:me"}, {"Authorization": "Bearer dev:you"}
ASK = {"messages": [{"role": "user", "content": "올해 어떤 책?"}], "today": "2026-10-20"}

# 1. 로그인하지 않으면 지키는 길에 들어오지 못한다. 본문 읽기와 설정은 열려 있다
assert client.post("/api/chat", json=ASK).json()["code"] == "sign_in"
assert client.get("/api/config").status_code == 200
assert client.get("/api/meditation/books").status_code == 200

# 2. 명단에 없는 계정은 들어오지 못하고, 어느 계정인지 알려 준다
r = client.get("/api/diary/records", headers=STRANGER)
assert r.status_code == 403 and r.json()["code"] == "not_invited" and r.json()["email"] == "you@dev", r.text
assert client.post("/api/meditation/start", json={"ref": "요한복음 1:1-5"}, headers=STRANGER).status_code == 403
assert client.get("/api/conversations", headers=STRANGER).status_code == 403

# 3. 명단에 있는 계정은 들어온다
assert client.get("/api/diary/records", headers=ME).status_code == 200
assert client.post("/api/chat", json=ASK, headers=ME).status_code == 200

# 4. 하루 천장 (시험에서는 3번): 넘으면 429. 일기장 읽기는 세지 않는다
assert client.post("/api/chat", json=ASK, headers=ME).status_code == 200
assert client.post("/api/chat", json=ASK, headers=ME).status_code == 200
r = client.post("/api/chat", json=ASK, headers=ME)
assert r.status_code == 429 and r.json()["code"] == "daily_limit", r.text
assert client.get("/api/diary/records", headers=ME).status_code == 200
assert store.usage[("me", gate.today())] == 4

# 5. 브라우저의 사전 문의(OPTIONS)는 막지 않는다
assert client.options("/api/chat").status_code != 403

# 6. 처음 온 사람은 /api/join으로 선착순 참여: 명단과 시트에 한 줄. 이미 있으면 그대로
assert client.post("/api/join").json()["code"] == "sign_in"
r = client.post("/api/join", headers=STRANGER)
assert r.status_code == 200 and r.json() == {"joined": True, "new": True}, r.text
assert store.members["you@dev"]["name"] == "you" and sheet_rows[-1][1:] == ["you", "you@dev"]
assert client.get("/api/diary/records", headers=STRANGER).status_code == 200     # 참여하자마자 들어온다
assert client.post("/api/join", headers=STRANGER).json() == {"joined": True, "new": False} and len(sheet_rows) == 1
assert client.post("/api/join", headers=ME).json()["new"] is False

# 7. 자리(시험에서는 2명)가 차면 다음 사람은 들어오지 못한다
r = client.post("/api/join", headers={"Authorization": "Bearer dev:third"})
assert r.status_code == 403 and r.json()["code"] == "full" and "third@dev" not in store.members, r.text

# 8. 관리자가 막은 사람(disabled: true)은 참여하기로 되살아나지 않는다
store.members["you@dev"]["disabled"] = True; gate.reset()
assert client.get("/api/diary/records", headers=STRANGER).status_code == 403
assert client.post("/api/join", headers=STRANGER).json()["code"] == "not_invited"

# ---- Firestore 쪽 코드: 명단 문서와 사용 횟수 ----
class Snap:
    def __init__(self, data):
        self.exists, self._data = data is not None, data

    def to_dict(self):
        return copy.deepcopy(self._data)


class Doc:
    def __init__(self, docs, path):
        self.docs, self.path = docs, path

    def get(self):
        return Snap(self.docs.get(self.path))

    def set(self, data):
        self.docs[self.path] = copy.deepcopy(data)


class Listed:
    def __init__(self, data):
        self._data = data


class Col:
    def __init__(self, docs, name):
        self.docs, self.name = docs, name

    def document(self, doc_id):
        return Doc(self.docs, (self.name, doc_id))

    def stream(self):
        return [Listed(d) for p, d in self.docs.items() if p[0] == self.name]


class FakeFirestore:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return Col(self.docs, name)


db = FakeFirestore()
fs = FirestoreStore(db)
db.docs[("members", "hong@gmail.com")] = {"name": "홍길동"}
db.docs[("members", "gone@gmail.com")] = {"disabled": True}
assert fs.is_member("Hong@Gmail.com ")                  # 대소문자, 띄어쓰기는 가리지 않는다
assert not fs.is_member("gone@gmail.com")               # disabled: true면 초대 취소
assert not fs.is_member("nobody@gmail.com") and not fs.is_member("")
assert fs.count_members() == 2                          # 막아 둔 사람도 자리를 차지한다
fs.add_member("New@Gmail.com", {"name": "새 사람"})
assert fs.find_member("new@gmail.com") == {"name": "새 사람"} and fs.count_members() == 3
assert [fs.count_use("u1", "2026-10-20") for _ in range(3)] == [1, 2, 3]
assert fs.count_use("u1", "2026-10-21") == 1            # 날마다 새로 센다
assert db.docs[("usage", "u1_2026-10-20")] == {"uid": "u1", "day": "2026-10-20", "count": 3}

print("모든 검사 통과")
