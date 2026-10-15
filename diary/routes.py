"""일기장: 묵상 기록을 사용자별로 저장하고 내어 준다.

  GET    /api/config                 화면이 쓸 설정 (로그인 방법). 접속 암호 없이 읽는다
  GET    /api/diary/records          내 묵상 기록 모두
  POST   /api/diary/records          묵상 하나를 저장한다 (새로 만들기만 한다)
  DELETE /api/diary/records/{번호}   묵상 하나에 "지움" 표시를 한다
  GET    /api/diary/state            내 현재 상태
  PUT    /api/diary/state            내 현재 상태를 적어 둔다

모든 요청은 로그인 정보(Authorization: Bearer …)로 사용자를 확인한다.
서버의 작업 기록에는 묵상의 글을 남기지 않는다.
"""
from typing import Any, Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import access
from .schema import RecordError, check_existing_id, check_id, clean_record
from .store import Conflict

router = APIRouter(tags=["diary"])

STATE_FIELDS = ["progress", "draft", "planned", "guided", "updated_at"]
MAX_STATE_SIZE = 600_000        # 하다가 멈춘 묵상의 대화가 들어간다


def error(message, status):
    return JSONResponse({"error": message}, status_code=status)


class SaveRequest(BaseModel):
    id: str
    record: dict[str, Any]


class StateRequest(BaseModel):
    state: dict[str, Any]


def _user(authorization):
    """(uid, 오류 응답). 일기장이 꺼져 있거나 로그인하지 않았으면 오류 응답을 돌려준다."""
    if access.store() is None:
        return None, error("일기장이 아직 연결되지 않았습니다.", 503)
    try:
        uid, _ = access.who(authorization)
    except access.NotSignedIn:
        return None, error("로그인이 필요합니다.", 403)
    return uid, None


@router.get("/api/config")
def config():
    return access.web_config()


@router.get("/api/diary/records")
def list_records(authorization: Optional[str] = Header(default=None)):
    uid, problem = _user(authorization)
    if problem:
        return problem
    return {"records": access.store().list(uid)}


@router.post("/api/diary/records")
def save_record(request: SaveRequest, authorization: Optional[str] = Header(default=None)):
    uid, problem = _user(authorization)
    if problem:
        return problem
    try:
        record_id = check_id(request.id)
        record = clean_record(request.record)
    except RecordError as e:
        return error(f"저장하지 않았습니다. {e}", 400)
    try:
        stored = access.store().add(uid, record_id, record)
    except Conflict:
        return error("저장하지 않았습니다. 같은 번호로 다른 내용의 기록이 이미 있습니다.", 409)
    if stored is None or any(stored[field] != record[field] for field in record):
        return error("저장한 기록을 다시 읽었더니 보낸 것과 다릅니다.", 500)
    return {"record": stored}


@router.delete("/api/diary/records/{record_id}")
def remove_record(record_id: str, authorization: Optional[str] = Header(default=None)):
    uid, problem = _user(authorization)
    if problem:
        return problem
    try:
        check_existing_id(record_id)
    except RecordError as e:
        return error(str(e), 400)
    if not access.store().remove(uid, record_id):
        return error("그 기록을 찾지 못했습니다.", 404)
    return {"removed": record_id}


@router.get("/api/diary/state")
def get_state(authorization: Optional[str] = Header(default=None)):
    uid, problem = _user(authorization)
    if problem:
        return problem
    return {"state": access.store().get_state(uid)}


@router.put("/api/diary/state")
def put_state(request: StateRequest, authorization: Optional[str] = Header(default=None)):
    uid, problem = _user(authorization)
    if problem:
        return problem
    state = {field: request.state.get(field) for field in STATE_FIELDS}
    if not isinstance(state["updated_at"], (int, float)) or isinstance(state["updated_at"], bool):
        return error("updated_at이 필요합니다.", 400)
    import json
    if len(json.dumps(state, ensure_ascii=False)) > MAX_STATE_SIZE:
        return error("상태가 너무 큽니다.", 400)
    return {"state": access.store().set_state(uid, state)}
