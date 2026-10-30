"""7단계 묵상 인도 (묵상 부분).

밖에서 보면 세 가지 일만 한다.
  POST /api/meditation/start   본문을 정하고 새 묵상을 연다
  POST /api/meditation/chat    묵상자의 글을 받아 인도자의 다음 말을 돌려준다
  POST /api/meditation/record  끝난 묵상의 "묵상 완료 기록"을 만든다
  POST /api/meditation/resume  멈췄던 묵상을 기기에 보관된 대화로 되살린다
본문을 정하는 것을 돕는 것들도 있다.
  GET  /api/meditation/books       66권과, 단락이 준비된 책
  GET  /api/meditation/paragraphs  한 책의 단락 목록 (장절만, 제목 없음)
  GET  /api/meditation/read        긴 단락의 본문을 읽어 보기만 한다 (120절까지)
  GET  /api/meditation/following   묵상하던 책에서 이어지는 본문을 보여 준다
  GET  /api/meditation/suggest     그 본문에서 한 단락이 끝나는 절을 알려 준다 (단락이 있는 책은 단락대로, 없는 책은 AI가 제안)

7단계 진행은 코드에 없다. AI 지시문(prompts/meditation_system.md) 안에 있다.
묵상이 끝났는지는 인도자에게 시키지 않고, 대화 밖에서 따로 확인한다 (prompts/meditation_finish.md).
인도자의 지시문에는 앱을 위한 요구를 넣지 않는다. 인도가 굳어지기 때문이다.
로그인, 저장, 조회는 이 부분의 일이 아니다. uid를 받지도 만들지도 않는다.
"""
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bible import KO, Bible, BibleSetupError, PassageError
from bible.lookup import _eun
from bible import paragraphs as PARAGRAPHS

from once import Once
from settings import read_prompt

from . import ai_client
from .record import RecordError, build_record
from .signals import OPENING, RESUME_SIGNAL, SIGNALS, START_SIGNAL

ONCE = Once()          # 같은 정리 요청을 다시 보내도 AI를 한 번만 부른다

router = APIRouter(prefix="/api/meditation", tags=["meditation"])

# 진행 중인 대화 기록. 서버 메모리에 둔다 (서버를 끄면 사라진다).
SESSIONS = {}
MAX_SESSIONS = 500
MAX_MESSAGE_LENGTH = 4000
IN_PROGRESS_WAIT = 120   # 같은 글이 다시 왔는데 앞의 답을 만드는 중이면, 이만큼(초) 기다려 그 답을 돌려준다

MAX_RESUME_MESSAGES = 300
# 묵상자의 글이 이만큼 쌓인 뒤부터, 답할 때마다 묵상이 끝났는지 확인한다.
# 7단계를 다 걸으려면 적어도 이만큼은 주고받게 된다.
FINISH_CHECK_AFTER = 6

_bible = None


def get_bible():
    global _bible
    if _bible is None:
        _bible = Bible()
    return _bible


def error(message, status):
    return JSONResponse({"error": message}, status_code=status)


def build_system(passage):
    """시스템 프롬프트 = 7단계와 원칙(prompts/meditation_system.md) + 오늘의 본문."""
    prompt = read_prompt("meditation_system.md")
    lines = [f'{v["chapter"]}:{v["label"]} {v["text"]}' for v in passage["verses"]]
    block = f'\n\n<본문 범위="{passage["passage"]}">\n' + "\n".join(lines) + "\n</본문>"
    if passage["missing"]:
        block += ("\n\n성경 DB에 없는 절: " + ", ".join(passage["missing"])
                  + "\n이 절들은 인용하지 말고, 비어 있다는 것을 묵상자에게 알리세요.")
    return prompt + block


def finished(messages):
    """묵상이 끝났는지 대화의 마지막 부분을 보고 판단한다. 인도자와는 별개의 질문이다.
    확인에 실패하면 끝나지 않은 것으로 본다. 묵상을 방해하지 않기 위해서다."""
    written = sum(1 for m in messages if m["role"] == "user" and m["content"] not in SIGNALS)
    if written < FINISH_CHECK_AFTER:
        return False
    tail = "\n\n".join(
        ("[묵상자]\n" if m["role"] == "user" else "[인도자]\n") + m["content"] for m in messages[-4:])
    prompt = read_prompt("meditation_finish.md")
    try:
        verdict = ai_client.reply(prompt, [{"role": "user", "content": tail}])
    except ai_client.AIError:
        return False
    return verdict.strip().startswith("끝남")


class StartRequest(BaseModel):
    ref: str


class ChatRequest(BaseModel):
    session_id: str
    message: Optional[str] = None
    resume: bool = False        # 멈췄다가 돌아온 직후의 첫 호출
    expect: Optional[int] = None    # 화면이 알고 있는 지금까지의 대화 수. 같은 글이 두 번 오는 것을 가려낸다


class SavedMessage(BaseModel):
    role: str                   # "user" 또는 "assistant"
    content: str = ""
    hidden: Optional[str] = None    # "resume": 예전에 돌아왔던 자리 (화면에 보이지 않던 신호)


class ResumeRequest(BaseModel):
    ref: str
    messages: list[SavedMessage]


class RecordRequest(BaseModel):
    session_id: str
    request_id: str = Field(default="", max_length=64)   # 같은 요청을 다시 보내도 정리를 한 번만 만든다


@router.get("/health")
def health():
    try:
        return {"ok": True, "bible": get_bible().describe()}
    except BibleSetupError as e:
        return error(str(e), 500)


@router.get("/passage")
def passage(ref: str):
    """본문만 조회한다. API 키 없이 확인할 수 있다."""
    try:
        return get_bible().lookup(ref)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)


@router.get("/books")
def books():
    """66권. 단락이 준비된 책은 paragraphs가 True. 책의 마지막 장과 절도 알려 준다 (그 책을 끝까지 마쳤는지 보는 데 쓴다)."""
    try:
        ready = PARAGRAPHS.load(get_bible())
    except BibleSetupError as e:
        return error(str(e), 500)
    bible = get_bible()
    out = []
    for i, name in enumerate(KO):
        last = bible.last_chapter.get(i + 1)
        out.append({"name": name, "testament": "구약" if i < 39 else "신약", "paragraphs": name in ready,
                    "last_chapter": last, "last_verse": bible.last_verse.get((i + 1, last)) if last else None})
    return {"books": out}


@router.get("/paragraphs")
def paragraphs(book: str):
    """한 책의 묵상 단락. 단락이 아직 없는 책이면 404."""
    try:
        bible = get_bible()
        name = KO[bible.book_number(book)]
        items = PARAGRAPHS.of_book(bible, name)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)
    if not items:
        return error(f"{name}{_eun(name)} 아직 단락을 나누지 않았습니다. 위 칸에 본문을 적어 주세요.", 404)
    return {"book": name, "paragraphs": items}


READ_LIMIT = 120   # 긴 단락을 읽어 보기만 할 때 한 번에 펼치는 가장 긴 범위 (묵상할 범위는 30절까지)


@router.get("/read")
def read(ref: str):
    """긴 단락을 읽어 보기만 한다. 묵상자는 읽고 나서 묵상할 부분을 정해 적는다."""
    try:
        return get_bible().lookup(ref, READ_LIMIT)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)


AHEAD = 30   # 이어지는 본문을 몇 절까지 펼쳐 보는가. 한 단락이 이 안에서 끝난다고 본다. 묵상 분량의 제한이 아니다


@router.get("/following")
def following(book: str, chapter: int = 1, verse: int = 0):
    """그 책에서 (chapter, verse) 다음에 이어지는 본문. 묵상자가 보고 오늘의 마지막 절을 고른다."""
    try:
        return get_bible().following(book, chapter, verse, AHEAD)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)


@router.get("/suggest")
def suggest(book: str, chapter: int = 1, verse: int = 0):
    """이어지는 본문에서 한 단락이 마무리되는 끝 절을 제안한다. 제안일 뿐이고 묵상자가 바꿀 수 있다.
    제안하지 못하면 end가 null이다. 그때는 묵상자가 직접 끝 절을 고른다."""
    try:
        found = get_bible().following(book, chapter, verse, AHEAD)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)

    candidates = found["verses"]         # 절 수를 제한하지 않는다. 단락이 끝나는 곳이면 어디든 끝이 될 수 있다
    nothing = {"book": found["book"], "chapter": None, "end": None}
    items = PARAGRAPHS.of_book(get_bible(), found["book"])
    if items and candidates:             # 단락을 나눈 책: 다음 절이 든 단락의 끝까지. AI에게 묻지 않는다
        first = candidates[0]
        item = PARAGRAPHS.containing(items, first["chapter"], first["start"])
        if item:
            return {"book": found["book"], "chapter": item["chapter_end"], "end": item["verse_end"]}
    if len(candidates) < 2:
        return nothing

    lines = "\n".join(f'{u["chapter"]}:{u["label"]} {u["text"]}' for u in found["verses"])
    prompt = read_prompt("meditation_suggest.md")
    try:
        answer = ai_client.reply(prompt, [{"role": "user", "content": lines}])
    except ai_client.AIError:
        return nothing
    match = re.search(r"(\d+)\s*:\s*(\d+)(?:\s*-\s*(\d+))?", answer)
    if not match:
        return nothing
    ch, last = int(match[1]), int(match[3] or match[2])
    for unit in candidates:              # 묶인 단위 안의 절을 답했으면 그 단위의 끝으로 맞춘다
        if unit["chapter"] == ch and unit["start"] <= last <= unit["end"]:
            return {"book": found["book"], "chapter": ch, "end": unit["end"]}
    return nothing


@router.post("/start")
def start(request: StartRequest):
    try:
        found = get_bible().lookup(request.ref)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)

    if len(SESSIONS) >= MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))  # 가장 오래된 대화부터 비운다
    session_id = uuid.uuid4().hex
    # 첫 말은 정해 둔 한 문장이다. 대화 기록에 넣어 두어, 인도자가 그다음부터 이어 가게 한다
    SESSIONS[session_id] = {"passage": found, "system": build_system(found), "completed": False,
                            "messages": [{"role": "user", "content": START_SIGNAL},
                                         {"role": "assistant", "content": OPENING}]}
    return {"session_id": session_id, "opening": OPENING, **found}


@router.post("/resume")
def resume(request: ResumeRequest):
    """멈췄던 묵상을 이어서 연다. 기기에 보관해 둔 대화를 받아 그대로 되살린다.
    서버가 그사이 꺼졌다 켜졌어도 이어서 할 수 있다."""
    try:
        found = get_bible().lookup(request.ref)
    except PassageError as e:
        return error(e.message, e.status)
    except BibleSetupError as e:
        return error(str(e), 500)

    if not request.messages or len(request.messages) > MAX_RESUME_MESSAGES:
        return error("이어서 할 대화가 없습니다. 묵상을 새로 시작해 주세요.", 400)
    messages = [{"role": "user", "content": START_SIGNAL}]
    for saved in request.messages:
        text = RESUME_SIGNAL if saved.hidden == "resume" else saved.content.strip()
        expected = "assistant" if messages[-1]["role"] == "user" else "user"
        if saved.role != expected or not text or len(text) > 20000:
            return error("보관된 대화를 읽지 못했습니다. 묵상을 새로 시작해 주세요.", 400)
        messages.append({"role": saved.role, "content": text})
    if messages[-1]["role"] != "assistant":
        return error("보관된 대화를 읽지 못했습니다. 묵상을 새로 시작해 주세요.", 400)

    if len(SESSIONS) >= MAX_SESSIONS:
        SESSIONS.pop(next(iter(SESSIONS)))
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {"passage": found, "system": build_system(found),
                            "messages": messages, "completed": False}
    return {"session_id": session_id, **found}


@router.post("/chat")
def chat(request: ChatRequest):
    session = SESSIONS.get(request.session_id)
    if session is None:
        return error("이 묵상을 찾을 수 없습니다. 본문을 다시 불러와 주세요.", 404)

    messages = session["messages"]
    text = (request.message or "").strip()
    if (not text and not request.resume and len(messages) == 2 and messages[1]["content"] == OPENING):
        return {"reply": OPENING, "completed": False}   # 첫 말을 청하는 예전 화면에도 같은 첫 말을 준다
    if not messages or (request.expect == 0 and not request.resume and not text):
        text = START_SIGNAL  # 첫 호출: 인도자가 먼저 말을 연다
    elif request.resume:
        text = RESUME_SIGNAL  # 멈췄다가 돌아온 직후: 인도자가 어디까지 했는지 짚고 이어 간다
    elif not text:
        return error("보낼 글이 비어 있습니다.", 400)
    elif len(text) > MAX_MESSAGE_LENGTH:
        return error(f"한 번에 {MAX_MESSAGE_LENGTH}자까지 보낼 수 있습니다.", 400)

    # 연결이 끊겨 화면이 같은 글을 다시 보냈는데, 앞의 글에 대한 답을 아직 만드는 중인 경우: 그 답을 기다린다
    if (request.expect is not None and len(messages) == request.expect + 1
            and messages[-1]["role"] == "user" and messages[-1]["content"] == text):
        for _ in range(IN_PROGRESS_WAIT * 2):
            time.sleep(0.5)
            if len(messages) != request.expect + 1 or messages[-1]["role"] != "user":
                break
    # 연결이 끊겨 화면이 같은 글을 다시 보낸 경우: 이미 받은 답을 그대로 돌려준다 (대화가 두 번 쌓이지 않게)
    if (request.expect is not None and len(messages) == request.expect + 2
            and messages[-2]["content"] == text and messages[-1]["role"] == "assistant"):
        return {"reply": messages[-1]["content"], "completed": session["completed"]}
    if messages and text == START_SIGNAL:
        return error("이미 시작한 묵상입니다. 화면을 새로 불러와 주세요.", 409)

    messages.append({"role": "user", "content": text})
    try:
        answer = ai_client.reply(session["system"], messages)
    except ai_client.AIError as e:
        messages.pop()  # 답을 받지 못했으면 기록에 남기지 않는다 (다시 보내도 중복되지 않게)
        return error(str(e), 502)
    messages.append({"role": "assistant", "content": answer})

    if not session["completed"]:
        session["completed"] = finished(messages)
    return {"reply": answer, "completed": session["completed"]}


@router.post("/record")
def record(request: RecordRequest):
    """묵상 완료 기록을 만든다. 묵상자가 정리를 청했을 때 부른다.
    저장하지 않는다. date, meditation_time, uid는 넣지 않는다."""
    session = SESSIONS.get(request.session_id)
    if session is None:
        return error("이 묵상을 찾을 수 없습니다. 본문을 다시 불러와 주세요.", 404)
    if not any(m["role"] == "user" and m["content"] not in SIGNALS for m in session["messages"]):
        return error("아직 정리할 묵상이 없습니다.", 409)
    def work():
        try:
            return build_record(session)
        except RecordError as e:
            return error(str(e), 502)
    key = f"record:{request.session_id}:{request.request_id}" if request.request_id else ""
    return ONCE.run(key, work)
