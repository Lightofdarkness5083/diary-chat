"""묵상 완료 기록 만들기.

끝난 묵상의 대화를 AI에게 한 번 더 보내 글 항목을 정리하게 하고,
본문 위치 여섯 항목은 묵상자가 처음 정한 본문에서 그대로 가져온다.

원문 보존: prayer(시작 기도), truth(진리), applied_truth(적용 진리), closing_prayer(마침기도)는 묵상자의 글이다. AI는 맞춤법과 띄어쓰기만
바로잡을 수 있다. 이 코드가 AI의 글을 묵상자의 원문과 견주어, 낱말이 달라졌으면 버리고
원문을 쓴다.

만들지 않는 것: date, meditation_time, uid. 이 값들은 저장하는 쪽이 넣는다.
"""
import json
import re
from difflib import SequenceMatcher

from settings import read_prompt

from . import ai_client
from .signals import SIGNALS

POSITION_FIELDS = ["book", "chapter_start", "verse_start", "chapter_end", "verse_end", "passage"]
TEXT_FIELDS = ["title", "prayer", "observation", "background", "interpretation", "truth",
               "applied_truth", "application", "closing_prayer"]
OPTIONAL_FIELDS = ("closing_prayer",)       # 마침기도를 쓰지 않고 마친 묵상에서는 빈 글
RECORD_FIELDS = POSITION_FIELDS + TEXT_FIELDS
VERBATIM_FIELDS = ("prayer", "truth", "closing_prayer")   # 묵상자가 직접 쓴 글
MARKER = re.compile(r"\[\[[^\]]*\]\]")
LINE_MARK = re.compile(r"^(?:[-•]|\d+[.)])\s+")   # 줄 앞의 "- "와 "1. "


class RecordError(Exception):
    """기록을 만들지 못했을 때. message는 화면에 그대로 보여 줄 수 있다."""


def _transcript(messages):
    """대화 기록을 글로 옮긴다. 묵상자의 글에 번호를 붙인다. 앱이 넣은 신호는 뺀다."""
    lines, originals = [], []
    for message in messages:
        if message["content"] in SIGNALS:      # 앱이 넣은 신호는 묵상자의 글이 아니다
            continue
        if message["role"] == "user":
            originals.append(message["content"])
            lines.append(f"[묵상자 {len(originals)}]\n{message['content']}")
        else:
            lines.append(f"[인도자]\n{MARKER.sub('', message['content']).strip()}")
    return "\n\n".join(lines), originals


def _jamo(text):
    """견주기 위해 글을 자모로 푼다. 띄어쓰기와 문장 부호는 뺀다.
    오타는 대개 한 글자의 자모 하나가 다른 것이라, 자모로 견주면 오타와 고쳐 쓰기가 갈린다."""
    out = []
    for ch in re.sub(r"[\s.,!?~\"'“”‘’…·]", "", text):
        code = ord(ch) - 0xAC00
        if 0 <= code <= 11171:
            out += [f"L{code // 588}", f"V{code % 588 // 28}"] + ([f"T{code % 28}"] if code % 28 else [])
        else:
            out.append(ch)
    return out


def _only_spelling_fixed(quote, original):
    """quote가 original(또는 그 일부)에서 맞춤법과 띄어쓰기만 고친 글인지 본다.
    자모의 9할 이상이 원문에 같은 순서로, 한곳에 모여 있어야 한다.
    어미를 바꾸거나, 말을 보태거나, 순서를 바꾼 글은 걸러진다. 짧은 낱말 하나를 비슷한 말로
    바꾼 것까지는 가려내지 못하므로, 마지막 확인은 묵상자가 저장 전에 직접 한다."""
    q, o = _jamo(quote), _jamo(original)
    if not q:
        return False
    blocks = [b for b in SequenceMatcher(None, q, o, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return False
    matched = sum(b.size for b in blocks)
    span = blocks[-1].b + blocks[-1].size - blocks[0].b      # 원문에서 차지하는 길이
    return matched >= 0.9 * len(q) and span <= 1.15 * len(q) + 3


def _original(text, indexes, originals, field):
    """묵상자의 글을 꺼낸다. indexes는 묵상자의 글 번호 하나 또는 여럿.
    AI가 옮긴 글의 모든 줄이 그 원문에서 맞춤법과 띄어쓰기만 고친 것이면 그 글을 쓰고,
    한 줄이라도 낱말이 달라졌으면 버리고 그 번호의 원문 전체를 쓴다. 이때 원문의 오타는 따로 바로잡는다."""
    numbers = indexes if isinstance(indexes, list) else [indexes]
    if not numbers or any(not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(originals)
                          for n in numbers):
        raise ValueError(f"{field}_from이 묵상자의 글 번호가 아닙니다: {indexes!r}")
    sources = [originals[n - 1] for n in numbers]
    lines = [line.strip() for line in text.splitlines() if line.strip()] if isinstance(text, str) else []
    faithful = lines and all(
        any(_only_spelling_fixed(LINE_MARK.sub("", line), source) for source in sources) for line in lines)
    if faithful:
        return "\n".join(lines)
    return "\n".join(_respell(source.strip()) for source in sources)


RESPELL_PROMPT = ("아래 글의 맞춤법과 띄어쓰기만 바로잡아 그대로 돌려줍니다. "
                  "낱말을 바꾸거나, 문장을 다듬거나, 내용을 더하거나 빼지 않습니다. 설명 없이 고친 글만 답합니다.")


def _respell(text):
    """묵상자의 원문에서 오타만 바로잡는다. 바로잡은 글이 원문과 낱말이 다르거나 줄었으면 원문을 그대로 쓴다."""
    try:
        fixed = ai_client.reply(RESPELL_PROMPT, [{"role": "user", "content": text}]).strip()
    except ai_client.AIError:
        return text
    whole = len(_jamo(fixed)) >= 0.9 * len(_jamo(text))
    return fixed if whole and _only_spelling_fixed(fixed, text) else text


def _applied_truth(data, originals):
    """적용 진리: 찾은 진리 가운데 묵상자가 삶에 적용하기로 고른 하나. 묵상자의 글이어야 한다.
    묵상자가 번호로만 골랐을 수 있으므로, 진리를 쓴 글과 고른 글을 함께 원문으로 본다.
    AI가 옮긴 글이 그 원문에 없으면 버리고, 묵상자가 쓴 진리를 그대로 둔다."""
    def numbers(value):
        value = value if isinstance(value, list) else [value]
        return [n for n in value if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(originals)]
    sources = [originals[n - 1] for n in dict.fromkeys(numbers(data.get("truth_from")) + numbers(data.get("applied_truth_from")))]
    text = data.get("applied_truth")
    lines = [LINE_MARK.sub("", line.strip()) for line in text.splitlines() if line.strip()] if isinstance(text, str) else []
    faithful = lines and all(any(_only_spelling_fixed(line, source) for source in sources) for line in lines)
    if faithful:
        return "\n".join(lines)
    truths = [LINE_MARK.sub("", line) for line in data["truth"].splitlines() if line.strip()]
    return truths[0] if len(truths) == 1 else data["truth"]


def _parse(answer, originals):
    cleaned = re.sub(r"^```(?:json)?|```$", "", answer.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아닙니다")
    for field in VERBATIM_FIELDS:
        if field in OPTIONAL_FIELDS and data.get(f"{field}_from") in (None, [], ""):
            data[field] = ""
            continue
        data[field] = _original(data.get(field), data.get(f"{field}_from"), originals, field)
    data["applied_truth"] = _applied_truth(data, originals)
    texts = {}
    for field in TEXT_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or (not value.strip() and field not in OPTIONAL_FIELDS):
            raise ValueError(f"{field} 항목이 비어 있습니다")
        texts[field] = value.strip()
    return texts


QUOTED = re.compile(r'["“”\'‘’]([^"“”\'‘’\n]{2,60})["“”\'‘’]')
OWN_WORDS_FIELDS = ("observation", "interpretation", "application")   # 묵상자의 말을 살려 정리하는 항목


def _plain(text):
    """띄어쓰기와 문장 부호를 뺀 글자."""
    return re.sub(r"[\s.,!?~…·\-]", "", text)


def _strange_quotes(texts, originals):
    """정리한 글의 따옴표 안에 든 표현 가운데, 묵상자가 쓴 글에 그대로 없는 것을 찾는다.
    예: 묵상자는 "난 것이 아님"이라고 썼는데 정리에는 "난 것이 아니"라고 적힌 경우."""
    said = _plain(" ".join(originals))
    strange = []
    for field in OWN_WORDS_FIELDS:
        for quote in QUOTED.findall(texts[field]):
            if _plain(quote) and _plain(quote) not in said and quote not in strange:
                strange.append(quote)
    return strange


def build_record(session):
    """session: {"passage": 본문 조회 결과, "messages": 대화 기록}  ->  묵상 완료 기록"""
    transcript, originals = _transcript(session["messages"])
    if not originals:
        raise RecordError("묵상자가 쓴 글이 없어 기록을 만들 수 없습니다.")
    prompt = read_prompt("meditation_record.md")
    asking = f"<대화>\n{transcript}\n</대화>"

    texts, problem, note = None, None, ""
    for _ in range(2):  # 모양이 맞지 않거나 묵상자의 표현이 바뀌었으면 한 번 더 요청한다
        try:
            made = _parse(ai_client.reply(prompt, [{"role": "user", "content": asking + note}]), originals)
        except ai_client.AIError as error:
            if texts is not None:
                break               # 다시 묻다가 실패하면 처음 정리한 것을 쓴다
            raise RecordError(str(error))
        except (ValueError, TypeError) as error:
            problem = error
            continue
        strange = _strange_quotes(made, originals)
        if texts is None or not strange:
            texts = made
        if not strange:
            break
        note = ("\n\n앞서 정리한 글에서 아래 따옴표 안의 표현은 묵상자가 쓴 글에 그대로 없습니다. "
                "묵상자가 쓴 표현 그대로 다시 정리해 주세요. 본문의 표현에 맞추어 바꾸지 않습니다.\n"
                + "\n".join(f"- {quote}" for quote in strange))
    if texts is None:
        raise RecordError(f"묵상 기록을 정리하지 못했습니다. ({problem})")

    record = {field: session["passage"][field] for field in POSITION_FIELDS}
    record.update(texts)
    return record
