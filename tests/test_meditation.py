"""묵상 부분 검사.  실행: .venv/bin/python -m tests.test_meditation
AI를 부르지 않고 흉내 낸 답으로, 대화 흐름과 묵상 완료 기록의 모양을 확인한다."""
import json
import os

from tests.test_bible import make_db

os.environ["BIBLE_DB"] = make_db(merged=[(3, 18, 19)], all_books=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import meditation  # noqa: E402
from meditation import ai_client, record, routes  # noqa: E402

app = FastAPI()
app.include_router(meditation.router)
client = TestClient(app)
API = "/api/meditation"

PRAYER = "주님, 오늘 말씀 앞에 마음을 엽니다.\n제 생각을 내려놓고 듣게 하소서."
TRUTH = "음, 제가 발견한 진리는 이것입니다. 모든 관계의 주인은 그리스도시다."
CLOSING = "주님, 오늘 만나는 사람을 주께 하듯 대하게 하소서. 아멘."
GUIDE = ["기도를 적어 주세요.", "본문을 읽어 보세요.\n\n[[본문]]", "무엇을 관찰하셨나요?", "반복되는 말을 찾아보세요.",
         "진리를 한 문장으로 써 보세요.", "어떻게 적용하시겠어요? 마침기도도 적어 주세요.", "아멘. 오늘 묵상을 여기서 마칩니다."]
USER = [PRAYER, "다 읽었습니다.", "아내와 남편에게 하신 말씀입니다.", "주라는 말이 나옵니다.", TRUTH, "오늘 가족에게 주께 하듯 말하겠습니다.\n" + CLOSING]
record_answers, finish_answers, finish_seen = [], [], []
suggest_answers, suggest_seen = [], []


def fake(system, messages):
    if "묵상 완료 기록" in system:           # 기록 정리 요청
        return record_answers.pop(0)
    if "한 단락으로 마무리" in system:        # 끝 절을 제안해 달라는 요청
        suggest_seen.append(messages[0]["content"])
        return suggest_answers.pop(0)
    if "끝났는지 판단" in system:            # 묵상이 끝났는지 확인하는 요청
        finish_seen.append(messages[0]["content"])
        return finish_answers.pop(0)
    return GUIDE[min(len(messages) // 2, len(GUIDE) - 1)]


ai_client.reply = fake


def good(**changes):
    data = {"title": "주 안에서 맺는 관계", "prayer_from": 1, "prayer": PRAYER,
            "observation": "- 아내와 남편에게 주신 말씀 (18-19절)\n- 반복되는 말: 주",
            "background": "- 바울이 감옥에서 골로새 교회에 쓴 편지", "interpretation": "- 모든 관계는 주님을 섬기는 자리였다.",
            "truth_from": [5], "truth": "모든 관계의 주인은 그리스도시다.",
            "application": "- 오늘 가족에게 주께 하듯 말한다.",
            "applied_truth_from": [5], "applied_truth": "모든 관계의 주인은 그리스도시다.",
            "closing_prayer_from": 6, "closing_prayer": CLOSING}
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


# 시작: 본문 위치가 약속한 항목 이름으로 나온다
started = client.post(f"{API}/start", json={"ref": "골 3:18-4:1"}).json()
sid = started["session_id"]
assert [started[k] for k in record.POSITION_FIELDS] == ["골로새서", 3, 18, 4, 1, "골로새서 3:18-4:1"]
assert started["verses"][0]["label"] == "18-19"
assert started["opening"] == "기도로 묵상을 시작하겠습니다."        # 첫 말은 AI가 짓지 않는다. 늘 이 한 문장이다

# 대화: 인도자의 말은 손대지 않고 그대로 내보낸다. 묵상자의 글이 6개가 되기 전에는 끝을 확인하지 않는다
first = client.post(f"{API}/chat", json={"session_id": sid, "message": None}).json()
assert first == {"reply": started["opening"], "completed": False}   # 첫 말을 청해도 같은 문장이 온다
assert client.post(f"{API}/record", json={"session_id": sid}).status_code == 409   # 아직 정리할 것이 없다
for text in USER[:5]:
    reply = client.post(f"{API}/chat", json={"session_id": sid, "message": text}).json()
    assert reply["completed"] is False
assert finish_seen == []

# 여섯 번째 글부터 끝을 확인한다. 확인은 대화의 마지막 부분만 본다
finish_answers[:] = ["끝남"]
reply = client.post(f"{API}/chat", json={"session_id": sid, "message": USER[5]}).json()
assert reply == {"reply": GUIDE[6], "completed": True}
assert len(finish_seen) == 1 and CLOSING in finish_seen[0] and "[인도자]\n" + GUIDE[6] in finish_seen[0]
assert PRAYER not in finish_seen[0]

# 끝을 확인하다 오류가 나도 묵상은 이어진다 (끝나지 않은 것으로 본다)
other = client.post(f"{API}/start", json={"ref": "골 4:2-6"}).json()["session_id"]
client.post(f"{API}/chat", json={"session_id": other, "message": None})
finish_answers[:] = ["진행중"]
for i in range(6):
    assert client.post(f"{API}/chat", json={"session_id": other, "message": f"글 {i}"}).json()["completed"] is False
def broken(system, messages):
    if "끝났는지 판단" in system:
        raise ai_client.AIError("확인 실패")
    return fake(system, messages)
ai_client.reply = broken
assert client.post(f"{API}/chat", json={"session_id": other, "message": "하나 더"}).json()["completed"] is False
ai_client.reply = fake

# 기록: 약속한 항목만, 약속한 순서로. date, meditation_time, uid는 없다
record_answers[:] = [good()]
made = client.post(f"{API}/record", json={"session_id": sid}).json()
assert list(made) == record.RECORD_FIELDS, list(made)
assert made["passage"] == "골로새서 3:18-4:1" and made["chapter_start"] == 3 and made["chapter_end"] == 4
assert made["title"] == "주 안에서 맺는 관계"
assert made["prayer"] == PRAYER and made["closing_prayer"] == CLOSING
assert made["truth"] == "모든 관계의 주인은 그리스도시다."        # 원문 안의 한 문장
assert made["observation"].splitlines()[1] == "- 반복되는 말: 주"

# 적용 진리: 진리가 하나뿐이면 그 진리가 적용 진리다. AI가 줄이거나 바꿔 쓰면 버리고 묵상자의 진리를 쓴다
assert made["applied_truth"] == "모든 관계의 주인은 그리스도시다." and "truthSummary" not in made
record_answers[:] = [good(applied_truth="관계의 주인은 그리스도")]                      # 줄인 글
assert client.post(f"{API}/record", json={"session_id": sid}).json()["applied_truth"] == "관계의 주인은 그리스도"   # 원문 안에 그대로 있는 구절은 묵상자의 말이다
record_answers[:] = [good(applied_truth="관계의 중심은 예수님이시다.")]                 # 바꿔 쓴 글
assert client.post(f"{API}/record", json={"session_id": sid}).json()["applied_truth"] == "모든 관계의 주인은 그리스도시다."
# 진리가 여럿이고 묵상자가 "두 번째"라고 번호로 골랐으면, 그 번호의 진리 문장이 적용 진리다
two = {"truth_from": [1], "truth": "1. 우리는 교회다.\n2. 교회는 그분의 권세 아래에 있다.",
       "applied_truth_from": [2], "applied_truth": "2. 교회는 그분의 권세 아래에 있다."}
said = ["1. 우리는 교회다 2. 교회는 그분의 권세 아래에 있다", "두 번째 진리를 적용할게요"]
assert record._applied_truth(two, said) == "교회는 그분의 권세 아래에 있다."
assert record._applied_truth(dict(two, applied_truth="교회는 주님께 속했다."), said) == two["truth"]   # 바꿔 쓰면 찾은 진리를 그대로 둔다

# 마침기도 없이 마친 묵상에서는 그 항목이 빈 글이다
record_answers[:] = [good(closing_prayer_from=None, closing_prayer="")]
assert client.post(f"{API}/record", json={"session_id": sid}).json()["closing_prayer"] == ""

# AI가 묵상자의 글을 고쳐 써서 돌려주면, 그 글을 버리고 묵상자의 원문 전체를 쓴다
record_answers[:] = [good(truth="모든 관계의 주인은 그리스도이십니다.", prayer="주님, 제 마음을 열어 주세요.")]
made = client.post(f"{API}/record", json={"session_id": sid}).json()
assert made["truth"] == TRUTH and made["prayer"] == PRAYER

# 정리한 글이 묵상자의 표현을 바꿔 따옴표에 넣었으면, 그 표현을 짚어 한 번 더 정리하게 한다
said = ['"난 것이 아님"이 두 번 나옵니다. 구원은 선물이라는 뜻 같아요.']
changed = {f: "글" for f in record.TEXT_FIELDS}
changed["interpretation"] = '- "난 것이 아니"가 두 번 반복되는 것은 구원이 선물이라는 뜻이다.'
assert record._strange_quotes(changed, said) == ["난 것이 아니"]
kept = dict(changed, interpretation='- "난 것이 아님"이 두 번 반복되는 것은 구원이 "선물"이라는 뜻이다.')
assert record._strange_quotes(kept, said) == []                      # 묵상자가 쓴 표현은 그대로 두어도 된다
asked_again = []
def twice(system, messages):
    if "묵상 완료 기록" not in system:
        return fake(system, messages)
    asked_again.append(messages[0]["content"])
    wrong = len(asked_again) == 1
    return good(interpretation='- "주께 하는 듯"이라는 말이 되풀이된다.' if wrong else '- "주께 하듯"이라는 말이 되풀이된다.')
ai_client.reply = twice
made = client.post(f"{API}/record", json={"session_id": sid}).json()
assert made["interpretation"] == '- "주께 하듯"이라는 말이 되풀이된다.' and len(asked_again) == 2
assert "- 주께 하는 듯" in asked_again[1] and "묵상자가 쓴 표현 그대로" in asked_again[1]
asked_again.clear()
ai_client.reply = lambda system, messages: twice(system, messages) if not asked_again else good(interpretation='- "주께 하는 듯"이라고 또 바꿈')
made = client.post(f"{API}/record", json={"session_id": sid}).json()    # 두 번 다 바꿔 쓰면 처음 정리한 것을 쓴다 (기록은 나온다)
assert made["interpretation"] == '- "주께 하는 듯"이라는 말이 되풀이된다.'
ai_client.reply = fake

# 원문으로 돌아갈 때에도 원문의 오타는 따로 바로잡는다. 그 교정이 낱말을 바꾸면 원문 그대로 쓴다
def respell(answer):
    def reply(system, messages):
        return answer if "맞춤법과 띄어쓰기만 바로잡아" in system else fake(system, messages)
    return reply
ai_client.reply = respell("모든 관계의 주인은 그리스도시다.")
assert record._original("전혀 다른 문장입니다.", 1, ["모든 관게의 주인은 그리스도 시다"], "truth") == "모든 관계의 주인은 그리스도시다."
ai_client.reply = respell("모든 관계의 중심은 예수님이십니다.")
assert record._original("전혀 다른 문장입니다.", 1, ["모든 관게의 주인은 그리스도 시다"], "truth") == "모든 관게의 주인은 그리스도 시다"
ai_client.reply = respell("모든 관계의")                       # 줄어든 글도 받지 않는다
assert record._original("전혀 다른 문장입니다.", 1, ["모든 관게의 주인은 그리스도 시다"], "truth") == "모든 관게의 주인은 그리스도 시다"
ai_client.reply = fake

# 진리가 여러 문장이고 여러 글에 걸쳐 있어도, 줄마다 원문과 견준다
truths = ["1. 우리는 교회다 2. 교회는 그분의 권세 아래에 있다", "하나 더 있어요. 그분은 만물을 다스리는 분이시다"]
good_lines = "1. 우리는 교회다.\n2. 교회는 그분의 권세 아래에 있다.\n3. 그분은 만물을 다스리는 분이시다."
assert record._original(good_lines, [1, 2], truths, "truth") == good_lines
changed_lines = good_lines.replace("만물을 다스리는 분", "온 세상을 통치하시는 분")
assert record._original(changed_lines, [1, 2], truths, "truth") == "\n".join(truths)

# 맞춤법과 띄어쓰기만 바로잡은 글은 받아들인다. 낱말, 어미, 순서를 바꾸거나 보탠 글은 버린다
typo = "모든 관게의 주인은 그리스도 시다"
assert record._only_spelling_fixed("모든 관계의 주인은 그리스도시다.", typo)
for changed in ["모든 관계의 중심은 그리스도시다.", "모든 관계의 주인은 그리스도이십니다.",
                "그리스도는 모든 관계의 주인이시다.", "모든 관계의 주인은 그리스도시며 우리는 그분을 섬긴다."]:
    assert not record._only_spelling_fixed(changed, typo), changed

# 모양이 틀린 답은 한 번 더 요청한다. 두 번 다 틀리면 오류로 알린다
record_answers[:] = ["정리했습니다: {", "```json\n" + good() + "\n```"]
assert client.post(f"{API}/record", json={"session_id": sid}).status_code == 200
record_answers[:] = [good(truth_from=[99]), good(observation="")]
failed = client.post(f"{API}/record", json={"session_id": sid})
assert failed.status_code == 502 and "정리하지 못했습니다" in failed.json()["error"]

# AI에게 보낸 대화에는 묵상자의 글에 번호가 붙고, 시작 신호와 본문 표시는 빠진다
text, originals = record._transcript(routes.SESSIONS[sid]["messages"])
assert originals == USER and text.startswith("[인도자]\n기도로 묵상을 시작하겠습니다.")
assert "[묵상자 5]\n" + TRUTH in text and "[[" not in text and "시작했습니다" not in text

# 단락을 나눈 책: AI에게 묻지 않고 다음 절이 든 단락의 끝까지 (bible/paragraphs.json)
seen_before = len(suggest_seen)
assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 6}).json() == {"book": "골로새서", "chapter": 4, "end": 9}
assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 3, "verse": 17}).json()["end"] == 1      # 3:18-4:1
assert len(suggest_seen) == seen_before
assert client.get(f"{API}/paragraphs", params={"book": "골"}).json()["paragraphs"][0]["ref"] == "골로새서 1:1-2"
assert client.get(f"{API}/books").json()["books"][50] == {"name": "골로새서", "testament": "신약", "paragraphs": True,
                                                         "last_chapter": 4, "last_verse": 18}

# 단락이 없을 때 (자료에 문제가 있는 책): 이어지는 본문을 AI에게 보여 주고, 그 안의 절이면 받아들인다. 절 수 제한은 없다
real_of_book = routes.PARAGRAPHS.of_book
routes.PARAGRAPHS.of_book = lambda bible, name: None
suggest_answers[:] = ["4:9"]
got = client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 6}).json()
assert got == {"book": "골로새서", "chapter": 4, "end": 9}
assert suggest_seen[-1].startswith("4:7 시험 본문 4:7") and "4:18 시험 본문 4:18" in suggest_seen[-1]
suggest_answers[:] = ["이 단락은 3:19에서 끝납니다."]          # 묶인 단위(18-19) 안이면 그 단위의 끝으로
assert client.get(f"{API}/suggest", params={"book": "골", "chapter": 3, "verse": 17}).json()["end"] == 19
suggest_answers[:] = ["4:17"]                                    # 11번째 절도 단락의 끝이면 받아들인다
assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 6}).json()["end"] == 17
for wrong in ["5:1", "모르겠습니다"]:                            # 없는 절이면 제안하지 않는다
    suggest_answers[:] = [wrong]
    assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 6}).json()["end"] is None
def no_suggest(system, messages):
    raise ai_client.AIError("제안 실패")
ai_client.reply = no_suggest                                      # AI가 답하지 못해도 오류가 아니다
assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 6}).json()["end"] is None
ai_client.reply = fake
assert client.get(f"{API}/suggest", params={"book": "골로새서", "chapter": 4, "verse": 18}).json()["end"] is None   # 책의 끝
assert client.get(f"{API}/following", params={"book": "골로새서", "chapter": 4, "verse": 18}).json()["finished"] is True
assert client.get(f"{API}/following", params={"book": "없는책"}).status_code == 400
routes.PARAGRAPHS.of_book = real_of_book

# 이어서 하기: 기기에 보관해 둔 대화로 새 세션을 열면, 인도자가 그 대화를 모두 받아 이어 간다
saved = [{"role": "assistant", "content": GUIDE[0]}, {"role": "user", "content": PRAYER},
         {"role": "assistant", "content": GUIDE[1]}, {"role": "user", "content": "다 읽었습니다."},
         {"role": "assistant", "content": GUIDE[2]}]
back = client.post(f"{API}/resume", json={"ref": "골로새서 3:18-4:1", "messages": saved}).json()
assert back["passage"] == "골로새서 3:18-4:1" and back["session_id"] != sid and back["verses"]
seen = []
def spy(system, messages):
    seen.append([m["content"] for m in messages]); return "아침에 본문을 읽으셨지요. 이어서 볼게요."
ai_client.reply = spy
welcome = client.post(f"{API}/chat", json={"session_id": back["session_id"], "message": None, "resume": True}).json()
assert welcome["reply"].startswith("아침에") and welcome["completed"] is False
assert seen[-1][1] == GUIDE[0] and seen[-1][2] == PRAYER and "돌아왔습니다" in seen[-1][-1]
ai_client.reply = fake
# 돌아온 자리의 신호는 묵상자의 글로 세지 않는다. 한 번 더 멈췄다 돌아와도 된다
text, originals = record._transcript(routes.SESSIONS[back["session_id"]]["messages"])
assert originals == [PRAYER, "다 읽었습니다."] and "돌아왔습니다" not in text
again = saved + [{"role": "user", "hidden": "resume"}, {"role": "assistant", "content": welcome["reply"]}]
assert client.post(f"{API}/resume", json={"ref": "골로새서 3:18-4:1", "messages": again}).status_code == 200
# 연결이 끊겨 같은 글이 두 번 와도 대화가 두 번 쌓이지 않는다. 이미 받은 답을 그대로 돌려준다
twice = client.post(f"{API}/start", json={"ref": "골 4:2-6"}).json()["session_id"]
calls = []
def counting(system, messages):
    calls.append(1); return f"답 {len(messages)}"
ai_client.reply = counting
for _ in range(2):      # 첫 말: AI를 부르지 않는다
    assert client.post(f"{API}/chat", json={"session_id": twice, "message": None, "expect": 0}).json()["reply"] == started["opening"]
for _ in range(2):      # 묵상자의 글
    assert client.post(f"{API}/chat", json={"session_id": twice, "message": "기도합니다.", "expect": 2}).json()["reply"] == "답 3"
assert len(calls) == 1 and len(routes.SESSIONS[twice]["messages"]) == 4
assert client.post(f"{API}/chat", json={"session_id": twice, "message": "기도합니다.", "expect": 4}).json()["reply"] == "답 5"   # 같은 말을 정말 한 번 더 쓴 것은 새 글이다
ai_client.reply = fake

# 순서가 어긋났거나 묵상자의 글로 끝나는 대화는 받지 않는다
for broken_saved in [[], saved[:2], saved[1:], [saved[0], saved[0]]]:
    assert client.post(f"{API}/resume", json={"ref": "골로새서 3:18-4:1", "messages": broken_saved}).status_code == 400
assert client.post(f"{API}/resume", json={"ref": "골로새서 9:1", "messages": saved}).status_code == 400

# 두 사람의 묵상은 섞이지 않는다
assert len(routes.SESSIONS[sid]["messages"]) == 14 and len(routes.SESSIONS[other]["messages"]) == 16
assert client.post(f"{API}/chat", json={"session_id": "없는것", "message": "a"}).status_code == 404

print("모든 검사 통과")
