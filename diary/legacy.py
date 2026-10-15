"""예전에 저장된 묵상을 지금의 구조에 맞춘다.

예전 문서의 항목(11개): date, meditation_time, passage, prayer, observation, background,
interpretation, truth, application, truthSummary, uid

지금의 구조에 더해야 하는 것:
  book, chapter_start, verse_start, chapter_end, verse_end   passage의 글에서 읽어 낸다
  title, closing_prayer                                       빈 글
  applied_truth                                               예전 truthSummary의 내용 (적용 진리가 거기에 들어 있다)
  deleted                                                     False

이미 있는 항목은 건드리지 않는다. 더하기만 한다.
"""
from bible.lookup import KO, PassageError, parse_reference

import re

from .schema import NUMBER_FIELDS, TEXT_FIELDS


_MORE = re.compile(r"^\s*(?:(\d+)\s*[:장]\s*)?(\d+)\s*절?(?:\s*[-~]\s*(?:(\d+)\s*[:장]\s*)?(\d+)\s*절?)?\s*$")


def position(passage):
    """본문의 글("골로새서 3:14-4:1")에서 책, 장, 절을 읽어 낸다. 읽지 못하면 None.
    범위가 둘 이상이면("민수기 1:1-4, 1:44-46") 첫 범위의 시작부터 마지막 범위의 끝까지로 적는다.
    passage의 글은 그대로 두므로 실제로 묵상한 범위는 거기에 남는다."""
    parts = (passage or "").split(",")
    try:
        book, c1, v1, c2, v2 = parse_reference(parts[0])
    except PassageError:
        return None
    for part in parts[1:]:
        m = _MORE.match(re.sub(r"[–—−]", "-", part))
        if not m:
            return None
        chapter = int(m[1]) if m[1] else c2
        start = (chapter, int(m[2]))
        end = (int(m[3]) if m[3] else chapter, int(m[4])) if m[4] else start
        if start <= (c2, v2) or end < start:        # 뒤의 범위는 앞의 범위보다 뒤에 있어야 한다
            return None
        c2, v2 = end
    return {"book": KO[book], "chapter_start": c1, "verse_start": v1, "chapter_end": c2, "verse_end": v2}


def missing_fields(doc):
    """이 문서에 더해야 할 항목과 값. 더할 것이 없으면 빈 사전.
    본문을 읽어 내지 못하면 None을 돌려준다 (사람이 정해 주어야 한다)."""
    add = {}
    if any(field not in doc for field in ["book"] + NUMBER_FIELDS):
        found = position(doc.get("passage"))
        if found is None:
            return None
        add.update({field: value for field, value in found.items() if field not in doc})
    for field in ("title", "closing_prayer"):
        if field not in doc:
            add[field] = ""
    if "applied_truth" not in doc:
        summary = doc.get("truthSummary")
        add["applied_truth"] = summary if isinstance(summary, str) else ""
    if "deleted" not in doc:
        add["deleted"] = False
    return add


def as_current(doc):
    """읽을 때의 안전망: 아직 맞추지 않은 예전 문서도 지금의 모양으로 내어 준다. 문서는 바꾸지 않는다."""
    add = missing_fields(doc)
    merged = {**doc, **(add or {})}
    for field in TEXT_FIELDS + ["date", "meditation_time"]:
        if not isinstance(merged.get(field), str):
            merged[field] = "" if field != "applied_truth" else (doc.get("truthSummary") or "")
    for field in NUMBER_FIELDS:
        if not isinstance(merged.get(field), int) or isinstance(merged.get(field), bool):
            merged[field] = 0            # 본문을 읽어 내지 못한 묵상
    return merged
