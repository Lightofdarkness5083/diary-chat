"""묵상 단락: 책마다 미리 나누어 검토한 단락 (bible/paragraphs.json).

단락이 있는 책은 "이어서 묵상"과 단락 목록이 이 나눔을 따른다. AI에게 묻지 않으므로 날마다 같다.
단락이 없는 책은 예전처럼 묵상자가 본문을 적거나, AI가 단락의 끝을 제안한다.
"""
import json
from pathlib import Path

from .lookup import KO, parse_reference

FILE = Path(__file__).with_name("paragraphs.json")
_cache = {}
problems = {}       # 검사를 통과하지 못한 책과 까닭


class ParagraphError(Exception):
    """단락 자료가 잘못되었다 (빈틈, 겹침, 장절 오류)."""


def _ref(book, c1, v1, c2, v2):
    return f"{book} {c1}:{v1}-{v2}" if c1 == c2 else f"{book} {c1}:{v1}-{c2}:{v2}"


def load(bible, path=FILE):
    """단락 자료를 읽고 성경 DB와 맞추어 검사한다. {책 이름: [단락, ...]}
    검사를 통과하지 못한 책은 빼고 problems에 적는다 (그 책은 단락 없이, 예전 방식으로 묵상한다)."""
    key = (path, id(bible))
    if key in _cache:
        return _cache[key]
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    books = {}
    for name, refs in raw.items():
        if name.startswith("_"):
            continue
        try:
            books[name] = _check(bible, name, refs)
        except Exception as e:           # 장절 오류, 빈틈, 겹침, DB에 없는 장
            problems[name] = str(e)
    _cache[key] = books
    return books



def _check(bible, name, refs):
    """한 책의 단락이 책의 처음부터 끝까지 빈틈과 겹침 없이 이어지는지 검사한다."""
    if name not in KO:
        raise ParagraphError(f"책 이름이 틀립니다: {name}")
    order = KO.index(name) + 1
    expect, items = (1, 1), []
    for text in refs:
        book, c1, v1, c2, v2 = parse_reference(f"{name} {text}")
        if (c1, v1) != expect:
            raise ParagraphError(f"{name} {text}: {expect[0]}:{expect[1]}에서 시작해야 합니다 (빈틈이나 겹침)")
        if v2 > bible.last_verse[(order, c2)]:
            raise ParagraphError(f"{name} {text}: {c2}장은 {bible.last_verse[(order, c2)]}절까지입니다")
        count = v2 - v1 + 1 if c1 == c2 else (bible.last_verse[(order, c1)] - v1 + 1) + v2 + \
            sum(bible.last_verse[(order, c)] for c in range(c1 + 1, c2))
        items.append({"ref": _ref(name, c1, v1, c2, v2), "chapter_start": c1, "verse_start": v1,
                      "chapter_end": c2, "verse_end": v2, "verses": count})
        expect = (c2, v2 + 1) if v2 < bible.last_verse[(order, c2)] else (c2 + 1, 1)
    if expect != (bible.last_chapter[order] + 1, 1):
        raise ParagraphError(f"{name}: 책의 끝까지 나누지 않았습니다 ({expect[0]}:{expect[1]}부터 없음)")
    return items


def of_book(bible, name):
    """그 책의 단락 목록. 단락이 없는 책이면 None."""
    return load(bible).get(name)


def containing(items, chapter, verse):
    """(chapter, verse)가 들어 있는 단락."""
    for item in items:
        if (item["chapter_start"], item["verse_start"]) <= (chapter, verse) <= (item["chapter_end"], item["verse_end"]):
            return item
    return None
