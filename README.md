# Diary with Jesus: 묵상 부분 (meditation 브랜치)

7단계 묵상 인도를 맡는 부분이다. 저장, 조회, 챗봇, 로그인, `main.py`는 Diary 쪽이 맡는다.

## 들어 있는 것

| 자리 | 내용 | 담당 |
| --- | --- | --- |
| `meditation/` | 7단계 묵상 대화, AI 호출, 시스템 프롬프트, 묵상 완료 기록 | 묵상 부분 |
| `chat/` | 묵상 일기 비서. 저장한 묵상을 도구로 찾아 읽고 답한다 | 비서 |
| `diary/` | 일기장. 묵상 기록을 사용자별로 Firestore에 저장한다 | 일기장 |
| `bible/` | 본문 조회와 DB 검사. `bible_clean.db`를 여기에 둔다 | 공통 (읽기 전용) |
| `frontend/index.html` | 참고용 대화 화면 | Diary 쪽에 넘김 |
| `dev_main.py` | 앱의 출입구. 묵상 부분을 연결하고 화면을 내어 준다. 접속 암호를 확인한다 | 묵상 부분 |
| `tests/` | 본문 조회와 묵상 부분 검사 | 묵상 부분 |

Diary 쪽이 연결할 때 읽을 문서는 `meditation/README.md`다.

## 화면의 흐름

1. 앱을 열면 이번 달 달력이 나온다. 묵상한 날에는 그날의 본문이 적혀 있고, 누르면 묵상 정리가 열린다.
2. 오늘 날짜를 누르면 묵상하던 책에서 이어지는 본문이 끝 절까지 골라져 나온다. 그대로 시작하거나, 다른 절을 눌러 끝을 바꾸거나, 함께 읽는 본문을 직접 적는다. 한 책을 마치기 전에는 그 책에 머문다.
3. 7단계 묵상을 한다.
4. 묵상이 끝나면 정리할지 묻고, 정리를 보여 준 뒤 저장할지 묻는다.
5. 저장하면 달력으로 돌아온다.

달력 아래의 칸 하나에 세 가지를 적을 수 있다.

- 본문 (`골로새서 3:18-4:1`): 그 본문으로 묵상한다.
- `이어서 묵상`: 하던 책의 다음 단락으로 바로 묵상한다.
- 그 밖의 말: 묵상 일기 비서에게 묻는다. 비서는 저장한 묵상을 찾아 읽고 답한다.
  - "은혜에 대해 뭐라고 썼지?" 낱말로 묵상을 찾는다.
  - "골로새서에서 찾은 진리를 보여 줘" 한 책의 진리와 요약을 본문 순서대로 모아 보여 준다. 책을 끝까지 마치면 이 정리를 권한다.
  - "올해 묵상을 돌아보고 싶어" 묵상한 날을 열두 달의 칸으로 보여 주고, 언제 어느 본문을 묵상했는지 알려 준다.

묵상을 중간에 멈추어도 대화가 기기에 보관된다. 다시 열면 오늘 칸에서 이어서 할 수 있다.

묵상 기록과 "어느 책의 어디까지 묵상했는가"는 지금은 기기의 브라우저에 임시로 보관한다. 일기장(DB)의 구조를 정한 뒤에 옮긴다.

## 새 컴퓨터에서 시작하기

1. 이 브랜치를 내려받는다.
2. `bible/` 폴더에 `bible_clean.db`를 넣는다.
3. 터미널에서 `sh setup.sh`를 실행한다. 끝에 "결과: 모든 검사 통과"가 나와야 한다.
4. `.env`를 열어 `ANTHROPIC_API_KEY=` 뒤에 API 키를 넣는다.
5. `sh run.sh`로 켜고 브라우저에서 http://127.0.0.1:8000 을 연다. 끌 때는 `Ctrl + C`.

## 인터넷에 올리기 (Render)

휴대폰에서 쓰려면 인터넷에 올린다. Render의 Web Service로 이 저장소의 `meditation` 브랜치를 연결한다.

| 항목 | 값 |
| --- | --- |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn dev_main:app --host 0.0.0.0 --port $PORT` |
| 환경변수 `ANTHROPIC_API_KEY` | Anthropic API 키 |
| 환경변수 `APP_PASSCODE` | 접속 암호. 꼭 정한다 |

접속 암호를 정하지 않으면 주소를 아는 누구나 들어와 API 요금을 쓰게 된다. 암호는 처음 한 번만 묻고 기기에 적어 둔다.

## 일기장 (Firestore)

묵상 기록을 사용자별로 Firestore에 저장한다. Render의 환경변수 두 개를 넣으면 켜진다. 넣지 않으면 일기장은 꺼져 있고, 묵상 기록은 기기에만 보관된다.

| 환경변수 | 값 | 비밀인가 |
| --- | --- | --- |
| `FIREBASE_SERVICE_ACCOUNT` | 서비스 계정 키 JSON 전체 | 비밀 |
| `FIREBASE_WEB_CONFIG` | Firebase 웹 앱 설정 JSON | 공개되어도 됨 |

- 표지를 펼치면 Google 계정으로 로그인한다. 누구의 기록인지는 서버가 로그인 정보에서만 확인한다.
- 자리: Firebase 프로젝트 `Diary-with-Jesus`의 `diaries/{기록 번호}` (묵상 하나), `diary_state/{uid}` (묵상 중인 책의 자리, 하다가 멈춘 묵상). 다른 컬렉션은 건드리지 않는다.
- 모든 묵상 문서는 같은 19개 항목을 가진다: 기록 17개 항목(`diary/schema.py`) + `uid` + `deleted`. 누구의 것인지는 문서 안의 `uid`로 가른다.
- 묵상은 새로 만들기만 한다. 같은 번호로 다시 와도 하나만 남고, 다른 내용으로 덮어쓰지 않는다. 지우기는 "지움" 표시만 한다.
- 기기에만 있던 묵상은 로그인한 뒤 달력 아래의 "일기장으로 옮기기"로 올린다. 올린 뒤 다시 읽어 같은지 확인한다.
- 코드는 `diary/`에 있다. 검사: `.venv/bin/python -m tests.test_diary`

### 예전에 저장된 묵상을 지금의 구조에 맞추기

예전 문서는 11개 항목이다. 모자란 항목을 채워 새 묵상과 같은 구조로 만든다. 예전 `truthSummary`에 들어 있던 적용 진리는 `applied_truth`로 옮긴다. 순서를 지킨다.

```
.venv/bin/python -m tools.diaries backup  --key 키파일.json          # 1. 사본을 내려받는다 (읽기만)
.venv/bin/python -m tools.diaries inspect --key 키파일.json          # 2. 살펴본다 (읽기만)
.venv/bin/python -m tools.diaries upgrade --key 키파일.json          # 3. 무엇을 채울지 미리 본다 (읽기만)
.venv/bin/python -m tools.diaries upgrade --key 키파일.json --apply --backup backup/사본.json   # 4. 채운다 (더하기만)
.venv/bin/python -m tools.diaries drop-summary --key 키파일.json --apply --backup backup/사본.json  # 5. 확인이 끝난 뒤 truthSummary를 없앤다
```

- 4번은 항목을 더하기만 한다. 이미 있는 항목은 바꾸지도 지우지도 않는다. 사본이 지금의 DB와 다르면 멈춘다.
- 본문을 읽지 못한 문서(책 이름 오타 등)는 건드리지 않고 목록으로 알려 준다. 사람이 정한다.
- 키 파일과 `backup/` 폴더는 깃에 올리지 않는다. 공용 컴퓨터에서는 일을 마치면 둘 다 지운다.

## 작업을 마칠 때

공용 컴퓨터에서는 폴더가 지워질 수 있다. 자리를 뜨기 전에 커밋하고 동기화한 뒤, GitHub 화면에서 올라간 것을 눈으로 확인한다. `.env`와 `.venv`는 올라가지 않는다.

## 검사

```
.venv/bin/python -m tests.test_bible
.venv/bin/python -m tests.test_meditation
.venv/bin/python -m tests.test_chat
.venv/bin/python -m tests.test_passcode
.venv/bin/python -m bible.check_db
```

앞의 둘은 시험용 DB와 흉내 낸 AI 답으로 돌고, 마지막은 실제 성경 DB를 검사한다.
