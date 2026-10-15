"""본문 조회 검사.  실행: .venv/bin/python -m tests.test_bible
실제 성경 본문을 쓰지 않고, 성경 DB와 구조만 같은 시험용 DB를 만들어 확인한다."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

from bible import KO, Bible, BibleSetupError, PassageError, parse_reference

COL = 51  # 골로새서의 book_order


def make_db(skip=(), merged=(), schema_version="1", metadata=True, all_books=False):
    """골로새서(29, 23, 25, 18절)가 든 시험용 DB.
    skip: 뺄 절 {(장, 절)},  merged: 묶을 단위 [(장, 첫절, 끝절)],  all_books: 66권을 모두 넣기"""
    path = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE books (book_order, book, official_name, code);
        CREATE TABLE chapters (book_order, chapter, last_verse, unit_count);
        CREATE TABLE verses (id INTEGER PRIMARY KEY, book_order, book, chapter,
            verse_start, verse_end, verse_label, unit_type, text, source);
    """)
    shape = {order: {1: 3} for order in range(1, 67)} if all_books else {}
    shape[COL] = {1: 29, 2: 23, 3: 25, 4: 18}
    in_merged = {(c, n) for c, a, b in merged for n in range(a, b + 1)}
    for order, chapters in shape.items():
        name = KO[order - 1]
        con.execute("INSERT INTO books VALUES (?,?,?,?)", (order, name, name, f"b{order}"))
        for chapter, last in chapters.items():
            count = 0
            for verse in range(1, last + 1):
                if order == COL and ((chapter, verse) in skip or (chapter, verse) in in_merged):
                    continue
                con.execute(
                    "INSERT INTO verses (book_order, book, chapter, verse_start, verse_end,"
                    " verse_label, unit_type, text) VALUES (?,?,?,?,?,?,?,?)",
                    (order, name, chapter, verse, verse, str(verse), "SINGLE",
                     f"시험 본문 {chapter}:{verse}"))
                count += 1
            if order == COL:
                for c, a, b in merged:
                    if c == chapter:
                        con.execute(
                            "INSERT INTO verses (book_order, book, chapter, verse_start, verse_end,"
                            " verse_label, unit_type, text) VALUES (?,?,?,?,?,?,?,?)",
                            (order, name, c, a, b, f"{a}-{b}", "SOURCE_MERGED",
                             f"시험 본문 {c}:{a}-{b}"))
                        count += 1
            con.execute("INSERT INTO chapters VALUES (?,?,?,?)", (order, chapter, last, count))
    if metadata:
        con.execute("CREATE TABLE metadata (key, value)")
        single = con.execute("SELECT COUNT(*) FROM verses WHERE unit_type='SINGLE'").fetchone()[0]
        merged_cover = sum(b - a + 1 for _, a, b in merged)
        counts = {"books": len(shape), "chapters": sum(len(c) for c in shape.values()),
                  "verses": single + len(merged), "SINGLE": single, "SOURCE_MERGED": len(merged),
                  "merged_coverage": merged_cover, "coverage": single + merged_cover}
        con.executemany("INSERT INTO metadata VALUES (?,?)", [
            ("schema_version", schema_version), ("version", "TEST"), ("publisher", "시험"),
            ("expected_counts", json.dumps(counts))])
    con.commit()
    con.close()
    return path


def expect_error(fn, status=None, kind=PassageError):
    try:
        fn()
    except kind as e:
        if status is not None:
            assert e.status == status, e.status
        return str(e)
    raise AssertionError("오류가 나야 하는데 나지 않았습니다")


def labels(found):
    return [f'{v["chapter"]}:{v["label"]}' for v in found["verses"]]


def main():
    # 장절 적는 방식
    assert parse_reference("골로새서 3:18-4:1") == (50, 3, 18, 4, 1)
    assert parse_reference("골 4:2-6") == (50, 4, 2, 4, 6)
    assert parse_reference("골로새서 4장 2-6절") == (50, 4, 2, 4, 6)
    assert parse_reference("골로새서 4:2–6") == (50, 4, 2, 4, 6)       # 긴 줄표
    assert parse_reference("요한1서 1:1-4") == (61, 1, 1, 1, 4)
    assert parse_reference("1 Samuel 3:1-10") == (8, 3, 1, 3, 10)
    expect_error(lambda: parse_reference("골로새서"))
    expect_error(lambda: parse_reference("없는책 1:1"))
    expect_error(lambda: parse_reference("골로새서 4:6-2"))

    # 기본 조회와 장을 넘는 범위
    bible = Bible(make_db())
    found = bible.lookup("골로새서 3:18-4:1")
    assert found["passage"] == "골로새서 3:18-4:1" and found["missing"] == []
    assert (found["book"], found["chapter_start"], found["verse_start"], found["chapter_end"], found["verse_end"]) == ("골로새서", 3, 18, 4, 1)
    assert labels(found) == [f"3:{n}" for n in range(18, 26)] + ["4:1"]
    assert found["verses"][0] == {"chapter": 3, "start": 18, "end": 18, "label": "18",
                                  "text": "시험 본문 3:18"}
    assert len(bible.lookup("골 4:2-11")["verses"]) == 10
    # 10절은 권하는 분량일 뿐이다. 묵상자가 정한 범위는 넘어도 그대로 받는다
    long = bible.lookup("골로새서 4:1-18")
    assert long["passage"] == "골로새서 4:1-18" and sum(u["end"] - u["start"] + 1 for u in long["verses"]) == 18
    assert bible.lookup("골로새서 3:16-4:1")["passage"] == "골로새서 3:16-4:1"   # 장을 넘어 11절
    assert sum(u["end"] - u["start"] + 1 for u in bible.lookup("골로새서 1:1-2:1")["verses"]) == 30   # 꼭 30절은 받는다
    print("31절:", expect_error(lambda: bible.lookup("골로새서 1:1-2:2"), 400))                      # 터무니없이 긴 범위만 거른다
    expect_error(lambda: bible.lookup("골로새서 1:1-4:18"), 400)
    print("장의 끝:", expect_error(lambda: bible.lookup("골로새서 4:15-19"), 400))
    print("없는 장:", expect_error(lambda: bible.lookup("골로새서 5:1"), 400))
    print("없는 책:", expect_error(lambda: bible.lookup("창세기 1:1"), 404))

    # 묶인 단위는 쪼개지 않는다
    bible = Bible(make_db(merged=[(4, 3, 5), (2, 1, 2)]))
    assert labels(bible.lookup("골로새서 4:4")) == ["4:3-5"]                    # 가운데 절만 요청
    assert labels(bible.lookup("골로새서 4:2-4")) == ["4:2", "4:3-5"]           # 끝이 걸침
    assert labels(bible.lookup("골로새서 4:5-6")) == ["4:3-5", "4:6"]           # 시작이 걸침
    assert labels(bible.lookup("골로새서 1:29-2:1")) == ["1:29", "2:1-2"]       # 장을 넘어 걸침
    unit = bible.lookup("골로새서 4:4")["verses"][0]
    assert (unit["start"], unit["end"]) == (3, 5)

    # 이어지는 본문: 묵상한 곳 다음 절부터, 장을 넘어 이어진다. 걸친 묶인 단위는 건너뛴다
    after = bible.following("골로새서", 4, 2)
    assert after["book"] == "골로새서" and labels(after)[:2] == ["4:3-5", "4:6"]
    assert labels(bible.following("골로새서", 4, 4))[:2] == ["4:6", "4:7"]          # 걸쳐 있던 3-5절 묶음은 건너뜀
    assert labels(bible.following("골", 1, 27))[:3] == ["1:28", "1:29", "2:1-2"]
    assert labels(bible.following("골로새서", 1, 0))[0] == "1:1"                    # 책의 처음부터
    tail = bible.following("골로새서", 4, 10)
    assert labels(tail) == [f"4:{n}" for n in range(11, 19)] and tail["ends_book"] and not tail["finished"]
    done = bible.following("골로새서", 4, 18)
    assert done["verses"] == [] and done["finished"]
    assert sum(u["end"] - u["start"] + 1 for u in bible.following("골로새서", 1, 0)["verses"]) == 12
    expect_error(lambda: bible.following("없는책", 1, 0))

    # 가운데 절이 빈 DB: 본문은 주되 빈 절을 알린다. 시작이나 끝이 비면 멈춘다
    bible = Bible(make_db(skip={(4, 4)}))
    found = bible.lookup("골로새서 4:2-6")
    assert found["missing"] == ["4:4"] and len(found["verses"]) == 4
    expect_error(lambda: bible.lookup("골로새서 4:4-6"), 404)
    expect_error(lambda: bible.lookup("골로새서 4:2-4"), 404)

    # 끝이 잘린 장: chapters는 18절까지라고 하는데 본문은 9절까지만 있다
    bible = Bible(make_db(skip={(4, n) for n in range(10, 19)}))
    print("잘린 장:", expect_error(lambda: bible.lookup("골로새서 4:7-12"), 404))

    # 구조가 다른 DB는 읽지 않는다
    print("구조가 다른 DB:", expect_error(lambda: Bible(make_db(schema_version="2")), kind=BibleSetupError)[:44])
    print("구조가 다른 DB:", expect_error(lambda: Bible(make_db(metadata=False)), kind=BibleSetupError)[:44])

    # check_db.py: 온전한 DB는 통과, 잘린 DB는 실패
    def run_check(path):
        env = dict(os.environ, BIBLE_DB=path)
        return subprocess.run([sys.executable, "-m", "bible.check_db"], env=env, capture_output=True, text=True)

    good = run_check(make_db(merged=[(4, 3, 5)], all_books=True))
    assert good.returncode == 0 and "모든 검사 통과" in good.stdout, good.stdout + good.stderr
    bad = run_check(make_db(skip={(4, 10)}, all_books=True))
    assert bad.returncode == 1 and "골로새서 4장" in bad.stdout, bad.stdout + bad.stderr


    # ---- 묵상 단락 (bible/paragraphs.json) ----
    import json as _json, tempfile as _tempfile  # noqa: E402
    from bible import paragraphs as P  # noqa: E402
    REAL = Bible()                                               # 실제 성경 DB
    real = P.load(REAL)
    assert P.problems == {}, P.problems                         # 실제 자료는 모두 검사를 통과한다
    eph = real["에베소서"]
    assert eph[0]["ref"] == "에베소서 1:1-2" and eph[-1]["ref"] == "에베소서 6:21-24" and len(eph) == 17
    assert P.containing(eph, 2, 4)["ref"] == "에베소서 2:1-10" and P.containing(eph, 7, 1) is None
    for wrong, why in ((["1:1-2", "1:4-23"], "빈틈"), (["1:1-3", "1:3-23"], "겹침"), (["1:1-24"], "넘침"), (["1:1-23", "2:1-10"], "끝까지 아님")):
        path = _tempfile.mktemp(suffix=".json")
        open(path, "w", encoding="utf-8").write(_json.dumps({"에베소서": wrong}))
        P.problems.clear()
        assert "에베소서" not in P.load(REAL, path) and "에베소서" in P.problems, why     # 잘못된 책은 빼고 앱은 돈다
    P.problems.clear()
    print("모든 검사 통과")


if __name__ == "__main__":
    main()
