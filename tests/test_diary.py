import json
"""일기장 검사.  실행: .venv/bin/python -m tests.test_diary
실제 Firestore에 연결하지 않는다. 가짜 저장소로 데이터를 다루는 원칙을 하나씩 확인한다."""
import copy
import os

os.environ.pop("FIREBASE_SERVICE_ACCOUNT", None)
os.environ["DIARY_DEV_LOGIN"] = "1"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import diary  # noqa: E402
from diary import access  # noqa: E402
from diary.schema import FIELDS, RecordError, clean_record  # noqa: E402
from diary.store import Conflict, FirestoreStore, MemoryStore  # noqa: E402

RECORD = {"date": "2026-10-10", "meditation_time": "07:10", "book": "골로새서", "chapter_start": 3, "verse_start": 18,
          "chapter_end": 4, "verse_end": 1, "passage": "골로새서 3:18-4:1", "title": "주 안에서 맺는 관계",
          "prayer": "주님, 마음을 엽니다.", "observation": "- 관찰\n- 반복되는 말: 주", "background": "- 배경",
          "interpretation": "- 해석", "truth": "1. 모든 관계의 주인은 그리스도시다.\n2. 나는 주님을 섬긴다.",
          "applied_truth": "나는 주님을 섬긴다.", "application": "- 주께 하듯 말한다.", "closing_prayer": ""}
assert len(FIELDS) == 17 and set(RECORD) == set(FIELDS)


def changed(**fields):
    return {**RECORD, **fields}


def without(field):
    return {k: v for k, v in RECORD.items() if k != field}


# ---- 모양이 틀린 것은 받지 않는다 ----
assert clean_record(RECORD) == RECORD and clean_record(RECORD) is not RECORD
for bad in [without("truth"), changed(uid="남의 번호"), changed(truthSummary="예전 항목"), changed(date="2026-13-01"),
            changed(date="10월 10일"), changed(meditation_time="7:10"), changed(chapter_start="3"), changed(verse_end=0),
            changed(chapter_end=True), changed(truth=None), changed(prayer=["목록"]), changed(passage="  "),
            changed(observation="가" * 20001), "글", None]:
    try:
        clean_record(bad)
        raise AssertionError(f"받으면 안 된다: {str(bad)[:40]}")
    except RecordError:
        pass


# ---- 가짜 Firestore: 실제 저장소 코드(FirestoreStore)와 도구를 그대로 돌려 본다 ----
class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id, self.exists, self._data = doc_id, data is not None, data

    def to_dict(self):
        return copy.deepcopy(self._data)


class FakeDocument:
    def __init__(self, docs, path):
        self.docs, self.path = docs, path

    def get(self):
        return FakeSnapshot(self.path[-1], self.docs.get(self.path))

    def create(self, data):
        if self.path in self.docs:
            raise RuntimeError("이미 있는 문서")
        self.docs[self.path] = copy.deepcopy(data)

    def update(self, data):
        self.docs[self.path].update(copy.deepcopy(data))

    def set(self, data):
        self.docs[self.path] = copy.deepcopy(data)


class FakeCollection:
    def __init__(self, docs, name, only=None):
        self.docs, self.name, self.only = docs, name, only

    def document(self, doc_id):
        return FakeDocument(self.docs, (self.name, doc_id))

    def where(self, field, op, value):
        assert op == "=="
        return FakeCollection(self.docs, self.name, (field, value))

    def stream(self):
        return [FakeSnapshot(path[1], data) for path, data in list(self.docs.items())
                if path[0] == self.name and (self.only is None or data.get(self.only[0]) == self.only[1])]


class FakeFirestore:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return FakeCollection(self.docs, name)


for make in (MemoryStore, lambda: FirestoreStore(FakeFirestore())):
    s = make()
    raw = (lambda rid: s.records[rid]) if isinstance(s, MemoryStore) else (lambda rid: s.db.docs[("diaries", rid)])
    # 저장하면 다시 읽어 돌려준다. 보낸 것과 한 글자도 다르지 않다
    stored = s.add("mina", "rec00001", RECORD)
    assert stored == {"id": "rec00001", **RECORD} and s.get("mina", "rec00001") == stored
    assert set(raw("rec00001")) == set(FIELDS) | {"uid", "deleted"} and raw("rec00001")["uid"] == "mina"     # 한 문서는 19개 항목
    # 겹쳐 쌓지 않는다: 같은 번호로 같은 내용이 다시 와도 하나다
    assert s.add("mina", "rec00001", RECORD) == stored and len(s.list("mina")) == 1
    # 덮어쓰지 않는다: 같은 번호로 다른 내용이 오면 거절하고, 처음 것이 그대로 남는다
    for who, what in (("mina", changed(truth="바뀐 진리")), ("joon", RECORD), ("joon", changed(truth="준의 진리"))):
        try:
            s.add(who, "rec00001", what)                      # 남이 같은 번호를 써도 내 기록은 바뀌지 않는다
            raise AssertionError("거절해야 한다")
        except Conflict:
            pass
    assert s.get("mina", "rec00001")["truth"] == RECORD["truth"] and raw("rec00001")["uid"] == "mina"
    # 남의 것과 섞이지 않는다: 남의 기록은 보이지도, 지워지지도 않는다
    assert s.list("joon") == [] and s.get("joon", "rec00001") is None and s.remove("joon", "rec00001") is False
    s.add("joon", "rec0000j", changed(truth="준의 진리"))
    assert [r["id"] for r in s.list("mina")] == ["rec00001"] and [r["id"] for r in s.list("joon")] == ["rec0000j"]
    # 하루에 두 번 묵상해도 둘 다 남고, 날짜와 시각 순서로 나온다
    s.add("mina", "rec00002", changed(meditation_time="21:30", passage="골로새서 4:2-6"))
    s.add("mina", "rec00000", changed(date="2026-10-09"))
    assert [r["id"] for r in s.list("mina")] == ["rec00000", "rec00001", "rec00002"]
    # 지우기는 표시만 한다: 목록에서 사라지지만 문서는 남아 있고, 같은 기록이 다시 오면 되살아난다
    assert s.remove("mina", "rec00002") is True and s.remove("mina", "rec00002") is False
    assert [r["id"] for r in s.list("mina")] == ["rec00000", "rec00001"] and s.get("mina", "rec00002") is None
    assert raw("rec00002")["deleted"] is True and raw("rec00002")["truth"] == RECORD["truth"]
    assert s.add("mina", "rec00002", changed(meditation_time="21:30", passage="골로새서 4:2-6"))["id"] == "rec00002"
    assert len(s.list("mina")) == 3
    # 상태도 사람마다 따로다
    assert s.get_state("mina") is None
    s.set_state("mina", {"progress": {"book": "골로새서", "chapter": 4, "verse": 1}, "updated_at": 5})
    assert s.get_state("mina")["progress"]["verse"] == 1 and s.get_state("joon") is None
assert ("diaries", "rec00001") in s.db.docs and ("diary_state", "mina") in s.db.docs      # 실제 일기장의 자리 이름

# ---- 예전에 저장된 묵상: 지금의 구조에 맞춘다 ----
from diary import legacy  # noqa: E402
from tools import diaries as tool  # noqa: E402

OLD = {"date": "2024-03-21", "meditation_time": "16:35", "passage": "데살로니가후서 1:1-12", "prayer": "하나님, 첫 번째 공부입니다.",
       "observation": "바울과 실루아노와 디모데가 편지를 쓴다.", "background": "이방인 교회로 박해를 받았다.", "interpretation": "해석 글",
       "truth": "1. 우리는 공동체 안에서 사랑으로 산다.\n2. 선을 행하다 낙심하지 말고 포기하지 말아야 한다.",
       "application": "선을 행하되 포기하지 않는다.", "truthSummary": "선을 행하다 낙심하지 말고 포기하지 말아야 한다.", "uid": "mina"}
assert legacy.position("골로새서 3:14-4:1") == {"book": "골로새서", "chapter_start": 3, "verse_start": 14, "chapter_end": 4, "verse_end": 1}
assert legacy.position("골로세서 3:14") is None and legacy.position(None) is None
# 실제 일기장에서 읽지 못했던 아홉 본문
P = lambda text: (lambda f: f and (f["book"], f["chapter_start"], f["verse_start"], f["chapter_end"], f["verse_end"]))(legacy.position(text))
assert P("민수기 1:1-4, 1:44-46") == ("민수기", 1, 1, 1, 46) and P("사사기 9:1-6, 9:50-57") == ("사사기", 9, 1, 9, 57)
assert P("골로새서 3:18-25, 4:1") == ("골로새서", 3, 18, 4, 1)
assert P("아모스서 2:6-12") == ("아모스", 2, 6, 2, 12) and P("아모스서 9:11-15") == ("아모스", 9, 11, 9, 15) and P("호세아서 4:6-10") == ("호세아", 4, 6, 4, 10)
assert P("민수기 1:1-4, 44-46") == ("민수기", 1, 1, 1, 46)                  # 장을 다시 적지 않은 모양
assert P("민수기 1:44-46, 1:1-4") is None and P("민수기 1:1-4, 둘째") is None   # 순서가 거꾸로이거나 읽을 수 없으면 사람이 정한다
add = legacy.missing_fields(OLD)
assert add == {"book": "데살로니가후서", "chapter_start": 1, "verse_start": 1, "chapter_end": 1, "verse_end": 12, "title": "",
               "closing_prayer": "", "applied_truth": OLD["truthSummary"], "deleted": False}       # 적용 진리는 truthSummary에 들어 있었다
assert not set(add) & set(OLD)                                          # 더하기만 한다. 이미 있는 항목은 하나도 없다
assert legacy.missing_fields({**OLD, **add}) == {}                      # 한 번 맞춘 문서에는 더할 것이 없다
assert legacy.missing_fields({**OLD, "passage": "골로세서 3:14"}) is None  # 본문을 읽지 못하면 사람이 정한다

fake = FakeFirestore()
store = FirestoreStore(fake)
fake.docs[("diaries", "IHBJEoK4wk_2024-03-21")] = copy.deepcopy(OLD)
fake.docs[("diaries", "CkdKQeKCAOXPECUsk7gN")] = {**OLD, "date": "2024-03-22", "passage": "골로세서 3:14-4:1", "truthSummary": ""}
fake.docs[("diaries", "someoneElse0001")] = {**OLD, "uid": "joon"}
# 맞추기 전에도 읽을 수 있다 (안전망). 문서는 바뀌지 않는다
seen = store.list("mina")
assert [r["id"] for r in seen] == ["IHBJEoK4wk_2024-03-21", "CkdKQeKCAOXPECUsk7gN"] and set(seen[0]) == set(FIELDS) | {"id"}
assert seen[0]["book"] == "데살로니가후서" and seen[0]["applied_truth"] == OLD["truthSummary"] and seen[0]["prayer"] == OLD["prayer"]
assert seen[1]["book"] == "" and seen[1]["chapter_start"] == 0 and seen[1]["passage"] == "골로세서 3:14-4:1"   # 읽지 못한 묵상도 빼지 않는다
assert fake.docs[("diaries", "IHBJEoK4wk_2024-03-21")] == OLD
assert store.remove("mina", "someoneElse0001") is False

# 살펴보기와 미리 보기는 아무것도 바꾸지 않는다
before = copy.deepcopy(fake.docs)
report = tool.inspect(fake)
assert "diaries의 문서: 3개" in report and "'골로세서 3:14-4:1' (1개)" in report and "truth의 한 줄과 같음: 2개" in report
assert OLD["observation"] not in report                                 # 화면에 묵상의 글을 찍지 않는다
preview = tool.upgrade(fake)
assert "채울 문서 2개" in preview and "그대로 두는 문서 1개" in preview and "아직 아무것도 바꾸지 않았습니다" in preview
assert fake.docs == before

# 채우기: 사본이 있어야 하고, 사본이 지금의 DB와 같아야 한다. 채운 뒤 예전 항목은 그대로다
import tempfile  # noqa: E402
folder = tempfile.mkdtemp()
path, count = tool.backup(fake, folder)
assert count == 3 and fake.docs == before
for wrong in (None, folder + "/없는파일.json"):
    try:
        tool.upgrade(fake, apply=True, backup_path=wrong)
        raise AssertionError("사본 없이 바꾸면 안 된다")
    except SystemExit:
        pass
assert fake.docs == before
done = tool.upgrade(fake, apply=True, backup_path=str(path))
assert "2개 문서에 항목을 채웠습니다" in done and "예전 항목은 모두 그대로입니다" in done
fixed = fake.docs[("diaries", "IHBJEoK4wk_2024-03-21")]
assert all(fixed[k] == v for k, v in OLD.items()) and set(fixed) == set(FIELDS) | {"uid", "deleted", "truthSummary"}
assert fixed["applied_truth"] == OLD["truthSummary"] and fixed["chapter_end"] == 1
assert fake.docs[("diaries", "CkdKQeKCAOXPECUsk7gN")] == before[("diaries", "CkdKQeKCAOXPECUsk7gN")]      # 읽지 못한 문서는 그대로
assert "채울 문서 0개" in tool.upgrade(fake)                             # 다시 돌려도 더 바꿀 것이 없다
# 새로 저장한 묵상과 맞춘 예전 묵상은 같은 항목을 가진다 (truthSummary는 마지막 단계에서 없앤다)
store.add("mina", "rec00009", RECORD)
assert set(fake.docs[("diaries", "rec00009")]) == set(fixed) - {"truthSummary"}

# ---- API: 누구의 기록인지는 로그인 정보로만 정한다 ----
access.reset()
app = FastAPI()
app.include_router(diary.router)
client = TestClient(app)
mina, joon = {"Authorization": "Bearer dev:mina"}, {"Authorization": "Bearer dev:joon"}

assert client.get("/api/config").json() == {"login": "dev", "firebase": None, "why": None}
for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer something-else"}, {"Authorization": "dev:mina"}):
    assert client.get("/api/diary/records", headers=headers).status_code == 403          # 로그인하지 않으면 아무것도 못 한다
    assert client.post("/api/diary/records", headers=headers, json={"id": "rec00001", "record": RECORD}).status_code == 403

saved = client.post("/api/diary/records", headers=mina, json={"id": "rec00001", "record": RECORD})
assert saved.status_code == 200 and saved.json()["record"] == {"id": "rec00001", **RECORD}
assert client.post("/api/diary/records", headers=mina, json={"id": "rec00001", "record": RECORD}).status_code == 200   # 다시 보내도 된다
assert len(client.get("/api/diary/records", headers=mina).json()["records"]) == 1
assert client.get("/api/diary/records", headers=joon).json()["records"] == []                 # 남의 기록은 보이지 않는다
assert client.delete("/api/diary/records/rec00001", headers=joon).status_code == 404         # 지울 수도 없다
assert client.post("/api/diary/records", headers=joon, json={"id": "rec00001", "record": RECORD}).status_code == 409   # 같은 번호로 끼어들 수도 없다
assert client.post("/api/diary/records", headers=mina, json={"id": "rec00001", "record": changed(truth="바뀜")}).status_code == 409
# 본문에 남의 번호를 적어 보내도 소용없다 (약속에 없는 항목이라 받지 않는다)
assert client.post("/api/diary/records", headers=joon, json={"id": "rec00009", "record": changed(uid="mina")}).status_code == 400
for bad_id in ["짧", "REC00001", "rec 0001", "../state"]:
    assert client.post("/api/diary/records", headers=mina, json={"id": bad_id, "record": RECORD}).status_code == 400
assert client.post("/api/diary/records", headers=mina, json={"id": "rec00002", "record": without("prayer")}).status_code == 400
assert len(client.get("/api/diary/records", headers=mina).json()["records"]) == 1            # 거절한 것은 하나도 들어가지 않았다

assert client.delete("/api/diary/records/rec00001", headers=mina).json() == {"removed": "rec00001"}
assert client.get("/api/diary/records", headers=mina).json()["records"] == []

# 상태: 약속한 항목만 담는다
assert client.get("/api/diary/state", headers=mina).json() == {"state": None}
state = {"progress": {"book": "골로새서", "chapter": 4, "verse": 1}, "draft": None, "planned": None, "guided": True,
         "updated_at": 1760000000000, "다른 것": "버려진다"}
assert client.put("/api/diary/state", headers=mina, json={"state": state}).status_code == 200
got = client.get("/api/diary/state", headers=mina).json()["state"]
assert got["progress"]["verse"] == 1 and got["guided"] is True and "다른 것" not in got
assert client.put("/api/diary/state", headers=mina, json={"state": {"progress": None}}).status_code == 400
assert client.get("/api/diary/state", headers=joon).json() == {"state": None}

# 일기장이 꺼져 있으면: 설정은 비어 있고, 저장 요청은 503이다 (앱은 기기에만 보관한다)
os.environ.pop("DIARY_DEV_LOGIN")
access.reset()
assert client.get("/api/config").json() == {"login": None, "firebase": None, "why": "열쇠가 없음"}
assert client.get("/api/diary/records", headers=mina).status_code == 503

# ---- 웹 설정: 콘솔에서 복사한 모양 그대로 넣어도 읽는다 ----
from diary.access import read_web_config  # noqa: E402
WEB = {"apiKey": "AIza-x", "authDomain": "diary-with-jesus.firebaseapp.com", "projectId": "diary-with-jesus", "appId": "1:23:web:ab"}
assert read_web_config(json.dumps(WEB)) == WEB
assert read_web_config('const firebaseConfig = {\n  apiKey: "AIza-x",\n  authDomain: "diary-with-jesus.firebaseapp.com",\n  projectId: "diary-with-jesus",\n  appId: "1:23:web:ab",\n};') == WEB
COPIED = '''// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
const firebaseConfig = {
  apiKey: "AIza-x",
  authDomain: "diary-with-jesus.firebaseapp.com",
  projectId: "diary-with-jesus",
  appId: "1:23:web:ab"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);'''
assert read_web_config(COPIED) == WEB                     # 복사 단추로 통째로 복사한 글
assert read_web_config("") is None and read_web_config("{apiKey: }") is None and read_web_config('{"apiKey": "x"}') is None

# 열쇠가 깨져 있어도 앱은 서고, 까닭만 알려 준다 (열쇠의 내용은 내보내지 않는다)
os.environ["FIREBASE_SERVICE_ACCOUNT"] = '{"type": "service_account", "private_key": "SECRET-TEXT"'
access.reset()
answer = client.get("/api/config").json()
assert answer["login"] is None and answer["why"].startswith("열쇠를 읽지 못함") and "SECRET" not in json.dumps(answer, ensure_ascii=False)
assert "private_key 있음" in answer["why"] and "첫 글자 {" in answer["why"]
del os.environ["FIREBASE_SERVICE_ACCOUNT"]
access.reset()
# 붙여 넣는 동안 모양이 달라진 열쇠도 읽는다
import base64  # noqa: E402
KEY = {"type": "service_account", "project_id": "p", "private_key": "-----BEGIN PRIVATE KEY-----\nAAA\nBBB\n-----END PRIVATE KEY-----\n"}
pretty = json.dumps(KEY, indent=2)
assert access.read_key(pretty) == KEY and access.read_key("'" + pretty + "'") == KEY
assert access.read_key(pretty.replace("\\n", "\n")) == KEY                    # private_key 안이 진짜 줄바꿈이 된 것
assert access.read_key(base64.b64encode(pretty.encode()).decode()) == KEY
for wrong in ("APP_PASSCODE", json.dumps(WEB), "{", ""):
    try:
        access.read_key(wrong)
        raise AssertionError("읽으면 안 된다")
    except AssertionError:
        raise
    except Exception:
        pass

print("모든 검사 통과")
