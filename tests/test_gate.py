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
from diary.store import AlreadyExists, FirestoreStore  # noqa: E402
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
assert store.members["you@dev"]["name"] == "you" and sheet_rows[-1][0] == 2 and sheet_rows[-1][2:] == ["you", "you@dev"]
assert store.members["you@dev"]["seat"] == 2
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

# 9. 마지막 자리에 여러 사람이 동시에 들어와도 자리 수를 넘지 않는다
import threading  # noqa: E402
os.environ["MAX_MEMBERS"] = "5"
slow_count = store.count_members
def counting_slowly():
    n = slow_count(); import time; time.sleep(0.05); return n
store.count_members = counting_slowly
answers = []
people = [threading.Thread(target=lambda i=i: answers.append(
    client.post("/api/join", headers={"Authorization": f"Bearer dev:crowd{i}"}).json())) for i in range(8)]
[t.start() for t in people]; [t.join() for t in people]
store.count_members = slow_count
assert len(store.members) == 5, len(store.members)
assert sum(1 for a in answers if a.get("new")) == 3 and sum(1 for a in answers if a.get("code") == "full") == 5
assert sorted(m["seat"] for m in store.members.values() if "seat" in m) == [2, 3, 4, 5]
os.environ["MAX_MEMBERS"] = "2"

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

    def set(self, data, merge=False):
        old = copy.deepcopy(self.docs.get(self.path) or {}) if merge else {}
        for key, value in data.items():       # Increment(1)은 있던 값에 더한다
            old[key] = old.get(key, 0) + value.value if type(value).__name__ == "Increment" else copy.deepcopy(value)
        self.docs[self.path] = old

    def create(self, data):
        if self.path in self.docs:
            raise AlreadyExists("있음")
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


# 같은 기록이 거의 동시에 두 번 오면: 늦은 요청은 '없다'를 본 뒤 create에서 '이미 있음'을 만난다. 500이 아니라 같은 기록으로 받는다
from diary.schema import FIELDS  # noqa: E402
rec = {k: "" for k in FIELDS}
rec.update(date="2026-10-20", passage="시편 23:1-6", book="시편", chapter_start=23, verse_start=1, chapter_end=23, verse_end=6)
fs.add("u1", "rec1", rec)                       # 먼저 온 요청이 만들었다
looked = []
real_doc = fs._doc
class LateDoc(Doc):
    def get(self):
        if not looked:                          # 늦은 요청이 처음 볼 때는 아직 없었다
            looked.append(1)
            return Snap(None)
        return super().get()
fs._doc = lambda record_id: LateDoc(db.docs, ("diaries", record_id))
again = fs.add("u1", "rec1", rec)
fs._doc = real_doc
assert looked and again["passage"] == "시편 23:1-6", again
other = dict(rec, passage="시편 24:1-6")
looked.clear(); fs._doc = lambda record_id: LateDoc(db.docs, ("diaries", record_id))
try:
    fs.add("u1", "rec1", other); raise AssertionError("다른 내용은 거절해야 한다")
except AssertionError:
    raise
except Exception as refused:
    assert type(refused).__name__ == "Conflict", refused
fs._doc = real_doc
print("모든 검사 통과")
