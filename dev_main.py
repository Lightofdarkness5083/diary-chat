"""앱의 출입구.  내 컴퓨터에서: sh run.sh   인터넷에 올릴 때: uvicorn dev_main:app --host 0.0.0.0 --port $PORT

묵상 부분(meditation)과 일기 비서(chat)를 연결하고, 화면(frontend/index.html)을 내어 준다.

문지기(gate.py): 일기장(Firebase)이 켜져 있으면 초대 명단(Firestore members)에 있는 Google 계정만
묵상과 비서를 쓸 수 있고, 한 사람이 하루에 AI를 부르는 횟수에 높은 천장을 둔다.
인터넷에 올리면 주소를 아는 누구나 들어올 수 있고, 묵상할 때마다 API 요금이 나가기 때문이다.

접속 암호: 환경변수 APP_PASSCODE를 정해 두면 그 암호도 함께 묻는다. 초대 명단을 쓰면 정하지 않는다.
"""
import hmac
import os
from urllib.parse import unquote

from settings import ROOT, PromptMissing, load_env

load_env()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

import chat  # noqa: E402
import gate  # noqa: E402
import conversations  # noqa: E402
import diary  # noqa: E402
import meditation  # noqa: E402

app = FastAPI(title="Diary with Jesus")
app.include_router(meditation.router)   # 7단계 묵상 인도
app.include_router(chat.router)         # 묵상 일기 비서
app.include_router(conversations.router)  # 비서와 나눈 대화 기록
app.include_router(diary.router)        # 일기장: 묵상 기록을 사용자별로 저장


@app.middleware("http")
async def check_passcode(request: Request, call_next):
    passcode = os.environ.get("APP_PASSCODE", "")
    if passcode and request.url.path.startswith("/api/") and request.url.path != "/api/config":
        given = unquote(request.headers.get("x-passcode", ""))
        if not hmac.compare_digest(given.encode("utf-8"), passcode.encode("utf-8")):
            return JSONResponse({"error": "접속 암호가 맞지 않습니다."}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def gatekeeper(request: Request, call_next):
    # 초대받은 계정만, 하루 천장 안에서. 무엇을 지키는지는 gate.py에 있다
    if request.method != "OPTIONS":
        refused = await run_in_threadpool(gate.check, request.url.path, request.headers.get("authorization"))
        if refused:
            return JSONResponse(refused[1], status_code=refused[0])
    return await call_next(request)


# 다른 주소의 화면(Vercel)이 이 서버를 부를 수 있게 하는 명단. 환경변수 ALLOWED_ORIGINS에 쉼표로 적는다.
# 명단일 뿐 자물쇠가 아니다: 접속 암호와 로그인 확인은 그대로 한다.
# 접속 암호 확인보다 뒤에 붙여야 바깥에서 먼저 받는다. 그래야 브라우저의 사전 문의(OPTIONS)에 답하고,
# 암호가 틀렸다는 답(401)도 화면이 읽을 수 있다.
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Passcode"])


@app.exception_handler(PromptMissing)
async def prompt_missing(request: Request, problem: PromptMissing):
    # 지시문 파일을 금고(Render Secret Files)에 올리지 않았을 때. 무엇이 빠졌는지 분명히 알린다
    return JSONResponse({"error": str(problem)}, status_code=503)


@app.get("/")
def index():
    # 휴대폰이 옛 화면을 붙들고 있지 않도록, 열 때마다 새 화면인지 서버에 묻게 한다
    return FileResponse(ROOT / "frontend" / "index.html", headers={"Cache-Control": "no-cache"})


# 홈 화면에 추가할 때 쓰는 앱 정보와 아이콘 (암호 없이 열린다: 묵상 내용이 없다)
APP_FILES = {
    "config.js": "text/javascript",
    "manifest.webmanifest": "application/manifest+json",
    "apple-touch-icon.png": "image/png",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "icon-maskable-512.png": "image/png",
}


@app.get("/{name}")
def app_file(name: str):
    if name not in APP_FILES:
        return JSONResponse({"error": "없는 주소입니다."}, status_code=404)
    return FileResponse(ROOT / "frontend" / name, media_type=APP_FILES[name])
