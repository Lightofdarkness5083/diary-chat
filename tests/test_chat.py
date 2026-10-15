"""묵상 돌아보기 비서 검사.  실행: .venv/bin/python -m tests.test_chat
AI를 부르지 않고, 비서가 쓰는 도구와 주고받는 모양을 확인한다."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat
from chat import routes
from meditation import ai_client


def rec(date, book, c1, v1, c2, v2, title, truth, summary, application="적용 글"):
    ref = f"{book} {c1}:{v1}-{v2}" if c1 == c2 else f"{book} {c1}:{v1}-{c2}:{v2}"
    return {"date": date, "meditation_time": "07:10", "book": book, "chapter_start": c1, "verse_start": v1,
            "chapter_end": c2, "verse_end": v2, "passage": ref, "title": title, "prayer": "주님, 마음을 엽니다.",
            "observation": "- 관찰 글", "background": "- 배경 글", "interpretation": "- 해석 글", "truth": truth,
            "application": application, "closing_prayer": "아멘.", "applied_truth": summary, "모르는 항목": "버려진다"}


import unicodedata

from diary import access

RECORDS = [rec("2026-10-05", "골로새서", 4, 2, 4, 6, "기도와 은혜의 말", "기도는 복음의 문을 연다.", "기도는 복음의 문"),
           rec("2026-10-02", "골로새서", 3, 18, 4, 1, "주 안에서 맺는 관계", "모든 관계의 주인은 그리스도시다.", "관계의 주인은 그리스도"),
           rec("2025-03-15", "여호수아", 18, 1, 18, 7, "남은 땅", "약속의 땅을 차지하라.", "믿음으로 차지함", "미루던 일을 오늘 시작한다"),
           rec("2025-07-01", "여호수아", 1, 1, 1, 9, "강하고 담대하라", "말씀을 지키면 형통하다.", "강하고 담대하라"),
           rec("2024-08-15", "여호수아", 24, 14, 24, 18, "섬길 자를 택하라", "오직 여호와만 섬긴다.", "여호와만 섬긴다"),
           rec("2025-12-31", "시편", 23, 1, 23, 6, "목자", "여호와는 나의 목자시다.", "나의 목자"),
           {**rec("2025-05-05", "여호수아", 2, 1, 2, 7, "지운 묵상", "지운 진리", "지운 진리"), "deleted": True},
           {"date": "날짜 아님", "book": "버려진다"}]
# Mac 파일 이름에서 온 기록처럼 책 이름이 자모로 나뉜(NFD) 것도 섞는다
RECORDS[3]["book"] = unicodedata.normalize("NFD", "여호수아")
RECORDS[3]["passage"] = unicodedata.normalize("NFD", RECORDS[3]["passage"])

records = routes.load_records(RECORDS)
assert [r["date"] for r in records] == ["2024-08-15", "2025-03-15", "2025-07-01", "2025-12-31", "2026-10-02", "2026-10-05"]
assert "모르는 항목" not in records[0] and "observation" not in records[0] and "truth" not in records[0]   # 비서는 필요한 항목만 본다
assert all(r["book"] == unicodedata.normalize("NFC", r["book"]) for r in records)                      # 한글은 NFC로 맞춘다
assert {r["book"] for r in records} == {"여호수아", "시편", "골로새서"}
run = routes.make_tools(records)

# 기간으로 찾기: 책별 횟수와 처음·마지막 날짜. 기간을 비우면 전체
y2025 = run("books_in_period", {"start": "2025-01-01", "end": "2025-12-31"})
assert y2025.startswith("2025-01-01부터 2025-12-31까지: 묵상 3편, 책 2권") and "- 여호수아: 2편 (2025-03-15 ~ 2025-07-01)" in y2025
assert y2025.index("여호수아") < y2025.index("시편") and "골로새서" not in y2025
everything = run("books_in_period", {})
assert everything.startswith("전체 기간: 묵상 6편, 책 3권") and "- 여호수아: 3편 (2024-08-15 ~ 2025-07-01)" in everything
assert "없습니다" in run("books_in_period", {"start": "2023-01-01", "end": "2023-12-31"})
assert "YYYY-MM-DD" in run("books_in_period", {"start": "2025년"})

# 책으로 찾기: 성경 순서, 붙잡은 진리와 적용. 기간을 주면 그 기간만
josh = run("book_records", {"book": "여호수아서", "start": "2025-01-01", "end": "2025-12-31"})      # '서'가 붙어도, NFD로 저장돼도 찾는다
assert josh.startswith("여호수아 묵상 2편 (2025-03-15 ~ 2025-07-01)")
assert josh.index("■ 2025-07-01") < josh.index("■ 2025-03-15")                                          # 1장이 18장보다 앞
assert "[붙잡은 진리] 믿음으로 차지함" in josh and "[적용] 미루던 일을 오늘 시작한다" in josh
assert "여호와만 섬긴다" not in josh and "지운 진리" not in josh                                    # 기간 밖, 지운 묵상은 빠진다
assert "묵상 3편" in run("book_records", {"book": unicodedata.normalize("NFD", "여호수아")})
missing = run("book_records", {"book": "에베소서", "start": "2025-01-01", "end": "2025-12-31"})
assert "에베소서 묵상이 없습니다" in missing and "이 기간에 묵상한 책: 시편, 여호수아" in missing
# 잘못 부른 도구는 오류 대신 말로 알린다. 예전 도구는 이제 없다
assert "없는 도구" in run("find_records", {"words": ["은혜"]}) and "맞지 않습니다" in run("book_records", {"책": "여호수아"})
assert [t["name"] for t in routes.TOOLS] == ["books_in_period", "book_records"]

# 비서에게 처음 주는 것은 기록 전체가 아니라 윤곽뿐이다
outline = routes.overview(records, "2026-10-13")
assert "저장된 묵상: 6편 (2024-08-15부터 2026-10-05까지)" in outline and "여호수아, 시편, 골로새서" in outline
assert "믿음으로 차지함" not in outline

# 주고받기
app = FastAPI()
app.include_router(chat.router)
client = TestClient(app)
seen = {}


def fake(system, messages, tools, run_tool):
    seen.update(system=system, messages=messages, tools=[t["name"] for t in tools])
    return "📖 내 묵상에서\n" + run_tool("book_records", {"book": "여호수아"})


ai_client.reply_with_tools = fake
talk = [{"role": "assistant", "content": "앞의 말"}, {"role": "user", "content": "2025년에는 어떤 책을 묵상했지?"},
        {"role": "assistant", "content": "여호수아 2편, 시편 1편이에요."}, {"role": "user", "content": "그 책에서 붙잡은 진리는?"}]

# 1) 일기장이 꺼져 있으면 (내 컴퓨터에서 시험) 화면이 보낸 기록으로 답한다
access.reset()
answer = client.post("/api/chat", json={"messages": talk, "records": RECORDS, "today": "2026-10-13"}).json()
assert "믿음으로 차지함" in answer["reply"]
assert [m["role"] for m in seen["messages"]] == ["user", "assistant", "user"]            # 묵상자의 말로 시작하도록 다듬는다
assert seen["tools"] == ["books_in_period", "book_records"]
assert "오늘: 2026-10-13" in seen["system"] and "📖 내 묵상에서" in seen["system"] and "비교는 하지 않습니다" in seen["system"]
assert "한 책의 묵상을 요약해 달라고 할 때" in seen["system"]
long_talk = [{"role": r, "content": f"말 {i}"} for i, r in enumerate(["user", "assistant"] * 15)] + [{"role": "user", "content": "끝 물음"}]
client.post("/api/chat", json={"messages": long_talk, "records": []})
assert len(seen["messages"]) <= 20 and seen["messages"][-1]["content"] == "끝 물음"      # 최근 10쪽만 기억한다
assert client.post("/api/chat", json={"messages": [{"role": "user", "content": " "}], "records": []}).status_code == 400
assert client.post("/api/chat", json={"messages": talk[:3], "records": []}).status_code == 400    # 비서의 말로 끝나면 물음이 없다

# 2) 일기장이 켜져 있으면 로그인한 사람의 기록만 일기장에서 읽는다. 화면이 보낸 기록은 쓰지 않는다
import os
from diary.store import MemoryStore

os.environ["DIARY_DEV_LOGIN"] = "1"
access.reset()
db = access.store()
assert isinstance(db, MemoryStore)
for i, r in enumerate(RECORDS[:6]):
    clean = {k: v for k, v in r.items() if k != "모르는 항목"}
    db.add("moon", f"moonrecord{i:02d}", clean)
db.add("other", "otherrecord01", {k: v for k, v in rec("2025-06-01", "여호수아", 5, 1, 5, 9, "남의 묵상", "남의 진리", "남의 진리").items() if k != "모르는 항목"})
db.remove("moon", "moonrecord03")                                                     # 지운 묵상 (2025-07-01)
fake_sent = [rec("2025-02-02", "여호수아", 3, 1, 3, 5, "보낸 기록", "보낸 진리", "화면이 보낸 진리")]
signed = {"Authorization": "Bearer dev:moon"}
reply = client.post("/api/chat", json={"messages": talk, "records": fake_sent}, headers=signed).json()["reply"]
assert "믿음으로 차지함" in reply and "여호와만 섬긴다" in reply
assert "남의 진리" not in reply and "화면이 보낸 진리" not in reply and "강하고 담대하라" not in reply
assert "여호수아 묵상 2편" in reply
assert client.post("/api/chat", json={"messages": talk}).status_code == 403                                        # 로그인하지 않음
assert client.post("/api/chat", json={"messages": talk}, headers={"Authorization": "Bearer wrong-token"}).status_code == 403
del os.environ["DIARY_DEV_LOGIN"]
access.reset()


def failing(system, messages, tools, run_tool):
    raise ai_client.AIError("AI API 오류")


ai_client.reply_with_tools = failing
assert client.post("/api/chat", json={"messages": talk, "records": []}).status_code == 502

# 도구를 쓰는 대화의 흐름: AI가 도구를 부르면 실행해 결과를 돌려주고, 글로 된 답이 나올 때까지 잇는다
import importlib
import os
import sys
import types


class Block:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class Response:
    def __init__(self, stop_reason, content):
        self.stop_reason, self.content, self.usage = stop_reason, content, Block(output_tokens=1)


script = [Response("tool_use", [Block(type="thinking"), Block(type="tool_use", id="t1", name="books_in_period", input={"start": "2025-01-01"})]),
          Response("end_turn", [Block(type="text", text="은혜에 대해 두 번 쓰셨어요.")])]
calls = []


class FakeClient:
    def __init__(self, api_key):
        self.messages = self

    def create(self, **request):
        calls.append(request)
        return script[len(calls) - 1]


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=FakeClient, APIError=RuntimeError)
real = importlib.reload(ai_client)
os.environ["ANTHROPIC_API_KEY"] = "test"
ran = []
text = real.reply_with_tools("시스템", [{"role": "user", "content": "은혜?"}], routes.TOOLS,
                             lambda name, values: ran.append((name, values)) or "찾은 기록")
assert text == "은혜에 대해 두 번 쓰셨어요." and ran == [("books_in_period", {"start": "2025-01-01"})]
second = calls[1]["messages"]
assert [m["role"] for m in second] == ["user", "assistant", "user"]
assert second[1]["content"] is script[0].content                                   # 생각 블록까지 그대로 돌려준다
assert second[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "찾은 기록"}]
calls.clear(); script[:] = [script[0]] * 6                                         # 도구만 계속 부르면 그만둔다
try:
    real.reply_with_tools("시스템", [{"role": "user", "content": "은혜?"}], routes.TOOLS, lambda n, v: "기록", max_rounds=3)
    raise AssertionError("오류가 나야 한다")
except real.AIError as e:
    assert "맺지 못했습니다" in str(e) and len(calls) == 3
del sys.modules["anthropic"], os.environ["ANTHROPIC_API_KEY"]

print("모든 검사 통과")
