"""새 참여자를 관리자의 Google 시트에 한 줄 적는다 (날짜, 이름, 이메일).

서버의 서비스 계정(FIREBASE_SERVICE_ACCOUNT)이 시트에 쓴다. 준비할 것:
  1. Google Cloud(프로젝트 diary-with-jesus)에서 Google Sheets API 켜기
  2. 시트의 [공유]에 서비스 계정 이메일(...@diary-with-jesus.iam.gserviceaccount.com)을 편집자로 더하기
  3. Render 환경변수 SIGNUP_SHEET_ID = 시트 주소의 /d/ 와 /edit 사이 글자

시트에 적지 못해도 참여는 막지 않는다. 명단의 원본은 Firestore members이고, 시트는 관리자가 보기 쉬운 사본이다.
"""
import os
import threading

from diary import access

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
URL = "https://sheets.googleapis.com/v4/spreadsheets/{id}/values/A1:append"


def ready():
    return bool(os.environ.get("SIGNUP_SHEET_ID", "").strip() and os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip())


def _append(row):
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        key = access.read_key(os.environ["FIREBASE_SERVICE_ACCOUNT"])
        session = AuthorizedSession(service_account.Credentials.from_service_account_info(key, scopes=[SCOPE]))
        answer = session.post(URL.format(id=os.environ["SIGNUP_SHEET_ID"].strip()),
                              params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                              json={"values": [row]}, timeout=15)
        if not answer.ok:          # 무엇이 틀렸는지만 남긴다 (이메일이나 열쇠는 남기지 않는다)
            print(f"참여자 시트에 적지 못함: {answer.status_code}", flush=True)
    except Exception as problem:
        print(f"참여자 시트에 적지 못함: {type(problem).__name__}", flush=True)


def add(row):
    """시트에 한 줄 적는 일을 뒤에서 한다. 참여자는 기다리지 않는다."""
    if ready():
        threading.Thread(target=_append, args=(list(row),), daemon=True).start()
