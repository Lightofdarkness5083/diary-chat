"""대화 기록 API.

  POST   /api/conversations         대화 하나를 저장한다 (말 목록을 받아 새 대화로)
  GET    /api/conversations         내 대화 목록. 말(messages)은 담지 않는다: 번호, 이름, 쪽 수, 만든 때, 고친 때
  GET    /api/conversations/{번호}  대화 하나의 말 전부
  DELETE /api/conversations/{번호}  대화 하나를 지운다

돌아보기 비서(POST /api/chat)가 답할 때마다 물음과 답은 자동으로 저장된다.
모든 요청은 로그인 정보로 사용자를 확인하고, 그 사람의 대화만 다룬다. 남의 대화는 없는 것으로 보인다.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from diary import access

from . import service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class SaveRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=100)


def error(message, status):
    return JSONResponse({"error": message}, status_code=status)


def _user(authorization):
    store = access.store()
    if store is None:
        return None, None, error("일기장이 아직 연결되지 않았습니다.", 503)
    try:
        uid, _ = access.who(authorization)
    except access.NotSignedIn:
        return None, None, error("로그인이 필요합니다.", 403)
    return store, uid, None


@router.post("", status_code=201)
def save(request: SaveRequest, authorization: Optional[str] = Header(default=None)):
    store, uid, problem = _user(authorization)
    if problem:
        return problem
    return service.create(store, uid, [m.model_dump() for m in request.messages], request.title)


@router.get("")
def list_conversations(authorization: Optional[str] = Header(default=None)):
    store, uid, problem = _user(authorization)
    if problem:
        return problem
    return {"conversations": store.list_conversations(uid)}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, authorization: Optional[str] = Header(default=None)):
    store, uid, problem = _user(authorization)
    if problem:
        return problem
    found = store.get_conversation(uid, conversation_id)
    return found if found else error("그런 대화가 없습니다.", 404)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, authorization: Optional[str] = Header(default=None)):
    store, uid, problem = _user(authorization)
    if problem:
        return problem
    if not store.remove_conversation(uid, conversation_id):
        return error("그런 대화가 없습니다.", 404)
    return {"deleted": conversation_id}
