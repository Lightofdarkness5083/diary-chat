# AI 지시문 (비공개)

묵상 인도자와 돌아보기 비서의 지시문은 이 저장소에 두지 않는다. 오래 다듬어 온 인도법이 담겨 있어 따로 지킨다.

서버는 아래 다섯 파일을 이 순서로 찾는다 (`settings.py`의 `read_prompt()`).

1. `PROMPTS_DIR` 환경변수가 가리키는 폴더
2. `/etc/secrets/` : Render의 Secret Files
3. 이 폴더 `prompts/` : 내 컴퓨터에서 쓸 때. `.gitignore`로 막혀 있다

| 파일 | 하는 일 |
| --- | --- |
| `meditation_system.md` | 7단계 묵상 인도자 |
| `meditation_record.md` | 묵상 대화를 일기 기록으로 정리 |
| `meditation_finish.md` | 묵상이 끝났는지 판단 |
| `meditation_suggest.md` | 오늘 묵상할 분량 고르기 |
| `chat_system.md` | 돌아보기 비서 |

파일이 없으면 서버는 "AI 지시문이 서버에 없습니다: 파일 이름"라고 알린다.
