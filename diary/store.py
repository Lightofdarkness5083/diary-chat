"""묵상 기록을 두는 곳.

    diaries/{기록 번호}       묵상 하나. 누구의 것인지는 문서 안의 uid로 가른다
    diary_state/{uid}        그 사람의 현재 상태 (묵상 중인 책의 자리, 하다가 멈춘 묵상)
    conversations/{대화 번호}  돌아보기 비서와 나눈 대화 하나. 누구의 것인지는 문서 안의 uid로 가른다

한 문서의 항목은 19개다: 묵상의 17개 항목(schema.FIELDS) + uid + deleted.

지키는 것:
- 한 사람의 요청은 그 사람의 문서만 만진다. 남의 문서는 없는 것으로 보인다.
- 묵상은 새로 만들기만 한다. 같은 번호로 같은 내용이 다시 오면 그대로 두고(겹쳐 쌓지 않는다),
  같은 번호로 다른 내용이 오면 거절한다(덮어쓰지 않는다).
- 지우기는 deleted를 True로 바꾸기만 한다. 문서는 남아 있어 되살릴 수 있다.

MemoryStore는 검사와 내 컴퓨터용이고, FirestoreStore가 실제 일기장이다. 둘은 같은 일을 한다.
"""
from .legacy import as_current
from .schema import FIELDS

RECORDS, STATES, CONVERSATIONS = "diaries", "diary_state", "conversations"
MAX_MESSAGES = 200        # 대화 하나에 담는 말의 수 (물음과 답 한 쌍이 한 쪽이니 100쪽)


class Conflict(Exception):
    """같은 번호로 다른 내용의 기록이 이미 있다."""


def _same(stored, record):
    return all(stored.get(field) == record[field] for field in FIELDS)


def _public(record_id, stored):
    """화면에 내어 주는 모양: 17개 항목과 기록 번호."""
    current = as_current(stored)
    return {"id": record_id, **{field: current[field] for field in FIELDS}}


def _order(record):
    return (record["date"], record["meditation_time"], record["id"])


# ---- 대화: 묵상과 달리 이어 붙이고, 지울 때는 정말 지운다 (묵상 기록이 아니라 물어본 쪽이다) ----
class TooLong(Exception):
    """대화 하나에 담을 수 있는 말을 넘었다. 새 대화로 이어 간다."""


def _conversation_summary(conversation_id, stored):
    """목록에 내어 주는 모양: 말(messages)은 담지 않는다."""
    return {"id": conversation_id, "title": stored["title"], "created_at": stored["created_at"],
            "updated_at": stored["updated_at"], "pages": sum(1 for m in stored["messages"] if m["role"] == "user")}


def _conversation_full(conversation_id, stored):
    return {**_conversation_summary(conversation_id, stored), "messages": stored["messages"]}


def _new_conversation(uid, title, messages, now):
    return {"uid": uid, "title": title, "messages": list(messages), "created_at": now, "updated_at": now}


def _sorted_conversations(found):
    return sorted(found, key=lambda c: (c["updated_at"], c["id"]), reverse=True)    # 최근 대화가 위


class MemoryStore:
    def __init__(self):
        self.records = {}     # 기록 번호 -> 문서
        self.states = {}      # uid -> 상태
        self.conversations = {}   # 대화 번호 -> 문서

    def _mine(self, uid, record_id):
        stored = self.records.get(record_id)
        return stored if stored is not None and stored.get("uid") == uid else None

    def add(self, uid, record_id, record):
        if record_id in self.records:
            stored = self._mine(uid, record_id)
            if stored is None or not _same(stored, record):      # 남의 번호이거나, 내용이 다르다
                raise Conflict(record_id)
            stored["deleted"] = False                            # 지웠던 기록이 다시 왔다: 되살린다
        else:
            self.records[record_id] = {**record, "uid": uid, "deleted": False}
        return self.get(uid, record_id)

    def get(self, uid, record_id):
        stored = self._mine(uid, record_id)
        return None if stored is None or stored.get("deleted") else _public(record_id, stored)

    def list(self, uid):
        found = [_public(rid, doc) for rid, doc in self.records.items() if doc.get("uid") == uid and not doc.get("deleted")]
        return sorted(found, key=_order)

    def remove(self, uid, record_id):
        stored = self._mine(uid, record_id)
        if stored is None or stored.get("deleted"):
            return False
        stored["deleted"] = True
        return True

    def get_state(self, uid):
        return self.states.get(uid)

    def set_state(self, uid, state):
        self.states[uid] = dict(state)
        return self.states[uid]

    # ---- 대화 ----
    def _my_conversation(self, uid, conversation_id):
        stored = self.conversations.get(conversation_id)
        return stored if stored is not None and stored.get("uid") == uid else None

    def create_conversation(self, uid, conversation_id, title, messages, now):
        if conversation_id in self.conversations:
            raise Conflict(conversation_id)
        if len(messages) > MAX_MESSAGES:
            raise TooLong(conversation_id)
        self.conversations[conversation_id] = _new_conversation(uid, title, messages, now)
        return self.get_conversation(uid, conversation_id)

    def append_conversation(self, uid, conversation_id, messages, now):
        stored = self._my_conversation(uid, conversation_id)
        if stored is None:
            return None
        if len(stored["messages"]) + len(messages) > MAX_MESSAGES:
            raise TooLong(conversation_id)
        stored["messages"] = stored["messages"] + list(messages)
        stored["updated_at"] = now
        return self.get_conversation(uid, conversation_id)

    def get_conversation(self, uid, conversation_id):
        stored = self._my_conversation(uid, conversation_id)
        return None if stored is None else _conversation_full(conversation_id, stored)

    def list_conversations(self, uid):
        return _sorted_conversations([_conversation_summary(cid, doc) for cid, doc in self.conversations.items()
                                      if doc.get("uid") == uid])

    def remove_conversation(self, uid, conversation_id):
        if self._my_conversation(uid, conversation_id) is None:
            return False
        del self.conversations[conversation_id]
        return True


class FirestoreStore:
    """Firestore에 둔다. client는 google.cloud.firestore.Client (firebase_admin.firestore.client())."""

    def __init__(self, client):
        self.db = client

    def _doc(self, record_id):
        return self.db.collection(RECORDS).document(record_id)

    def _mine(self, uid, record_id):
        snapshot = self._doc(record_id).get()
        if not snapshot.exists:
            return None
        stored = snapshot.to_dict()
        return stored if stored.get("uid") == uid else None

    def add(self, uid, record_id, record):
        ref = self._doc(record_id)
        if ref.get().exists:
            stored = self._mine(uid, record_id)
            if stored is None or not _same(stored, record):
                raise Conflict(record_id)
            if stored.get("deleted"):
                ref.update({"deleted": False})
        else:
            # create는 문서가 이미 있으면 실패한다. 그사이 다른 요청이 먼저 만들었어도 덮어쓰지 않는다
            ref.create({**record, "uid": uid, "deleted": False})
        return self.get(uid, record_id)        # 저장한 것을 다시 읽어 돌려준다

    def get(self, uid, record_id):
        stored = self._mine(uid, record_id)
        return None if stored is None or stored.get("deleted") else _public(record_id, stored)

    def list(self, uid):
        found = []
        for snapshot in self.db.collection(RECORDS).where("uid", "==", uid).stream():
            stored = snapshot.to_dict()
            if stored.get("uid") == uid and not stored.get("deleted"):
                found.append(_public(snapshot.id, stored))
        return sorted(found, key=_order)

    def remove(self, uid, record_id):
        stored = self._mine(uid, record_id)
        if stored is None or stored.get("deleted"):
            return False
        self._doc(record_id).update({"deleted": True})
        return True

    def get_state(self, uid):
        snapshot = self.db.collection(STATES).document(uid).get()
        return snapshot.to_dict() if snapshot.exists else None

    def set_state(self, uid, state):
        self.db.collection(STATES).document(uid).set(dict(state))
        return dict(state)

    # ---- 대화 ----
    def _conversation(self, conversation_id):
        return self.db.collection(CONVERSATIONS).document(conversation_id)

    def _my_conversation(self, uid, conversation_id):
        snapshot = self._conversation(conversation_id).get()
        if not snapshot.exists:
            return None
        stored = snapshot.to_dict()
        return stored if stored.get("uid") == uid else None

    def create_conversation(self, uid, conversation_id, title, messages, now):
        if len(messages) > MAX_MESSAGES:
            raise TooLong(conversation_id)
        try:
            self._conversation(conversation_id).create(_new_conversation(uid, title, messages, now))
        except Exception:                      # 같은 번호가 이미 있으면 만들지 않는다
            raise Conflict(conversation_id)
        return self.get_conversation(uid, conversation_id)

    def append_conversation(self, uid, conversation_id, messages, now):
        stored = self._my_conversation(uid, conversation_id)
        if stored is None:
            return None
        if len(stored["messages"]) + len(messages) > MAX_MESSAGES:
            raise TooLong(conversation_id)
        self._conversation(conversation_id).update({"messages": stored["messages"] + list(messages), "updated_at": now})
        return self.get_conversation(uid, conversation_id)

    def get_conversation(self, uid, conversation_id):
        stored = self._my_conversation(uid, conversation_id)
        return None if stored is None else _conversation_full(conversation_id, stored)

    def list_conversations(self, uid):
        found = []
        for snapshot in self.db.collection(CONVERSATIONS).where("uid", "==", uid).stream():
            stored = snapshot.to_dict()
            if stored.get("uid") == uid:
                found.append(_conversation_summary(snapshot.id, stored))
        return _sorted_conversations(found)

    def remove_conversation(self, uid, conversation_id):
        if self._my_conversation(uid, conversation_id) is None:
            return False
        self._conversation(conversation_id).delete()
        return True
