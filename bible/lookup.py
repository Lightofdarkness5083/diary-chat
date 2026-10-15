"""성경 본문 조회 (bible_clean.db, schema_version 1). 공통 부분: 읽기만 한다.

"골로새서 3:18-4:1" 같은 장절 범위를 받아 그 본문을 돌려준다.

bible.db의 구조 (대한성서공회 개역한글):
  verses   한 행이 한 단위. 대부분 한 절이고, 원문에서 묶인 절은 한 행이 여러 절을 덮는다
           (book_order, chapter, verse_start, verse_end, verse_label, unit_type, text)
  chapters 장마다 마지막 절 번호 (book_order, chapter, last_verse)
  metadata schema_version, expected_counts 등

원칙:
  - 묶인 단위는 쪼개지 않는다. 요청 범위가 걸치면 단위 전체를 돌려준다.
  - 본문 글자는 다듬지 않고 그대로 돌려준다.
  - 본문이 없으면 빈 채로 넘기지 않고 PassageError로 알린다.
"""
import os
import re
import sqlite3

SAFE_VERSES = 30   # 한 번에 묵상할 수 있는 가장 긴 범위. 터무니없이 긴 범위만 거른다
MAX_VERSES = SAFE_VERSES   # 예전 이름. 다른 곳에서 쓰지 않는다

KO = ["창세기", "출애굽기", "레위기", "민수기", "신명기", "여호수아", "사사기", "룻기",
      "사무엘상", "사무엘하", "열왕기상", "열왕기하", "역대상", "역대하", "에스라",
      "느헤미야", "에스더", "욥기", "시편", "잠언", "전도서", "아가", "이사야",
      "예레미야", "예레미야애가", "에스겔", "다니엘", "호세아", "요엘", "아모스",
      "오바댜", "요나", "미가", "나훔", "하박국", "스바냐", "학개", "스가랴", "말라기",
      "마태복음", "마가복음", "누가복음", "요한복음", "사도행전", "로마서",
      "고린도전서", "고린도후서", "갈라디아서", "에베소서", "빌립보서", "골로새서",
      "데살로니가전서", "데살로니가후서", "디모데전서", "디모데후서", "디도서",
      "빌레몬서", "히브리서", "야고보서", "베드로전서", "베드로후서", "요한일서",
      "요한이서", "요한삼서", "유다서", "요한계시록"]

AB = ["창", "출", "레", "민", "신", "수", "삿", "룻", "삼상", "삼하", "왕상", "왕하",
      "대상", "대하", "스", "느", "에", "욥", "시", "잠", "전", "아", "사", "렘", "애",
      "겔", "단", "호", "욜", "암", "옵", "욘", "미", "나", "합", "습", "학", "슥", "말",
      "마", "막", "눅", "요", "행", "롬", "고전", "고후", "갈", "엡", "빌", "골",
      "살전", "살후", "딤전", "딤후", "딛", "몬", "히", "약", "벧전", "벧후",
      "요일", "요이", "요삼", "유", "계"]

EN = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
      "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles",
      "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
      "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
      "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
      "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi", "Matthew",
      "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians",
      "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
      "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews",
      "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation"]

# 같은 책의 다른 표기
EXTRA = {"요한1서": 61, "요한2서": 62, "요한3서": 63, "계시록": 65, "애가": 24,
         "시편": 18, "psalm": 18, "songofsongs": 21, "여호수아서": 5, "룻": 7,
         "욥": 17, "디도": 55, "빌레몬": 56, "히브리": 57, "야고보": 58, "유다": 64}


def _norm(s):
    return re.sub(r"[\s.\-_]", "", str(s)).lower()


ALIASES = {}
for _i in range(66):
    for _name in (KO[_i], AB[_i], EN[_i]):
        ALIASES[_norm(_name)] = _i
for _name, _i in EXTRA.items():
    ALIASES.setdefault(_norm(_name), _i)
for _i in range(66):                      # "아모스서", "호세아서"처럼 끝에 '서'를 붙여 부르는 이름
    if KO[_i] in ("미가", "말라기") or not KO[_i].endswith(("서", "기", "가", "록", "복음", "편", "언", "전", "상", "하")):
        ALIASES.setdefault(_norm(KO[_i] + "서"), _i)

_REF = re.compile(
    r"^(?P<book>.+?)\s*(?P<c1>\d+)\s*[:장]\s*(?P<v1>\d+)\s*절?"
    r"(?:\s*[-~]\s*(?:(?P<c2>\d+)\s*[:장]\s*)?(?P<v2>\d+)\s*절?)?$"
)


class PassageError(Exception):
    """묵상자에게 그대로 보여 줄 수 있는 본문 오류."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class BibleSetupError(Exception):
    """bible.db를 열 수 없거나 구조가 다를 때."""


def _eun(word):
    """받침이 있으면 '은', 없으면 '는'."""
    code = ord(word[-1]) - 0xAC00
    return "은" if 0 <= code <= 11171 and code % 28 else "는"


def parse_reference(ref):
    """'골로새서 3:18-4:1' -> (책 번호 0~65, 3, 18, 4, 1)"""
    cleaned = re.sub(r"[–—−]", "-", (ref or "").strip())
    m = _REF.match(cleaned)
    if not m:
        raise PassageError("본문을 '골로새서 3:18-4:1'처럼 책 이름, 장:절-절 형식으로 적어 주세요.")
    book = ALIASES.get(_norm(m["book"]))
    if book is None:
        raise PassageError(f"책 이름을 알아보지 못했습니다: {m['book'].strip()}")
    c1, v1 = int(m["c1"]), int(m["v1"])
    c2 = int(m["c2"]) if m["c2"] else c1
    v2 = int(m["v2"]) if m["v2"] else v1
    if min(c1, v1, c2, v2) < 1 or (c2, v2) < (c1, v1):
        raise PassageError("절 범위의 끝이 시작보다 앞에 있습니다. 범위를 다시 확인해 주세요.")
    return book, c1, v1, c2, v2


def format_reference(book, c1, v1, c2, v2):
    if (c1, v1) == (c2, v2):
        return f"{KO[book]} {c1}:{v1}"
    if c1 == c2:
        return f"{KO[book]} {c1}:{v1}-{v2}"
    return f"{KO[book]} {c1}:{v1}-{c2}:{v2}"


TOO_LONG = f"한 번에 묵상할 본문은 {SAFE_VERSES}절 이내로 정해 주세요."


class Bible:
    def __init__(self, path=None):
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bible_clean.db")
        self.path = path or os.environ.get("BIBLE_DB") or default
        if not os.path.exists(self.path):
            raise BibleSetupError(
                f"성경 DB 파일을 찾지 못했습니다: {self.path}\n"
                "bible/ 폴더에 bible_clean.db를 두거나 .env의 BIBLE_DB에 경로를 적어 주세요."
            )
        con = self._connect()
        try:
            try:
                self.meta = dict(con.execute("SELECT key, value FROM metadata"))
            except sqlite3.Error as e:
                raise BibleSetupError(f"bible.db의 metadata 표를 읽지 못했습니다 ({e}): {self.path}")
            version = str(self.meta.get("schema_version"))
            if version != "1":
                raise BibleSetupError(
                    f"bible.db의 schema_version이 '{version}'입니다. "
                    f"이 코드는 schema_version 1만 읽을 수 있습니다: {self.path}")
            try:
                # {(책 순서, 장): 마지막 절}
                self.last_verse = {(b, c): last for b, c, last in con.execute(
                    "SELECT book_order, chapter, last_verse FROM chapters")}
                self.unit_count = con.execute("SELECT COUNT(*) FROM verses").fetchone()[0]
            except sqlite3.Error as e:
                raise BibleSetupError(f"bible.db의 표를 읽지 못했습니다 ({e}): {self.path}")
        finally:
            con.close()
        self.last_chapter = {}  # {책 순서: 마지막 장}
        for (b, c) in self.last_verse:
            self.last_chapter[b] = max(c, self.last_chapter.get(b, 0))

    def _connect(self):
        # 읽기 전용으로 연다. 이 앱은 성경 DB를 고치지 않는다.
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def describe(self):
        return {"schema_version": str(self.meta.get("schema_version")),
                "version": self.meta.get("version"),
                "publisher": self.meta.get("publisher"),
                "books": len(self.last_chapter), "chapters": len(self.last_verse),
                "units": self.unit_count}

    def units(self, book, chapter):
        """한 장의 단위 목록. book은 0~65."""
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT verse_start, verse_end, verse_label, text FROM verses "
                "WHERE book_order = ? AND chapter = ? ORDER BY verse_start",
                (book + 1, chapter)).fetchall()
        finally:
            con.close()
        return [{"chapter": chapter, "start": s, "end": e,
                 "label": label or (str(s) if s == e else f"{s}-{e}"), "text": text}
                for s, e, label, text in rows if text]

    def book_number(self, name):
        """책 이름(또는 약자)을 책 번호 0~65로 바꾼다. DB에 없는 책이면 PassageError."""
        book = ALIASES.get(_norm(name or ""))
        if book is None or book + 1 not in self.last_chapter:
            raise PassageError(f"책 이름을 알아보지 못했습니다: {name}")
        return book

    def following(self, name, chapter, verse, count=12):
        """그 책에서 (chapter, verse) 다음에 이어지는 본문을 돌려준다. 장을 넘어 이어진다.
        "이어서 묵상하기"에서 묵상자가 본문을 보고 마지막 절을 고르는 데 쓴다.
        처음부터 보려면 chapter=1, verse=0. 책이 끝났으면 verses가 비고 finished가 True."""
        book = self.book_number(name)
        order = book + 1
        units, covered = [], 0
        ch = max(chapter, 1)
        while ch <= self.last_chapter[order] and covered < count:
            for unit in self.units(book, ch):
                if covered >= count:
                    break
                if ch > chapter or unit["start"] > verse:      # 걸쳐 있던 묶인 단위는 이미 묵상한 것으로 본다
                    units.append(unit)
                    covered += unit["end"] - unit["start"] + 1
            ch += 1
        last = units[-1] if units else None
        last_chapter = self.last_chapter[order]
        ends_book = bool(last) and last["chapter"] == last_chapter and \
            last["end"] >= self.last_verse[(order, last_chapter)]
        return {"book": KO[book], "verses": units, "finished": not units, "ends_book": ends_book}

    def lookup(self, ref, limit=SAFE_VERSES):
        """장절 범위의 본문을 돌려준다.

        - 장의 끝(last_verse)을 넘는 요청은 "…장은 …절까지입니다"로 알린다
        - 요청 범위와 겹치는 단위를 모두 돌려준다. 묶인 단위는 통째로 돌려준다
        - 시작 절이나 끝 절의 본문이 DB에 없으면 PassageError (묵상을 시작하지 않는다)
        - 가운데 절이 비어 있으면 본문은 돌려주되 missing에 적어 알린다
        """
        book, c1, v1, c2, v2 = parse_reference(ref)
        name, order = KO[book], book + 1
        if order not in self.last_chapter:
            raise PassageError(f"성경 DB에 없는 책입니다: {name}", 404)
        for ch, v in ((c1, v1), (c2, v2)):
            if ch > self.last_chapter[order]:
                raise PassageError(f"{name}{_eun(name)} {self.last_chapter[order]}장까지입니다.")
            if v > self.last_verse[(order, ch)]:
                raise PassageError(f"{name} {ch}장은 {self.last_verse[(order, ch)]}절까지입니다.")

        # 장마다 요청한 절의 범위. 10절을 넘어도 묵상자가 정한 범위를 존중해 그대로 받는다.
        ranges = [(ch, v1 if ch == c1 else 1,
                   v2 if ch == c2 else self.last_verse.get((order, ch), 0))
                  for ch in range(c1, c2 + 1)]
        if sum(last - first + 1 for _, first, last in ranges) > limit:
            raise PassageError(TOO_LONG if limit == SAFE_VERSES else f"한 번에 {limit}절까지 펼쳐 볼 수 있습니다.")

        verses, missing = [], []
        for ch, first, last in ranges:
            covered = set()
            for unit in self.units(book, ch):
                if unit["start"] <= last and unit["end"] >= first:
                    verses.append(unit)
                    covered.update(range(unit["start"], unit["end"] + 1))
            for n in range(first, last + 1):
                if n not in covered:
                    if (ch, n) in ((c1, v1), (c2, v2)):
                        raise PassageError(f"{name} {ch}:{n}절이 성경 DB에 없습니다.", 404)
                    missing.append(f"{ch}:{n}")
        # 본문 위치는 묵상 완료 기록의 표준 항목 이름을 그대로 쓴다
        return {"book": name, "chapter_start": c1, "verse_start": v1,
                "chapter_end": c2, "verse_end": v2,
                "passage": format_reference(book, c1, v1, c2, v2),
                "verses": verses, "missing": missing}
