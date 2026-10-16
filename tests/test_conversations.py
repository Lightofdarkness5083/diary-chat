"""대화 기록 검사.  실행: .venv/bin/python -m tests.test_conversations
실제 Firestore와 AI에 연결하지 않는다. 가짜 저장소와 흉내 낸 비서로 원칙을 하나씩 확인한다."""
import copy
import os

os.environ.pop("FIREBASE_SERVICE_ACCOUNT", None)
os.environ["DIARY_DEV_LOGIN"] = "1"
os.environ.pop("APP_PASSCODE", None)

from fastapi.testclient import TestClient  # noqa: E402

import conversations.service as service  # noqa: E402
from diary import access  # noqa: E402
from diary.store import MAX_MESSAGES, Conflict, FirestoreStore, MemoryStore, TooLong  # noqa: E402
from meditation import ai_client  # noqa: E402
import settings  # noqa: E402


# ---- 가짜 Firestore (지우기까지) ----
class Snap:
    def __init__(self, doc_id, data):
        self.id, self.exists, self._data = doc_id, data is not None, data

    def to_dict(self):
        return copy.deepcopy(self._data)


class Doc:
    def __init__(self, docs, path):
        self.docs, self.path = docs, path

    def get(self):
        return Snap(self.path[1], self.docs.get(self.path))

    def create(self, data):
        if self.path in self.docs:
            raise RuntimeError("이미 있는 문서")
        self.docs[self.path] = copy.deepcopy(data)

    def update(self, data):
        self.docs[self.path].update(copy.deepcopy(data))

    def delete(self):
        self.docs.pop(self.path, None)


class Col:
    def __init__(self, docs, name, only=None):
        self.docs, self.name, self.only = docs, name, only

    def document(self, doc_id):
        return Doc(self.docs, (self.name, doc_id))

    def where(self, field, op, value):
        return Col(self.docs, self.name, (field, value))

    def stream(self):
        return [Snap(p[1], d) for p, d in list(self.docs.items())
                if p[0] == self.name and (self.only is None or d.get(self.only[0]) == self.only[1])]


class FakeFirestore:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return Col(self.docs, name)


TURN = [{"role": "user", "content": "골로새서 요약해 줘", "at": "t"}, {"role": "assistant", "content": "요약입니다.", "at": "t"}]

# ---- 저장소: 두 가지(가짜 메모리, Firestore 코드)가 똑같이 동작한다 ----
for make in (MemoryStore, lambda: FirestoreStore(FakeFirestore())):
    s = make()
    made = s.create_conversation("나", "c1", "골로새서 요약해 줘", TURN, "2026-10-16T01:00:00+00:00")
    assert made["id"] == "c1" and made["pages"] == 1 and made["messages"] == TURN
    try:
        s.create_conversation("나", "c1", "다시", TURN, "x"); raise AssertionError("같은 번호로 또 만들면 안 된다")
    except Conflict:
        pass
    s.create_conversation("나", "c2", "두 번째", TURN, "2026-10-16T02:00:00+00:00")
    s.create_conversation("남", "c3", "남의 대화", TURN, "2026-10-16T03:00:00+00:00")
    listed = s.list_conversations("나")
    assert [c["id"] for c in listed] == ["c2", "c1"]                    # 최근 대화가 위, 남의 대화는 없다
    assert all("messages" not in c for c in listed)                     # 목록에는 말을 담지 않는다
    assert s.get_conversation("나", "c3") is None                       # 남의 대화는 없는 것으로 보인다
    assert s.append_conversation("나", "c3", TURN, "x") is None
    assert s.remove_conversation("나", "c3") is False and s.get_conversation("남", "c3")
    longer = s.append_conversation("나", "c1", TURN, "2026-10-16T04:00:00+00:00")
    assert longer["pages"] == 2 and len(longer["messages"]) == 4 and longer["updated_at"].endswith("04:00:00+00:00")
    assert [c["id"] for c in s.list_conversations("나")] == ["c1", "c2"]   # 이어 붙인 대화가 위로
    try:
        s.append_conversation("나", "c1", TURN * MAX_MESSAGES, "x"); raise AssertionError("가득 찬 대화")
    except TooLong:
        pass
    assert s.remove_conversation("나", "c2") is True and s.get_conversation("나", "c2") is None
    assert s.remove_conversation("나", "c2") is False

# ---- 서비스: 이름 붙이기, 자동 저장 ----
assert service.title_from([{"role": "user", "content": "  올해\n어떤 책?  "}]) == "올해 어떤 책?"
assert service.title_from([{"role": "user", "content": "가" * 50}]) == "가" * 40 + "…"
s = MemoryStore()
first = service.save_turn(s, "나", "", "물음 1", "답 1")                  # 번호가 없으면 새 대화
again = service.save_turn(s, "나", first["id"], "물음 2", "답 2")          # 번호가 있으면 이어 붙인다
assert again["id"] == first["id"] and again["pages"] == 2 and again["title"] == "물음 1"
other = service.save_turn(s, "남", first["id"], "남의 물음", "답")          # 남의 번호로는 이어 붙이지 못한다: 새 대화
assert other["id"] != first["id"] and s.get_conversation("나", first["id"])["pages"] == 2
s.conversations[first["id"]]["messages"] = [{"role": "user", "content": "x", "at": "t"}] * MAX_MESSAGES
full = service.save_turn(s, "나", first["id"], "가득 찬 뒤", "답")          # 가득 차면 새 대화로 이어 간다
assert full["id"] != first["id"] and full["title"] == "가득 찬 뒤"

# ---- API ----
access.reset()
settings.read_prompt = lambda name: "시험용 지시문"
import chat.routes  # noqa: E402
chat.routes.read_prompt = lambda name: "시험용 지시문"
import dev_main  # noqa: E402

client = TestClient(dev_main.app)
ME, YOU = {"Authorization": "Bearer dev:me"}, {"Authorization": "Bearer dev:you"}

assert client.get("/api/conversations").status_code == 403                    # 로그인 없이는 못 본다
assert client.post("/api/conversations", json={"messages": []}, headers=ME).status_code == 422          # 빈 대화
assert client.post("/api/conversations", json={"messages": [{"role": "system", "content": "x"}]}, headers=ME).status_code == 422
assert client.post("/api/conversations", json={"messages": [{"role": "user", "content": ""}]}, headers=ME).status_code == 422
saved = client.post("/api/conversations", json={"messages": TURN}, headers=ME)
assert saved.status_code == 201 and saved.json()["title"] == "골로새서 요약해 줘", saved.text
cid = saved.json()["id"]
assert [c["id"] for c in client.get("/api/conversations", headers=ME).json()["conversations"]] == [cid]
assert client.get("/api/conversations", headers=YOU).json()["conversations"] == []
assert client.get(f"/api/conversations/{cid}", headers=ME).json()["messages"][0]["content"] == "골로새서 요약해 줘"
assert client.get(f"/api/conversations/{cid}", headers=YOU).status_code == 404
assert client.delete(f"/api/conversations/{cid}", headers=YOU).status_code == 404
assert client.delete(f"/api/conversations/{cid}", headers=ME).json() == {"deleted": cid}
assert client.get(f"/api/conversations/{cid}", headers=ME).status_code == 404

# 비서가 답하면 자동으로 남는다
asked = []
ai_client.reply_with_tools = lambda system, messages, tools, run, **kw: (asked.append(messages[-1]["content"]), "답: " + messages[-1]["content"])[1]
one = client.post("/api/chat", json={"messages": [{"role": "user", "content": "올해 어떤 책?"}], "today": "2026-10-16"}, headers=ME).json()
assert one["reply"] == "답: 올해 어떤 책?" and one["saved"] and one["conversation_id"]
two = client.post("/api/chat", json={"messages": [{"role": "user", "content": "올해 어떤 책?"}, {"role": "assistant", "content": one["reply"]},
                                                  {"role": "user", "content": "그 책의 진리는?"}],
                                     "conversation_id": one["conversation_id"], "today": "2026-10-16"}, headers=ME).json()
assert two["conversation_id"] == one["conversation_id"]
stored = client.get(f"/api/conversations/{one['conversation_id']}", headers=ME).json()
assert [m["content"] for m in stored["messages"]] == ["올해 어떤 책?", "답: 올해 어떤 책?", "그 책의 진리는?", "답: 그 책의 진리는?"]
assert stored["pages"] == 2 and stored["title"] == "올해 어떤 책?"

# 남기지 못해도 답은 온다
store = access.store()
original = store.append_conversation
store.append_conversation = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("저장소 고장"))
store.create_conversation, keep_create = (lambda *a, **k: (_ for _ in ()).throw(RuntimeError("저장소 고장"))), store.create_conversation
broken = client.post("/api/chat", json={"messages": [{"role": "user", "content": "고장 중에"}], "conversation_id": one["conversation_id"]}, headers=ME).json()
assert broken["reply"] == "답: 고장 중에" and broken["saved"] is False and broken["conversation_id"] == one["conversation_id"]
store.append_conversation, store.create_conversation = original, keep_create

# Swagger 문서에 다섯 길이 모두 보인다
paths = client.get("/openapi.json").json()["paths"]
assert {"get", "post"} <= set(paths["/api/conversations"]) and {"get", "delete"} <= set(paths["/api/conversations/{conversation_id}"])
assert client.get("/docs").status_code == 200

print("모든 검사 통과")
