"""일기장에 연결하고, 누가 요청했는지 확인한다.

환경변수:
  FIREBASE_SERVICE_ACCOUNT   서버가 Firestore에 쓰는 열쇠 (서비스 계정 키 JSON 전체). 비밀이다.
  FIREBASE_WEB_CONFIG        화면이 로그인에 쓰는 설정 (웹 앱 설정 JSON). 공개되어도 되는 값이다.
  DIARY_DEV_LOGIN=1          내 컴퓨터에서 로그인 없이 시험할 때만 쓴다. 열쇠가 있으면 무시한다.

둘 다 없으면 일기장은 꺼져 있고, 앱은 예전처럼 기기에만 보관한다.
"""
import json
import os

from .store import FirestoreStore, MemoryStore

_state = {"ready": False, "store": None, "verify": None, "mode": "off", "why": None}


class NotSignedIn(Exception):
    """로그인하지 않았거나 로그인 정보가 틀렸다."""


def read_key(raw):
    """서비스 계정 키를 읽는다. 붙여 넣는 동안 모양이 조금 달라져도 읽는다:
    private_key 안의 줄바꿈이 진짜 줄바꿈으로 바뀐 것, 앞뒤에 따옴표가 붙은 것, base64로 적은 것."""
    import base64
    text = raw.strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    if not text.startswith("{"):
        text = base64.b64decode(text, validate=True).decode("utf-8").strip()
    key = json.loads(text, strict=False)
    if not isinstance(key, dict) or key.get("type") != "service_account" or "private_key" not in key:
        raise ValueError("서비스 계정 키가 아니다")
    return key


def _connect():
    if _state["ready"]:
        return
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if raw:
        try:
            import firebase_admin
            from firebase_admin import auth, credentials, firestore
            try:
                app = firebase_admin.get_app()
            except ValueError:
                app = firebase_admin.initialize_app(credentials.Certificate(read_key(raw)))
        except Exception as problem:            # 열쇠를 읽지 못하면 일기장을 꺼 두고, 까닭의 종류만 적어 둔다 (열쇠의 내용은 적지 않는다)
            shape = f"{len(raw)}자, {len(raw.splitlines())}줄, 첫 글자 {'{' if raw.startswith('{') else '다름'}, private_key {'있음' if 'private_key' in raw else '없음'}"
            _state.update(ready=True, why=f"열쇠를 읽지 못함: {type(problem).__name__} ({shape})")
            return

        def verify(token):
            try:
                claims = auth.verify_id_token(token, app=app)
            except Exception:
                raise NotSignedIn()
            return claims["uid"], claims.get("email", "")

        _state.update(store=FirestoreStore(firestore.client(app)), verify=verify, mode="firebase")
    elif os.environ.get("DIARY_DEV_LOGIN") == "1":
        def verify(token):                      # 시험용: "dev:이름"을 그대로 믿는다
            if not token.startswith("dev:") or len(token) < 5:
                raise NotSignedIn()
            return token[4:], token[4:] + "@dev"

        _state.update(store=MemoryStore(), verify=verify, mode="dev")
    _state["ready"] = True


def reset():
    """검사에서 설정을 바꾼 뒤 다시 연결하게 한다."""
    _state.update(ready=False, store=None, verify=None, mode="off", why=None)


def mode():
    _connect()
    return _state["mode"]


def store():
    _connect()
    return _state["store"]


def who(authorization):
    """Authorization 머리말에서 사용자를 확인해 (uid, email)을 돌려준다.
    누구의 기록인지는 여기서만 정한다. 요청의 본문에 적힌 사용자 번호는 쓰지 않는다."""
    _connect()
    if _state["verify"] is None:
        raise NotSignedIn()
    kind, _, token = (authorization or "").partition(" ")
    if kind.lower() != "bearer" or not token.strip():
        raise NotSignedIn()
    return _state["verify"](token.strip())


def read_web_config(text):
    """Firebase 콘솔에서 복사한 웹 설정을 읽는다. 콘솔이 보여 주는 모양(const firebaseConfig = { apiKey: "..." };)도 받는다."""
    import re
    config = None
    for body in re.findall(r"\{[^{}]*\}", text or ""):       # 복사한 글에 다른 중괄호(import { ... })가 섞여 있어도 설정만 고른다
        if "apiKey" not in body:
            continue
        try:
            config = json.loads(body)
        except ValueError:
            body = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', body)      # 따옴표 없는 이름
            body = re.sub(r",\s*}", "}", body)                                   # 마지막 쉼표
            try:
                config = json.loads(body)
            except ValueError:
                config = None
        break
    if not isinstance(config, dict) or not all(isinstance(config.get(k), str) and config[k] for k in ("apiKey", "authDomain", "projectId")):
        return None
    return config


def web_config():
    """화면에 내어 주는 설정. why는 일기장이 꺼져 있을 때 그 까닭이다 (비밀은 담지 않는다)."""
    _connect()
    if _state["mode"] == "firebase":
        text = os.environ.get("FIREBASE_WEB_CONFIG", "")
        config = read_web_config(text)
        why = None if config else ("웹 설정이 없음" if not text.strip() else f"웹 설정을 읽지 못함: {len(text)}자, {len(text.splitlines())}줄, apiKey {'있음' if 'apiKey' in text else '없음'}")
        return {"login": "google" if config else None, "firebase": config, "why": why}
    if _state["mode"] == "dev":
        return {"login": "dev", "firebase": None, "why": None}
    return {"login": None, "firebase": None, "why": _state.get("why") or "열쇠가 없음"}
