"""묵상 부분의 AI API 호출은 이 파일에서만 한다.

묵상 인도 모델을 바꾸려면 이 파일만 고치면 된다.
받는 것: 시스템 프롬프트와 지금까지의 대화 기록
돌려주는 것: 인도자의 다음 말 (글자 그대로)

max_tokens에 대하여: 이 모델은 답하기 전에 생각하는 기능이 기본으로 켜져 있고,
생각에 쓴 분량도 max_tokens에 함께 계산된다. 값이 작으면 답이 비거나 중간에 끊긴다.
"""
import os

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_MAX_TOKENS = 8000


class AIError(Exception):
    """AI의 답을 받지 못했을 때. message는 화면에 그대로 보여 줄 수 있다."""


def reply(system, messages):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIError("ANTHROPIC_API_KEY가 없습니다. .env 파일에 API 키를 적어 주세요.")
    try:
        import anthropic  # 여기서 불러와야 키 없이도 본문 조회를 확인할 수 있다
    except ImportError:
        raise AIError("anthropic 패키지가 없습니다. sh setup.sh 를 실행해 주세요.")

    client = anthropic.Anthropic(api_key=api_key)
    for _ in range(2):  # 답에 글이 없거나 끊겼으면 같은 요청을 한 번 더 보낸다
        try:
            response = client.messages.create(
                model=os.environ.get("AI_MODEL", DEFAULT_MODEL),
                max_tokens=int(os.environ.get("AI_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
                system=system,
                messages=messages,
            )
        except anthropic.APIError as error:
            raise AIError(f"AI API 오류: {error}")

        block_types = ", ".join(block.type for block in response.content) or "없음"
        # 서버 터미널에 한 줄을 남긴다. 묵상 내용은 남기지 않는다.
        print(
            f"AI 응답: stop_reason={response.stop_reason}, "
            f"output_tokens={response.usage.output_tokens}, content 블록={block_types}",
            flush=True,
        )

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if text and response.stop_reason == "end_turn":
            return text

    if text:
        raise AIError(f"AI의 답이 중간에 끊겼습니다. (stop_reason: {response.stop_reason})")
    raise AIError(
        f"AI가 빈 답을 보냈습니다. (stop_reason: {response.stop_reason}, content 블록: {block_types})"
    )


def reply_with_tools(system, messages, tools, run_tool, max_rounds=6):
    """도구를 쓰는 대화. AI가 도구를 부르면 run_tool(이름, 값)로 실행해 결과를 돌려주고, 글로 된 답이 나올 때까지 잇는다.
    받는 것: 시스템 프롬프트, 대화 기록, 도구 설명, 도구를 실행하는 함수.  돌려주는 것: 마지막 답 (글자 그대로)"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIError("ANTHROPIC_API_KEY가 없습니다. .env 파일에 API 키를 적어 주세요.")
    try:
        import anthropic
    except ImportError:
        raise AIError("anthropic 패키지가 없습니다. sh setup.sh 를 실행해 주세요.")

    client = anthropic.Anthropic(api_key=api_key)
    conversation = list(messages)
    for _ in range(max_rounds):
        try:
            response = client.messages.create(
                model=os.environ.get("AI_MODEL", DEFAULT_MODEL),
                max_tokens=int(os.environ.get("AI_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
                system=system,
                messages=conversation,
                tools=tools,
            )
        except anthropic.APIError as error:
            raise AIError(f"AI API 오류: {error}")

        block_types = ", ".join(block.type for block in response.content) or "없음"
        print(f"AI 응답(비서): stop_reason={response.stop_reason}, "
              f"output_tokens={response.usage.output_tokens}, content 블록={block_types}", flush=True)

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
