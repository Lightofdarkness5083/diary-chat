"""문지기: 초대받은 계정만 들어오게 하고, 한 사람이 하루에 AI를 부르는 횟수에 높은 천장을 둔다.

서버의 한 곳(dev_main.py의 미들웨어)에서만 부른다. 묵상 인도(meditation)는 로그인을 모른 채로 둔다.

  초대 명단   Firestore members/{이메일}. 관리자가 Firebase 콘솔에서 문서를 더하면 초대, 지우면(또는 disabled: true) 취소.
  하루 천장   환경변수 AI_DAILY_LIMIT (기본 100). 보통의 쓰임으로는 닿지 않는다. 화면의 오류로 같은 요청이
              되풀이되는 사고를 막는 안전망이다. 날짜는 한국 시각으로 센다.

일기장이 꺼져 있으면(내 컴퓨터에서 열쇠 없이 시험할 때) 문을 열어 둔다.
"""
import datetime
import os
import time

from diary import access

# 문지기가 지키는 길: AI를 부르거나 사람의 기록을 다루는 곳. 본문 읽기(성경 DB)와 /api/config는 열어 둔다
GUARDED = ("/api/meditation/start", "/api/meditation/resume", "/api/meditation/chat",
           "/api/meditation/record", "/api/meditation/suggest",
           "/api/chat", "/api/diary/", "/api/conversations")
# 그중 AI를 부르는 길. 하루 천장을 센다
AI_CALLS = ("/api/meditation/chat", "/api/meditation/record", "/api/meditation/suggest", "/api/chat")
KST = datetime.timezone(datetime.timedelta(hours=9))

_seen = {}               # 이메일 -> (초대받았나, 언제까지 믿을지)
ALLOWED_FOR, REFUSED_FOR = 60, 10      # 초. 명단에서 뺀 사람은 1분 안에, 새로 넣은 사람은 10초 안에 반영된다


def daily_limit():
    try:
        return max(1, int(os.environ.get("AI_DAILY_LIMIT", "100")))
    except ValueError:
        return 100


def today():
    return datetime.datetime.now(KST).date().isoformat()


def _invited(store, email):
    key = (email or "").strip().lower()
    now = time.monotonic()
    known = _seen.get(key)
    if known and known[1] > now:
        return known[0]
    allowed = store.is_member(key)
    _seen[key] = (allowed, now + (ALLOWED_FOR if allowed else REFUSED_FOR))
    return allowed


def reset():
    """검사에서 명단을 바꾼 뒤 바로 반영되게 한다."""
    _seen.clear()


def check(path, authorization):
    """들어가도 되면 None, 안 되면 (상태 번호, 응답 본문)."""
    if not path.startswith(GUARDED):
        return None
    store = access.store()
    if store is None:
        return None
    try:
        uid, email = access.who(authorization)
    except access.NotSignedIn:
        return 403, {"error": "로그인이 필요합니다.", "code": "sign_in"}
    if not _invited(store, email):
        return 403, {"error": f"{email} 계정은 초대 명단에 없습니다. 초대받은 Google 계정으로 시작해 주세요.",
                     "code": "not_invited", "email": email}
    if path.startswith(AI_CALLS) and store.count_use(uid, today()) > daily_limit():
        return 429, {"error": "오늘 쓸 수 있는 만큼 모두 썼습니다. 내일 다시 이어서 해 주세요.", "code": "daily_limit"}
    return None
