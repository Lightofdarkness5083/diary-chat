"""대화 기록의 일: 만들고, 이어 붙이고, 목록을 주고, 하나를 읽고, 지운다.

대화 하나는 돌아보기에서 [새 대화]를 누르기 전까지 물은 쪽들의 묶음이다.
이름은 첫 물음으로 붙는다. 저장소(diary.store)는 일기장과 같은 곳을 쓴다.
"""
import datetime
import uuid

from diary.store import Conflict, TooLong

TITLE_LENGTH = 40


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def title_from(messages):
    first = next((m["content"] for m in messages if m["role"] == "user"), "").strip().replace("\n", " ")
    return (first[:TITLE_LENGTH] + "…") if len(first) > TITLE_LENGTH else (first or "새 대화")


def stamp(messages, at):
    return [{"role": m["role"], "content": m["content"], "at": m.get("at") or at} for m in messages]


def create(store, uid, messages, title=""):
    at = now()
    for _ in range(3):                     # 번호가 겹치는 일은 거의 없지만, 겹치면 새 번호로
        try:
            return store.create_conversation(uid, uuid.uuid4().hex, title.strip() or title_from(messages), stamp(messages, at), at)
        except Conflict:
            continue
    raise Conflict("대화 번호")


def save_turn(store, uid, conversation_id, question, answer):
    """비서의 답을 받은 뒤 물음과 답 한 쌍을 대화에 붙인다 (자동 저장).
    대화가 없거나 남의 것이거나 가득 찼으면 새 대화를 시작한다. 붙인 대화를 돌려준다."""
    turn = [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    if conversation_id:
        try:
            saved = store.append_conversation(uid, conversation_id, stamp(turn, now()), now())
            if saved is not None:
                return saved
        except TooLong:
            pass
    return create(store, uid, turn)
