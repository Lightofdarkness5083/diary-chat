"""성경 DB가 온전한지 확인한다.  실행: .venv/bin/python -m bible.check_db

1) DB에 적힌 기준(metadata의 expected_counts)과 실제 개수가 같은지
2) 66권이 코드의 책 목록과 같은지
3) 모든 장에서 1절부터 마지막 절까지 빠짐, 겹침, 넘침 없이 덮이는지
4) 골로새서 4장이 18절인지, 골로새서 3:18-4:1이 조회되는지
하나라도 실패하면 종료 코드 1로 끝난다.
"""
import json
import sys

from .lookup import KO, Bible, BibleSetupError, PassageError

failed = False


def report(ok, message):
    global failed
    failed = failed or not ok
    print(f"  [{'통과' if ok else '실패'}] {message}")


try:
    bible = Bible()
except BibleSetupError as e:
    print("[실패]", e)
    sys.exit(1)

info = bible.describe()
print(f"schema_version {info['schema_version']}, 번역 {info['version']}, 발행 {info['publisher']}")

con = bible._connect()
books = con.execute("SELECT book_order, book FROM books ORDER BY book_order").fetchall()
units = con.execute(
    "SELECT book_order, chapter, verse_start, verse_end, unit_type FROM verses").fetchall()
con.close()

covered = {}  # {(책 순서, 장): [절, 절, ...]}
for order, chapter, start, end, _ in units:
    covered.setdefault((order, chapter), []).extend(range(start, end + 1))
merged = [u for u in units if u[4] == "SOURCE_MERGED"]
actual = {
    "books": len(books),
    "chapters": len(bible.last_verse),
    "verses": len(units),
    "SINGLE": sum(1 for u in units if u[4] == "SINGLE"),
    "SOURCE_MERGED": len(merged),
    "merged_coverage": sum(u[3] - u[2] + 1 for u in merged),
    "coverage": sum(len(v) for v in covered.values()),
}

print("expected_counts와 실제 개수:")
expected = json.loads(bible.meta.get("expected_counts") or "{}")
if not expected:
    report(False, "metadata에 expected_counts가 없습니다")
for key, want in expected.items():
    report(actual.get(key) == want, f"{key}: 기준 {want}, 실제 {actual.get(key)}")

report([name for _, name in books] == KO and [o for o, _ in books] == list(range(1, 67)),
       "66권이 코드의 책 목록과 같습니다")

problems = []
for key in sorted(set(bible.last_verse) | set(covered)):
    last, verses = bible.last_verse.get(key), sorted(covered.get(key, []))
    if last is None or verses != list(range(1, last + 1)):
        problems.append(f"{KO[key[0] - 1] if 1 <= key[0] <= 66 else key[0]} {key[1]}장")
report(not problems, "모든 장이 1절부터 마지막 절까지 빠짐, 겹침, 넘침 없이 덮입니다"
       if not problems else f"덮임이 맞지 않는 장 {len(problems)}곳: {', '.join(problems[:10])}")

report(bible.last_verse.get((51, 4)) == 18, f"골로새서 4장 마지막 절: {bible.last_verse.get((51, 4))}")
try:
    found = bible.lookup("골로새서 3:18-4:1")
    report(len(found["verses"]) == 9 and not found["missing"],
           f"{found['passage']}: 단위 {len(found['verses'])}개, 빠진 절 {len(found['missing'])}개")
    for v in found["verses"]:
        print(f"      {v['chapter']}:{v['label']} {v['text'][:24]}")
except PassageError as e:
    report(False, f"골로새서 3:18-4:1: {e.message}")

print("결과:", "실패한 검사가 있습니다" if failed else "모든 검사 통과")
sys.exit(1 if failed else 0)
