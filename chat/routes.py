"""묵상 돌아보기 비서 (책 단위, 기간 단위로 지난 묵상을 돌아본다).

  POST /api/chat   물음과 최근 대화를 받아 비서의 답을 돌려준다. 물음과 답은 대화 기록에 자동으로 남긴다

기록은 서버가 일기장에서 직접 읽는다. 누구의 기록인지는 로그인 정보로만 정한다.
화면이 보낸 기록은 일기장이 꺼져 있을 때(내 컴퓨터에서 시험할 때)만 쓴다.
비서는 기록을 통째로 받지 않는다. 두 도구로 필요한 것만 꺼내 읽는다.
비서는 묵상 기록을 읽기만 한다. 물음과 답 한 쌍은 대화 기록(conversations)에 붙인다.
"""
import datetime
import re
import unicodedata
from typing import Any, Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import conversations.service as conversation_service
from diary import access
from meditation import ai_client
from once import Once
from settings import read_prompt

router = APIRouter(prefix="/api/chat", tags=["chat"])

TEXT_FIELDS = ["book", "passage", "title", "applied_truth", "application"]
NUMBER_FIELDS = ["chapter_start", "verse_start", "chapter_end", "verse_end"]
MAX_RECORDS, MAX_FIELD, MAX_TURNS = 3000, 6000, 20      # MAX_TURNS: 최근 10쪽 (물음과 답 한 쌍이 한 쪽)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

TOOLS = [
    {"name": "books_in_period",
     "description": "어떤 책을 몇 번 묵상했는지 센다. 기간을 주면 그 기간만, 주지 않으면 처음 묵상부터 지금까지 전부. "
                    "책마다 묵상 횟수와 처음·마지막 날짜를 돌려준다. "
                    "'2025년에는 어떤 책을 묵상했지?', '여호수아서는 몇 번 묵상했어?' 같은 물음에 쓴다.",
     "input_schema": {"type": "object", "properties": {
         "start": {"type": "string", "description": "시작 날짜 YYYY-MM-DD. 없으면 처음부터"},
         "end": {"type": "string", "description": "끝 날짜 YYYY-MM-DD. 없으면 지금까지"}}}},
    {"name": "book_records",
     "description": "한 책의 묵상을 성경 순서(장·절 순)로 모은다. 묵상마다 날짜, 본문, 붙잡은 진리(applied_truth), 적용을 돌려준다. "
                    "기간을 주면 그 기간의 묵상만. '그 책에서 주로 붙잡은 진리는?', '적용을 요약해 줘', '중심 주제는?' 같은 물음에 쓴다.",
     "input_schema": {"type": "object", "properties": {
         "book": {"type": "string", "description": "책 이름. 기록의 윤곽에 적힌 이름 그대로. 예: 여호수아"},
         "start": {"type": "string", "description": "시작 날짜 YYYY-MM-DD. 없으면 처음부터"},
         "end": {"type": "string", "description": "끝 날짜 YYYY-MM-DD. 없으면 지금까지"}},
         "required": ["book"]}},
]


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]      # [{"role": "user"|"assistant", "content": "…"}], 묵상자의 물음으로 끝난다
    records: list[dict[str, Any]] = []  # 일기장이 꺼져 있을 때만 쓴다 (시험용)
    today: str = ""                     # 묵상자의 오늘 날짜 YYYY-MM-DD
    conversation_id: str = ""           # 이어 갈 대화의 번호. 없으면 새 대화를 시작한다
    request_id: str = ""                # 같은 물음을 다시 보내도(연결이 끊겨) 한 번만 답하고 한 번만 남긴다


def nfc(text):
    """한글을 한 모양(NFC)으로 맞춘다. Mac 파일 이름에서 온 글자(NFD)와 손으로 친 글자를 같게 본다."""
    return unicodedata.normalize("NFC", str(text or ""))


def book_key(name):
    """책 이름을 비교할 때의 열쇠. '여호수아'와 '여호수아서', 띄어쓰기 차이를 같게 본다."""
    key = re.sub(r"\s+", "", nfc(name))
    return key[:-1] if len(key) > 1 and key.endswith("서") else key


def load_records(raw):
    """기록에서 비서가 쓰는 항목만 골라, 한글을 NFC로 맞춰 담는다. 날짜순."""
    records = []
    for item in raw[:MAX_RECORDS]:
        date = str(item.get("date", ""))
        if not DATE.fullmatch(date) or item.get("deleted") is True:
            continue
        record = {"date": date}
        for field in TEXT_FIELDS:
            record[field] = nfc(item.get(field))[:MAX_FIELD].strip()
        for field in NUMBER_FIELDS:
            value = item.get(field)
            record[field] = value if isinstance(value, int) and not isinstance(value, bool) else 0
        records.append(record)
    return sorted(records, key=lambda r: r["date"])


def _period(records, start, end):
    """기간 안의 기록. 날짜 모양이 틀리면 None."""
    start, end = (start or "").strip(), (end or "").strip()
    if (start and not DATE.fullmatch(start)) or (end and not DATE.fullmatch(end)):
        return None
    return [r for r in records if (not start or r["date"] >= start) and (not end or r["date"] <= end)]


def _span(start, end):
    if start and end:
        return f"{start}부터 {end}까지"
    if start:
        return f"{start}부터 지금까지"
    if end:
        return f"처음부터 {end}까지"
    return "전체 기간"


def make_tools(records):
    """기록을 읽는 두 도구. 비서는 이 도구로만 기록을 본다."""
    def books_in_period(start=None, end=None):
        chosen = _period(records, start, end)
        if chosen is None:
            return "날짜는 YYYY-MM-DD 모양으로 주세요."
        if not chosen:
            return f"{_span(start, end)}에 저장된 묵상이 없습니다."
        books = {}
        for r in chosen:
            books.setdefault(r["book"], []).append(r["date"])
        rows = sorted(books.items(), key=lambda item: (-len(item[1]), item[1][0]))
        lines = [f"{_span(start, end)}: 묵상 {len(chosen)}편, 책 {len(books)}권 (많이 묵상한 순)"]
        lines += [f"- {name}: {len(dates)}편 ({dates[0]} ~ {dates[-1]})" for name, dates in rows]
        return "\n".join(lines)

    def book_records(book, start=None, end=None):
        chosen = _period(records, start, end)
        if chosen is None:
            return "날짜는 YYYY-MM-DD 모양으로 주세요."
        key = book_key(book)
        mine = sorted((r for r in chosen if book_key(r["book"]) == key),
                      key=lambda r: (r["chapter_start"], r["verse_start"], r["date"]))
        if not mine:
            names = sorted({r["book"] for r in chosen})
            return f"{_span(start, end)}에 {nfc(book).strip()} 묵상이 없습니다. 이 기간에 묵상한 책: {', '.join(names) or '없음'}"
        dates = sorted(r["date"] for r in mine)
        lines = [f"{mine[0]['book']} 묵상 {len(mine)}편 ({dates[0]} ~ {dates[-1]}), 성경 순서"]
        for r in mine:
            lines.append(f"■ {r['date']} | {r['passage']}\n  [붙잡은 진리] {r['applied_truth'] or '(없음)'}\n  [적용] {r['application'] or '(없음)'}")
        return "\n".join(lines)

    tools = {"books_in_period": books_in_period, "book_records": book_records}

    def run(name, arguments):
        if name not in tools:
            return f"없는 도구입니다: {name}"
        try:
            return tools[name](**arguments)
        except TypeError:
            return "도구에 준 값이 맞지 않습니다."
    return run


def overview(records, today):
    """비서가 처음부터 알고 있는 것: 기록 전체가 아니라 어떤 책이 있는지의 윤곽."""
    if not records:
        return f"오늘: {today}\n저장된 묵상이 아직 없습니다."
    books = {}
    for record in records:
        books[record["book"]] = books.get(record["book"], 0) + 1
    lines = [f"오늘: {today}", f"저장된 묵상: {len(records)}편 ({records[0]['date']}부터 {records[-1]['date']}까지)",
             "묵상한 책 (도구에는 이 이름 그대로 씁니다): " + ", ".join(books)]
    return "\n".join(lines)


def _records_for(authorization, sent):
    """(기록, uid, 오류 응답). 일기장이 켜져 있으면 로그인한 사람의 기록을 일기장에서 읽는다."""
    store = access.store()
    if store is None:                                  # 일기장이 꺼져 있다: 화면이 보낸 기록으로 (시험용)
        return load_records(sent), None, None
    try:
        uid, _ = access.who(authorization)
    except access.NotSignedIn:
        return None, None, JSONResponse({"error": "로그인이 필요합니다."}, status_code=403)
    return load_records(store.list(uid)), uid, None


ONCE = Once()          # 같은 물음을 다시 보내도 AI를 한 번만 부르고 대화에 한 번만 남긴다


@router.post("")
def chat(request: ChatRequest, authorization: Optional[str] = Header(default=None)):
    try:
        who = access.who(authorization)[0] if access.store() is not None else "anon"
    except access.NotSignedIn:
        who = "anon"
    key = f"chat:{who}:{request.request_id[:64]}" if request.request_id else ""
    return ONCE.run(key, lambda: _answer(request, authorization))


def _answer(request, authorization):
    messages = []
    for item in request.messages[-MAX_TURNS:]:
        role, content = item.get("role"), str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:4000]})
    while messages and messages[0]["role"] != "user":       # 대화는 묵상자의 말로 시작해야 한다
        messages.pop(0)
    if not messages or messages[-1]["role"] != "user":
        return JSONResponse({"error": "물음이 비어 있습니다."}, status_code=400)

    records, uid, problem = _records_for(authorization, request.records)
    if problem:
        return problem
    today = request.today if DATE.fullmatch(request.today) else datetime.date.today().isoformat()
    system = read_prompt("chat_system.md") + "\n\n<기록의 윤곽>\n" + overview(records, today) + "\n</기록의 윤곽>"
    try:
        answer = ai_client.reply_with_tools(system, messages, TOOLS, make_tools(records))
    except ai_client.AIError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    if uid is None:                                    # 일기장이 꺼져 있으면 남기지 않는다
        return {"reply": answer, "conversation_id": None, "saved": False}
    try:                                               # 남기지 못해도 답은 돌려준다
        saved = conversation_service.save_turn(access.store(), uid, request.conversation_id, messages[-1]["content"], answer)
        return {"reply": answer, "conversation_id": saved["id"], "saved": True}
    except Exception:
        return {"reply": answer, "conversation_id": request.conversation_id or None, "saved": False}
