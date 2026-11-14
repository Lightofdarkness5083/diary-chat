"""AI API 호출은 이 파일에서만 한다.

받는 것: 시스템 프롬프트, 지금까지의 대화 기록, 무슨 일인지(job)
돌려주는 것: AI의 답 (글자 그대로)

일에 따라 모델을 나눈다 (job → 모델):
  큰 모델 (Sonnet): 마음과 말이 중요한 일
    guide    묵상 인도자의 말
    chat     돌아보기 비서
  작은 모델 (Haiku): 짧고 정답이 분명한 일
    finish   묵상이 끝났는지 확인 ("끝남"/"아직")
    respell  맞춤법만 바로잡기 (낱말이 바뀌면 record.py가 원문을 쓴다)
    record   묵상 기록 정리 (묵상자의 말은 record.py가 원문에서 가져온다)
    suggest  오늘 단락의 끝 절 제안 (단락 나눔표에 없을 때만)

모델은 환경변수로 바꾼다. 코드는 고치지 않는다.
  AI_MODEL             큰 모델 (비우면 claude-sonnet-5-5)
  AI_SMALL_MODEL       작은 모델 (비우면 claude-haiku-5-5)
  AI_MODEL_<JOB>       그 일 하나만 다른 모델로. 예: AI_MODEL_RECORD=claude-sonnet-5-5

캐시: 묵상 인도(guide)는 매번 지시문 + 본문 + 앞의 대화를 다시 보낸다. 1시간 캐시를 걸어
앞부분을 다시 읽을 때 값이 싸지게 한다. 묵상자가 천천히 생각하며 써도 묵상 한 편 동안 캐시가 남는다.

max_tokens에 대하여: 모델은 답하기 전에 생각하는 기능이 기본으로 켜져 있고,
생각에 쓴 분량도 max_tokens에 함께 계산된다. 값이 작으면 답이 비거나 중간에 끊긴다.
"""
import os

BIG_MODEL = "claude-sonnet-5-5"
SMALL_MODEL = "claude-haiku-5-5"
SMALL_JOBS = {"finish", "respell", "record", "suggest"}
CACHED_JOBS = {"guide"}
CACHE = {"type": "ephemeral", "ttl": "1h"}
DEFAULT_MAX_TOKENS = 8000


class AIError(Exception):
    """AI의 답을 받지 못했을 때. message는 화면에 그대로 보여 줄 수 있다."""


def model_for(job):
    """이 일을 맡을 모델. 그 일만의 설정 → 작은/큰 모델 설정 → 기본값 순서로 찾는다."""
    own = os.environ.get(f"AI_MODEL_{job.upper()}")
    if own:
        return own
    if job in SMALL_JOBS:
        return os.environ.get("AI_SMALL_MODEL") or SMALL_MODEL
    return os.environ.get("AI_MODEL") or BIG_MODEL


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIError("ANTHROPIC_API_KEY가 없습니다. .env 파일에 API 키를 적어 주세요.")
    try:
        import anthropic  # 여기서 불러와야 키 없이도 본문 조회를 확인할 수 있다
    except ImportError:
        raise AIError("anthropic 패키지가 없습니다. sh setup.sh 를 실행해 주세요.")
    return anthropic, anthropic.Anthropic(api_key=api_key)


def _request(job, system, messages, **more):
    request = dict(model=model_for(job), max_tokens=int(os.environ.get("AI_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
                   system=system, messages=messages, **more)
    if job in CACHED_JOBS:
        request["cache_control"] = CACHE      # 마지막 글까지를 캐시에 둔다. 대화가 길어지면 표시가 저절로 뒤로 옮겨 간다
    return request


def _log(job, request, response):
    """서버 터미널에 한 줄을 남긴다. 묵상 내용은 남기지 않는다. 비용을 셀 수 있게 토큰 수를 남긴다."""
    usage = response.usage
    blocks = ", ".join(block.type for block in response.content) or "없음"
    print(f"AI 응답({job}, {request['model']}): stop_reason={response.stop_reason}, "
          f"input={getattr(usage, 'input_tokens', '?')}, "
          f"cache_read={getattr(usage, 'cache_read_input_tokens', 0) or 0}, "
          f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0) or 0}, "
          f"output={usage.output_tokens}, content 블록={blocks}", flush=True)
    return blocks


def reply(system, messages, job="guide"):
    anthropic, client = _client()
    for _ in range(2):  # 답에 글이 없거나 끊겼으면 같은 요청을 한 번 더 보낸다
        request = _request(job, system, messages)
        try:
            response = client.messages.create(**request)
        except anthropic.APIError as error:
            raise AIError(f"AI API 오류: {error}")
        block_types = _log(job, request, response)

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if text and response.stop_reason == "end_turn":
            return text

    if text:
        raise AIError(f"AI의 답이 중간에 끊겼습니다. (stop_reason: {response.stop_reason})")
    raise AIError(
        f"AI가 빈 답을 보냈습니다. (stop_reason: {response.stop_reason}, content 블록: {block_types})"
    )


def reply_with_tools(system, messages, tools, run_tool, max_rounds=6, job="chat"):
    """도구를 쓰는 대화. AI가 도구를 부르면 run_tool(이름, 값)로 실행해 결과를 돌려주고, 글로 된 답이 나올 때까지 잇는다.
    받는 것: 시스템 프롬프트, 대화 기록, 도구 설명, 도구를 실행하는 함수.  돌려주는 것: 마지막 답 (글자 그대로)"""
    anthropic, client = _client()
    conversation = list(messages)
    for _ in range(max_rounds):
        request = _request(job, system, conversation, tools=tools)
        try:
            response = client.messages.create(**request)
        except anthropic.APIError as error:
            raise AIError(f"AI API 오류: {error}")
        _log(job, request, response)

        if response.stop_reason == "tool_use":
            # AI가 낸 블록(생각 포함)을 그대로 돌려주고, 도구 결과를 붙여 다시 묻는다
            conversation.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(run_tool(block.name, block.input))})
            conversation.append({"role": "user", "content": results})
            continue

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if text and response.stop_reason == "end_turn":
            return text
        raise AIError(f"AI의 답을 끝까지 받지 못했습니다. (stop_reason: {response.stop_reason})")
    raise AIError("AI가 기록을 찾다가 답을 맺지 못했습니다. 물음을 조금 좁혀 다시 물어 주세요.")
