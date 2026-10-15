"""성경 DB (공통). 묵상 부분과 Diary 부분이 함께 읽는다. 읽기 전용."""
from .lookup import (KO, MAX_VERSES, Bible, BibleSetupError, PassageError,  # noqa: F401
                     format_reference, parse_reference)
