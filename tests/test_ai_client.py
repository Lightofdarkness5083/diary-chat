"""AI 호출 검사: 일마다 맞는 모델을 쓰는가, 묵상 인도에만 1시간 캐시를 거는가.
실행: .venv/bin/python -m tests.test_ai_client     (AI를 실제로 부르지 않는다)"""
import contextlib
import importlib
import io
import os
import sys
import types

from meditation import ai_client

for key in [k for k in os.environ if k.startswith("AI_MODEL") or k == "AI_SMALL_MODEL"]:
    del os.environ[key]

# 1) 기본: 마음과 말이 중요한 일은 Sonnet, 짧고 정답이 분명한 일은 Haiku
for job in ("guide", "chat"):
    assert ai_client.model_for(job) == "claude-sonnet-5-5", job
for job in ("finish", "respell", "record", "suggest"):
    assert ai_client.model_for(job) == "claude-haiku-5-5", job

# 2) 환경변수로 바꾼다: 큰/작은 모델 전체, 그리고 한 가지 일만
os.environ["AI_MODEL"] = "big-x"
os.environ["AI_SMALL_MODEL"] = "small-x"
assert ai_client.model_for("guide") == "big-x" and ai_client.model_for("finish") == "small-x"
os.environ["AI_MODEL_RECORD"] = "claude-sonnet-5-5"           # 기록 정리만 Sonnet으로 되돌리기
assert ai_client.model_for("record") == "claude-sonnet-5-5" and ai_client.model_for("respell") == "small-x"
for key in ("AI_MODEL", "AI_SMALL_MODEL", "AI_MODEL_RECORD"):
    del os.environ[key]

# 3) 실제로 보내는 요청: 모델, 캐시 표시, 서버 기록 한 줄
calls = []


def answer():
    usage = types.SimpleNamespace(input_tokens=40, cache_read_input_tokens=3000, cache_creation_input_tokens=0, output_tokens=120)
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="답")], stop_reason="end_turn", usage=usage)


class FakeClient:
    def __init__(self, api_key):
        self.messages = self

    def create(self, **request):
        calls.append(request)
        return answer()


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=FakeClient, APIError=RuntimeError)
real = importlib.reload(ai_client)
os.environ["ANTHROPIC_API_KEY"] = "test"
talk = [{"role": "user", "content": "주님, 마음을 엽니다."}]

printed = io.StringIO()
with contextlib.redirect_stdout(printed):
    assert real.reply("지시문", talk, job="guide") == "답"
guide = calls[-1]
assert guide["model"] == "claude-sonnet-5-5"
assert guide["cache_control"] == {"type": "ephemeral", "ttl": "1h"}      # 묵상 한 편 동안 남는 캐시
assert guide["messages"] is talk and talk == [{"role": "user", "content": "주님, 마음을 엽니다."}]   # 대화 기록은 바꾸지 않는다
line = printed.getvalue()
assert "guide" in line and "claude-sonnet-5-5" in line and "input=40" in line and "cache_read=3000" in line and "output=120" in line
assert "마음을 엽니다" not in line                                         # 묵상 내용은 남기지 않는다

for job in ("finish", "respell", "record", "suggest"):
    with contextlib.redirect_stdout(io.StringIO()):
        real.reply("지시문", talk, job=job)
    assert calls[-1]["model"] == "claude-haiku-5-5" and "cache_control" not in calls[-1], job

with contextlib.redirect_stdout(io.StringIO()):
    real.reply_with_tools("비서", talk, [], lambda n, v: "")
assert calls[-1]["model"] == "claude-sonnet-5-5" and "cache_control" not in calls[-1]

del sys.modules["anthropic"], os.environ["ANTHROPIC_API_KEY"]
importlib.reload(ai_client)
print("AI 호출 검사 통과")
