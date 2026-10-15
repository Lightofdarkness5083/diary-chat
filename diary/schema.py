"""묵상 기록의 모양. 저장하기 전에 여기서 검사한다. 모양이 틀린 것은 저장하지 않는다."""
import re

NUMBER_FIELDS = ["chapter_start", "verse_start", "chapter_end", "verse_end"]
TEXT_FIELDS = ["book", "passage", "title", "prayer", "observation", "background", "interpretation",
               "truth", "applied_truth", "application", "closing_prayer"]
REQUIRED_TEXT = ["book", "passage"]          # 비어 있으면 안 되는 글
FIELDS = ["date", "meditation_time"] + NUMBER_FIELDS + TEXT_FIELDS     # 17개
MAX_TEXT = 20000

RECORD_ID = re.compile(r"[a-z0-9]{8,40}")
DATE = re.compile(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class RecordError(ValueError):
    """기록의 모양이 약속과 다르다."""


def clean_record(record):
    """기록을 검사해, 약속한 17개 항목만 담은 새 사전을 돌려준다. 틀리면 RecordError."""
    if not isinstance(record, dict):
        raise RecordError("기록이 사전 모양이 아닙니다.")
    unknown = sorted(set(record) - set(FIELDS))
    missing = [f for f in FIELDS if f not in record]
    if unknown:
        raise RecordError(f"약속에 없는 항목이 있습니다: {', '.join(unknown)}")
    if missing:
        raise RecordError(f"빠진 항목이 있습니다: {', '.join(missing)}")
    if not isinstance(record["date"], str) or not DATE.fullmatch(record["date"]):
        raise RecordError("date는 YYYY-MM-DD 모양이어야 합니다.")
    if not isinstance(record["meditation_time"], str) or not TIME.fullmatch(record["meditation_time"]):
        raise RecordError("meditation_time은 HH:MM 모양이어야 합니다.")
    for field in NUMBER_FIELDS:
        value = record[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RecordError(f"{field}는 1 이상의 정수여야 합니다.")
    for field in TEXT_FIELDS:
        value = record[field]
        if not isinstance(value, str):
            raise RecordError(f"{field}는 글이어야 합니다.")
        if len(value) > MAX_TEXT:
            raise RecordError(f"{field}가 너무 깁니다.")
    for field in REQUIRED_TEXT:
        if not record[field].strip():
            raise RecordError(f"{field}가 비어 있습니다.")
    return {field: record[field] for field in FIELDS}


def check_id(record_id):
    """새로 만드는 기록의 번호."""
    if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
        raise RecordError("기록 번호의 모양이 틀립니다.")
    return record_id


EXISTING_ID = re.compile(r"[A-Za-z0-9_-]{8,100}")


def check_existing_id(record_id):
    """이미 있는 기록의 번호. 예전에 저장된 문서의 번호는 모양이 다르다."""
    if not isinstance(record_id, str) or not EXISTING_ID.fullmatch(record_id):
        raise RecordError("기록 번호의 모양이 틀립니다.")
    return record_id
